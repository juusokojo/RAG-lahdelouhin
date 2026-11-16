"""Putken testit väärennetyllä Malli- ja Rag-oliolla ja keksityllä tekstillä. Ei verkkoa."""
import json
import re

import pytest

import louhinta.putki as putki

from louhinta.malli import MalliVirhe
from louhinta.mallit import Kysymys, Lahde, Osuma, Patteri, Tekija
from louhinta.paikannus import paikanna_patka, siisti
from louhinta.putki import (
    HAKU_JARJESTELMA, KOONTI_JARJESTELMA, OSUVUUS_JARJESTELMA, POIMINTA_JARJESTELMA,
    lataa_vastaus, tallenna_vastaus, vastaa, vastaa_tilastoin,
)

SIVU1 = ("Alfa study introduction. Participants in the invented course practised difficult conversations "
         "with simulated parents in a safe setting.\nThey met every week for two months and received "
         "written guidance before the first session.")
SIVU2 = ("Results. The ﬁnal analysis of the evidence indicated that  rehearsal before the conversation "
         "reduced anxiety among novices.\nThe effect was moderate in size and stable across sites. "
         "Teachers who skipped the rehearsal reported higher stress during the first conversation.")
SIVU3 = "Discussion. Limitations include the small sample and the short follow-up period of the invented trial."
ALFA = "\f".join([SIVU1, SIVU2, SIVU3])
BETA = "Beta report. Coaches in the invented programme gave short written feedback after each practice round."

# täsmälleen lähteen mukainen pätkä sivulta 2 ja ehdotus, jossa on pieniä eroja (ligatuuri, välilyönnit)
LAINAUS_ALFA = ("The final analysis of the evidence indicated that rehearsal before the conversation "
                "reduced anxiety among novices.")
LAINAUS_BETA = "Coaches in the invented programme gave short written feedback after each practice round."

TEKSTIT = {"f-alfa": ALFA, "f-beta": BETA}
TIEDOSTOT = {"alfa_2020.pdf": "f-alfa", "beta_2021.pdf": "f-beta"}


def osuma(tiedosto: str, patka: str) -> Osuma:
    fid = TIEDOSTOT[tiedosto]
    return Osuma(fid, tiedosto, patka, 0.9, paikanna_patka(patka, TEKSTIT[fid]))


class ValeRag:
    def __init__(self, osumat=None, tekstit=None):
        self.osumat = osumat if osumat is not None else [
            osuma("alfa_2020.pdf", SIVU2), osuma("beta_2021.pdf", BETA)]
        self.tekstit = tekstit or TEKSTIT
        self.haut = []

    def tiedostot(self):
        return [{"id": i, "tiedosto": t} for t, i in TIEDOSTOT.items()]

    def lahdeteksti(self, file_id):
        return self.tekstit[file_id]

    def hae(self, kysely, max_chunks=8, filter_ids=None):
        self.haut.append((kysely, max_chunks, filter_ids))
        osumat = [o for o in self.osumat if not filter_ids or o.file_id in filter_ids]
        return osumat[:max_chunks]


class ValeMalli:
    """Vastaa kehotteen järjestelmäosan perusteella; kirjaa kutsut."""

    def __init__(self, haku=None, poiminta=None, koonti=None, poiminta_kutsut=None, osuvuus=None):
        self.poiminta_kutsut = poiminta_kutsut      # vastaus kutsua kohti; viimeistä toistetaan
        self.haku = haku or {"haut": ["rehearsal anxiety"], "nimetyt": [], "puuttuvat": []}
        self.poiminta = poiminta if poiminta is not None else []
        self.koonti = koonti or {"osiot": [{"otsikko": "", "teksti": "Väite yksi [L1]."}]}
        self.osuvuus = osuvuus          # None = kaikki "suora"; muuten {tunnus: arvio} tai poikkeus
        self.kutsut = []
        self.kw = []

    def kysy_json(self, jarjestelma, kayttaja, **kw):
        vaihe = {HAKU_JARJESTELMA: "haku", POIMINTA_JARJESTELMA: "poiminta",
                 KOONTI_JARJESTELMA: "koonti", OSUVUUS_JARJESTELMA: "osuvuus"}[jarjestelma]
        self.kutsut.append((vaihe, kayttaja))
        self.kw.append((vaihe, kw))
        arvo = getattr(self, vaihe)
        if vaihe == "osuvuus" and not isinstance(arvo, Exception):
            tunnukset = re.findall(r"^\[(L\d+)\]", kayttaja, re.MULTILINE)
            return [{"tunnus": t, "arvio": (arvo or {}).get(t, "suora"), "perustelu": "Perustelu."}
                    for t in tunnukset]
        if vaihe == "poiminta" and self.poiminta_kutsut:
            arvo = self.poiminta_kutsut.pop(0) if len(self.poiminta_kutsut) > 1 else self.poiminta_kutsut[0]
        if isinstance(arvo, Exception):
            raise arvo
        return arvo

    def vaiheet(self):
        return [v for v, _ in self.kutsut]


