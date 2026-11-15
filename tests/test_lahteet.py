"""Testit lähderekisterille ja APA7-muotoilulle. Ei verkkoa; kaikki data on keksittyä."""
from __future__ import annotations

import json

from louhinta.lahteet import (
    lahdeluettelorivi, lajitteluavain, lataa_lahteet, lyhytviite, nimikirjaimet, painettu_sivu,
    tallenna_lahteet, tekstiviite, vuositunnukset, yhdista_tekstiviitteet,
)
from louhinta.mallit import Lahde, Tekija


def t(suku: str, etu: str = "") -> Tekija:
    return Tekija(suku, etu)


def artikkeli(**kw) -> Lahde:
    perus = dict(
        tiedosto="a.pdf", tyyppi="artikkeli", tekijat=[t("Virtanen", "Maija")], vuosi="2020",
        otsikko="Keksitty otsikko", julkaisu="Testilehti", vuosikerta="6", numero="3",
        sivut="164-171", doi="10.1234/abc", aloitussivu=164,
    )
    perus.update(kw)
    return Lahde(**perus)


def teksti(rivi) -> str:
    return "".join(osa for osa, _ in rivi)


# ---------------------------------------------------------------- tekstiviitteet

def test_tekstiviite_yksi_tekija():
    assert tekstiviite(artikkeli(aloitussivu=1, tekijat=[t("Brame")], vuosi="2016"), 3, 3) == "(Brame, 2016, s. 3)"


def test_tekstiviite_kaksi_tekijaa():
    lahde = artikkeli(tekijat=[t("Gerich", "J."), t("Schmitz", "M.")], vuosi="2016", aloitussivu=46)
    assert tekstiviite(lahde, 5, 5) == "(Gerich & Schmitz, 2016, s. 50)"


def test_tekstiviite_kolme_ja_useampi_tekijaa():
    lahde = artikkeli(tekijat=[t("Kolbe", "M."), t("Eppich", "W."), t("Rudolph", "J.")], aloitussivu=164)
    assert tekstiviite(lahde, 5, 5) == "(Kolbe ym., 2020, s. 168)"
    lahde.tekijat += [t("Cheng", "A.")]
    assert tekstiviite(lahde, 5, 5) == "(Kolbe ym., 2020, s. 168)"


def test_tekstiviite_sivuvali_ajatusviivalla():
    assert tekstiviite(artikkeli(), 5, 6) == "(Virtanen, 2020, ss. 168–169)"


def test_tekstiviite_sivuvali_joka_osuu_samalle_painetulle_sivulle():
    assert tekstiviite(artikkeli(), 5, 5) == "(Virtanen, 2020, s. 168)"


def test_tekstiviite_puuttuva_aloitussivu():
    lahde = artikkeli(aloitussivu=None)
    assert tekstiviite(lahde, 5, 5) == "(Virtanen, 2020, PDF-sivu 5)"
    assert tekstiviite(lahde, 5, 6) == "(Virtanen, 2020, PDF-sivut 5–6)"


def test_tekstiviite_yhteisotekija_kokonaisena():
    lahde = artikkeli(tekijat=[t("Maailman terveysjärjestö")], vuosi="2021", aloitussivu=10)
    assert tekstiviite(lahde, 1, 1) == "(Maailman terveysjärjestö, 2021, s. 10)"


def test_tekstiviite_vuositunnus_ja_nd():
    assert tekstiviite(artikkeli(), 1, 1, vuosi="2020b") == "(Virtanen, 2020b, s. 164)"
    assert tekstiviite(artikkeli(vuosi=""), 1, 1) == "(Virtanen, n.d., s. 164)"


def test_painettu_sivu():
    assert painettu_sivu(artikkeli(aloitussivu=164), 5) == 168
    assert painettu_sivu(artikkeli(aloitussivu=164), 1) == 164
    assert painettu_sivu(artikkeli(aloitussivu=None), 5) is None


# ---------------------------------------------------------------- nimikirjaimet

def test_nimikirjaimet():
    assert nimikirjaimet("Michaela") == "M."
    assert nimikirjaimet("Jean-Luc") == "J.-L."
    assert nimikirjaimet("J.-L.") == "J.-L."
    assert nimikirjaimet("Mary Jane") == "M. J."
    assert nimikirjaimet("M.J.") == "M. J."
    assert nimikirjaimet("M. J.") == "M. J."
    assert nimikirjaimet("Åsa") == "Å."


