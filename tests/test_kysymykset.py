"""Testit kysymystiedoston jäsentimelle (louhinta/kysymykset.py)."""
from pathlib import Path

import pytest

from louhinta.kysymykset import lue_patteri

ESIMERKKI = Path(__file__).resolve().parent.parent / "kysymykset" / "rooliharjoittelu.txt"


def _kirjoita(tmp_path: Path, teksti: str) -> Path:
    polku = tmp_path / "kysymykset.txt"
    polku.write_text(teksti, encoding="utf-8")
    return polku


@pytest.fixture(scope="module")
def esimerkki():
    return lue_patteri(ESIMERKKI)


def test_esimerkissa_34_kysymysta(esimerkki):
    assert len(esimerkki.kysymykset) == 34
    assert [k.nro for k in esimerkki.kysymykset] == list(range(1, 35))


def test_esimerkissa_9_ryhmaa(esimerkki):
    assert len({k.ryhma for k in esimerkki.kysymykset}) == 9
    assert esimerkki.kysymykset[0].ryhma == "K1"
    assert esimerkki.kysymykset[0].ryhma_otsikko == "Ohjeistuksen ajoitus"


def test_esimerkissa_8_saantoa_ja_8_rakennekohtaa(esimerkki):
    assert len(esimerkki.saannot) == 8
    assert len(esimerkki.rakenne) == 8
    assert not esimerkki.saannot[0][:3].startswith("1.")   # numerointi poistettu


def test_kysymyksen_6_merkinnat(esimerkki):
    kysymys = next(k for k in esimerkki.kysymykset if k.nro == 6)
    assert kysymys.merkinnat == ["J", "E"]
    assert kysymys.ryhma == "K2"


def test_kysymys_19_yhtena_kappaleena(esimerkki):
    kysymys = next(k for k in esimerkki.kysymykset if k.nro == 19)
    assert "\n" not in kysymys.teksti
    assert kysymys.teksti.endswith("selkeä kieli)?")


def test_saanto_3_sisaltaa_molemmat_alakohdat(esimerkki):
    saanto = esimerkki.saannot[2]
    assert "LÄHDE SANOO" in saanto
    assert "EHDOTUS VIDEOON" in saanto


def test_pelkat_kysymykset_ilman_ryhmia(tmp_path):
    polku = _kirjoita(tmp_path, "1. Ensimmäinen kysymys?\n2. (P) Toinen kysymys?\n"
                                "   jatkuu tästä.\n3. Kolmas?\n")
    patteri = lue_patteri(polku)
    assert [k.nro for k in patteri.kysymykset] == [1, 2, 3]
    assert {k.ryhma for k in patteri.kysymykset} == {"K1"}
    assert {k.ryhma_otsikko for k in patteri.kysymykset} == {"Kysymykset"}
    assert patteri.kysymykset[1].merkinnat == ["P"]
    assert patteri.kysymykset[1].teksti == "Toinen kysymys? jatkuu tästä."
    assert patteri.kysymykset[0].merkinnat == []
    assert patteri.tehtava == ""
    assert patteri.saannot == [] and patteri.rakenne == []


def test_virheellinen_tiedosto_ilman_kysymyksia(tmp_path):
    polku = _kirjoita(tmp_path, "TEHTÄVÄ:\nVain tehtävänanto.\n")
    with pytest.raises(ValueError):
        lue_patteri(polku)


def test_kaksi_samaa_kysymysnumeroa_rivinumeroineen(tmp_path):
    polku = _kirjoita(tmp_path, "K1. Ryhmä\n\n1. (P) Ensimmäinen?\n\n2. Toinen?\n1. Uusi sama?\n")
    with pytest.raises(ValueError, match="rivi 6"):
        lue_patteri(polku)


def test_sisennetty_rivi_ilman_kohtaa_antaa_rivinumeron(tmp_path):
    polku = _kirjoita(tmp_path, "K1. Ryhmä\n   tämä ei kuulu mihinkään\n1. Kysymys?\n")
    with pytest.raises(ValueError, match="rivi 2"):
        lue_patteri(polku)


def test_tunnistamaton_rivi_kysymysten_joukossa_antaa_rivinumeron(tmp_path):
    polku = _kirjoita(tmp_path, "K1. Ryhmä\n1. Kysymys?\nTämä rivi ei ole kysymys\n")
    with pytest.raises(ValueError, match="rivi 3"):
        lue_patteri(polku)


def test_kysymys_ilman_tekstia_antaa_rivinumeron(tmp_path):
    polku = _kirjoita(tmp_path, "1. (P)\n")
    with pytest.raises(ValueError, match="rivi 1"):
        lue_patteri(polku)