def ehdotus(osuma_tunnus="O1", lainaus=LAINAUS_ALFA, vaite="Väite suomeksi.", **lisa):
    return {"osuma": osuma_tunnus, "vaite": vaite, "lainaus": lainaus, **lisa}


KYSYMYS = Kysymys(7, "K2", "Ryhmä", ["P"], "Vähentääkö harjoittelu ahdistusta?")
PATTERI = Patteri(tehtava="Keksitty tehtävä.", saannot=[], rakenne=[], kysymykset=[KYSYMYS])
LAHTEET = {
    "alfa_2020.pdf": Lahde("alfa_2020.pdf", tekijat=[Tekija("Alfa", "A.")], vuosi="2020", otsikko="Alfa", aloitussivu=10),
    "beta_2021.pdf": Lahde("beta_2021.pdf", tekijat=[Tekija("Beta", "B.")], vuosi="2021", otsikko="Beta", aloitussivu=1),
}


def aja(malli, rag=None, patteri=PATTERI, loki=None):
    rag = rag or ValeRag()
    return vastaa_tilastoin(KYSYMYS, patteri, rag, malli, LAHTEET, loki)


# ---------------------------------------------------------------- ydinperiaate

def test_keksitty_lainaus_hylataan_eika_paady_vastaukseen():
    keksitty = "Rehearsal completely eliminates anxiety in every teacher according to this invented study."
    malli = ValeMalli(poiminta=[ehdotus("O1", keksitty, vaite="Keksitty väite"), ehdotus("O1")])
    v, t = aja(malli)
    assert [l.lainaus for l in v.loydokset] == [LAINAUS_ALFA]
    assert len(v.loydokset) == 1 and v.loydokset[0].tunnus == "L1"
    assert "eliminates" not in json.dumps(v.__dict__, default=lambda o: o.__dict__, ensure_ascii=False)
    assert (t.ehdotuksia, t.hyvaksyttyja, t.hylattyja) == (2, 1, 1)
    assert t.syyt == {"ei löydy lähdetekstistä": 1}
    assert any("1 lainausehdotusta hylättiin" in h for h in v.huomiot)


def test_lainaus_leikataan_lahdetekstista_ei_mallin_tekstista():
    malli = ValeMalli(poiminta=[ehdotus("O1", LAINAUS_ALFA)])      # ehdotuksessa "final" ja yksi välilyönti
    v, _ = aja(malli)
    lainaus = v.loydokset[0].lainaus
    assert lainaus == LAINAUS_ALFA                   # lähteessä on ligatuuri ﬁ ja kaksi välilyöntiä: siistitty
    assert "ﬁ" not in lainaus and "that  rehearsal" not in lainaus
    assert lainaus in siisti(SIVU2)        # sama kuin lähdeteksti siistittynä
    assert v.loydokset[0].tapa == "tarkka"
    assert (v.loydokset[0].pdf_sivu_alku, v.loydokset[0].pdf_sivu_loppu) == (2, 2)


def test_sivurajan_ylittava_lainaus_saa_molemmat_sivut():
    raja = "invented course practised difficult conversations with simulated parents in a safe setting. " \
           "They met every week for two months and received written guidance before the first session. Results."
    malli = ValeMalli(poiminta=[ehdotus("O1", raja)])
    rag = ValeRag([Osuma("f-alfa", "alfa_2020.pdf", "x", 0.9, [1, 2])])
    v, _ = aja(malli, rag)
    assert (v.loydokset[0].pdf_sivu_alku, v.loydokset[0].pdf_sivu_loppu) == (1, 2)


def test_ei_loydoksia_ei_vastausta_ilman_koontikutsua():
    malli = ValeMalli(poiminta=[])
    v, t = aja(malli)
    assert v.ei_vastausta and not v.osiot and not v.loydokset
    assert "koonti" not in malli.vaiheet()
    assert t.loydoksia == 0


def test_kaikki_ehdotukset_hylatty_ei_vastausta_ilman_koontikutsua():
    malli = ValeMalli(poiminta=[ehdotus("O1", "Täysin keksitty englanninkielinen lause joka ei ole missään lähteessä.")])
    v, t = aja(malli)
    assert v.ei_vastausta and "koonti" not in malli.vaiheet()
    assert t.hylattyja == 1 and any("hylättiin" in h for h in v.huomiot)


def test_ei_osumia_ei_poimintakutsua():
    malli = ValeMalli()
    v, t = aja(malli, ValeRag(osumat=[]))
    assert v.ei_vastausta and malli.vaiheet() == ["haku"] and t.osumia == 0


def test_tuntematon_osumatunnus_ja_liian_lyhyt_lainaus_hylataan():
    malli = ValeMalli(poiminta=[ehdotus("O9"), ehdotus("O1", "Results."), ehdotus("O1", ""), ehdotus("O1")])
    v, t = aja(malli)
    assert len(v.loydokset) == 1
    assert t.syyt == {"tuntematon osumatunnus": 1, "liian lyhyt": 1, "tyhjä lainaus": 1}


