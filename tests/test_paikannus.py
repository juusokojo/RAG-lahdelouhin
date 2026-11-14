"""Lainauksen paikannuksen testit. Keksitty teksti, ei verkkoa."""
import random
import re

import pytest

from louhinta.paikannus import (
    _normalisoi_kartalla, normalisoi, paikanna_lainaus, paikanna_patka, siisti, sivu,
)

SIVU1 = ("Oppiminen on aktiivinen prosessi, jossa opiskelija rakentaa merkityksiä.\n"
         "Simulaatioharjoittelu tarjoaa turvallisen ympäristön kokeilla toimintaa.\n"
         "Ohjaajan rooli korostuu palautteen antamisessa harjoituksen jälkeen.")
SIVU2 = ("Palaute annetaan heti harjoituksen päätyttyä, jotta kokemus on tuore.\n"
         "Tutkimukseen osallistui 48 hoitotyön opiskelijaa kolmesta korkeakoulusta.\n"
         "Aineisto kerättiin haastatteluilla ja analysoitiin sisällönanalyysilla.")
SIVU3 = ("Tulokset osoittivat, että strukturoitu purku lisäsi opiskelijoiden itseluottamusta.\n"
         "Rajoituksena oli pieni otoskoko, joten tuloksia ei voi yleistää.")
TEKSTI = "\f".join([SIVU1, SIVU2, SIVU3])


def kohta(osa: str) -> int:
    return TEKSTI.index(osa)


# ------------------------------------------------------------------ sivu, siisti

def test_sivu_laskee_sivunvaihdot_ennen_indeksia():
    t = "a\fb\fc"
    assert [sivu(t, i) for i in range(5)] == [1, 1, 2, 2, 3]
    assert sivu(t, 0) == 1


def test_siisti_yhdistaa_tavutuksen_pienen_kirjaimen_edessa():
    assert siisti("commu-\nnication on tärkeää") == "communication on tärkeää"


def test_siisti_ei_yhdista_ison_kirjaimen_tai_numeron_edessa():
    assert siisti("Kolbe-\nEppich") == "Kolbe- Eppich"
    assert siisti("vaihe-\n2 alkaa") == "vaihe- 2 alkaa"


def test_siisti_tyhjat_ja_reunat():
    assert siisti("  a \n\f b\t\tc \n") == "a b c"


def test_siisti_ei_koske_viivaan_ilman_rivinvaihtoa():
    assert siisti("itse-arviointi") == "itse-arviointi"


# ------------------------------------------------------------------ indeksikartta

def test_indeksikartta_ligatuuri():
    teksti = "a ﬁnal ﬂow"
    norm, alut, loput = _normalisoi_kartalla(teksti)
    assert norm == "afinalflow"
    assert len(alut) == len(loput) == len(norm)
    for i, m in enumerate(norm):
        # ryhmän alkuperäinen merkki normalisoituu osaksi samaa merkkijonoa
        ryhma = teksti[alut[i]:loput[i]]
        assert m in normalisoi(ryhma)
    # ligatuurin molemmat merkit osoittavat samaan alkuperäiseen merkkiin
    assert alut[1] == alut[2] == 2 and loput[1] == loput[2] == 3


def test_indeksikartta_yhdistavat_merkit_ja_normalisointi_yhtenevaa():
    hajotettu = "Café au lait"     # e + yhdistävä akuutti
    yhdistetty = "Café au lait"
    assert normalisoi(hajotettu) == normalisoi(yhdistetty) == "caféaulait"
    norm, alut, loput = _normalisoi_kartalla(hajotettu)
    assert hajotettu[alut[3]:loput[3]] == "é"


def test_indeksikartta_yleinen_ominaisuus():
    teksti = "Ǆ ﬃ x²  ä­ö, İstanbul ①"
    norm, alut, loput = _normalisoi_kartalla(teksti)
    assert all(0 <= a < l <= len(teksti) for a, l in zip(alut, loput))
    assert alut == sorted(alut)


# ------------------------------------------------------------------ paikanna_lainaus

