#!/usr/bin/env python3
"""Ankkurikoe: löytyvätkö RAGin tekstit paikallisista PDF:istä sivutarkasti?

Koe vertaa RAG-palvelun poimimaa tekstiä (GET /content/{id} -> source_text sekä
/context-haun pätkät) saman tiedoston paikalliseen PDF:ään ja kertoo, kuinka
suuri osa tekstistä voidaan paikantaa PDF-sivulle mekaanisesti.

Lisäksi koe paikantaa hakupätkät palvelun omaan source_textiin, jossa sivut
erottaa sivunvaihtomerkki (\\f), ja vertaa näin saatua sivua paikallisesta
PDF:stä saatuun. Jos sivut täsmäävät, sivutarkat viitteet saa RAGista
ilman paikallista PDF:ää.

Tietosuoja: skripti tulostaa ja tallentaa vain tilastoja, ei artikkelien
tekstiä. Valitsin --nayta-esimerkit tulostaa löytymättömiä katkelmia
vianetsintää varten; käytä sitä vain avoimesti saatavilla olevilla artikkeleilla.

Käyttö:
    export RAG_API_KEY=...        # omassa päätteessä, ei keskusteluun
    .venv/bin/python -I scripts/ankkurikoe.py --pdf-kansio ~/polku/pdf
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pymupdf
import requests
from rapidfuzz import fuzz

OLETUS_RAG_URL = os.environ.get("RAG_URL", "")   # RAG-palvelun perusosoite
OLETUSKYSELYT = [
    "research methods, participants and data",
    "main results and findings",
    "limitations of the study",
    "implications for practice and teacher education",
    "theoretical background and previous research",
]
ANKKURI = 50          # merkkiä normalisoitua tekstiä yhdessä ankkurissa
IKKUNA = 1000         # source_textin vertailuikkunan pituus (normalisoitua merkkiä)
SUMEA_RAJA = 90       # rapidfuzz partial_ratio -kynnys sumealle osumalle
TYHJA_SIVU = 50       # sivu on "tyhjä" (skannattu?), jos tekstiä alle tämän


# --------------------------------------------------------------------------
# Normalisointi ja paikannus (ei verkkoa, ei tekoälyä)
# --------------------------------------------------------------------------

def normalisoi(teksti: str) -> str:
    """Pelkät kirjaimet ja numerot pienaakkosina.

    Poistaa erot, jotka syntyvät eri PDF-poimijoiden välillä: välilyönnit,
    rivinvaihdot, tavutusviivat, välimerkit, ligatuurit (NFKC: ﬁ -> fi) ja
    Markdown-merkinnät.
    """
    teksti = unicodedata.normalize("NFKC", teksti).replace("­", "").lower()
    return "".join(m for m in teksti if m.isalnum())


@dataclass
class PdfTeksti:
    sivut: list[str]           # normalisoitu teksti sivuittain
    alut: list[int]            # kunkin sivun alkukohta koko tekstissä
    koko: str                  # sivut yhteen liitettynä

    @property
    def tyhjia_sivuja(self) -> int:
        return sum(1 for s in self.sivut if len(s) < TYHJA_SIVU)

    def sivu(self, kohta: int) -> int:
        """Normalisoidun tekstin kohta -> 1-pohjainen PDF-sivu."""
        return bisect_right(self.alut, kohta)


def lue_pdf(polku: Path) -> PdfTeksti:
    with pymupdf.open(polku) as doc:
        return sivuta([sivu.get_text("text") for sivu in doc])


def lue_lahdeteksti(source_text: str) -> PdfTeksti:
    """Lehmuksen source_text sivuina: sivut erottaa sivunvaihtomerkki \\f."""
    return sivuta(source_text.split("\f"))


def sivuta(raakasivut: list[str]) -> PdfTeksti:
    sivut = [normalisoi(s) for s in raakasivut]
    alut, kohta = [], 0
    for s in sivut:
        alut.append(kohta)
        kohta += len(s)
    return PdfTeksti(sivut, alut, "".join(sivut))


def paikanna(teksti_norm: str, pdf: PdfTeksti) -> tuple[str, list[int]]:
    """Etsii normalisoidun tekstin PDF:stä.

    Palauttaa tilan ja PDF-sivut:
      tarkka      kaikki kolme ankkuria (alku, keskikohta, loppu) löytyivät yksiselitteisesti
      osittainen  1–2 ankkuria löytyi
      sumea       ankkurit eivät löytyneet, mutta sumea vertailu osui sivuun
      ei_loydy    tekstiä ei löytynyt
      lyhyt       teksti liian lyhyt vertailuun
    """
    n = len(teksti_norm)
    if n < ANKKURI:
        return "lyhyt", []
    kohdat = [0, n // 2 - ANKKURI // 2, n - ANKKURI]
    sivut: set[int] = set()
    osumia = 0
    for k in kohdat:
        ankkuri = teksti_norm[k:k + ANKKURI]
        i = pdf.koko.find(ankkuri)
        if i >= 0 and pdf.koko.find(ankkuri, i + 1) < 0:   # vain yksiselitteiset
            osumia += 1
            sivut.add(pdf.sivu(i))
            sivut.add(pdf.sivu(i + ANKKURI - 1))
    if osumia == len(kohdat):
        return "tarkka", sorted(sivut)
    if osumia:
        return "osittainen", sorted(sivut)
    otos = teksti_norm[:400]
    parhaat = [(fuzz.partial_ratio(otos, s), nro) for nro, s in enumerate(pdf.sivut, 1) if s]
    if parhaat:
        pisteet, nro = max(parhaat)
        if pisteet >= SUMEA_RAJA:
            return "sumea", [nro]
    return "ei_loydy", []


def ikkunat(teksti_norm: str) -> list[str]:
    return [teksti_norm[i:i + IKKUNA] for i in range(0, len(teksti_norm), IKKUNA)
            if len(teksti_norm[i:i + IKKUNA]) >= ANKKURI]


# --------------------------------------------------------------------------
# RAG-palvelu
# --------------------------------------------------------------------------

class Rag:
    def __init__(self, url: str, avain: str):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {avain}", "Accept": "application/json"})

    def _get(self, polku: str, **params):
        r = self.s.get(f"{self.url}{polku}", params=params, timeout=60)
        r.raise_for_status()
        return r.json()

    def tiedostot(self) -> list[dict]:
        kaikki, cursor = [], None
        while True:
            params = {"limit": 500}
            if cursor:
                params["cursor"] = cursor
            vastaus = self._get("/files", **params)
            kaikki.extend(vastaus.get("files", []))
            cursor = vastaus.get("next_cursor")
            if not cursor:
                return kaikki

    def tiedosto(self, tid: str) -> dict:
        return self._get(f"/content/{tid}")     # alustaversio 3.3.0; /files/{id} vasta 3.5.0:ssa

    def hae(self, kysely: str, tid: str, max_chunks: int) -> dict:
        r = self.s.post(f"{self.url}/context", timeout=60,
                        json={"query": kysely, "max_chunks": max_chunks, "filter_ids": [tid]})
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------------------
# Koe
# --------------------------------------------------------------------------

TILAT = ["tarkka", "osittainen", "sumea", "ei_loydy", "lyhyt"]


@dataclass
class Tulos:
    tiedosto: str
    pdf_sivuja: int = 0
    tyhjia_sivuja: int = 0
    source_text: bool = False
    lahde_sivuja: int = 0      # source_textin sivut (\f-merkit + 1)
    ikkunat: dict = field(default_factory=lambda: dict.fromkeys(TILAT, 0))
    patkat: dict = field(default_factory=lambda: dict.fromkeys(TILAT, 0))
    patkat_lahteessa: dict = field(default_factory=lambda: dict.fromkeys(TILAT, 0))
    sivu_sama: int = 0         # pätkän sivu source_textistä = sivu paikallisesta PDF:stä
    sivu_eri: int = 0
    patkan_pituudet: list = field(default_factory=list)
    sivuvaleja: int = 0        # pätkiä, jotka ulottuvat useammalle sivulle
    virhe: str | None = None


def osuus(laskuri: dict) -> str:
    yht = sum(laskuri.values()) - laskuri["lyhyt"]
    if not yht:
        return "–"
    paikannettu = laskuri["tarkka"] + laskuri["osittainen"] + laskuri["sumea"]
    return f"{100 * paikannettu / yht:5.1f} % ({paikannettu}/{yht})"


def aja_tiedosto(rag: Rag, tid: str, polku: Path, kyselyt: list[str],
                 max_chunks: int, nayta: bool) -> Tulos:
    t = Tulos(polku.name)
    pdf = lue_pdf(polku)
    t.pdf_sivuja, t.tyhjia_sivuja = len(pdf.sivut), pdf.tyhjia_sivuja

    lahde = rag.tiedosto(tid).get("source_text")
    lahdesivut = None
    if lahde:
        t.source_text = True
        lahdesivut = lue_lahdeteksti(lahde)
        t.lahde_sivuja = len(lahdesivut.sivut)
        for ikkuna in ikkunat(normalisoi(lahde)):
            tila, _ = paikanna(ikkuna, pdf)
            t.ikkunat[tila] += 1
            if nayta and tila == "ei_loydy":
                print(f"    [ikkuna ei löydy] {ikkuna[:120]}")

    nahdyt: set[str] = set()
    for kysely in kyselyt:
        for patka in rag.hae(kysely, tid, max_chunks).get("chunks", []):
            if patka in nahdyt:
                continue
            nahdyt.add(patka)
            t.patkan_pituudet.append(len(patka))
            patka_norm = normalisoi(patka)
            tila, sivut = paikanna(patka_norm, pdf)
            t.patkat[tila] += 1
            if len(sivut) > 1:
                t.sivuvaleja += 1
            if nayta and tila == "ei_loydy":
                print(f"    [pätkä ei löydy] {patka[:200]!r}")
            if lahdesivut is None:
                continue
            tila_l, sivut_l = paikanna(patka_norm, lahdesivut)
            t.patkat_lahteessa[tila_l] += 1
            if tila == "tarkka" and tila_l == "tarkka":
                if sivut == sivut_l:
                    t.sivu_sama += 1
                else:
                    t.sivu_eri += 1
                    if nayta:
                        print(f"    [sivu eroaa] PDF {sivut}, source_text {sivut_l}: {patka[:80]!r}")
    return t


def vertailu(sama: int, eri: int) -> str:
    yht = sama + eri
    return f"{100 * sama / yht:5.1f} % ({sama}/{yht})" if yht else "–"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pdf-kansio", required=True, type=Path, help="paikallisten PDF:ien kansio (haetaan alikansioista)")
    p.add_argument("--rag-url", default=OLETUS_RAG_URL)
    p.add_argument("--max-chunks", type=int, default=8, help="pätkiä hakua kohden")
    p.add_argument("--raja", type=int, default=0, help="testaa enintään näin monta tiedostoa (0 = kaikki)")
    p.add_argument("--tulos", type=Path, default=None, help="tulos-JSON (oletus: tulokset/ankkurikoe-<aika>.json)")
    p.add_argument("--nayta-esimerkit", action="store_true",
                   help="tulosta löytymättömät katkelmat (VAIN avoimille artikkeleille)")
    a = p.parse_args()
    if not a.rag_url:
        print("Ympäristömuuttuja RAG_URL puuttuu (RAG-palvelun perusosoite).", file=sys.stderr)
        return 2

    avain = os.environ.get("RAG_API_KEY")
    if not avain:
        print("Ympäristömuuttuja RAG_API_KEY puuttuu.", file=sys.stderr)
        return 2

    rag = Rag(a.rag_url, avain)
    etat = rag.tiedostot()
    nimi_id = {}
    for f in etat:
        nimi = (f.get("metadata") or {}).get("filename")
        if nimi:
            nimi_id[nimi] = f["id"]
    paikalliset = {pp.name: pp for pp in sorted(a.pdf_kansio.expanduser().rglob("*.pdf"))}

    yhteiset = sorted(set(nimi_id) & set(paikalliset))
    print(f"RAGissa {len(nimi_id)} tiedostoa, paikallisesti {len(paikalliset)} PDF:ää, "
          f"samannimisiä {len(yhteiset)}.")
    vain_ragissa = sorted(n for n in set(nimi_id) - set(paikalliset) if n.lower().endswith(".pdf"))
    vain_paikallinen = sorted(set(paikalliset) - set(nimi_id))
    if vain_ragissa:
        print(f"  Vain RAGissa ({len(vain_ragissa)}): " + ", ".join(vain_ragissa[:10]) + (" …" if len(vain_ragissa) > 10 else ""))
    if vain_paikallinen:
        print(f"  Vain paikallisesti ({len(vain_paikallinen)}): " + ", ".join(vain_paikallinen[:10]) + (" …" if len(vain_paikallinen) > 10 else ""))
    if a.raja:
        yhteiset = yhteiset[:a.raja]

    tulokset: list[Tulos] = []
    for i, nimi in enumerate(yhteiset, 1):
        print(f"[{i}/{len(yhteiset)}] {nimi}")
        try:
            t = aja_tiedosto(rag, nimi_id[nimi], paikalliset[nimi], OLETUSKYSELYT, a.max_chunks, a.nayta_esimerkit)
        except Exception as e:  # yksi tiedosto ei kaada koko koetta
            t = Tulos(nimi, virhe=f"{type(e).__name__}: {e}")
        tulokset.append(t)
        if t.virhe:
            print(f"    VIRHE: {t.virhe}")
        else:
            print(f"    sivuja {t.pdf_sivuja} (tyhjiä {t.tyhjia_sivuja}), "
                  f"source_text {f'kyllä, {t.lahde_sivuja} sivua' if t.source_text else 'ei'}, "
                  f"ikkunat {osuus(t.ikkunat)}, pätkät {osuus(t.patkat)}, "
                  f"sivu sama {vertailu(t.sivu_sama, t.sivu_eri)}")

    ok = [t for t in tulokset if not t.virhe]
    yht_ikk = {k: sum(t.ikkunat[k] for t in ok) for k in TILAT}
    yht_pat = {k: sum(t.patkat[k] for t in ok) for k in TILAT}
    yht_lah = {k: sum(t.patkat_lahteessa[k] for t in ok) for k in TILAT}
    pituudet = [x for t in ok for x in t.patkan_pituudet]
    lahteelliset = [t for t in ok if t.source_text]
    print("\nYHTEENVETO")
    print(f"  Tiedostoja: {len(ok)} onnistui, {len(tulokset) - len(ok)} virhettä")
    print(f"  source_text saatavilla: {len(lahteelliset)}/{len(ok)}")
    print(f"  source_textin sivumäärä = PDF:n sivumäärä: "
          f"{sum(t.lahde_sivuja == t.pdf_sivuja for t in lahteelliset)}/{len(lahteelliset)}")
    print(f"  Sivuja ilman tekstikerrosta: {sum(t.tyhjia_sivuja for t in ok)}/{sum(t.pdf_sivuja for t in ok)}")
    print(f"  Koko tekstin ikkunat paikannettu: {osuus(yht_ikk)}  {yht_ikk}")
    print(f"  Hakupätkät paikannettu PDF:ään:   {osuus(yht_pat)}  {yht_pat}")
    print(f"  Hakupätkät paikannettu source_textiin: {osuus(yht_lah)}  {yht_lah}")
    print(f"  Sivu source_textistä = sivu PDF:stä (molemmat tarkkoja): "
          f"{vertailu(sum(t.sivu_sama for t in ok), sum(t.sivu_eri for t in ok))}")
    if pituudet:
        print(f"  Pätkän pituus (merkkiä): mediaani {statistics.median(pituudet):.0f}, "
              f"min {min(pituudet)}, max {max(pituudet)}")
        print(f"  Useammalle sivulle ulottuvia pätkiä: {sum(t.sivuvaleja for t in ok)}/{len(pituudet)}")

    polku = a.tulos or Path("tulokset") / f"ankkurikoe-{datetime.now():%Y%m%d-%H%M}.json"
    polku.parent.mkdir(parents=True, exist_ok=True)
    polku.write_text(json.dumps([t.__dict__ for t in tulokset], ensure_ascii=False, indent=2))
    print(f"\nTulokset tallennettu: {polku}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