def test_lainaus_toisen_osuman_lahteesta_ei_kelpaa():
    # mallin kuuluu viitata osumaan, josta lainaus on kopioitu; O2 on Betan pätkä
    malli = ValeMalli(poiminta=[ehdotus("O2", LAINAUS_ALFA)])
    rag = ValeRag([osuma("beta_2021.pdf", BETA), osuma("alfa_2020.pdf", SIVU2)])
    # osumat järjestetään pisteiden mukaan; molemmilla 0.9, joten järjestys säilyy: O1 = beta, O2 = alfa
    v, _ = aja(malli, rag)
    assert len(v.loydokset) == 1 and v.loydokset[0].tiedosto == "alfa_2020.pdf"
    malli = ValeMalli(poiminta=[ehdotus("O1", LAINAUS_ALFA)])       # O1 = beta: alfan lainaus ei löydy sieltä
    v, _ = aja(malli, rag)
    assert v.ei_vastausta


def test_sivu_ei_osu_osuman_sivuihin_antaa_sumean():
    malli = ValeMalli(poiminta=[ehdotus("O1")])
    rag = ValeRag([Osuma("f-alfa", "alfa_2020.pdf", "x", 0.9, [3])])   # lainaus on sivulla 2
    v, t = aja(malli, rag)
    assert v.loydokset[0].tapa == "sumea" and t.sumeita == 1
    # tyhjä pdf_sivut-lista ei laukaise sumeaa
    v, _ = aja(ValeMalli(poiminta=[ehdotus("O1")]), ValeRag([Osuma("f-alfa", "alfa_2020.pdf", "x", 0.9, [])]))
    assert v.loydokset[0].tapa == "tarkka"


def test_sumea_paikannus_merkitaan_sumeaksi():
    malli = ValeMalli(poiminta=[ehdotus("O1", LAINAUS_ALFA.replace("novices", "beginners") + " ")])
    v, _ = aja(malli)
    assert v.loydokset and v.loydokset[0].tapa == "sumea"
    assert "novices" in v.loydokset[0].lainaus          # teksti on silti lähteestä


# ---------------------------------------------------------------- yhdistäminen

def test_paallekkaiset_loydokset_yhdistetaan():
    a = "The final analysis of the evidence indicated that rehearsal before the conversation reduced anxiety among novices."
    b = ("rehearsal before the conversation reduced anxiety among novices. The effect was moderate in size "
         "and stable across sites.")
    malli = ValeMalli(poiminta=[ehdotus("O1", a, vaite="Ensimmäinen"), ehdotus("O1", b, vaite="Toinen",
                                                                          nayton_vahvuus="vahva")])
    v, t = aja(malli)
    assert len(v.loydokset) == 1 and t.hyvaksyttyja == 2 and t.loydoksia == 1
    l = v.loydokset[0]
    assert "final analysis" in l.lainaus and l.lainaus.endswith("stable across sites.")
    assert l.lainaus in siisti(SIVU2)       # yhdistetty lainaus on leikattu lähteestä
    assert "Ensimmäinen" in l.vaite and "Toinen" in l.vaite
    assert l.nayton_vahvuus == "vahva"


def test_erilliset_kohdat_ja_eri_tiedostot_eivat_yhdisty():
    malli = ValeMalli(poiminta=[
        ehdotus("O1", LAINAUS_ALFA),
        ehdotus("O1", "Teachers who skipped the rehearsal reported higher stress during the first conversation."),
        ehdotus("O2", LAINAUS_BETA),
    ])
    v, _ = aja(malli)
    assert [l.tunnus for l in v.loydokset] == ["L1", "L2", "L3"]
    assert [l.tiedosto for l in v.loydokset] == ["alfa_2020.pdf", "alfa_2020.pdf", "beta_2021.pdf"]


# ---------------------------------------------------------------- koonti

def test_tuntematon_tunnus_kirjataan_huomioihin():
    malli = ValeMalli(poiminta=[ehdotus("O1")],
                      koonti={"osiot": [{"otsikko": "LÄHDE SANOO", "teksti": "Hyvä [L1]. Outo [L9]."}]})
    v, _ = aja(malli)
    assert v.osiot[0].otsikko == "LÄHDE SANOO"
    assert "tuntematon tunnus [L9] jätettiin tekstiin" in v.huomiot
    assert not any("[L1]" in h for h in v.huomiot)


def test_tunnusryhma_puretaan_yksittaisiksi():
    malli = ValeMalli(poiminta=[ehdotus("O1"), ehdotus("O2", LAINAUS_BETA)],
                      koonti={"osiot": [{"otsikko": "", "teksti": "Molemmat [L1, L2] sanovat niin."}]})
    v, _ = aja(malli)
    assert v.osiot[0].teksti == "Molemmat [L1] [L2] sanovat niin."


