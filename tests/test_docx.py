"""Testit docx-tulostukselle (louhinta/docx_tulostus.py).

Lähdefunktiot (lahteet.py) korvataan keksityillä korvikkeilla, joten testit toimivat
ilman oikeaa moduulia. Korvikkeet asetetaan sys.modules-sanakirjaan, koska
docx_tulostus tuo funktiot kirjoitushetkellä.
"""
import sys
import types
from pathlib import Path

import pytest
from docx import Document

from louhinta.docx_tulostus import kirjoita_docx
from louhinta.mallit import Kysymys, Lahde, Loydos, Osio, Patteri, Tekija, Vastaus


def _korvikkeet() -> types.ModuleType:
    moduuli = types.ModuleType("louhinta.lahteet")

    def tekstiviite(lahde, pdf_sivu_alku, pdf_sivu_loppu, vuosi=None):
        return f"({lahde.tekijat[0].suku} ym., {vuosi}, s. {pdf_sivu_alku})"

    def lyhytviite(lahde, vuosi=None):
        return f"{lahde.tekijat[0].suku} ym., {vuosi}"

    def vuositunnukset(lahteet):
        return {lahde.tiedosto: lahde.vuosi for lahde in lahteet}

    def lahdeluettelorivi(lahde, vuosi=None):
        return [
            (f"{lahde.tekijat[0].suku}, {vuosi}. {lahde.otsikko}. ", False),
            (lahde.julkaisu, True),
        ]

    def lajitteluavain(lahde):
        return (lahde.tekijat[0].suku.lower(),)

    moduuli.tekstiviite = tekstiviite
    moduuli.lyhytviite = lyhytviite
    moduuli.vuositunnukset = vuositunnukset
    moduuli.lahdeluettelorivi = lahdeluettelorivi
    moduuli.lajitteluavain = lajitteluavain
    return moduuli


@pytest.fixture(autouse=True)
def korvikkeet(monkeypatch):
    monkeypatch.setitem(sys.modules, "louhinta.lahteet", _korvikkeet())


def _lahteet() -> dict[str, Lahde]:
    zeta = Lahde(
        tiedosto="zeta_2019.pdf", tekijat=[Tekija("Zeta", "Z.")], vuosi="2019",
        otsikko="Keksitty otsikko Zeta", julkaisu="Kuvitteellinen Lehti", aloitussivu=10,
    )
    alfa = Lahde(
        tiedosto="alfa_2020.pdf", tekijat=[Tekija("Alfa", "A.")], vuosi="2020",
        otsikko="Keksitty otsikko Alfa", julkaisu="Toinen Lehti", aloitussivu=20,
    )
    return {zeta.tiedosto: zeta, alfa.tiedosto: alfa}


def _patteri() -> Patteri:
    kysymykset = [
        Kysymys(1, "K1", "Ryhmä yksi", ["P"], "Ensimmäinen kysymys?"),
        Kysymys(2, "K1", "Ryhmä yksi", [], "Toinen kysymys, johon ei vastata?"),
        Kysymys(3, "K2", "Ryhmä kaksi", ["J", "E"], "Kolmas kysymys?"),
        Kysymys(4, "K2", "Ryhmä kaksi", [], "Neljäs kysymys, ei ajettu?"),
    ]
    return Patteri(tehtava="Keksitty tehtävänanto.", saannot=[], rakenne=[], kysymykset=kysymykset)


def _vastaukset() -> list[Vastaus]:
    return [
        Vastaus(
            kysymys_nro=1,
            osiot=[
                Osio("LÄHDE SANOO", "Ensimmäinen väite [L1].\n\nToinen väite [L2] ja tuntematon [L9]."),
                Osio("EHDOTUS VIDEOON", "Käytä väitettä [L1]."),
            ],
            loydokset=[
                Loydos("L1", 1, "id-zeta", "zeta_2019.pdf", "Väite Zetasta",
                       "Lainaus Zetasta.", 3, 4, nayton_vahvuus="vahva", tapa="tarkka"),
                Loydos("L2", 1, "id-alfa", "alfa_2020.pdf", "Väite Alfasta",
                       "Lainaus Alfasta.", 5, 5, nayton_vahvuus="alustava",
                       siirretty_alalta="hoitotyö", tapa="sumea"),
            ],
            huomiot=["Nimettyä lähdettä X ei ole kirjastossa"],
        ),
        Vastaus(kysymys_nro=3, ei_vastausta=True),
    ]


def _lue(polku: Path) -> list:
    return list(Document(polku).paragraphs)


def _lohko(kappaleet: list, otsikko: str) -> list:
    """Palauttaa kappaleet otsikon jälkeen seuraavaan tason 1 otsikkoon asti."""
    alku = next(i for i, k in enumerate(kappaleet) if k.text == otsikko)
    loppu = next((i for i in range(alku + 1, len(kappaleet))
                  if kappaleet[i].style.name == "Heading 1"), len(kappaleet))
    return kappaleet[alku + 1:loppu]


def _kirjoita(tmp_path: Path, vastaukset=None) -> Path:
    polku = tmp_path / "tulos.docx"
    kirjoita_docx(_patteri(), _vastaukset() if vastaukset is None else vastaukset,
                  _lahteet(), polku, otsikko="Koetulos")
    return polku


