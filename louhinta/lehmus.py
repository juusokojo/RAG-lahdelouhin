"""Lehmus-RAGin asiakas (vain lukukutsut). RAG-resurssin osoite: ympäristömuuttuja LEHMUS_RAG_URL."""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from louhinta.mallit import Osuma
from louhinta.paikannus import paikanna_patka

OLETUS_RAG_URL = os.environ.get("LEHMUS_RAG_URL", "")   # RAG-resurssin perusosoite portaalista
AIKAKATKAISU = 60        # sekuntia
UUDELLEENYRITYKSIA = 3   # lisäyrityksiä ensimmäisen jälkeen
ALKUVIIVE = 1.0          # sekuntia; kaksinkertaistuu joka yrityksellä
_TUNNUS = re.compile(r"[A-Za-z0-9_.-]+")


def _aika(arvo) -> datetime | None:
    """ISO-aikaleima -> aikavyöhykkeellinen datetime (puuttuva vyöhyke = UTC); virheellinen -> None."""
    try:
        aika = datetime.fromisoformat(str(arvo))
    except ValueError:
        return None
    return aika if aika.tzinfo else aika.replace(tzinfo=timezone.utc)


class Rag:
    def __init__(self, url: str = OLETUS_RAG_URL, avain: str | None = None,
                 valimuisti: Path = Path(".valimuisti")):
        avain = avain or os.environ.get("LEHMUS_API_KEY")
        if not avain:
            raise ValueError("Lehmuksen lukuavain puuttuu: aseta ympäristömuuttuja "
                             "LEHMUS_API_KEY tai anna avain-parametri.")
        if not url:
            raise ValueError("RAG-resurssin osoite puuttuu: aseta ympäristömuuttuja "
                             "LEHMUS_RAG_URL tai anna url-parametri.")
        self.url = url.rstrip("/")
        self.valimuisti = Path(valimuisti)
        self.istunto = requests.Session()
        self.istunto.headers.update({"Authorization": f"Bearer {avain}",
                                     "Accept": "application/json"})
        self._tekstit: dict[str, str] = {}
        self._paivitetty: dict[str, datetime] = {}   # id -> updated_at (tiedostot()-kutsusta)

    def _pyynto(self, metodi: str, polku: str, **kwargs) -> dict:
        """GET/POST uudelleenyrityksin: verkkovirheet, 5xx ja 429 yritetään uudelleen."""
        viive = ALKUVIIVE
        for yritys in range(UUDELLEENYRITYKSIA + 1):
            viimeinen = yritys == UUDELLEENYRITYKSIA
            try:
                r = getattr(self.istunto, metodi)(f"{self.url}{polku}", timeout=AIKAKATKAISU, **kwargs)
            except requests.RequestException:
                if viimeinen:
                    raise
            else:
                if r.status_code != 429 and r.status_code < 500:
                    r.raise_for_status()
                    return r.json()
                if viimeinen:
                    r.raise_for_status()
            time.sleep(viive)
            viive *= 2
        raise AssertionError("ei pitäisi päätyä tänne")

    def tiedostot(self) -> list[dict]:
        """Kaikki RAGin tiedostot: {"id", "tiedosto"}. Sivutus cursorilla."""
        kaikki: list[dict] = []
        cursor = None
        while True:
            params: dict = {"limit": 500}
            if cursor:
                params["cursor"] = cursor
            vastaus = self._pyynto("get", "/files", params=params)
            for f in vastaus.get("files", []):
                nimi = (f.get("metadata") or {}).get("filename") or f.get("filename") or ""
                kaikki.append({"id": f["id"], "tiedosto": nimi})
                paivitetty = _aika(f.get("updated_at"))
                if paivitetty:
                    self._paivitetty[f["id"]] = paivitetty
            seuraava = vastaus.get("next_cursor")
            if not seuraava or seuraava == cursor:
                return kaikki
            cursor = seuraava

    def lahdeteksti(self, file_id: str) -> str:
        """source_text; levyvälimuisti .valimuisti/lahdetekstit/<id>.txt."""
        if not _TUNNUS.fullmatch(file_id) or file_id in (".", ".."):
            raise ValueError(f"Virheellinen tiedostotunnus: {file_id!r}")
        if file_id in self._tekstit:
            return self._tekstit[file_id]
        polku = self.valimuisti / "lahdetekstit" / f"{file_id}.txt"
        if polku.is_file() and not self._vanhentunut(file_id, polku):
            with open(polku, encoding="utf-8", newline="") as f:
                teksti = f.read()
        else:
            teksti = self._pyynto("get", f"/content/{file_id}").get("source_text")
            if not teksti:
                raise ValueError(f"Tiedostolla {file_id} ei ole source_text-kenttää.")
            polku.parent.mkdir(parents=True, exist_ok=True)
            valiaikainen = polku.with_name(polku.name + ".tmp")
            with open(valiaikainen, "w", encoding="utf-8", newline="") as f:
                f.write(teksti)
            valiaikainen.replace(polku)
        self._tekstit[file_id] = teksti
        return teksti

    def _vanhentunut(self, file_id: str, polku: Path) -> bool:
        """Onko RAGin teksti päivitetty (sama id, uusi teksti) välimuistitiedoston jälkeen?

        Tieto on käytettävissä vasta, kun tiedostot() on kutsuttu tällä oliolla.
        """
        paivitetty = self._paivitetty.get(file_id)
        return bool(paivitetty) and paivitetty > datetime.fromtimestamp(polku.stat().st_mtime, timezone.utc)

    def hae(self, kysely: str, max_chunks: int = 8,
            filter_ids: list[str] | None = None) -> list[Osuma]:
        """Hakee pätkät ja paikantaa ne lähdetekstiin (pdf_sivut)."""
        runko: dict = {"query": kysely, "max_chunks": max_chunks}
        if filter_ids:
            runko["filter_ids"] = filter_ids
        vastaus = self._pyynto("post", "/context", json=runko)
        patkat = vastaus.get("chunks") or []
        pisteet = vastaus.get("scores") or []
        tiedostot = vastaus.get("files") or []
        if not len(patkat) == len(pisteet) == len(tiedostot):
            raise ValueError("/context-vastaus: chunks, scores ja files eri pituisia")
        osumat = []
        for patka, piste, f in zip(patkat, pisteet, tiedostot):
            nimi = (f.get("metadata") or {}).get("filename") or f.get("filename") or ""
            try:
                sivut = paikanna_patka(patka, self.lahdeteksti(f["id"]))
            except ValueError:      # ei source_text-kenttää: ei sivua
                sivut = []
            osumat.append(Osuma(file_id=f["id"], tiedosto=nimi, teksti=patka,
                                pisteet=float(piste), pdf_sivut=sivut))
        return osumat