def test_koonti_ilman_osioita_on_virhe():
    malli = ValeMalli(poiminta=[ehdotus("O1")], koonti={"osiot": []})
    with pytest.raises(MalliVirhe):
        aja(malli)


def test_koontikehote_sisaltaa_loydokset_ja_saannot():
    patteri = Patteri(tehtava="Keksitty tehtävä.", saannot=["Erottele LÄHDE SANOO ja EHDOTUS."], rakenne=[],
                      kysymykset=[KYSYMYS])
    malli = ValeMalli(poiminta=[ehdotus("O1", vaite="Harjoittelu vähentää ahdistusta.")])
    aja(malli, patteri=patteri)
    kehote = next(k for v, k in malli.kutsut if v == "koonti")
    assert "[L1]" in kehote and "Harjoittelu vähentää ahdistusta." in kehote
    assert "Erottele LÄHDE SANOO" in kehote and "Keksitty tehtävä." in kehote
    assert "Alfa ym." not in kehote and "Alfa, 2020" in kehote     # lähde lyhytviitteenä


# ---------------------------------------------------------------- haku ja hakulauseet

def test_puuttuvat_lahteet_huomioihin_ja_tuntematon_tiedosto_pudotetaan(monkeypatch):
    monkeypatch.setattr(putki, "KOKOTEKSTI_SIVUJA_ENINTAAN", 0)     # pitkän lähteen polku: rajattu haku
    malli = ValeMalli(haku={"haut": ["a", "b"], "nimetyt": ["alfa_2020.pdf", "olematon.pdf"],
                            "puuttuvat": ["Gamma (2019)"]})
    rag = ValeRag()
    v, _ = aja(malli, rag)
    assert any("Gamma (2019)" in h and "ei ole kirjastossa" in h for h in v.huomiot)
    assert any("olematon.pdf" in h for h in v.huomiot)
    # rajaamattomat haut (8) ja nimettyyn tiedostoon rajatut (6, filter_ids)
    assert ("a", 8, None) in rag.haut and ("b", 8, None) in rag.haut
    assert ("a", 6, ["f-alfa"]) in rag.haut
    assert not any(f == ["olematon.pdf"] for _, _, f in rag.haut)


def test_sama_patka_vain_kerran_ja_kutsukohtainen_raja(monkeypatch):
    monkeypatch.setattr(putki, "OSUMIA_KUTSUSSA", 3)
    patkat = [osuma("alfa_2020.pdf", SIVU2)] * 3 + [Osuma("f-beta", "beta_2021.pdf", f"pätkä {i}", 0.5 - i / 1000, [1])
                                                   for i in range(4)]
    malli = ValeMalli(haku={"haut": ["a", "b"], "nimetyt": [], "puuttuvat": []})
    _, t = aja(malli, ValeRag(patkat))
    assert t.osumia == 5                                      # 3 samaa pätkää -> 1, ja 4 muuta
    kehotteet = [k for v, k in malli.kutsut if v == "poiminta"]
    assert len(kehotteet) == 2                                # 3 + 2 osumaa
    assert kehotteet[0].count(SIVU2) == 1
    assert "[O3]" in kehotteet[0] and "[O4]" not in kehotteet[0]


def test_nimettyjen_osumat_sailytetaan_osumarajassa(monkeypatch):
    monkeypatch.setattr(putki, "OSUMIA_ENINTAAN", 5)
    monkeypatch.setattr(putki, "MUITA_VAHINTAAN", 0)
    monkeypatch.setattr(putki, "KOKOTEKSTI_SIVUJA_ENINTAAN", 0)
    muut = [Osuma("f-beta", "beta_2021.pdf", f"beta {i}", 0.9 - i / 1000, [1]) for i in range(8)]
    nimetty = Osuma("f-alfa", "alfa_2020.pdf", SIVU2, 0.01, [2])         # huonoin piste
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []})
    _, t = aja(malli, ValeRag(muut + [nimetty]))
    assert t.osumia == 5
    assert any(SIVU2 in k for v, k in malli.kutsut if v == "poiminta")


def test_tyhjat_hakulauseet_korvataan_kysymyksella():
    malli = ValeMalli(haku={"haut": [], "nimetyt": [], "puuttuvat": []})
    rag = ValeRag()
    v, _ = aja(malli, rag)
    assert rag.haut[0][0] == KYSYMYS.teksti
    assert any("hakulauseita" in h for h in v.huomiot)


# ---------------------------------------------------------------- poiminnan erikoistapaukset

