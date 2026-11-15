"""Lähderekisteri ja suomenkielinen APA7-muotoilu. Selitykset: docs/maarittely.md (1A).

Rekisteri on JSON-tiedosto (lahteet.json), jonka avaimena on RAGin tiedostonimi.
Muotoilu on puhdasta merkkijonotyötä: ei verkkoa, ei tekoälyä.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, fields
from pathlib import Path
from typing import Iterable

from louhinta.mallit import Lahde, Tekija

ENINTAAN_TEKIJOITA = 20     # APA7: enintään 20 tekijää kokonaan
NAYTETTAVIA_PITKASSA = 19   # 21+ tekijää: 19 ensimmäistä, …, viimeinen


# ---------------------------------------------------------------- lataus ja tallennus

def _tekija(d: dict) -> Tekija:
    return Tekija(suku=d.get("suku", ""), etu=d.get("etu", ""))


def _lahde(d: dict) -> Lahde:
    nimet = {f.name for f in fields(Lahde)}
    arvot = {k: v for k, v in d.items() if k in nimet}
    arvot["tekijat"] = [_tekija(t) for t in d.get("tekijat", [])]
    arvot["toimittajat"] = [_tekija(t) for t in d.get("toimittajat", [])]
    return Lahde(**arvot)


def lataa_lahteet(polku: Path) -> dict[str, Lahde]:
    """Lukee rekisterin. Avain = tiedosto."""
    raaka = json.loads(Path(polku).read_text(encoding="utf-8"))
    return {avain: _lahde(rivi) for avain, rivi in raaka.items()}


def tallenna_lahteet(lahteet: dict[str, Lahde], polku: Path) -> None:
    polku = Path(polku)
    polku.parent.mkdir(parents=True, exist_ok=True)
    raaka = {avain: asdict(lahde) for avain, lahde in lahteet.items()}
    polku.write_text(json.dumps(raaka, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- sivut ja vuositunnukset

def painettu_sivu(lahde: Lahde, pdf_sivu: int) -> int | None:
    """Painettu sivu tai None, jos aloitussivua ei tiedetä tai tulos olisi < 1.

    Aloitussivu saa olla nolla tai negatiivinen (kirjan alussa numeroimattomia sivuja);
    numeroimattomalle sivulle ei ole painettua sivunumeroa, joten viitteeseen tulee PDF-sivu.
    """
    if lahde.aloitussivu is None:
        return None
    sivu = lahde.aloitussivu + pdf_sivu - 1
    return sivu if sivu >= 1 else None


def _poista_tarkkeet(teksti: str) -> str:
    erotettu = unicodedata.normalize("NFKD", teksti)
    return "".join(m for m in erotettu if not unicodedata.combining(m)).casefold()


def _tekijoiden_avain(lahde: Lahde) -> tuple:
    return tuple((_poista_tarkkeet(t.suku), _poista_tarkkeet(t.etu)) for t in lahde.tekijat)


def _vuosi(lahde: Lahde) -> str:
    return lahde.vuosi.strip() or "n.d."


def vuositunnukset(lahteet: Iterable[Lahde]) -> dict[str, str]:
    """tiedosto -> "2020"; sama tekijäjoukko ja vuosi → "2020a", "2020b" otsikon aakkosjärjestyksessä."""
    ryhmat: dict[tuple, list[Lahde]] = {}
    for lahde in lahteet:
        ryhmat.setdefault((_tekijoiden_avain(lahde), _vuosi(lahde)), []).append(lahde)
    tulos: dict[str, str] = {}
    for (_, vuosi), jasenet in ryhmat.items():
        if len(jasenet) == 1:
            tulos[jasenet[0].tiedosto] = vuosi
            continue
        jasenet.sort(key=lambda l: (_poista_tarkkeet(l.otsikko), l.tiedosto))
        for i, lahde in enumerate(jasenet):
            kirjain = chr(ord("a") + i) if i < 26 else str(i + 1)
            tulos[lahde.tiedosto] = f"{vuosi}-{kirjain}" if vuosi == "n.d." else f"{vuosi}{kirjain}"
    return tulos


# ---------------------------------------------------------------- tekstiviite

def _tiedostonimi_ilman_paatetta(lahde: Lahde) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,5}$", "", lahde.tiedosto)


def _tekstiviitteen_tekijat(lahde: Lahde) -> str:
    sukunimet = [t.suku for t in lahde.tekijat]
    if not sukunimet:
        return lahde.otsikko or _tiedostonimi_ilman_paatetta(lahde)
    if len(sukunimet) == 1:
        return sukunimet[0]
    if len(sukunimet) == 2:
        return f"{sukunimet[0]} & {sukunimet[1]}"
    return f"{sukunimet[0]} ym."


def _sivuviite(lahde: Lahde, alku: int, loppu: int) -> str:
    a, b = painettu_sivu(lahde, alku), painettu_sivu(lahde, loppu)
    if a is None or b is None:      # aloitussivu tuntematon tai sivu ilman painettua numeroa
        if alku == loppu:
            return f"PDF-sivu {alku}"
        return f"PDF-sivut {alku}–{loppu}"
    return f"s. {a}" if a == b else f"ss. {a}–{b}"


def tekstiviite(lahde: Lahde, pdf_sivu_alku: int, pdf_sivu_loppu: int, vuosi: str | None = None) -> str:
    vuosi = vuosi or _vuosi(lahde)
    return f"({_tekstiviitteen_tekijat(lahde)}, {vuosi}, {_sivuviite(lahde, pdf_sivu_alku, pdf_sivu_loppu)})"


def _sivuyksikko(lahde: Lahde, alku: int, loppu: int, painettu: bool) -> tuple[int, int]:
    if painettu:
        return painettu_sivu(lahde, alku), painettu_sivu(lahde, loppu)
    return alku, loppu


def _sivut_yhdistettyna(lahde: Lahde, sivut: list[tuple[int, int]]) -> str:
    """Saman lähteen PDF-sivuvälit -> "s. 78", "ss. 78, 83" tai "ss. 78–79, 83"; nousevasti, ei toistoja."""
    painettu = all(painettu_sivu(lahde, a) is not None and painettu_sivu(lahde, b) is not None
                   for a, b in sivut)
    yksikot = sorted({_sivuyksikko(lahde, a, b, painettu) for a, b in sivut})
    # yksittäinen sivu, joka sisältyy johonkin sivuväliin, jätetään pois
    yksikot = [(a, b) for a, b in yksikot
               if not (a == b and any(c <= a <= d and (c, d) != (a, b) for c, d in yksikot))]
    osat = [str(a) if a == b else f"{a}–{b}" for a, b in yksikot]
    if painettu:
        return ("s. " if len(yksikot) == 1 and yksikot[0][0] == yksikot[0][1] else "ss. ") + ", ".join(osat)
    return ("PDF-sivu " if len(yksikot) == 1 and yksikot[0][0] == yksikot[0][1] else "PDF-sivut ") + ", ".join(osat)


def yhdista_tekstiviitteet(viitteet: list[tuple[Lahde, int, int]], vuodet: dict[str, str] | None = None) -> str:
    """Peräkkäiset viitteet yhdeksi: "(Page-Cutrara & Turk, 2017, ss. 78, 83)".

    viitteet: (lähde, PDF-sivu alku, PDF-sivu loppu). Sama lähde yhdistetään (sivut nousevassa
    järjestyksessä, sama sivu kerran); eri lähteet erotetaan puolipisteellä aakkosjärjestyksessä:
    "(Kolbe ym., 2020, s. 168; Sinha & Kapur, 2021, s. 761)".
    """
    vuodet = vuodet or {}
    ryhmat: dict[str, tuple[Lahde, list[tuple[int, int]]]] = {}
    for lahde, alku, loppu in viitteet:
        ryhmat.setdefault(lahde.tiedosto, (lahde, []))[1].append((alku, loppu))
    jarjestetty = sorted(ryhmat.values(), key=lambda r: (lajitteluavain(r[0]), vuodet.get(r[0].tiedosto, _vuosi(r[0]))))
    osat = [f"{_tekstiviitteen_tekijat(l)}, {vuodet.get(l.tiedosto) or _vuosi(l)}, {_sivut_yhdistettyna(l, sivut)}"
            for l, sivut in jarjestetty]
    return "(" + "; ".join(osat) + ")"


def lyhytviite(lahde: Lahde, vuosi: str | None = None) -> str:
    """Viite ilman sivua ja sulkeita: "Kolbe ym., 2020"."""
    return f"{_tekstiviitteen_tekijat(lahde)}, {vuosi or _vuosi(lahde)}"


# ---------------------------------------------------------------- lähdeluettelo

def nimikirjaimet(etunimet: str) -> str:
    """"Jean-Luc" -> "J.-L.", "Mary Jane" -> "M. J.", "M.J." -> "M. J."."""
    etunimet = re.sub(r"\.(?=\w)", ". ", etunimet.strip())
    sanat = []
    for sana in etunimet.split():
        kirjaimet = [pala.strip(".")[:1].upper() for pala in sana.split("-") if pala.strip(".")]
        if kirjaimet:
            sanat.append("-".join(k + "." for k in kirjaimet))
    return " ".join(sanat)


def _tekija_luettelossa(t: Tekija) -> str:
    return f"{t.suku}, {nimikirjaimet(t.etu)}" if t.etu.strip() else t.suku


def _tekijat_luettelossa(tekijat: list[Tekija]) -> str:
    nimet = [_tekija_luettelossa(t) for t in tekijat]
    n = len(nimet)
    if n == 0:
        return ""
    if n == 1:
        return nimet[0]
    if n > ENINTAAN_TEKIJOITA:
        return ", ".join(nimet[:NAYTETTAVIA_PITKASSA]) + ", … " + nimet[-1]
    return ", ".join(nimet[:-1]) + ", & " + nimet[-1]


def _toimittajat(toimittajat: list[Tekija]) -> str:
    nimet = [f"{nimikirjaimet(t.etu)} {t.suku}".strip() for t in toimittajat]
    if len(nimet) <= 2:
        nimilista = " & ".join(nimet)
    else:
        nimilista = ", ".join(nimet[:-1]) + ", & " + nimet[-1]
    return f"{nimilista} (toim.)"


def _sivut(sivut: str) -> str:
    return re.sub(r"(?<=\d)\s*[-‐‑–—]+\s*(?=\d)", "–", sivut.strip())


def _piste(teksti: str) -> str:
    teksti = teksti.strip()
    return teksti if teksti.endswith((".", "?", "!")) else teksti + "."


class _Rivi:
    """Kokoaa (teksti, kursiivi)-pätkät ja yhdistää vierekkäiset samanlaiset."""

    def __init__(self) -> None:
        self.osat: list[tuple[str, bool]] = []

    def lisaa(self, teksti: str, kursiivi: bool = False) -> None:
        if not teksti:
            return
        if self.osat and self.osat[-1][1] == kursiivi:
            self.osat[-1] = (self.osat[-1][0] + teksti, kursiivi)
        else:
            self.osat.append((teksti, kursiivi))

    def valmis(self) -> list[tuple[str, bool]]:
        if self.osat:
            teksti, kursiivi = self.osat[-1]
            self.osat[-1] = (teksti.rstrip(), kursiivi)
        return self.osat


def _linkki(lahde: Lahde) -> str:
    if lahde.doi:
        doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", lahde.doi.strip())
        return f"https://doi.org/{doi}"
    return lahde.url.strip()


def lahdeluettelorivi(lahde: Lahde, vuosi: str | None = None) -> list[tuple[str, bool]]:
    """APA7-rivi pätkinä (teksti, kursiivi). Pätkien liittäminen antaa koko rivin."""
    vuosi = vuosi or _vuosi(lahde)
    r = _Rivi()
    tyyppi = lahde.tyyppi
    otsikko = _piste(lahde.otsikko) if lahde.otsikko else ""
    kirjamainen = tyyppi in ("kirja", "raportti", "verkkosivu")

    # Alku: tekijät ja vuosi. Ilman tekijöitä otsikko siirtyy tekijän paikalle.
    if lahde.tekijat:
        r.lisaa(_piste(_tekijat_luettelossa(lahde.tekijat)) + f" ({vuosi}). ")
    elif kirjamainen and lahde.otsikko:
        r.lisaa(_piste(lahde.otsikko), True)
        r.lisaa(f" ({vuosi}). ")
    else:       # ei tekijöitä eikä otsikkoa (rekisterin tyhjä rivi): tiedostonimi ilman päätettä
        r.lisaa((otsikko or _piste(_tiedostonimi_ilman_paatetta(lahde))) + f" ({vuosi}). ")

    if tyyppi == "artikkeli":
        if lahde.tekijat and otsikko:
            r.lisaa(otsikko + " ")
        if lahde.julkaisu:
            r.lisaa(lahde.julkaisu, True)
            if lahde.vuosikerta:
                r.lisaa(", ")
                r.lisaa(lahde.vuosikerta, True)
            if lahde.numero:
                r.lisaa(f"({lahde.numero})")
            sijainti = _sivut(lahde.sivut) or lahde.artikkelinumero
            if sijainti:
                r.lisaa(f", {sijainti}")
            r.lisaa(". ")
    elif tyyppi == "luku":
        if lahde.tekijat and otsikko:
            r.lisaa(otsikko + " ")
        r.lisaa("Teoksessa ")
        if lahde.toimittajat:
            r.lisaa(_toimittajat(lahde.toimittajat) + ", ")
        if lahde.julkaisu:
            r.lisaa(lahde.julkaisu, True)
        sivut = _sivut(lahde.sivut)
        if sivut:
            etuliite = "ss." if "–" in sivut else "s."
            r.lisaa(f" ({etuliite} {sivut})")
        r.lisaa(". ")
        if lahde.kustantaja:
            r.lisaa(_piste(lahde.kustantaja) + " ")
    else:  # kirja, raportti, verkkosivu
        if lahde.tekijat and lahde.otsikko:
            r.lisaa(_piste(lahde.otsikko), True)
            r.lisaa(" ")
        if tyyppi == "verkkosivu" and lahde.julkaisu:
            r.lisaa(_piste(lahde.julkaisu) + " ")
        if lahde.kustantaja and lahde.kustantaja != lahde.julkaisu \
                and lahde.kustantaja not in [t.suku for t in lahde.tekijat]:
            r.lisaa(_piste(lahde.kustantaja) + " ")

    r.lisaa(_linkki(lahde))
    return r.valmis()


# ---------------------------------------------------------------- lajittelu

def lajitteluavain(lahde: Lahde) -> tuple:
    """Ensimmäisen tekijän sukunimi, muut tekijät, vuosi; kirjainkoosta ja tarkkeista riippumatta.

    Ilman tekijöitä lajitellaan otsikon mukaan. Vuosi "n.d." menee ennen vuosilukuja.
    """
    tekijat = _tekijoiden_avain(lahde) or ((_poista_tarkkeet(lahde.otsikko), ""),)
    vuosi = _vuosi(lahde)
    return (tekijat, "" if vuosi == "n.d." else vuosi, _poista_tarkkeet(lahde.otsikko))