# ---------------------------------------------------------------- lähdeluettelo

def test_artikkeli_kursiivit_ja_valimerkit():
    lahde = artikkeli(tekijat=[t("Kolbe", "Michaela"), t("Eppich", "Walter"), t("Cheng", "Jean-Luc")],
                      otsikko="Otsikko")
    rivi = lahdeluettelorivi(lahde)
    assert teksti(rivi) == (
        "Kolbe, M., Eppich, W., & Cheng, J.-L. (2020). Otsikko. Testilehti, 6(3), 164–171. "
        "https://doi.org/10.1234/abc"
    )
    kursiiviset = [osa for osa, k in rivi if k]
    assert kursiiviset == ["Testilehti", "6"]


def test_artikkeli_kaksi_tekijaa_pilkku_ennen_and_merkkia():
    lahde = artikkeli(tekijat=[t("Gerich", "J."), t("Schmitz", "M.")])
    assert teksti(lahdeluettelorivi(lahde)).startswith("Gerich, J., & Schmitz, M. (2020).")


def test_artikkeli_otsikon_kysymysmerkin_jalkeen_ei_pistetta():
    rivi = teksti(lahdeluettelorivi(artikkeli(otsikko="Toimiiko tämä?")))
    assert "Toimiiko tämä? Testilehti" in rivi


def test_artikkeli_artikkelinumero_ilman_sivuja():
    lahde = artikkeli(sivut="", artikkelinumero="e0123456", numero="")
    assert "Testilehti, 6, e0123456. https://doi.org/" in teksti(lahdeluettelorivi(lahde))


def test_artikkeli_doi_etuliite_ei_tuplaannu():
    lahde = artikkeli(doi="https://doi.org/10.1234/abc")
    assert teksti(lahdeluettelorivi(lahde)).endswith("https://doi.org/10.1234/abc")


def test_yhteisotekija_ei_saa_tuplapistetta():
    lahde = artikkeli(tekijat=[t("Maailman terveysjärjestö.")])
    assert teksti(lahdeluettelorivi(lahde)).startswith("Maailman terveysjärjestö. (2020).")
    lahde = artikkeli(tekijat=[t("Maailman terveysjärjestö")])
    assert teksti(lahdeluettelorivi(lahde)).startswith("Maailman terveysjärjestö. (2020).")


def test_21_tekijaa_19_ensimmaista_kolme_pistetta_ja_viimeinen():
    tekijat = [t(f"Sukunimi{i:02d}", "Etu") for i in range(1, 22)]
    rivi = teksti(lahdeluettelorivi(artikkeli(tekijat=tekijat)))
    alku = rivi.split(" (2020)")[0]
    assert "Sukunimi19, E., … Sukunimi21, E." in alku
    assert "Sukunimi20" not in alku
    assert alku.count(", E.") == 20


def test_20_tekijaa_kokonaan():
    tekijat = [t(f"Sukunimi{i:02d}", "Etu") for i in range(1, 21)]
    alku = teksti(lahdeluettelorivi(artikkeli(tekijat=tekijat))).split(" (2020)")[0]
    assert "…" not in alku
    assert "Sukunimi19, E., & Sukunimi20, E." in alku


def test_vuositunnus_lahdeluettelossa():
    assert "(2020b)." in teksti(lahdeluettelorivi(artikkeli(), vuosi="2020b"))
    assert "(n.d.)." in teksti(lahdeluettelorivi(artikkeli(vuosi="")))


def test_kirja():
    lahde = Lahde("k.pdf", tyyppi="kirja", tekijat=[t("Brown", "Anna")], vuosi="2018",
                  otsikko="Kirjan nimi", kustantaja="Otava")
    rivi = lahdeluettelorivi(lahde)
    assert teksti(rivi) == "Brown, A. (2018). Kirjan nimi. Otava."
    assert [osa for osa, k in rivi if k] == ["Kirjan nimi."]


def test_kirja_doilla():
    lahde = Lahde("k.pdf", tyyppi="kirja", tekijat=[t("Brown", "Anna")], vuosi="2018",
                  otsikko="Kirjan nimi", kustantaja="Otava", doi="10.5/xyz")
    assert teksti(lahdeluettelorivi(lahde)) == "Brown, A. (2018). Kirjan nimi. Otava. https://doi.org/10.5/xyz"