def test_nayton_vahvuus_pyydetaan_vain_jos_saannot_vaativat():
    malli = ValeMalli(poiminta=[])
    aja(malli)
    assert "nayton_vahvuus" not in next(k for v, k in malli.kutsut if v == "poiminta")

    patteri = Patteri(tehtava="", rakenne=[], kysymykset=[KYSYMYS], saannot=[
        "Arvioi näytön vahvuus: vahva, kohtalainen, alustava.",
        "Merkitse, jos päätelmä on siirretty toiselta alalta."])
    malli = ValeMalli(poiminta=[ehdotus("O1", nayton_vahvuus="kohtalainen", siirretty_alalta="hoitotyö")])
    v, _ = aja(malli, patteri=patteri)
    kehote = next(k for v_, k in malli.kutsut if v_ == "poiminta")
    assert "nayton_vahvuus" in kehote and "siirretty_alalta" in kehote
    assert (v.loydokset[0].nayton_vahvuus, v.loydokset[0].siirretty_alalta) == ("kohtalainen", "hoitotyö")


def test_poiminnan_vastaus_oliona_tai_koodiaitoineen_kelpaa():
    malli = ValeMalli(poiminta={"loydokset": [ehdotus("O1")]})
    v, _ = aja(malli)
    assert len(v.loydokset) == 1


def test_yksi_poimintakutsu_epaonnistuu_muut_jatkuvat(monkeypatch):
    monkeypatch.setattr(putki, "OSUMIA_KUTSUSSA", 2)
    patkat = [osuma("alfa_2020.pdf", SIVU2)] + [
        Osuma("f-alfa", "alfa_2020.pdf", f"pätkä {i}", 0.5 - i / 100, [2]) for i in range(2)]
    malli = ValeMalli(poiminta_kutsut=[MalliVirhe("rikki"), [ehdotus("O1")]])
    v, _ = aja(malli, ValeRag(patkat))
    assert any("Poimintakutsu 1/2" in h for h in v.huomiot)
    assert not v.ei_vastausta and len(v.loydokset) == 1      # jälkimmäinen erä onnistui


def test_kaikki_poimintakutsut_epaonnistuvat_on_virhe():
    malli = ValeMalli(poiminta_kutsut=[MalliVirhe("rikki")])
    with pytest.raises(MalliVirhe, match="kaikki poimintakutsut"):
        aja(malli)


def test_loki_kirjoitetaan(tmp_path):
    malli = ValeMalli(poiminta=[ehdotus("O1", "Täysin keksitty englanninkielinen lause joka ei ole missään lähteessä."),
                                ehdotus("O1")])
    aja(malli, loki=tmp_path / "loki")
    nimet = {p.name for p in (tmp_path / "loki").iterdir()}
    assert {"k7_1_osumat.json", "k7_3_hylatyt.json"} <= nimet
    hylatyt = json.loads((tmp_path / "loki" / "k7_3_hylatyt.json").read_text(encoding="utf-8"))
    assert hylatyt[0]["syy"] == "ei löydy lähdetekstistä"


def test_vastaa_palauttaa_vastauksen():
    v = vastaa(KYSYMYS, PATTERI, ValeRag(), ValeMalli(poiminta=[ehdotus("O1")]), LAHTEET)
    assert v.kysymys_nro == 7 and len(v.loydokset) == 1 and v.osiot


# ---------------------------------------------------------------- tallennus

def test_tallenna_ja_lataa_edestakaisin(tmp_path):
    malli = ValeMalli(poiminta=[ehdotus("O1", nayton_vahvuus="vahva"), ehdotus("O2", LAINAUS_BETA)],
                      koonti={"osiot": [{"otsikko": "LÄHDE SANOO", "teksti": "A [L1].\n\nB [L2]."},
                                        {"otsikko": "EHDOTUS", "teksti": "C [L1]."}]})
    v, _ = aja(malli)
    polku = tmp_path / "vastaukset" / "k7.json"
    tallenna_vastaus(v, polku)
    assert lataa_vastaus(polku) == v
    assert "LÄHDE SANOO" in polku.read_text(encoding="utf-8")    # ei \u-koodauksia


def test_tallenna_ja_lataa_ei_vastausta(tmp_path):
    v, _ = aja(ValeMalli(poiminta=[]))
    tallenna_vastaus(v, tmp_path / "k7.json")
    ladattu = lataa_vastaus(tmp_path / "k7.json")
    assert ladattu == v and ladattu.ei_vastausta


# ---------------------------------------------------------------- osuvuustarkistus

def _kaksi_loydosta(**osuvuus):
    return ValeMalli(poiminta=[ehdotus("O1", LAINAUS_ALFA, vaite="Alfa-väite"), ehdotus("O2", LAINAUS_BETA, vaite="Beta-väite")],
                     koonti={"osiot": [{"otsikko": "", "teksti": "Väite [L1]."}]}, **osuvuus)


