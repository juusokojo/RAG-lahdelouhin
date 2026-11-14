"""Rag-asiakkaan testit väärennetyllä requests.Session-oliolla. Ei verkkoa."""
import pytest
import requests

import louhinta.lehmus as lehmus
from louhinta.lehmus import Rag

LAHDE_A = "Ensimmäinen sivu alkaa tässä ja jatkuu pitkään.\r\nToinen rivi.\fToinen sivu sisältää tärkeän väitteen tutkimuksesta.\fKolmas sivu."
LAHDE_B = "Toisen tiedoston ainoa sivu sisältää aivan eri asian kokonaan."


class Vastaus:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class Istunto:
    """Jono vastauksia polun mukaan; kirjaa kutsut."""

    def __init__(self, vastaukset):
        self.vastaukset = vastaukset      # (metodi, polku) -> lista vastauksia tai poikkeuksia
        self.kutsut = []
        self.headers = {}

    def _kutsu(self, metodi, url, **kwargs):
        polku = url.split("/api/testi", 1)[1]
        self.kutsut.append((metodi, polku, kwargs))
        jono = self.vastaukset[(metodi, polku)]
        v = jono.pop(0) if len(jono) > 1 else jono[0]
        if isinstance(v, Exception):
            raise v
        return v

    def get(self, url, **kwargs):
        return self._kutsu("get", url, **kwargs)

    def post(self, url, **kwargs):
        return self._kutsu("post", url, **kwargs)


@pytest.fixture(autouse=True)
def ei_odotusta(monkeypatch):
    viiveet = []
    monkeypatch.setattr(lehmus.time, "sleep", viiveet.append)
    return viiveet


def rag(tmp_path, vastaukset):
    r = Rag(url="https://example.invalid/api/testi/", avain="testiavain", valimuisti=tmp_path / "vm")
    r.istunto = Istunto(vastaukset)
    return r


