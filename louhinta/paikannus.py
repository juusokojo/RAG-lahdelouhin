"""Lainauksen paikannus lähdetekstiin.

Takuu: Paikannus.lainaus on aina siisti(source_text[alku:loppu]), eli leikattu
lähdetekstistä, ei koskaan kielimallin ehdotuksesta. Ehdotusta käytetään vain
hakuavaimena. Selitykset: docs/maarittely.md, kohta 1B.

Vertailu tehdään normalisoidulla tekstillä (NFKC, pienaakkoset, vain kirjaimet
ja numerot). Normalisoinnin mukana kulkee indeksikartta, joka vie jokaisen
normalisoidun merkin takaisin alkuperäisen tekstin kohtaan, myös kun NFKC
muuttaa merkkimäärää (ﬁ -> fi).
"""
from __future__ import annotations

import re
import unicodedata
from bisect import bisect_left
from functools import lru_cache
from typing import NamedTuple

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from louhinta.mallit import Paikannus

# Mallin lyhentämän lainauksen katkokohdat: [...], [ … ], ... ja …
_KATKO = re.compile(r"\[\s*(?:\.{3}|…)\s*\]|\.{3}|…")
# Rivin lopun tavutus: kirjain, viiva, rivinvaihto (tai sivunvaihto)
_TAVUTUS = re.compile(r"(?<=[^\W\d_])-[ \t]*(?:\r?\n|\f)[ \t]*(?=\S)")


class _Kartta(NamedTuple):
    norm: str                # normalisoitu teksti
    alut: list[int]          # norm[i]:n alkukohta alkuperäisessä tekstissä
    loput: list[int]         # norm[i]:tä vastaavan alkuperäisen merkkiryhmän loppu (ei mukana)
    sivunvaihdot: list[int]  # \f-merkkien indeksit alkuperäisessä tekstissä


def _normalisoi_kartalla(teksti: str) -> tuple[str, list[int], list[int]]:
    """Normalisoi tekstin ja palauttaa indeksikartan alkuperäiseen tekstiin.

    Teksti käsitellään ryhminä (perusmerkki + yhdistävät merkit), jotta NFKC
    yhdistää tarkkeet samoin kuin koko merkkijonoon sovellettuna. Jokainen
    ryhmän tuottama normalisoitu merkki saa ryhmän alun ja lopun.
    """
    norm: list[str] = []
    alut: list[int] = []
    loput: list[int] = []
    n = len(teksti)
    i = 0
    while i < n:
        c = teksti[i]
        j = i + 1
        if c < "\x80" and (j == n or teksti[j] < "\x80"):   # nopea polku: ASCII ei yhdisty
            if c.isalnum():
                norm.append(c.lower())
                alut.append(i)
                loput.append(j)
            i = j
            continue
        while j < n and unicodedata.combining(teksti[j]):
            j += 1
        for m in unicodedata.normalize("NFKC", teksti[i:j]).lower():
            if m.isalnum():
                norm.append(m)
                alut.append(i)
                loput.append(j)
        i = j
    return "".join(norm), alut, loput


def normalisoi(teksti: str) -> str:
    """Pelkät kirjaimet ja numerot pienaakkosina (ilman indeksikarttaa)."""
    return _normalisoi_kartalla(teksti)[0]


@lru_cache(maxsize=16)
def _kartta(source_text: str) -> _Kartta:
    """Lähdetekstin normalisointi tehdään kerran per teksti."""
    norm, alut, loput = _normalisoi_kartalla(source_text)
    sivunvaihdot = [m.start() for m in re.finditer("\f", source_text)]
    return _Kartta(norm, alut, loput, sivunvaihdot)


def sivu(source_text: str, indeksi: int) -> int:
    """1-pohjainen PDF-sivu: 1 + \\f-merkkien määrä ennen indeksiä."""
    return 1 + source_text.count("\f", 0, max(indeksi, 0))


def siisti(teksti: str) -> str:
    """Näyttömuoto: tavutus yhdistetty, tyhjät yhdeksi välilyönniksi, reunat siistitty."""
    def yhdista(m: re.Match) -> str:
        # ei kosketa, jos seuraava rivi alkaa isolla kirjaimella, numerolla tms.
        return "" if m.string[m.end()].islower() else m.group(0)

    teksti = _TAVUTUS.sub(yhdista, teksti)
    return re.sub(r"\s+", " ", teksti).strip()