def test_osuvuus_ei_pudotetaan_ja_loput_numeroidaan_uudelleen():
    malli = _kaksi_loydosta(osuvuus={"L1": "ei", "L2": "osittainen"})
    v, t = aja(malli)
    assert [(l.tunnus, l.tiedosto) for l in v.loydokset] == [("L1", "beta_2021.pdf")]
    assert t.osuvuus_pudotettuja == 1 and t.loydoksia == 1
    assert any("1 löydöstä pudotettiin osuvuustarkistuksessa" in h for h in v.huomiot)
    assert malli.vaiheet() == ["haku", "poiminta", "osuvuus", "koonti"]
    koonto = dict(malli.kutsut)["koonti"]
    assert "Beta" in koonto or "beta" in koonto
    assert "Alfa-väite" not in koonto


def test_osuvuus_kehote_sisaltaa_kysymyksen_ja_loydokset_ja_lampotila_nolla():
    malli = _kaksi_loydosta()
    aja(malli)
    kayttaja = dict(malli.kutsut)["osuvuus"]
    assert KYSYMYS.teksti in kayttaja and "Alfa-väite" in kayttaja and LAINAUS_ALFA in kayttaja
    assert "[L1]" in kayttaja and "[L2]" in kayttaja
    assert all(kw.get("lampotila") == 0 for vaihe, kw in malli.kw if vaihe in ("poiminta", "osuvuus"))


def test_osuvuus_kaikki_pudotettu_antaa_ei_vastausta():
    malli = _kaksi_loydosta(osuvuus={"L1": "ei", "L2": "ei"})
    v, t = aja(malli)
    assert v.ei_vastausta and v.loydokset == [] and t.osuvuus_pudotettuja == 2 and t.loydoksia == 0
    assert "koonti" not in malli.vaiheet()


def test_osuvuuskutsun_epaonnistuminen_sailyttaa_loydokset():
    malli = _kaksi_loydosta(osuvuus=MalliVirhe("kaatui"))
    v, t = aja(malli)
    assert [l.tunnus for l in v.loydokset] == ["L1", "L2"] and t.osuvuus_pudotettuja == 0
    assert any("Osuvuustarkistus epäonnistui" in h for h in v.huomiot)
    assert not v.ei_vastausta


def test_osuvuus_puuttuva_tai_outo_arvio_sailytetaan():
    malli = _kaksi_loydosta(osuvuus={"L1": "ehkä"})
    v, _ = aja(malli)
    assert len(v.loydokset) == 2


# ---------------------------------------------------------------- lainaus kokonaisina virkkeinä

def test_lainaus_laajenee_kokonaisiin_virkkeisiin_ja_sivut_laajennetusta_valista():
    # ehdotus alkaa keskeltä virkettä sivulla 1 ja päättyy kesken virkkeen sivulla 2
    sivu1 = "Intro. The invented method was first described by several early groups in a long and careful report of results"
    sivu2 = "and it was later replicated by many others across the field. Next sentence follows here."
    teksti = "\f".join([sivu1, sivu2])
    rag = ValeRag(osumat=[Osuma("f-x", "x.pdf", sivu1, 0.9, [1, 2])], tekstit={**TEKSTIT, "f-x": teksti})
    rag.tiedostot = lambda: [{"id": "f-x", "tiedosto": "x.pdf"}]
    ehd = "first described by several early groups in a long and careful report of results and it was later replicated"
    v, _ = vastaa_tilastoin(KYSYMYS, PATTERI, rag, ValeMalli(poiminta=[ehdotus("O1", ehd)]), {}, None)
    l = v.loydokset[0]
    assert l.lainaus == ("The invented method was first described by several early groups in a long and careful report "
                         "of results and it was later replicated by many others across the field.")
    assert (l.pdf_sivu_alku, l.pdf_sivu_loppu) == (1, 2)


def test_laajennusta_ei_tehda_jos_lainaus_ylittaa_700_merkkia():
    alku = "Lead sentence. Start " + " ".join(["alpha"] * 40)                 # ~240 merkkiä ennen ehdotusta
    keski = "Middle part of the quoted passage " + " ".join(["beta"] * 60)    # ~330 merkkiä
    loppu = " ".join(["gamma"] * 40) + " end. Final sentence."                # ~240 merkkiä jälkeen
    teksti = f"{alku} {keski} {loppu}"
    rag = ValeRag(osumat=[Osuma("f-x", "x.pdf", teksti, 0.9, [1])], tekstit={**TEKSTIT, "f-x": teksti})
    rag.tiedostot = lambda: [{"id": "f-x", "tiedosto": "x.pdf"}]
    ehd = "Middle part of the quoted passage " + " ".join(["beta"] * 60)
    v, _ = vastaa_tilastoin(KYSYMYS, PATTERI, rag, ValeMalli(poiminta=[ehdotus("O1", ehd)]), {}, None)
    l = v.loydokset[0].lainaus
    assert len(siisti(teksti)) > 700 and len(l) < 400 and l.startswith("Middle part")    # laajennus kokonaisuudessaan > 700


# ---------------------------------------------------------------- nimetty lähde kokonaan, väärä oletus, aineisto