def test_otsikot_ja_tasot(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    assert kappaleet[0].style.name == "Title" and kappaleet[0].text == "Koetulos"
    otsikot = [(k.style.name, k.text) for k in kappaleet if k.style.name.startswith("Heading")]
    assert ("Heading 1", "K1. Ryhmä yksi") in otsikot
    assert ("Heading 1", "K2. Ryhmä kaksi") in otsikot
    assert ("Heading 2", "1. (P)") in otsikot
    assert ("Heading 2", "3. (J, E)") in otsikot
    assert ("Heading 2", "2.") in otsikot


def test_viite_korvautuu_ja_tuntematon_tunnus_jaa_nakyviin(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    teksti = "\n".join(k.text for k in kappaleet)
    assert "[L1]" not in teksti.split("Lainaukset")[0]
    assert "Ensimmäinen väite (Zeta ym., 2019, s. 3)." in teksti
    assert "[L9]" in teksti
    assert "tuntematon tunnus [L9]" in teksti


def test_osion_otsikko_lihavoitu(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    osio = next(k for k in kappaleet if k.text == "LÄHDE SANOO")
    assert osio.runs[0].bold


def test_kysymys_ilman_vastausta_ja_ei_vastausta(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    teksti = [k.text for k in kappaleet]
    assert "Ei ajettu." in teksti
    assert "Ei vastausta liitetyissä lähteissä." in teksti


def test_sumea_lainaus_merkitaan(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    lainaukset = _lohko(kappaleet, "Lainaukset")
    teksti = [k.text for k in lainaukset]
    assert any("[tarkista lainaus]" in t for t in teksti)
    assert any(t == "”Lainaus Zetasta.”" for t in teksti)
    assert any("Näytön vahvuus: vahva." in t for t in teksti)
    assert any("Siirretty alalta: hoitotyö." in t for t in teksti)


def test_lahdeluettelo_jarjestys_ja_kursiivit(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    lahteet = _lohko(kappaleet, "Lähteet")
    assert [k.text.split(",")[0] for k in lahteet] == ["Alfa", "Zeta"]
    for kappale in lahteet:
        kursiivit = [r.text for r in kappale.runs if r.italic]
        assert len(kursiivit) == 1
    assert [r.text for r in lahteet[0].runs if r.italic] == ["Toinen Lehti"]
    assert lahteet[0].paragraph_format.first_line_indent is not None


def test_lahteet_vain_viitatut(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    lahteet = _lohko(kappaleet, "Lähteet")
    assert len(lahteet) == 2
    assert all("Keksitty otsikko" in k.text for k in lahteet)


def test_lahteiden_kayttotaulukko(tmp_path):
    polku = _kirjoita(tmp_path)
    taulu = Document(polku).tables[0]
    rivit = [[solu.text for solu in rivi.cells] for rivi in taulu.rows]
    assert rivit[0] == ["Lähde", "Lainauksia", "Kysymykset"]
    assert ["Alfa ym., 2020", "1", "1"] in rivit      # lyhyt viite, ei tiedostonimeä
    assert ["Zeta ym., 2019", "1", "1"] in rivit
    assert not any(solu.text.endswith(".pdf") for rivi in taulu.rows for solu in rivi.cells)


def test_huomiot_loppuun(tmp_path):
    kappaleet = _lue(_kirjoita(tmp_path))
    huomiot = [k.text for k in _lohko(kappaleet, "Huomiot")]
    assert "Kysymys 1: Nimettyä lähdettä X ei ole kirjastossa" in huomiot
    assert any("tuntematon tunnus [L9]" in h for h in huomiot)


def test_puuttuvat_viitetiedot_mainitaan_huomioissa(tmp_path):
    lahteet = _lahteet()
    lahteet["zeta_2019.pdf"].aloitussivu = None
    polku = tmp_path / "vajaa.docx"
    kirjoita_docx(_patteri(), _vastaukset(), lahteet, polku)
    huomiot = [k.text for k in _lohko(_lue(polku), "Huomiot")]
    assert any("zeta_2019.pdf" in h and "painettu aloitussivu" in h for h in huomiot)
    assert not any("alfa_2020.pdf" in h and "viitetiedoista" in h for h in huomiot)


def test_puuttuva_lahderivi_kirjataan_huomioksi(tmp_path):
    vastaukset = _vastaukset()
    vastaukset[0].loydokset[0].tiedosto = "puuttuu_2021.pdf"
    polku = tmp_path / "puuttuu.docx"
    kirjoita_docx(_patteri(), vastaukset, {k: v for k, v in _lahteet().items()
                                           if k != "zeta_2019.pdf"}, polku)
    kappaleet = _lue(polku)
    huomiot = [k.text for k in _lohko(kappaleet, "Huomiot")]
    assert any("puuttuu_2021.pdf" in h for h in huomiot)


def test_tiedosto_tallentuu_luodulle_kansiolle(tmp_path):
    polku = tmp_path / "uusi" / "kansio" / "tulos.docx"
    kirjoita_docx(_patteri(), _vastaukset(), _lahteet(), polku)
    assert polku.exists()
