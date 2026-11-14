"""Malli-asiakkaan testit väärennetyllä requests.Session-oliolla. Ei verkkoa."""
import json

import pytest
import requests

import louhinta.malli as malli_moduuli
from louhinta.malli import Malli, MalliVirhe, poista_koodiaidat


class Vastaus:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data if data is not None else {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def chat(content, reasoning=None, finish="stop"):
    viesti = {"role": "assistant", "content": content}
    if reasoning is not None:
        viesti["reasoning_content"] = reasoning
    return Vastaus(200, {"choices": [{"message": viesti, "finish_reason": finish}]})


class Istunto:
    """Jono vastauksia tai poikkeuksia; kirjaa kutsut."""

    def __init__(self, *jono):
        self.jono = list(jono)
        self.kutsut = []
        self.headers = {}

    def post(self, url, **kwargs):
        self.kutsut.append((url, kwargs))
        v = self.jono.pop(0) if len(self.jono) > 1 else self.jono[0]
        if isinstance(v, Exception):
            raise v
        return v


@pytest.fixture(autouse=True)
def ei_odotusta(monkeypatch):
    monkeypatch.setattr(malli_moduuli.time, "sleep", lambda s: None)


def malli_istunnolla(*jono, **kw):
    m = Malli(avain="testiavain", **kw)
    m.istunto = Istunto(*jono)
    return m


# ---------------------------------------------------------------- kysy

def test_kysy_lukee_contentin_ei_reasoning_contentia():
    m = malli_istunnolla(chat("Vastaus tähän.", reasoning="ajattelua jota ei haluta"))
    assert m.kysy("järjestelmä", "käyttäjä") == "Vastaus tähän."


def test_kysy_pyynnon_muoto():
    m = malli_istunnolla(chat("ok"))
    m.kysy("sys", "usr", max_tokens=123, lampotila=0.3)
    url, kw = m.istunto.kutsut[0]
    assert url == "https://api.lehmus-ai.oulu.fi/v1/chat/completions"
    assert kw["json"]["model"] == "jwwqblcgkizlhxjjbkcp"          # gemma31
    assert kw["json"]["messages"] == [{"role": "system", "content": "sys"},
                                      {"role": "user", "content": "usr"}]
    assert kw["json"]["max_tokens"] == 123 and kw["json"]["temperature"] == 0.3
    assert kw["timeout"] == 600


def test_malli_avain_tai_suora_model_id():
    assert Malli("qwen27", avain="x").malli_id == "Qwen3.8-27B"
    assert Malli("jokin-suora-id", avain="x").malli_id == "jokin-suora-id"


def test_avain_puuttuu(monkeypatch):
    monkeypatch.delenv("LEHMUS_API_KEY", raising=False)
    with pytest.raises(ValueError, match="LEHMUS_API_KEY"):
        Malli()


@pytest.mark.parametrize("content", ["", None, "   \n"])
def test_tyhja_content_on_virhe(content):
    m = malli_istunnolla(chat(content, reasoning="pitkä ajattelu", finish="length"))
    with pytest.raises(MalliVirhe, match="tyhjän content"):
        m.kysy("s", "u")


def test_odottamaton_vastausmuoto_on_virhe():
    m = malli_istunnolla(Vastaus(200, {"error": "outo"}))
    with pytest.raises(MalliVirhe, match="Odottamaton"):
        m.kysy("s", "u")


def test_5xx_ja_429_yritetaan_uudelleen():
    m = malli_istunnolla(Vastaus(503), Vastaus(429), chat("läpi"))
    assert m.kysy("s", "u") == "läpi"
    assert len(m.istunto.kutsut) == 3


def test_verkkovirhe_yritetaan_uudelleen():
    m = malli_istunnolla(requests.ConnectionError("poikki"), chat("läpi"))
    assert m.kysy("s", "u") == "läpi"


def test_uudelleenyritykset_loppuvat():
    m = malli_istunnolla(Vastaus(500))
    with pytest.raises(requests.HTTPError):
        m.kysy("s", "u")
    assert len(m.istunto.kutsut) == 4          # ensimmäinen + 3 uudelleenyritystä


def test_4xx_ei_yritetä_uudelleen():
    m = malli_istunnolla(Vastaus(401))
    with pytest.raises(requests.HTTPError):
        m.kysy("s", "u")
    assert len(m.istunto.kutsut) == 1


# ---------------------------------------------------------------- JSON

def test_poista_koodiaidat():
    assert poista_koodiaidat('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert poista_koodiaidat('```\n[1, 2]\n```  ') == "[1, 2]"
    assert poista_koodiaidat('{"a": 1}') == '{"a": 1}'


def test_kysy_json_purkaa_koodiaidat():
    m = malli_istunnolla(chat('```json\n{"haut": ["a", "b"]}\n```'))
    assert m.kysy_json("s", "u") == {"haut": ["a", "b"]}
    assert len(m.istunto.kutsut) == 1


def test_kysy_json_sietaa_selitystekstin_json_ymparilla():
    m = malli_istunnolla(chat('Tässä vastaus:\n[{"osuma": "O1"}]\nToivottavasti auttaa.'))
    assert m.kysy_json("s", "u") == [{"osuma": "O1"}]


def test_kysy_json_valittaa_kwargit_kysylle():
    m = malli_istunnolla(chat("[]"))
    assert m.kysy_json("s", "u", max_tokens=77) == []
    assert m.istunto.kutsut[0][1]["json"]["max_tokens"] == 77


def test_kysy_json_yrittaa_kerran_uudelleen_virheilmoituksen_kanssa():
    m = malli_istunnolla(chat('{"rikki": '), chat('{"ok": true}'))
    assert m.kysy_json("s", "alkuperäinen kysymys") == {"ok": True}
    assert len(m.istunto.kutsut) == 2
    toinen = m.istunto.kutsut[1][1]["json"]["messages"][1]["content"]
    assert "alkuperäinen kysymys" in toinen
    assert "ei ollut kelvollista JSONia" in toinen and "virhe:" in toinen


def test_kysy_json_epaonnistuu_kahden_yrityksen_jalkeen():
    m = malli_istunnolla(chat("ei jsonia lainkaan"))
    with pytest.raises(MalliVirhe, match="JSON"):
        m.kysy_json("s", "u")
    assert len(m.istunto.kutsut) == 2


def test_kysy_json_tyhja_content_on_virhe_eika_yritys():
    m = malli_istunnolla(chat(""))
    with pytest.raises(MalliVirhe, match="tyhjän content"):
        m.kysy_json("s", "u")


def test_kysy_json_kirjoittaa_lokin(tmp_path):
    m = malli_istunnolla(chat("rikki"), chat('{"a": 1}'))
    m.kysy_json("järjestelmäkehote", "käyttäjäkehote", loki=tmp_path / "loki" / "k1_haut")
    kehote = (tmp_path / "loki" / "k1_haut.kehote.txt").read_text(encoding="utf-8")
    vastaus = (tmp_path / "loki" / "k1_haut.vastaus.txt").read_text(encoding="utf-8")
    assert "järjestelmäkehote" in kehote and "käyttäjäkehote" in kehote
    assert "rikki" in vastaus and '{"a": 1}' in vastaus
    json.loads(vastaus.split("=== UUDELLEENYRITYS ===")[1])