def test_luku():
    lahde = Lahde("l.pdf", tyyppi="luku", tekijat=[t("Aalto", "Liisa")], vuosi="2015",
                  otsikko="Luvun otsikko", julkaisu="Kirjan nimi", sivut="10-25",
                  toimittajat=[t("Toimittaja", "Eero")], kustantaja="Gaudeamus")
    rivi = lahdeluettelorivi(lahde)
    assert teksti(rivi) == (
        "Aalto, L. (2015). Luvun otsikko. Teoksessa E. Toimittaja (toim.), Kirjan nimi (ss. 10–25). Gaudeamus."
    )
    assert [osa for osa, k in rivi if k] == ["Kirjan nimi"]


def test_luku_kaksi_toimittajaa_ja_yksi_sivu():
    lahde = Lahde("l.pdf", tyyppi="luku", tekijat=[t("Aalto", "Liisa")], vuosi="2015",
                  otsikko="Luku", julkaisu="Kirja", sivut="7",
                  toimittajat=[t("Toimittaja", "Eero"), t("Muu", "Kaisa")], kustantaja="WSOY")
    assert "Teoksessa E. Toimittaja & K. Muu (toim.), Kirja (s. 7). WSOY." in teksti(lahdeluettelorivi(lahde))


def test_raportti():
    lahde = Lahde("r.pdf", tyyppi="raportti", tekijat=[t("Terveyden ja hyvinvoinnin laitos")], vuosi="2019",
                  otsikko="Raportin nimi", kustantaja="Terveyden ja hyvinvoinnin laitos",
                  url="https://example.org/r.pdf")
    rivi = lahdeluettelorivi(lahde)
    assert teksti(rivi) == (
        "Terveyden ja hyvinvoinnin laitos. (2019). Raportin nimi. https://example.org/r.pdf"
    )
    assert [osa for osa, k in rivi if k] == ["Raportin nimi."]


def test_verkkosivu():
    lahde = Lahde("v.html", tyyppi="verkkosivu", tekijat=[t("Kirjoittaja", "Kalle")], vuosi="",
                  otsikko="Sivun otsikko", julkaisu="Sivuston nimi", url="https://example.org/sivu")
    rivi = lahdeluettelorivi(lahde)
    assert teksti(rivi) == "Kirjoittaja, K. (n.d.). Sivun otsikko. Sivuston nimi. https://example.org/sivu"
    assert [osa for osa, k in rivi if k] == ["Sivun otsikko."]


def test_ilman_tekijoita_otsikko_alkuun():
    lahde = artikkeli(tekijat=[], otsikko="Nimetön")
    assert teksti(lahdeluettelorivi(lahde)).startswith("Nimetön. (2020). Testilehti")


# ---------------------------------------------------------------- vuositunnukset

def test_vuositunnukset_a_ja_b_samalle_tekijajoukolle_ja_vuodelle():
    a = artikkeli(tiedosto="a.pdf", otsikko="Toinen")
    b = artikkeli(tiedosto="b.pdf", otsikko="Ensimmäinen")
    c = artikkeli(tiedosto="c.pdf", tekijat=[t("Muu", "Mikko")])
    d = artikkeli(tiedosto="d.pdf", vuosi="2021")
    tunnukset = vuositunnukset([a, b, c, d])
    assert tunnukset == {"b.pdf": "2020a", "a.pdf": "2020b", "c.pdf": "2020", "d.pdf": "2021"}


def test_vuositunnukset_eri_tekijajarjestys_ei_ole_sama_joukko():
    a = artikkeli(tiedosto="a.pdf", tekijat=[t("X", "A"), t("Y", "B")])
    b = artikkeli(tiedosto="b.pdf", tekijat=[t("Y", "B"), t("X", "A")])
    assert vuositunnukset([a, b]) == {"a.pdf": "2020", "b.pdf": "2020"}


def test_vuositunnukset_nd():
    a = artikkeli(tiedosto="a.pdf", vuosi="", otsikko="A")
    b = artikkeli(tiedosto="b.pdf", vuosi="n.d.", otsikko="B")
    assert vuositunnukset([a, b]) == {"a.pdf": "n.d.-a", "b.pdf": "n.d.-b"}