def test_avain_puuttuu(monkeypatch, tmp_path):
    monkeypatch.delenv("LEHMUS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="LEHMUS_API_KEY"):
        Rag(valimuisti=tmp_path)


def test_avain_ymparistomuuttujasta_ja_otsake(monkeypatch, tmp_path):
    monkeypatch.setenv("LEHMUS_API_KEY", "ymparisto-avain")
    r = Rag(url="https://rag.testi", valimuisti=tmp_path)
    assert r.istunto.headers["Authorization"] == "Bearer ymparisto-avain"


def test_tiedostot_sivutus_cursorilla(tmp_path):
    r = rag(tmp_path, {("get", "/files"): [
        Vastaus(data={"files": [{"id": "a", "metadata": {"filename": "a.pdf"}},
                                {"id": "b", "metadata": {"filename": "b.pdf"}}], "next_cursor": "kursori2"}),
        Vastaus(data={"files": [{"id": "c", "filename": "c.pdf", "metadata": {}}], "next_cursor": None}),
    ]})
    assert r.tiedostot() == [{"id": "a", "tiedosto": "a.pdf"}, {"id": "b", "tiedosto": "b.pdf"},
                             {"id": "c", "tiedosto": "c.pdf"}]
    kutsut = r.istunto.kutsut
    assert "cursor" not in kutsut[0][2]["params"] and kutsut[1][2]["params"]["cursor"] == "kursori2"
    assert kutsut[0][2]["timeout"] == 60


def test_lahdeteksti_valimuisti_sailyttaa_f_ja_rivinvaihdot(tmp_path):
    r = rag(tmp_path, {("get", "/content/abc-123"): [Vastaus(data={"source_text": LAHDE_A})]})
    assert r.lahdeteksti("abc-123") == LAHDE_A
    tiedosto = tmp_path / "vm" / "lahdetekstit" / "abc-123.txt"
    assert tiedosto.read_bytes() == LAHDE_A.encode("utf-8")      # \r\n ja \f merkilleen
    # uusi asiakas lukee levyltä eikä kutsu verkkoa
    r2 = rag(tmp_path, {})
    assert r2.lahdeteksti("abc-123") == LAHDE_A
    assert r2.istunto.kutsut == []
    # toinen kutsu samalla oliolla ei kutsu verkkoa
    assert r.lahdeteksti("abc-123") == LAHDE_A
    assert len(r.istunto.kutsut) == 1


def test_lahdeteksti_puuttuva_source_text_ja_vaarat_tunnukset(tmp_path):
    r = rag(tmp_path, {("get", "/content/x"): [Vastaus(data={"source_text": None})]})
    with pytest.raises(ValueError):
        r.lahdeteksti("x")
    assert not (tmp_path / "vm" / "lahdetekstit" / "x.txt").exists()
    for paha in ("../ulos", "a/b", "", ".."):
        with pytest.raises(ValueError):
            r.lahdeteksti(paha)


def context_vastaus():
    return {
        "chunks": ["Toinen sivu sisältää tärkeän väitteen tutkimuksesta.",
                   "Toisen tiedoston ainoa sivu sisältää aivan eri asian kokonaan.",
                   "Tätä pätkää ei ole lähteessä lainkaan, ei sinne päinkään"],
        "scores": [0.9, 0.7, 0.5],
        "files": [{"id": "a", "metadata": {"filename": "a.pdf"}},
                  {"id": "b", "metadata": {"filename": "b.pdf"}},
                  {"id": "a", "metadata": {"filename": "a.pdf"}}],
    }


def haku_istunto(tmp_path):
    return rag(tmp_path, {
        ("post", "/context"): [Vastaus(data=context_vastaus())],
        ("get", "/content/a"): [Vastaus(data={"source_text": LAHDE_A})],
        ("get", "/content/b"): [Vastaus(data={"source_text": LAHDE_B})],
    })


def test_hae_yhdistaa_chunks_scores_files_ja_paikantaa_sivut(tmp_path):
    r = haku_istunto(tmp_path)
    osumat = r.hae("kysely")
    assert [(o.file_id, o.tiedosto, o.pisteet, o.pdf_sivut) for o in osumat] == [
        ("a", "a.pdf", 0.9, [2]), ("b", "b.pdf", 0.7, [1]), ("a", "a.pdf", 0.5, [])]
    assert osumat[0].teksti.startswith("Toinen sivu")
    metodi, polku, kw = r.istunto.kutsut[0]
    assert (metodi, polku) == ("post", "/context")
    assert kw["json"] == {"query": "kysely", "max_chunks": 8}            # ei filter_ids-avainta
    # lähdeteksti haettiin kerran per tiedosto
    assert [k[1] for k in r.istunto.kutsut].count("/content/a") == 1


def test_hae_filter_ids_ja_max_chunks(tmp_path):
    r = haku_istunto(tmp_path)
    r.hae("kysely", max_chunks=3, filter_ids=["a", "b"])
    assert r.istunto.kutsut[0][2]["json"] == {"query": "kysely", "max_chunks": 3, "filter_ids": ["a", "b"]}


def test_hae_epajohdonmukainen_vastaus(tmp_path):
    huono = context_vastaus()
    huono["scores"] = [0.9]
    r = rag(tmp_path, {("post", "/context"): [Vastaus(data=huono)]})
    with pytest.raises(ValueError):
        r.hae("kysely")


def test_uudelleenyritys_5xx_ja_verkkovirhe_kasvavalla_viiveella(tmp_path, ei_odotusta):
    ok = Vastaus(data={"files": [], "next_cursor": None})
    r = rag(tmp_path, {("get", "/files"): [Vastaus(503), requests.ConnectionError("x"), Vastaus(429), ok]})
    assert r.tiedostot() == []
    assert len(r.istunto.kutsut) == 4
    assert ei_odotusta == [1.0, 2.0, 4.0]


def test_uudelleenyritykset_loppuvat_kolmeen(tmp_path, ei_odotusta):
    r = rag(tmp_path, {("get", "/files"): [Vastaus(500)]})
    with pytest.raises(requests.HTTPError):
        r.tiedostot()
    assert len(r.istunto.kutsut) == 4          # 1 + 3 uudelleenyritystä
    r = rag(tmp_path, {("get", "/files"): [requests.Timeout("t")]})
    with pytest.raises(requests.Timeout):
        r.tiedostot()
    assert len(r.istunto.kutsut) == 4


def test_4xx_ei_yriteta_uudelleen(tmp_path):
    r = rag(tmp_path, {("get", "/content/zzz"): [Vastaus(404)]})
    with pytest.raises(requests.HTTPError):
        r.lahdeteksti("zzz")
    assert len(r.istunto.kutsut) == 1


def test_paivitetty_teksti_haetaan_uudelleen_valimuistin_ohi(tmp_path):
    polku = tmp_path / "vm" / "lahdetekstit" / "a.txt"
    polku.parent.mkdir(parents=True)
    polku.write_text("vanha teksti", encoding="utf-8")
    uusi = "Uusi teksti.\fToinen sivu."
    r = rag(tmp_path, {
        ("get", "/files"): [Vastaus(data={"files": [{"id": "a", "metadata": {"filename": "a.pdf"},
                                                     "updated_at": "2999-01-01T00:00:00Z"}]})],
        ("get", "/content/a"): [Vastaus(data={"source_text": uusi})],
    })
    r.tiedostot()
    assert r.lahdeteksti("a") == uusi
    assert polku.read_text(encoding="utf-8") == uusi


def test_muuttumaton_teksti_luetaan_valimuistista(tmp_path):
    polku = tmp_path / "vm" / "lahdetekstit" / "a.txt"
    polku.parent.mkdir(parents=True)
    polku.write_text("välimuistissa", encoding="utf-8")
    r = rag(tmp_path, {("get", "/files"): [Vastaus(data={"files": [
        {"id": "a", "metadata": {"filename": "a.pdf"}, "updated_at": "2000-01-01T00:00:00+00:00"}]})]})
    r.tiedostot()
    assert r.lahdeteksti("a") == "välimuistissa"
