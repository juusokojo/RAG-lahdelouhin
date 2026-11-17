#!/usr/bin/env python3
"""Rakentaa lähderekisterin (lahteet.json) ja tarkistustaulukon (lahteet-tarkistus.md).

1. Hakee RAGin tiedostolistan ja jokaisen tiedoston source_textin (vain lukukutsuja).
2. Etsii DOI:n kahdelta ensimmäiseltä sivulta ja hakee tiedot Crossrefistä.
   Crossrefiin lähetetään vain DOI ja User-Agent "artikkelien-louhinta/0.1".
3. Päättelee painetun aloitussivun sivujen ylä- ja alareunojen sivunumeroista
   ja vertaa sitä Crossrefin sivuihin. Epävarmuutta ei arvata: se kirjataan huomioon.
4. Kirjoittaa lahteet.json (tarkistettu: false) ja lahteet-tarkistus.md.
5. Uusi ajo ei ylikirjoita rivejä, joissa tarkistettu: true.

Tietosuoja: skripti ei tulosta eikä tallenna artikkelien tekstiä.

Käyttö:
    export RAG_API_KEY=...        # omassa päätteessä
    .venv/bin/python -I scripts/rakenna_lahteet.py
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import requests

JUURI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(JUURI))   # -I-tila ei lisää skriptin kansiota hakupolkuun

from louhinta.lahteet import (  # noqa: E402
    lahdeluettelorivi, lajitteluavain, lataa_lahteet, tallenna_lahteet,
)
from louhinta.mallit import Lahde, Tekija  # noqa: E402

OLETUS_RAG_URL = os.environ.get("RAG_URL", "")   # RAG-palvelun perusosoite
CROSSREF_URL = "https://api.crossref.org/works/"
USER_AGENT = "artikkelien-louhinta/0.1"
CROSSREF_VALI = 1.0          # s; enintään yksi pyyntö sekunnissa
DOI_SIVUJA = 2               # DOI etsitään näin monelta ensimmäiseltä sivulta
RIVEJA_REUNALLA = 4          # sivunumeroa etsitään sivun näin monelta ensimmäiseltä ja viimeiseltä riviltä

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
SIVUNUMERO_RE = re.compile(r"^\s*[-–—]?\s*(\d{1,4})\s*[-–—]?\s*$")

TYYPIT = {
    "journal-article": "artikkeli",
    "proceedings-article": "artikkeli",
    "posted-content": "artikkeli",
    "book": "kirja",
    "monograph": "kirja",
    "edited-book": "kirja",
    "book-chapter": "luku",
    "book-part": "luku",
    "reference-entry": "luku",
    "report": "raportti",
    "report-component": "raportti",
}


# --------------------------------------------------------------------------
# RAG-asiakas (pieni lukuasiakas, vain tiedostolista ja source_text)
# --------------------------------------------------------------------------

class Rag:
    def __init__(self, url: str, avain: str):
        self.url = url.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {avain}", "Accept": "application/json"})

    def _get(self, polku: str, **params):
        viive = 2.0
        for yritys in range(4):
            try:
                r = self.s.get(f"{self.url}{polku}", params=params, timeout=60)
                if r.status_code in (429, 500, 502, 503, 504) and yritys < 3:
                    raise requests.HTTPError(f"{r.status_code}")
                r.raise_for_status()
                return r.json()
            except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
                if yritys == 3:
                    raise
                time.sleep(viive)
                viive *= 2

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
                return [{"id": f["id"], "tiedosto": (f.get("metadata") or {}).get("filename") or f.get("filename", "")}
                        for f in kaikki]

    def lahdeteksti(self, file_id: str) -> str:
        return self._get(f"/content/{file_id}").get("source_text") or ""


# --------------------------------------------------------------------------
# DOI ja Crossref
# --------------------------------------------------------------------------

def etsi_doi(sivut: list[str]) -> tuple[str | None, list[str]]:
    """Ensimmäinen DOI kahdelta ensimmäiseltä sivulta ja mahdolliset muut ehdokkaat."""
    ehdokkaat: list[str] = []
    for sivu in sivut[:DOI_SIVUJA]:
        for osuma in DOI_RE.findall(sivu):
            doi = osuma.rstrip(".,;:)]}'\"").lower()
            if re.search(r"n{4,}", doi):      # mallipohjan paikkamerkki, esim. 10.1145/nnnnnnn.nnnnnnn
                continue
            if doi not in ehdokkaat:
                ehdokkaat.append(doi)
    if not ehdokkaat:
        return None, []
    return ehdokkaat[0], ehdokkaat[1:]


class Crossref:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT})   # ei muita käyttäjätietoja
        self.viimeksi = 0.0

    def hae(self, doi: str) -> tuple[dict | None, str]:
        """(message, virheilmoitus)."""
        viive = 2.0
        for yritys in range(3):
            odotus = CROSSREF_VALI - (time.monotonic() - self.viimeksi)
            if odotus > 0:
                time.sleep(odotus)
            self.viimeksi = time.monotonic()
            try:
                r = self.s.get(CROSSREF_URL + requests.utils.quote(doi, safe="/"), timeout=30)
            except (requests.ConnectionError, requests.Timeout) as e:
                if yritys == 2:
                    return None, f"Crossref-yhteysvirhe ({type(e).__name__})"
                time.sleep(viive)
                viive *= 2
                continue
            if r.status_code == 404:
                return None, "DOI:ta ei löytynyt Crossrefistä"
            if r.status_code in (429, 500, 502, 503, 504) and yritys < 2:
                time.sleep(viive)
                viive *= 2
                continue
            if not r.ok:
                return None, f"Crossref palautti {r.status_code}"
            return r.json().get("message"), ""
        return None, "Crossref ei vastannut"


def puhdista(teksti: str) -> str:
    teksti = re.sub(r"<[^>]+>", "", teksti or "")
    return re.sub(r"\s+", " ", html.unescape(teksti)).strip()


def _tekija(d: dict) -> Tekija | None:
    if d.get("name"):
        return Tekija(puhdista(d["name"]), "")
    if d.get("family"):
        return Tekija(puhdista(d["family"]), puhdista(d.get("given", "")))
    return None


def _vuosi(viesti: dict) -> str:
    for kentta in ("published-print", "issued", "published-online", "published", "created"):   # APA: painettu vuosi ensin
        osat = (viesti.get(kentta) or {}).get("date-parts") or [[None]]
        if osat[0] and osat[0][0]:
            return str(osat[0][0])
    return ""


def sivut_crossrefista(sivut: str) -> str:
    return re.sub(r"(?<=\d)\s*[-‐‑–—]+\s*(?=\d)", "–", sivut.strip())


def tayta_crossrefista(lahde: Lahde, viesti: dict) -> list[str]:
    """Täyttää rivin Crossrefin tiedoilla ja palauttaa huomiot."""
    huomiot: list[str] = []
    ctype = viesti.get("type", "")
    lahde.tyyppi = TYYPIT.get(ctype, "artikkeli")
    if ctype not in TYYPIT:
        huomiot.append(f"Crossref-tyyppi '{ctype}' tulkittu artikkeliksi, tarkista tyyppi")
    if ctype == "proceedings-article":
        huomiot.append("Konferenssijulkaisu: lähdeluettelorivi muotoiltu artikkelina, tarkista")
    lahde.tekijat = [t for t in map(_tekija, viesti.get("author") or []) if t]
    lahde.toimittajat = [t for t in map(_tekija, viesti.get("editor") or []) if t] if lahde.tyyppi == "luku" else []
    lahde.vuosi = _vuosi(viesti)
    otsikko = puhdista((viesti.get("title") or [""])[0])
    alaotsikko = puhdista((viesti.get("subtitle") or [""])[0])
    if alaotsikko and alaotsikko.lower() not in otsikko.lower():
        otsikko = f"{otsikko.rstrip(':')}: {alaotsikko}"
    lahde.otsikko = otsikko
    lahde.julkaisu = puhdista((viesti.get("container-title") or [""])[0])
    lahde.vuosikerta = puhdista(viesti.get("volume", ""))
    lahde.numero = puhdista(viesti.get("issue", ""))
    lahde.sivut = sivut_crossrefista(viesti.get("page", ""))
    lahde.artikkelinumero = puhdista(viesti.get("article-number", ""))
    lahde.kustantaja = puhdista(viesti.get("publisher", ""))
    lahde.doi = viesti.get("DOI", lahde.doi)
    if not lahde.tekijat:
        huomiot.append("Crossref ei antanut tekijöitä")
    if not lahde.vuosi:
        huomiot.append("Crossref ei antanut vuotta")
    return huomiot


# --------------------------------------------------------------------------
# Painetun aloitussivun päättely
# --------------------------------------------------------------------------

def sivunumeroehdokkaat(sivu: str) -> set[int]:
    """Yksinäiset kokonaisluvut sivun ensimmäisiltä ja viimeisiltä riveiltä."""
    rivit = [r for r in sivu.splitlines() if r.strip()]
    reunat = rivit[:RIVEJA_REUNALLA] + rivit[-RIVEJA_REUNALLA:]
    luvut = set()
    for rivi in reunat:
        m = SIVUNUMERO_RE.match(rivi)
        if m:
            luvut.add(int(m.group(1)))
    return luvut


def paattele_aloitussivu(sivut: list[str]) -> tuple[int | None, str]:
    """Painettu sivunumero PDF:n sivulla 1 tai (None, syy).

    Jokainen sivun i (1-pohjainen) ehdokasluku n antaa äänen aloitussivulle n - i + 1.
    Hyväksytään, jos yksi aloitussivu saa selvästi eniten ääniä (vähintään 2 ja
    vähintään 40 % sivuista), eli luvut kasvavat yhdellä sivulta toiselle.
    """
    if len(sivut) < 2:
        return None, "liian vähän sivuja sivunumeroiden päättelyyn"
    aanet: Counter[int] = Counter()
    for i, sivu in enumerate(sivut, 1):
        for n in sivunumeroehdokkaat(sivu):
            aanet[n - i + 1] += 1
    if not aanet:
        return None, "PDF:stä ei löytynyt yksinäisiä sivunumeroita"
    (paras, maara), *loput = aanet.most_common(2)
    if maara < 2 or maara < 0.4 * len(sivut):
        return None, f"sivunumeroita löytyi vain {maara}/{len(sivut)} sivulta peräkkäisinä"
    if loput and loput[0][1] == maara:
        return None, "sivunumerot tulkittavissa usealla tavalla"
    if paras < 1:
        return None, f"sivunumeroista saatu aloitussivu {paras} (kansilehti tai muu poikkeama)"
    return paras, ""


def crossrefin_alkusivu(sivut: str) -> int | None:
    m = re.match(r"\s*(\d+)", sivut or "")
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------
# Rakennus
# --------------------------------------------------------------------------

def rakenna_rivi(tiedosto: str, teksti: str, crossref: Crossref) -> tuple[Lahde, dict]:
    """Rakentaa yhden rivin. Palauttaa (lähde, tilasto: doi/crossref/aloitussivu/ristiriita)."""
    tila = {"doi": False, "crossref": False, "aloitussivu": False, "ristiriita": False}
    lahde = Lahde(tiedosto=tiedosto)
    huomiot: list[str] = []
    if not teksti.strip():
        lahde.huomio = "RAGin source_text on tyhjä; tiedot syötettävä käsin"
        return lahde, tila
    sivut = teksti.split("\f")

    doi, muut = etsi_doi(sivut)
    cr_sivut = ""
    if doi:
        tila["doi"] = True
        lahde.doi = doi
        if muut:
            huomiot.append("Useita DOI-ehdokkaita kahdella ensimmäisellä sivulla (valittu ensimmäinen): "
                           + ", ".join(muut[:3]))
        viesti, virhe = crossref.hae(doi)
        if viesti:
            tila["crossref"] = True
            huomiot += tayta_crossrefista(lahde, viesti)
            cr_sivut = lahde.sivut
        else:
            huomiot.append(f"{virhe}: {doi}")
    else:
        huomiot.append("DOI:ta ei löytynyt kahdelta ensimmäiseltä sivulta; tiedot syötettävä käsin")

    paattely, syy = paattele_aloitussivu(sivut)
    cr_alku = crossrefin_alkusivu(cr_sivut)
    if paattely is not None:
        if cr_alku is None:
            lahde.aloitussivu = paattely
            tila["aloitussivu"] = True
            if tila["crossref"]:
                huomiot.append("Crossrefillä ei sivuja vertailuun")
        elif cr_alku == paattely:
            lahde.aloitussivu = paattely
            tila["aloitussivu"] = True
        elif re.fullmatch(r"\d+", cr_sivut.strip()):
            # Yksittäinen luku Crossrefin page-kentässä on usein artikkelinumero (esim. Elsevier, Frontiers)
            lahde.aloitussivu = paattely
            tila["aloitussivu"] = True
            if not lahde.artikkelinumero:
                lahde.artikkelinumero = cr_sivut.strip()
            lahde.sivut = ""
            huomiot.append(f"Crossrefin sivu '{cr_sivut}' on yksittäinen luku (tulkittu artikkelinumeroksi); "
                           f"PDF:n sivutus alkaa luvusta {paattely}")
        else:
            tila["ristiriita"] = True
            huomiot.append(f"Aloitussivu ja Crossrefin sivut ristiriidassa: PDF:stä päätelty {paattely}, "
                           f"Crossref {cr_sivut}; aloitussivua ei asetettu")
    else:
        huomiot.append(f"Aloitussivua ei päätelty: {syy}"
                       + (f"; Crossrefin sivut {cr_sivut}" if cr_sivut else ""))
    lahde.huomio = "; ".join(huomiot)
    return lahde, tila


def md_solu(teksti: str) -> str:
    return teksti.replace("|", "\\|").replace("\n", " ")


def md_rivi(lahde: Lahde) -> str:
    if not (lahde.tekijat or lahde.otsikko):
        return "(ei tietoja)"
    return "".join(f"*{t}*" if k else t for t, k in lahdeluettelorivi(lahde))


def kirjoita_tarkistus(lahteet: dict[str, Lahde], polku: Path) -> None:
    rivit = [
        "# Lähderekisterin tarkistus",
        "",
        "Rivit tulevat Crossrefistä ja PDF:n sivunumeroista. Tarkista jokainen rivi ja aseta `tarkistettu: true` "
        "tiedostossa `lahteet.json`; tarkistettuja rivejä uusi ajo ei ylikirjoita. "
        "Tähdet (`*…*`) tarkoittavat kursiivia.",
        "",
        "| Tiedosto | Lähdeluettelorivi | Aloitussivu | Tark. | Huomio |",
        "|---|---|---|---|---|",
    ]
    for tiedosto, l in sorted(lahteet.items(), key=lambda kv: lajitteluavain(kv[1])):
        rivit.append("| " + " | ".join([
            md_solu(tiedosto), md_solu(md_rivi(l)),
            "" if l.aloitussivu is None else str(l.aloitussivu),
            "kyllä" if l.tarkistettu else "ei", md_solu(l.huomio),
        ]) + " |")
    polku.write_text("\n".join(rivit) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rag-url", default=OLETUS_RAG_URL)
    p.add_argument("--json", type=Path, default=JUURI / "lahteet.json")
    p.add_argument("--tarkistus", type=Path, default=JUURI / "lahteet-tarkistus.md")
    a = p.parse_args()
    if not a.rag_url:
        print("Ympäristömuuttuja RAG_URL puuttuu (RAG-palvelun perusosoite).", file=sys.stderr)
        return 2

    avain = os.environ.get("RAG_API_KEY")
    if not avain:
        print("Ympäristömuuttuja RAG_API_KEY puuttuu.", file=sys.stderr)
        return 2

    vanhat = lataa_lahteet(a.json) if a.json.exists() else {}
    rag = Rag(a.rag_url, avain)
    crossref = Crossref()
    tiedostot = sorted(rag.tiedostot(), key=lambda f: f["tiedosto"])
    print(f"RAGissa {len(tiedostot)} tiedostoa.")

    lahteet: dict[str, Lahde] = {}
    summa = Counter()
    tyhjat: list[str] = []
    for i, f in enumerate(tiedostot, 1):
        nimi = f["tiedosto"]
        if nimi in vanhat and vanhat[nimi].tarkistettu:
            lahteet[nimi] = vanhat[nimi]
            summa["sailytetty"] += 1
            print(f"[{i}/{len(tiedostot)}] {nimi}: tarkistettu, säilytetään")
            continue
        try:
            teksti = rag.lahdeteksti(f["id"])
            lahde, tila = rakenna_rivi(nimi, teksti, crossref)
        except Exception as e:  # yksi tiedosto ei kaada koko ajoa
            lahde, tila = Lahde(tiedosto=nimi, huomio=f"Käsittely epäonnistui: {type(e).__name__}"), {}
        if nimi in vanhat and vanhat[nimi].aineisto:     # käsin kirjoitettu, ei tule Crossrefistä
            lahde.aineisto = vanhat[nimi].aineisto
        lahteet[nimi] = lahde
        summa["tiedostoja"] += 1
        for avain_, arvo in tila.items():
            summa[avain_] += int(arvo)
        if not (lahde.tekijat or lahde.otsikko):
            tyhjat.append(nimi)
        print(f"[{i}/{len(tiedostot)}] {nimi}: DOI {'kyllä' if tila.get('doi') else 'ei'}, "
              f"Crossref {'kyllä' if tila.get('crossref') else 'ei'}, "
              f"aloitussivu {lahde.aloitussivu if lahde.aloitussivu is not None else '–'}"
              + (", RISTIRIITA" if tila.get("ristiriita") else ""))

    tallenna_lahteet(lahteet, a.json)
    kirjoita_tarkistus(lahteet, a.tarkistus)
    print("\nYHTEENVETO")
    print(f"  Tiedostoja RAGissa: {len(tiedostot)} (uudelleen rakennettu {summa['tiedostoja']}, "
          f"tarkistettuina säilytetty {summa['sailytetty']})")
    print(f"  DOI löytyi: {summa['doi']}, Crossref-osuma: {summa['crossref']}")
    print(f"  Aloitussivu löytyi: {summa['aloitussivu']}, ristiriitoja: {summa['ristiriita']}")
    print(f"  Ilman tekijä- ja otsikkotietoja: {len(tyhjat)}" + (f" ({', '.join(tyhjat)})" if tyhjat else ""))
    print(f"  Kirjoitettu: {a.json}, {a.tarkistus}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