def test_vuositunnukset_hyvaksyy_generaattorin():
    assert vuositunnukset(l for l in [artikkeli()]) == {"a.pdf": "2020"}


# ---------------------------------------------------------------- lajittelu

def test_lajittelu_sukunimen_kirjainkoosta_ja_tarkkeista_riippumatta():
    nimet = ["Zeta", "Åberg", "Ahonen", "adams", "Écrit"]
    lahteet = [artikkeli(tiedosto=f"{i}.pdf", tekijat=[t(n, "X")]) for i, n in enumerate(nimet)]
    jarjestetty = [l.tekijat[0].suku for l in sorted(lahteet, key=lajitteluavain)]
    # tarkkeet poistetaan: Åberg ~ aberg < adams < ahonen
    assert jarjestetty == ["Åberg", "adams", "Ahonen", "Écrit", "Zeta"]


def test_lajittelu_kirjainkoko():
    assert lajitteluavain(artikkeli(tekijat=[t("virtanen")])) == lajitteluavain(artikkeli(tekijat=[t("VIRTANEN")]))


def test_lajittelu_muut_tekijat_ja_vuosi():
    a = artikkeli(tekijat=[t("Kolbe", "M."), t("Aho", "A.")], vuosi="2020")
    b = artikkeli(tekijat=[t("Kolbe", "M."), t("Bell", "B.")], vuosi="2019")
    c = artikkeli(tekijat=[t("Kolbe", "M.")], vuosi="2021")
    d = artikkeli(tekijat=[t("Kolbe", "M."), t("Aho", "A.")], vuosi="2018")
    jarjestys = sorted([a, b, c, d], key=lajitteluavain)
    assert jarjestys == [c, d, a, b]  # yksin kirjoitettu ensin, sitten toinen tekijä, sitten vuosi


def test_lajittelu_nd_ennen_vuosilukuja():
    a = artikkeli(vuosi="2000")
    b = artikkeli(vuosi="")
    assert sorted([a, b], key=lajitteluavain) == [b, a]


# ---------------------------------------------------------------- lataus ja tallennus

def test_tallennus_ja_lataus_edestakaisin(tmp_path):
    lahteet = {
        "a.pdf": artikkeli(tekijat=[t("Äyräs", "Åsa"), t("Kolbe", "Michaela")], tarkistettu=True,
                           huomio="Ääkköset säilyvät"),
        "l.pdf": Lahde("l.pdf", tyyppi="luku", tekijat=[t("Aalto", "Liisa")], toimittajat=[t("Toim", "Eero")],
                       aloitussivu=None, otsikko="Luku"),
    }
    polku = tmp_path / "ala" / "lahteet.json"
    tallenna_lahteet(lahteet, polku)
    assert lataa_lahteet(polku) == lahteet
    sisalto = polku.read_text(encoding="utf-8")
    assert "Äyräs" in sisalto and "\\u" not in sisalto   # ensure_ascii=False
    assert json.loads(sisalto)["a.pdf"]["tekijat"][0] == {"suku": "Äyräs", "etu": "Åsa"}
    assert "\n  " in sisalto                              # indent=2


def test_lataus_sietaa_puuttuvat_ja_tuntemattomat_kentat(tmp_path):
    polku = tmp_path / "l.json"
    polku.write_text(json.dumps({"x.pdf": {"tiedosto": "x.pdf", "uusi_kentta": 1,
                                           "tekijat": [{"suku": "S", "etu": "E"}]}}), encoding="utf-8")
    lahde = lataa_lahteet(polku)["x.pdf"]
    assert lahde.tekijat == [Tekija("S", "E")]
    assert lahde.aloitussivu is None and lahde.tarkistettu is False


# ---------------------------------------------------------------- vaiheen 2 korjaukset

def test_painettu_sivu_nolla_ja_negatiivinen_aloitussivu():
    kirja = artikkeli(aloitussivu=-2)       # kolme numeroimatonta sivua ennen sivua 1
    assert painettu_sivu(kirja, 1) is None  # -2
    assert painettu_sivu(kirja, 3) is None  # 0
    assert painettu_sivu(kirja, 4) == 1
    assert painettu_sivu(artikkeli(aloitussivu=0), 1) is None
    assert painettu_sivu(artikkeli(aloitussivu=0), 2) == 1


