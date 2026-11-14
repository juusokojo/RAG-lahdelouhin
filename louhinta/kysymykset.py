"""Kysymystiedoston jäsennin. Muoto: docs/maarittely.md, kohta 1C."""
from __future__ import annotations

import re
from pathlib import Path

from louhinta.mallit import Kysymys, Patteri

TEHTAVA = "TEHTÄVÄ"
SAANNOT = "SÄÄNNÖT"
RAKENNE = "RAPORTIN RAKENNE"
KYSYMYSPATTERI = "KYSYMYSPATTERI"

OSIO_RE = re.compile(r"^(TEHTÄVÄ|SÄÄNNÖT|RAPORTIN RAKENNE|KYSYMYSPATTERI)\b(.*)$")
RYHMA_RE = re.compile(r"^([A-ZÄÖÅ]\d+)\.\s+(\S.*)$")
KOHTA_RE = re.compile(r"^(\d+)\.\s*(.*)$")
MERKINNAT_RE = re.compile(r"^\(([A-ZÄÖÅ](?:\s*,\s*[A-ZÄÖÅ])*)\)\s*(.*)$")


def _yhdista(alku: str, lisa: str) -> str:
    """Liittää jatkorivin. Alaluettelon kohta (alkaa "- ") jää omalle rivilleen."""
    if lisa.startswith("- "):
        return f"{alku}\n{lisa}"
    return f"{alku} {lisa}"


def lue_patteri(polku: Path) -> Patteri:
    rivit = polku.read_text(encoding="utf-8").splitlines()

    tehtava: list[str] = []
    saannot: list[str] = []
    rakenne: list[str] = []
    kysymykset: list[Kysymys] = []
    nahdyt: dict[int, int] = {}         # kysymysnumero -> rivinumero
    osio: str | None = None             # None ennen ensimmäistä otsikkoa
    ryhma, ryhma_otsikko = "K1", "Kysymykset"
    ryhma_nahty = False
    kysymys: Kysymys | None = None      # viimeisin kysymys, jatkorivit kuuluvat siihen

    for rivinro, rivi in enumerate(rivit, 1):
        if not rivi.strip():
            continue

        # Sisennetty rivi on jatkorivi edelliseen kohtaan.
        if rivi[0].isspace():
            lisa = rivi.strip()
            kohdat = saannot if osio == SAANNOT else rakenne if osio == RAKENNE else None
            if kohdat:
                kohdat[-1] = _yhdista(kohdat[-1], lisa)
            elif kysymys is not None:
                kysymys.teksti = _yhdista(kysymys.teksti, lisa)
            elif osio == TEHTAVA:
                tehtava.append(lisa)
            else:
                raise ValueError(f"rivi {rivinro}: sisennetty rivi ilman edeltävää kohtaa")
            continue

        otsikko = OSIO_RE.match(rivi)
        if otsikko:
            osio = otsikko.group(1)
            kysymys = None
            jaannos = otsikko.group(2).lstrip(": ").strip()
            if osio == TEHTAVA and jaannos:
                tehtava.append(jaannos)
            continue

        ryhma_rivi = RYHMA_RE.match(rivi)
        if ryhma_rivi:
            ryhma, ryhma_otsikko = ryhma_rivi.group(1), ryhma_rivi.group(2).strip()
            ryhma_nahty = True
            osio = KYSYMYSPATTERI
            kysymys = None
            continue

        kohta = KOHTA_RE.match(rivi)
        if osio in (None, KYSYMYSPATTERI) and kohta:
            nro = int(kohta.group(1))
            if nro in nahdyt:
                raise ValueError(f"rivi {rivinro}: kysymys {nro} on jo rivillä {nahdyt[nro]}")
            nahdyt[nro] = rivinro
            merkinnat: list[str] = []
            teksti = kohta.group(2).strip()
            merkki = MERKINNAT_RE.match(teksti)
            if merkki:
                merkinnat = [m.strip() for m in merkki.group(1).split(",")]
                teksti = merkki.group(2).strip()
            if not teksti:
                raise ValueError(f"rivi {rivinro}: kysymys {nro} ei sisällä tekstiä")
            kysymys = Kysymys(nro, ryhma, ryhma_otsikko, merkinnat, teksti)
            kysymykset.append(kysymys)
            osio = KYSYMYSPATTERI
            continue

        if osio == TEHTAVA:
            tehtava.append(rivi.strip())
        elif osio in (SAANNOT, RAKENNE):
            kohdat = saannot if osio == SAANNOT else rakenne
            kohta = KOHTA_RE.match(rivi.strip())
            if rivi.strip()[0].isdigit() and kohta:
                kohdat.append(kohta.group(2).strip())
            elif kohdat:
                kohdat[-1] = _yhdista(kohdat[-1], rivi.strip())
            else:
                raise ValueError(f"rivi {rivinro}: odottamaton rivi ennen ensimmäistä kohtaa")
        elif ryhma_nahty or kysymys is not None:
            raise ValueError(f"rivi {rivinro}: tunnistamaton rivi kysymysten joukossa: {rivi.strip()!r}")
        # muuten: kysymyspatterin johdantokappale ennen ensimmäistä ryhmää, ohitetaan

    if not kysymykset:
        raise ValueError(f"{polku.name}: tiedostosta ei löydy yhtään kysymystä")

    return Patteri(
        tehtava=" ".join(tehtava),
        saannot=saannot,
        rakenne=rakenne,
        kysymykset=kysymykset,
    )
