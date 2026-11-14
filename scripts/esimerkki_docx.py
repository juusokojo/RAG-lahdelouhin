#!/usr/bin/env python3
"""Esimerkki: keksitystä datasta docx-tiedosto, jolla tarkistetaan asettelu.

Data on keksittyä: lähteet ovat kuvitteellisia, eikä mitään tekstiä ole artikkeleista.
Tuloksena tulokset/esimerkki.docx: 2 ryhmää, 3 kysymystä, joista yksi ilman vastausta,
ja yksi sumeasti paikannettu lainaus.

Käyttö (projektin juuresta):
    .venv/bin/python -I scripts/esimerkki_docx.py
"""
from __future__ import annotations

import sys
from pathlib import Path

JUURI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(JUURI))          # -I-tilassa projektin juuri ei ole polussa

from louhinta.docx_tulostus import kirjoita_docx  # noqa: E402
from louhinta.mallit import (  # noqa: E402
    Kysymys, Lahde, Loydos, Osio, Patteri, Tekija, Vastaus,
)


def esimerkkidata() -> tuple[Patteri, list[Vastaus], dict[str, Lahde]]:
    lahteet = {
        "esimerkki_a_2020.pdf": Lahde(
            tiedosto="esimerkki_a_2020.pdf",
            tekijat=[Tekija("Keksitty", "Aino"), Tekija("Kuvitelma", "Veli")],
            vuosi="2020", otsikko="Kuvitteellinen tutkimus vuorovaikutuksesta",
            julkaisu="Kuvitteellinen aikakauslehti", vuosikerta="6", numero="3",
            sivut="164–171", doi="10.0000/keksitty.2020.001", aloitussivu=164,
        ),
        "esimerkki_b_2018.pdf": Lahde(
            tiedosto="esimerkki_b_2018.pdf",
            tekijat=[Tekija("Fiktiivinen", "B.")],
            vuosi="2018", otsikko="Oletettu raportti harjoittelusta",
            julkaisu="Oletettu kustantaja", aloitussivu=None,
            tyyppi="raportti", kustantaja="Oletettu kustantaja",
        ),
    }
    patteri = Patteri(
        tehtava="Keksitty tehtävänanto esimerkkidokumentille.",
        saannot=["Käytä vain keksittyjä lähteitä."],
        rakenne=["Ryhmä ja kysymykset."],
        kysymykset=[
            Kysymys(1, "K1", "Ensimmäinen ryhmä", ["P"], "Ensimmäinen esimerkkikysymys?"),
            Kysymys(2, "K1", "Ensimmäinen ryhmä", ["J", "E"], "Toinen esimerkkikysymys?"),
            Kysymys(3, "K2", "Toinen ryhmä", [], "Kolmas esimerkkikysymys, johon ei löydy vastausta?"),
        ],
    )
    vastaukset = [
        Vastaus(
            kysymys_nro=1,
            osiot=[
                Osio("LÄHDE SANOO", "Keksitty väite, joka perustuu [L1].\n\nToinen kappale [L2]."),
                Osio("EHDOTUS VIDEOON", "Käytä esimerkin mukaisesti [L1]."),
            ],
            loydokset=[
                Loydos("L1", 1, "id-a", "esimerkki_a_2020.pdf", "Keksitty väite A:sta",
                       "Tämä on keksitty lainaus lähteestä A.", 3, 3,
                       nayton_vahvuus="kohtalainen", tapa="tarkka"),
                Loydos("L2", 1, "id-b", "esimerkki_b_2018.pdf", "Keksitty väite B:stä",
                       "Tämä on toinen keksitty lainaus lähteestä B.", 2, 2,
                       nayton_vahvuus="asiantuntijan näkemys", siirretty_alalta="hoitotyö",
                       tapa="sumea"),
            ],
            huomiot=["Esimerkkihuomio: lähde on keksitty"],
        ),
        Vastaus(
            kysymys_nro=2,
            osiot=[Osio("", "Vastaus ilman erillisiä osioita, viittaa [L1].")],
            loydokset=[
                Loydos("L1", 2, "id-a", "esimerkki_a_2020.pdf", "Toinen väite A:sta",
                       "Toinen keksitty lainaus.", 7, 8, nayton_vahvuus="vahva", tapa="tarkka"),
            ],
        ),
        Vastaus(kysymys_nro=3, ei_vastausta=True),
    ]
    return patteri, vastaukset, lahteet


def main() -> int:
    patteri, vastaukset, lahteet = esimerkkidata()
    polku = JUURI / "tulokset" / "esimerkki.docx"
    kirjoita_docx(patteri, vastaukset, lahteet, polku, otsikko="Esimerkkikoonti")
    print(f"Kirjoitettu: {polku}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