def test_tarkka_osuma_ja_sivu():
    p = paikanna_lainaus("Palaute annetaan heti harjoituksen päätyttyä, jotta kokemus on tuore.", TEKSTI)
    assert p is not None
    assert p.tapa == "tarkka" and p.pisteet == 100.0
    assert p.pdf_sivu_alku == p.pdf_sivu_loppu == 2
    assert p.lainaus == "Palaute annetaan heti harjoituksen päätyttyä, jotta kokemus on tuore."
    assert p.alku == kohta("Palaute annetaan")
    assert p.lainaus == siisti(TEKSTI[p.alku:p.loppu])


def test_tarkka_osuma_valinpitamaton_kirjainkoosta_valimerkeista_ja_valilyonneista():
    p = paikanna_lainaus("SIMULAATIOHARJOITTELU tarjoaa   turvallisen ympäristön kokeilla toimintaa", TEKSTI)
    assert p is not None and p.tapa == "tarkka"
    assert p.lainaus == "Simulaatioharjoittelu tarjoaa turvallisen ympäristön kokeilla toimintaa."


def test_sivurajan_ylittava_lainaus():
    ehdotus = "palautteen antamisessa harjoituksen jälkeen. Palaute annetaan heti harjoituksen päätyttyä"
    p = paikanna_lainaus(ehdotus, TEKSTI)
    assert p is not None
    assert (p.pdf_sivu_alku, p.pdf_sivu_loppu) == (1, 2)
    assert p.lainaus == siisti(TEKSTI[p.alku:p.loppu])
    assert "\f" not in p.lainaus


def test_ligatuuri_lahteessa():
    teksti = "Alku on tässä.\fTutkimus osoitti, että oﬃce-työntekijöiden ﬂexibility ja ﬁnal-arvosana paranivat selvästi."
    p = paikanna_lainaus("että office-työntekijöiden flexibility ja final-arvosana paranivat", teksti)
    assert p is not None and p.tapa == "tarkka"
    assert p.pdf_sivu_alku == p.pdf_sivu_loppu == 2
    assert p.lainaus.startswith("että oﬃce-työntekijöiden ﬂexibility")   # leikattu alkuperäisestä
    assert p.lainaus == siisti(teksti[p.alku:p.loppu])


def test_ligatuuri_ehdotuksessa():
    teksti = "Alku.\fTutkimus osoitti, että office-työntekijöiden flexibility ja final-arvosana paranivat."
    p = paikanna_lainaus("että oﬃce-työntekijöiden ﬂexibility ja ﬁnal-arvosana paranivat", teksti)
    assert p is not None
    assert p.lainaus == "että office-työntekijöiden flexibility ja final-arvosana paranivat."


def test_alku_ligatuurin_keskelta_laajenee_sanan_alkuun():
    teksti = "Johdanto.\fTässä on ﬁnaali ja jatkoa tekstille kappaleessa."
    p = paikanna_lainaus("naali ja jatkoa tekstille kappaleessa", teksti)
    assert p is not None
    assert p.lainaus == "ﬁnaali ja jatkoa tekstille kappaleessa."
    assert p.alku == teksti.index("ﬁnaali")


def test_tavutus():
    teksti = "Sivu yksi.\fHyvä commu-\nnication on tärkeää ryhmän toiminnalle ja tulokselle.\nSeuraava rivi."
    p = paikanna_lainaus("Hyvä communication on tärkeää ryhmän toiminnalle", teksti)
    assert p is not None and p.tapa == "tarkka"
    assert p.lainaus == "Hyvä communication on tärkeää ryhmän toiminnalle"
    assert p.pdf_sivu_alku == 2


def test_alku_tavutetun_sanan_jalkiosasta_laajenee():
    teksti = "Edellinen kappale loppuu sanaan commu-\nnication ja jatkuu tästä eteenpäin pitkään."
    p = paikanna_lainaus("nication ja jatkuu tästä eteenpäin pitkään", teksti)
    assert p is not None
    assert p.lainaus == "communication ja jatkuu tästä eteenpäin pitkään."
    assert p.alku == teksti.index("commu-")