def test_lyhyt_nimetty_lahde_luetaan_kokonaan_sivulohkoina(monkeypatch):
    monkeypatch.setattr(putki, "KOKOTEKSTI_LOHKO", len(SIVU1) + 10)      # yksi sivu lohkoa kohti
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []})
    rag = ValeRag([osuma("beta_2021.pdf", BETA)])        # semanttinen haku ei löydä alfasta mitään
    _, t = aja(malli, rag)
    assert not any(f for _, _, f in rag.haut)            # kokonaan luetusta ei tehdä rajattua hakua
    kehote = next(k for v, k in malli.kutsut if v == "poiminta")
    assert SIVU1 in kehote and SIVU3 in kehote and BETA in kehote
    assert "PDF-sivu 3" in kehote
    assert t.osumia == 4                                  # kolme sivulohkoa + beta


def test_kokonaan_luetun_lainaus_saa_oikean_sivun():
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []},
                      poiminta=[ehdotus("O1")])
    v, _ = aja(malli, ValeRag([]))
    assert len(v.loydokset) == 1
    assert v.loydokset[0].pdf_sivu_alku == 2 and v.loydokset[0].tapa == "tarkka"


def test_pitka_nimetty_lahde_haetaan_rajatusti(monkeypatch):
    monkeypatch.setattr(putki, "KOKOTEKSTI_SIVUJA_ENINTAAN", 2)          # alfassa on 3 sivua
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []})
    rag = ValeRag()
    aja(malli, rag)
    assert ("a", 6, ["f-alfa"]) in rag.haut


KYSYMYS_ALFA = Kysymys(8, "K2", "Ryhmä", ["P"], "Mitä Alfan ryhmä (2020) sanoo ahdistuksesta?")


def test_nimetty_ilman_loydoksia_huomioihin_ja_koontiin():
    # kysymys nimeää alfan, mutta asia löytyy betasta (väärä oletus)
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []},
                      poiminta=[ehdotus("O2", lainaus=LAINAUS_BETA)])   # O1 = alfa kokonaan
    v, _ = vastaa_tilastoin(KYSYMYS_ALFA, PATTERI, ValeRag([osuma("beta_2021.pdf", BETA)]), malli, LAHTEET, None)
    assert [l.tiedosto for l in v.loydokset] == ["beta_2021.pdf"]
    huomio = next(h for h in v.huomiot if "nimetystä lähteestä" in h)
    assert "Alfa, 2020" in huomio and "luettiin kokonaan" in huomio and "Beta, 2021" in huomio
    koonti = next(k for vaihe, k in malli.kutsut if vaihe == "koonti")
    assert "Alfa, 2020 (ei löydöksiä)" in koonti


def test_nimetty_jolla_on_loydos_ei_saa_huomiota():
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []},
                      poiminta=[ehdotus("O1")])
    v, _ = vastaa_tilastoin(KYSYMYS_ALFA, PATTERI, ValeRag([]), malli, LAHTEET, None)
    assert v.loydokset and not any("nimetystä lähteestä" in h for h in v.huomiot)
    koonti = next(k for vaihe, k in malli.kutsut if vaihe == "koonti")
    assert "Alfa, 2020 (löydökset L1)" in koonti


def test_aineisto_valitetaan_koontiin():
    lahteet = dict(LAHTEET)
    lahteet["alfa_2020.pdf"] = Lahde("alfa_2020.pdf", tekijat=[Tekija("Alfa", "A.")], vuosi="2020",
                                     otsikko="Alfa", aloitussivu=10, aineisto="11 haastattelua: 10 äitiä")
    malli = ValeMalli(poiminta=[ehdotus("O1")])
    vastaa_tilastoin(KYSYMYS, PATTERI, ValeRag(), malli, lahteet, None)
    koonti = next(k for v, k in malli.kutsut if v == "koonti")
    assert "aineisto: 11 haastattelua: 10 äitiä" in koonti and ", aineisto)" in koonti


def test_vahvuus_ja_alasiirto_yhtenaistetaan_lahteittain():
    toinen = "Teachers who skipped the rehearsal reported higher stress during the first conversation."
    malli = ValeMalli(poiminta=[
        ehdotus("O1", nayton_vahvuus="kohtalainen", siirretty_alalta="lääketiede"),
        ehdotus("O1", lainaus=toinen, nayton_vahvuus="kohtalainen", siirretty_alalta=""),
        ehdotus("O2", lainaus=LAINAUS_BETA, nayton_vahvuus="alustava", siirretty_alalta="")])
    v, _ = aja(malli)
    alfat = [l for l in v.loydokset if l.tiedosto == "alfa_2020.pdf"]
    assert len(alfat) == 2 and all(l.siirretty_alalta == "lääketiede" for l in alfat)
    beta = next(l for l in v.loydokset if l.tiedosto == "beta_2021.pdf")
    assert beta.siirretty_alalta == "" and beta.nayton_vahvuus == "alustava"