def _laajenna(t: str, alku: int, loppu: int) -> tuple[int, int]:
    """Laajentaa välin kokonaisiin sanoihin (tavutetut sanat kokonaan)."""
    n = len(t)
    while alku > 0 and not t[alku - 1].isspace():
        alku -= 1
    while loppu < n and not t[loppu].isspace():
        loppu += 1
    # väli päättyy tavuviivaan ja rivinvaihtoon: ota sanan loppuosa mukaan
    if loppu < n and t[loppu - 1] == "-" and loppu >= 2 and t[loppu - 2].isalpha():
        m = re.compile(r"[ \t]*(?:\r?\n|\f)[ \t]*").match(t, loppu)
        if m and m.end() < n and t[m.end()].islower():
            loppu = m.end()
            while loppu < n and not t[loppu].isspace():
                loppu += 1
    # väli alkaa tavutetun sanan jälkiosasta: ota sanan alkuosa mukaan
    if alku > 0 and t[alku].islower() and t[alku - 1].isspace():
        m = re.compile(r"(?<=[^\W\d_])-[ \t]*(?:\r?\n|\f)[ \t]*\Z").search(t, max(alku - 40, 0), alku)
        if m:
            alku = m.start()
            while alku > 0 and not t[alku - 1].isspace():
                alku -= 1
    return alku, loppu


def _leikkaa(source_text: str, k: _Kartta, a: int, b: int, tapa: str, pisteet: float) -> Paikannus:
    """Normalisoitu väli [a, b) -> Paikannus alkuperäisestä tekstistä."""
    alku, loppu = _laajenna(source_text, k.alut[a], k.loput[b - 1])
    return Paikannus(
        lainaus=siisti(source_text[alku:loppu]),
        alku=alku,
        loppu=loppu,
        pdf_sivu_alku=1 + bisect_left(k.sivunvaihdot, alku),
        pdf_sivu_loppu=1 + bisect_left(k.sivunvaihdot, loppu - 1),
        tapa=tapa,
        pisteet=pisteet,
    )


def paikanna_lainaus(ehdotus: str, source_text: str, sumea_raja: float = 92.0,
                     min_pituus: int = 20) -> Paikannus | None:
    """Etsii mallin ehdottaman lainauksen lähdetekstistä ja leikkaa sen sieltä."""
    koko = normalisoi(ehdotus)
    if len(koko) < min_pituus:
        return None
    k = _kartta(source_text)

    i = k.norm.find(koko)
    if i >= 0:
        return _leikkaa(source_text, k, i, i + len(koko), "tarkka", 100.0)

    ehdokas = koko
    osat = [normalisoi(o) for o in _KATKO.split(ehdotus)]
    if len(osat) > 1:                       # mallin lyhentämä lainaus: pisin kelvollinen osa
        ehdokas = max(osat, key=len)
        if len(ehdokas) < min_pituus:
            return None
        i = k.norm.find(ehdokas)
        if i >= 0:
            return _leikkaa(source_text, k, i, i + len(ehdokas), "tarkka", 100.0)

    if len(ehdokas) > len(k.norm):
        return None
    tulos = fuzz.partial_ratio_alignment(ehdokas, k.norm, score_cutoff=sumea_raja)
    if tulos is None or tulos.score < sumea_raja or tulos.dest_end <= tulos.dest_start:
        return None
    alku, loppu = tulos.dest_start, tulos.dest_end
    # partial_ratio:n ikkuna on ehdotuksen mittainen ja voi vuotaa naapurisanaan:
    # leikataan reunoilta merkit, joita ehdotuksessa ei ole
    ops = Levenshtein.opcodes(ehdokas, k.norm[alku:loppu])
    if len(ops) > 1:
        ensin, viimeksi = ops[0], ops[-1]
        if ensin.tag == "insert":
            alku += ensin.dest_end - ensin.dest_start
        if viimeksi.tag == "insert":
            loppu -= viimeksi.dest_end - viimeksi.dest_start
    if loppu <= alku:
        return None
    return _leikkaa(source_text, k, alku, loppu, "sumea", float(tulos.score))


def paikanna_patka(patka: str, source_text: str) -> list[int]:
    """Pätkän PDF-sivut lähdetekstistä; [] jos ei löydy.

    Ensin tarkka osuma. Jos sitä ei ole, käytetään pätkän alku- ja loppuankkureita
    (100 normalisoitua merkkiä), mutta vain jos ankkuri löytyy yksiselitteisesti.
    """
    haettu = normalisoi(patka)
    if not haettu:
        return []
    k = _kartta(source_text)

    def sivut(a: int, b: int) -> set[int]:
        alku = 1 + bisect_left(k.sivunvaihdot, k.alut[a])
        loppu = 1 + bisect_left(k.sivunvaihdot, k.loput[b - 1] - 1)
        return set(range(alku, loppu + 1))

    i = k.norm.find(haettu)
    if i >= 0:
        return sorted(sivut(i, i + len(haettu)))
    ANKKURI = 100
    if len(haettu) < 2 * ANKKURI:
        return []
    loydetyt: set[int] = set()
    for ankkuri in (haettu[:ANKKURI], haettu[-ANKKURI:]):
        j = k.norm.find(ankkuri)
        if j >= 0 and k.norm.find(ankkuri, j + 1) < 0:
            loydetyt |= sivut(j, j + ANKKURI)
    return sorted(loydetyt)