def test_lyhennetty_ehdotus_valitsee_pisimman_osan():
    for katko in ("…", "...", "[...]", "[…]"):
        ehdotus = f"Palaute annetaan {katko} Tutkimukseen osallistui 48 hoitotyön opiskelijaa kolmesta {katko} lyhyt"
        p = paikanna_lainaus(ehdotus, TEKSTI)
        assert p is not None, katko
        assert p.tapa == "tarkka"
        assert p.lainaus == "Tutkimukseen osallistui 48 hoitotyön opiskelijaa kolmesta"
        assert p.pdf_sivu_alku == 2


def test_lyhennetty_ehdotus_vain_lyhyita_osia_ei_loydy():
    assert paikanna_lainaus("Palaute annetaan … tuore … hoitotyön", TEKSTI) is None


def test_yhden_sanan_virhe_on_sumea():
    ehdotus = "Palaute annetaan heti harjoituksen päättyttyä, jotta kokemus on tuore."
    p = paikanna_lainaus(ehdotus, TEKSTI)
    assert p is not None
    assert p.tapa == "sumea" and 92.0 <= p.pisteet < 100.0
    assert p.pdf_sivu_alku == p.pdf_sivu_loppu == 2
    # lainaus on lähteen sanamuodossa, ei ehdotuksen
    assert "päätyttyä" in p.lainaus and "päättyttyä" not in p.lainaus
    assert p.lainaus == siisti(TEKSTI[p.alku:p.loppu])


def test_keksitty_lainaus_ei_loydy():
    assert paikanna_lainaus("Kielimalli keksi tämän lauseen, jota ei ole missään lähteessä.", TEKSTI) is None
    assert paikanna_lainaus("Gamma-säteily lisää opiskelijoiden motivaatiota merkittävästi kaikissa ryhmissä", TEKSTI) is None


def test_liian_lyhyt_ehdotus():
    assert paikanna_lainaus("Palaute annetaan", TEKSTI) is None
    assert paikanna_lainaus("", TEKSTI) is None
    assert paikanna_lainaus("Palaute annetaan", TEKSTI, min_pituus=10) is not None


def test_useasta_kohdasta_valitaan_ensimmainen():
    teksti = "Alku. Sama lause toistuu tässä kokonaan.\fVälissä muuta.\fSama lause toistuu tässä kokonaan."
    p = paikanna_lainaus("Sama lause toistuu tässä kokonaan", teksti)
    assert p is not None and p.pdf_sivu_alku == 1 and p.alku == teksti.index("Sama")


def test_lainaus_laajenee_kokonaisiin_sanoihin():
    p = paikanna_lainaus("ristön kokeilla toimin", TEKSTI)
    assert p is not None
    assert p.lainaus == "ympäristön kokeilla toimintaa."
    assert TEKSTI[p.alku - 1] == " "


def test_sumea_raja_toimii():
    ehdotus = "Palaute annetaan heti harjoituksen päättyttyä, jotta kokemus on tuore."
    assert paikanna_lainaus(ehdotus, TEKSTI, sumea_raja=100.0) is None


# ------------------------------------------------------------------ paikanna_patka

def test_patka_sivut():
    assert paikanna_patka("Tutkimukseen osallistui 48 hoitotyön opiskelijaa", TEKSTI) == [2]
    assert paikanna_patka("jälkeen.\nPalaute annetaan heti harjoituksen", TEKSTI) == [1, 2]
    assert paikanna_patka("Tätä tekstiä ei ole lähteessä lainkaan, ei sinne päinkään", TEKSTI) == []
    assert paikanna_patka("", TEKSTI) == []


def test_patka_ankkurit_kun_kokonaisuus_ei_tasmaa():
    pitka = " ".join(f"sana{n}kokeilu" for n in range(60))
    lahde = "esipuhe\f" + pitka + "\floppu"
    patka = pitka[:600] + " lisätty ylimääräinen osa joka ei ole lähteessä " + pitka[-600:]
    assert paikanna_patka(patka, lahde) == [2]