def test_hakuvaiheen_ehdottama_lahde_jota_kysymys_ei_nimea_ei_saa_huomiota():
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []},
                      poiminta=[ehdotus("O2", lainaus=LAINAUS_BETA)])
    v, _ = aja(malli, ValeRag([osuma("beta_2021.pdf", BETA)]))       # KYSYMYS ei mainitse Alfaa
    assert v.loydokset and not any("nimetystä lähteestä" in h for h in v.huomiot)
    koonti = next(k for vaihe, k in malli.kutsut if vaihe == "koonti")
    assert "Kysymyksessä nimetyt lähteet" not in koonti


def test_lahdeluettelo_jatetaan_pois_kokotekstista():
    lahdeluettelo = "\nReferences\nMiller S. Why having control reduces stress. Academic Press; 1980."
    tekstit = {"f-alfa": ALFA + lahdeluettelo, "f-beta": BETA}
    malli = ValeMalli(haku={"haut": ["a"], "nimetyt": ["alfa_2020.pdf"], "puuttuvat": []})
    aja(malli, ValeRag([], tekstit))
    kehote = next(k for v, k in malli.kutsut if v == "poiminta")
    assert SIVU3 in kehote and "Miller S." not in kehote


def test_nimetty_ilman_loydoksia_saman_tekijan_vuositunnus_ja_toinen_nimetty_muissa():
    # kysymys nimeää kaksi saman tekijän saman vuoden lähdettä; löydökset vain toisesta
    lahteet = {
        "alfa_2020.pdf": Lahde("alfa_2020.pdf", tekijat=[Tekija("Alfa", "A.")], vuosi="2020", otsikko="A-otsikko"),
        "beta_2021.pdf": Lahde("beta_2021.pdf", tekijat=[Tekija("Alfa", "A.")], vuosi="2020", otsikko="B-otsikko"),
    }
    huomiot = putki._nimetyt_ilman_loydoksia(
        ["alfa_2020.pdf", "beta_2021.pdf"],
        [putki.Loydos("L1", 1, "f-beta", "beta_2021.pdf", "v", "l", 1, 1)], lahteet, set())
    assert huomiot == ["Kysymyksessä nimetystä lähteestä Alfa, 2020a ei löytynyt kysymykseen vastaavaa kohtaa "
                       "(haku ei löytänyt sopivaa kohtaa). Aihetta käsittelevät: Alfa, 2020b."]


PATTERI_OSIOT = Patteri(tehtava="T.", saannot=["Erottele kaksi osaa:\n- LÄHDE SANOO: mitä lähde sanoo.\n"
                                                "- EHDOTUS VIDEOON: miten käytetään."],
                        rakenne=[], kysymykset=[KYSYMYS])


def test_vaarat_osio_otsikot_yritetaan_kerran_uudelleen():
    vaarin = {"osiot": [{"otsikko": "Alakysymys 1", "teksti": "LÄHDE SANOO: Väite [L1]."}]}
    oikein = {"osiot": [{"otsikko": "LÄHDE SANOO", "teksti": "Väite [L1]."},
                        {"otsikko": "EHDOTUS VIDEOON", "teksti": "Ehdotus [L1]."}]}
    malli = ValeMalli(poiminta=[ehdotus("O1")])
    vastaukset = [vaarin, oikein]
    malli.koonti = None
    alkuperainen = malli.kysy_json

    def kysy(jarjestelma, kayttaja, **kw):
        if jarjestelma == KOONTI_JARJESTELMA:
            malli.kutsut.append(("koonti", kayttaja))
            return vastaukset.pop(0)
        return alkuperainen(jarjestelma, kayttaja, **kw)
    malli.kysy_json = kysy
    v, _ = aja(malli, patteri=PATTERI_OSIOT)
    assert [o.otsikko for o in v.osiot] == ["LÄHDE SANOO", "EHDOTUS VIDEOON"]
    koonnit = [k for vaihe, k in malli.kutsut if vaihe == "koonti"]
    assert len(koonnit) == 2 and '"Alakysymys 1"' in koonnit[1]


def test_vaarat_otsikot_toistamiseen_huomioihin():
    malli = ValeMalli(poiminta=[ehdotus("O1")],
                      koonti={"osiot": [{"otsikko": "Oma", "teksti": "Väite [L1]."}]})
    v, _ = aja(malli, patteri=PATTERI_OSIOT)
    assert [o.otsikko for o in v.osiot] == ["Oma"]
    assert any("osiojakoa" in h for h in v.huomiot)
    assert malli.vaiheet().count("koonti") == 2


def test_oikeat_otsikot_ei_uutta_yritysta():
    malli = ValeMalli(poiminta=[ehdotus("O1")], koonti={"osiot": [
        {"otsikko": "LÄHDE SANOO", "teksti": "Väite [L1]."}, {"otsikko": "EHDOTUS VIDEOON", "teksti": "E [L1]."}]})
    aja(malli, patteri=PATTERI_OSIOT)
    assert malli.vaiheet().count("koonti") == 1