def test_tekstiviite_numeroimaton_sivu_antaa_pdf_sivun():
    kirja = artikkeli(aloitussivu=-2)
    assert tekstiviite(kirja, 2, 2) == "(Virtanen, 2020, PDF-sivu 2)"
    assert tekstiviite(kirja, 3, 5) == "(Virtanen, 2020, PDF-sivut 3–5)"   # alku ilman painettua sivua
    assert tekstiviite(kirja, 4, 5) == "(Virtanen, 2020, ss. 1–2)"


def test_tekijaton_rivi_kayttaa_tiedostonimea_ilman_paatetta():
    tyhja = Lahde(tiedosto="adams_christenson_2000.pdf", aloitussivu=477)
    assert tekstiviite(tyhja, 1, 1) == "(adams_christenson_2000, n.d., s. 477)"
    rivi = teksti(lahdeluettelorivi(tyhja))
    assert rivi.startswith("adams_christenson_2000. (n.d.).")
    assert ".pdf" not in rivi


def test_tekijaton_rivi_otsikolla_pitaa_otsikon():
    lahde = artikkeli(tekijat=[], otsikko="Nimetön", tiedosto="x.pdf")
    assert tekstiviite(lahde, 1, 1).startswith("(Nimetön, 2020")


def test_lyhytviite():
    assert lyhytviite(artikkeli(tekijat=[t("Kolbe"), t("Eppich"), t("Rudolph")])) == "Kolbe ym., 2020"
    assert lyhytviite(artikkeli(), "2020a") == "Virtanen, 2020a"
    assert lyhytviite(Lahde(tiedosto="a_b_2000.pdf")) == "a_b_2000, n.d."


# ---------------------------------------------------------------- yhdistetyt viitteet

def _page() -> Lahde:
    return artikkeli(tiedosto="p.pdf", tekijat=[t("Page-Cutrara", "K."), t("Turk", "M.")], vuosi="2017", aloitussivu=71)


def _kolbe() -> Lahde:
    return artikkeli(tiedosto="k.pdf", tekijat=[t("Kolbe"), t("B"), t("C")], vuosi="2020", aloitussivu=164)


def _sinha() -> Lahde:
    return artikkeli(tiedosto="s.pdf", tekijat=[t("Sinha"), t("Kapur")], vuosi="2021", aloitussivu=751)


def test_yhdistetty_viite_sama_lahde_sivut_nousevasti_ja_ilman_toistoa():
    viitteet = [(_page(), 13, 13), (_page(), 8, 8), (_page(), 8, 8)]
    assert yhdista_tekstiviitteet(viitteet) == "(Page-Cutrara & Turk, 2017, ss. 78, 83)"


def test_yhdistetty_viite_yksi_sivu_ja_sivuvali():
    assert yhdista_tekstiviitteet([(_page(), 8, 8)]) == "(Page-Cutrara & Turk, 2017, s. 78)"
    assert yhdista_tekstiviitteet([(_page(), 8, 9)]) == "(Page-Cutrara & Turk, 2017, ss. 78–79)"
    assert yhdista_tekstiviitteet([(_page(), 8, 9), (_page(), 9, 9), (_page(), 20, 20)]) \
        == "(Page-Cutrara & Turk, 2017, ss. 78–79, 90)"


def test_yhdistetty_viite_eri_lahteet_puolipisteella_aakkosjarjestyksessa():
    viitteet = [(_sinha(), 11, 11), (_kolbe(), 5, 5), (_sinha(), 11, 11)]
    assert yhdista_tekstiviitteet(viitteet) == "(Kolbe ym., 2020, s. 168; Sinha & Kapur, 2021, s. 761)"


def test_yhdistetty_viite_kayttaa_vuositunnuksia_ja_pdf_sivuja():
    ilman = artikkeli(tiedosto="x.pdf", tekijat=[t("Zed")], vuosi="2019", aloitussivu=None)
    assert yhdista_tekstiviitteet([(ilman, 9, 9), (ilman, 2, 2)], {"x.pdf": "2019a"}) == "(Zed, 2019a, PDF-sivut 2, 9)"
    assert yhdista_tekstiviitteet([(ilman, 2, 2)]) == "(Zed, 2019, PDF-sivu 2)"


def test_yhdistetty_viite_yhdella_viitteella_vastaa_tekstiviitetta():
    assert yhdista_tekstiviitteet([(_kolbe(), 5, 6)]) == tekstiviite(_kolbe(), 5, 6)