# ------------------------------------------------------------------ ominaisuustesti

def _keksitty_teksti(rng: random.Random, sivuja: int = 12) -> tuple[str, list[int]]:
    """Monisivuinen teksti satunnaisilla sanoilla; palauttaa tekstin ja sivujen alkuindeksit."""
    aakkoset = "abcdefghijklmnopqrstuvwxyzäö"
    ligatuurit = ["ﬁ", "ﬂ", "ﬀ", "ﬃ"]

    def sana() -> str:
        s = "".join(rng.choice(aakkoset) for _ in range(rng.randint(2, 9)))
        if rng.random() < 0.08:
            k = rng.randint(0, len(s))
            s = s[:k] + rng.choice(ligatuurit) + s[k:]
        if rng.random() < 0.1:
            s = s.capitalize()
        return s + rng.choice(["", "", "", ",", ".", ";"])

    sivut = []
    for _ in range(sivuja):
        rivit = [" ".join(sana() for _ in range(rng.randint(5, 12))) for _ in range(rng.randint(8, 20))]
        sivut.append("\n".join(rivit))
    alut, kohta_ = [], 0
    for s in sivut:
        alut.append(kohta_)
        kohta_ += len(s) + 1
    return "\f".join(sivut), alut


@pytest.mark.parametrize("siemen", [1, 2, 3])
def test_satunnaiset_leikkaukset_loytyvat_samasta_kohdasta_ja_sivulta(siemen):
    rng = random.Random(siemen)
    teksti, sivualut = _keksitty_teksti(rng)
    mahdolliset = [i for i, c in enumerate(teksti) if c.isalnum()]
    ligatuurit_auki = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi"})

    def sivu_oikea(indeksi: int) -> int:
        return max(n for n, a in enumerate(sivualut, 1) if a <= indeksi)

    def sanan_alku(i: int) -> int:
        while i > 0 and not teksti[i - 1].isspace():
            i -= 1
        return i

    def sanan_loppu(i: int) -> int:       # i = viimeisen merkin indeksi
        while i + 1 < len(teksti) and not teksti[i + 1].isspace():
            i += 1
        return i + 1

    for _ in range(400):
        a = rng.choice(mahdolliset)
        b = rng.choice([m for m in mahdolliset if a + 25 <= m <= a + 600] or [a + 25])
        if b >= len(teksti) or not teksti[b].isalnum():
            continue
        leike = teksti[a:b + 1]
        ehdotus = leike
        if rng.random() < 0.5:
            ehdotus = ehdotus.translate(ligatuurit_auki)
        if rng.random() < 0.5:
            ehdotus = re.sub(r"\s+", " ", ehdotus).swapcase()
        p = paikanna_lainaus(ehdotus, teksti)
        assert p is not None
        assert p.tapa == "tarkka"
        odotettu_alku, odotettu_loppu = sanan_alku(a), sanan_loppu(b)
        assert (p.alku, p.loppu) == (odotettu_alku, odotettu_loppu)
        assert p.pdf_sivu_alku == sivu_oikea(odotettu_alku)
        assert p.pdf_sivu_loppu == sivu_oikea(odotettu_loppu - 1)
        assert p.lainaus == siisti(teksti[p.alku:p.loppu])
        assert paikanna_patka(ehdotus, teksti) == list(range(sivu_oikea(a), sivu_oikea(b) + 1))


def test_sumea_virhe_ensimmaisessa_ja_viimeisessa_sanassa_ei_vuoda_naapureihin():
    ehdotus = "Palaute annettiin heti harjoituksen päätyttyä, jotta kokemus on tuori."
    p = paikanna_lainaus(ehdotus, TEKSTI)
    assert p is not None and p.tapa == "sumea"
    assert p.lainaus == "Palaute annetaan heti harjoituksen päätyttyä, jotta kokemus on tuore."
    assert p.pdf_sivu_alku == p.pdf_sivu_loppu == 2
