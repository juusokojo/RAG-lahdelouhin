"""Kielimallin asiakas (OpenAI-yhteensopiva /chat/completions).

Rajapinnan osoite, malli ja avain: ympäristömuuttujat MALLI_URL, MALLI ja
MALLI_API_KEY (puuttuessa RAG_API_KEY, jos sama avain käy molempiin).

Vastaus luetaan vain kentästä choices[0].message.content. Päättelyn jäsentimen
erottama ajattelu (reasoning_content) ei kuulu vastaukseen. Selitykset:
docs/maarittely.md, kohta 2.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests

AIKAKATKAISU = 300        # sekuntia; pitkät poiminta- ja koontikutsut voivat kestää minuutteja
AIKAKATKAISUJA_ENINT = 2  # aikakatkaisun jälkeen yritetään vain kerran uudelleen
UUDELLEENYRITYKSIA = 3    # lisäyrityksiä ensimmäisen jälkeen
ALKUVIIVE = 2.0           # sekuntia; kaksinkertaistuu joka yrityksellä

_AIDAT = re.compile(r"^\s*```[A-Za-z0-9_-]*[ \t]*\r?\n?|\r?\n?```\s*$")


class MalliVirhe(RuntimeError):
    """Mallikutsu epäonnistui tai vastaus oli käyttökelvoton."""


def poista_koodiaidat(teksti: str) -> str:
    """Poistaa vastauksen ympäriltä ```json … ``` -aidat."""
    return _AIDAT.sub("", teksti.strip()).strip()


def _jasenna(teksti: str) -> dict | list:
    """JSON koodiaidoista puhdistetusta tekstistä; sallii JSONia ympäröivän selitystekstin."""
    puhdas = poista_koodiaidat(teksti)
    try:
        return json.loads(puhdas, strict=False)
    except json.JSONDecodeError as virhe:
        # malli saattoi lisätä JSONin ympärille prosaa: kokeillaan ensimmäisestä { tai [ viimeiseen } tai ]
        alku = min((i for i in (puhdas.find("{"), puhdas.find("[")) if i >= 0), default=-1)
        loppu = max(puhdas.rfind("}"), puhdas.rfind("]"))
        if alku >= 0 and loppu > alku:
            try:
                return json.loads(puhdas[alku:loppu + 1], strict=False)
            except json.JSONDecodeError:
                pass
        raise virhe


class Malli:
    def __init__(self, malli: str | None = None, url: str | None = None,
                 avain: str | None = None, aikakatkaisu: int = AIKAKATKAISU):
        avain = avain or os.environ.get("MALLI_API_KEY") or os.environ.get("RAG_API_KEY")
        if not avain:
            raise ValueError("Mallin avain puuttuu: aseta ympäristömuuttuja "
                             "MALLI_API_KEY (tai RAG_API_KEY) tai anna avain-parametri.")
        malli = malli or os.environ.get("MALLI")
        if not malli:
            raise ValueError("Malli puuttuu: aseta ympäristömuuttuja MALLI tai anna malli-parametri.")
        url = url or os.environ.get("MALLI_URL")
        if not url:
            raise ValueError("Mallirajapinnan osoite puuttuu: aseta ympäristömuuttuja "
                             "MALLI_URL tai anna url-parametri.")
        self.nimi = malli
        self.malli_id = malli
        self.url = url.rstrip("/")
        self.aikakatkaisu = aikakatkaisu
        self.istunto = requests.Session()
        self.istunto.headers.update({"Authorization": f"Bearer {avain}",
                                     "Content-Type": "application/json"})

    def _pyynto(self, runko: dict) -> dict:
        """POST uudelleenyrityksin: verkkovirheet, 5xx ja 429 yritetään uudelleen."""
        viive = ALKUVIIVE
        aikakatkaisuja = 0
        for yritys in range(UUDELLEENYRITYKSIA + 1):
            viimeinen = yritys == UUDELLEENYRITYKSIA
            try:
                r = self.istunto.post(f"{self.url}/chat/completions", json=runko,
                                      timeout=self.aikakatkaisu)
            except requests.Timeout:
                aikakatkaisuja += 1
                if viimeinen or aikakatkaisuja >= AIKAKATKAISUJA_ENINT:
                    raise
            except requests.RequestException:
                if viimeinen:
                    raise
            else:
                if r.status_code != 429 and r.status_code < 500:
                    r.raise_for_status()
                    return r.json()
                if viimeinen:
                    r.raise_for_status()
            time.sleep(viive)
            viive *= 2
        raise AssertionError("ei pitäisi päätyä tänne")

    def kysy(self, jarjestelma: str, kayttaja: str, max_tokens: int = 4000,
             lampotila: float = 0.1) -> str:
        """Yksi kierros: järjestelmäkehote + käyttäjän viesti -> vastauksen content."""
        runko = {
            "model": self.malli_id,
            "messages": [{"role": "system", "content": jarjestelma},
                         {"role": "user", "content": kayttaja}],
            "max_tokens": max_tokens,
            "temperature": lampotila,
        }
        vastaus = self._pyynto(runko)
        try:
            valinta = vastaus["choices"][0]
            teksti = valinta["message"].get("content")
        except (KeyError, IndexError, TypeError, AttributeError):
            raise MalliVirhe(f"Odottamaton vastausmuoto mallilta {self.nimi}: {str(vastaus)[:200]}")
        if not teksti or not teksti.strip():
            syy = valinta.get("finish_reason")
            raise MalliVirhe(f"Malli {self.nimi} palautti tyhjän content-kentän (finish_reason={syy}); "
                             f"ajattelu söi todennäköisesti kaikki {max_tokens} tokenia.")
        return teksti

    def kysy_json(self, jarjestelma: str, kayttaja: str, loki: Path | None = None, **kw) -> dict | list:
        """Kuten kysy, mutta jäsentää vastauksen JSONiksi; yrittää kerran uudelleen virheilmoituksen kanssa.

        `loki` on polun etuliite: kehote ja raakavastaukset tallennetaan tiedostoihin
        <loki>.kehote.txt ja <loki>.vastaus.txt (vianetsintää varten).
        """
        raaka = ""
        virhe: Exception | None = None
        lokiteksti = f"=== JÄRJESTELMÄ ===\n{jarjestelma}\n\n=== KÄYTTÄJÄ ===\n{kayttaja}\n"
        vastaukset: list[str] = []
        try:
            for yritys in range(2):
                pyynto = kayttaja
                if yritys:
                    pyynto = (f"{kayttaja}\n\nEdellinen vastauksesi ei ollut kelvollista JSONia "
                              f"(virhe: {virhe}). Vastaa uudelleen: pelkkä kelvollinen JSON, "
                              "ei selityksiä eikä koodiaitoja.")
                raaka = self.kysy(jarjestelma, pyynto, **kw)
                vastaukset.append(raaka)
                try:
                    return _jasenna(raaka)
                except json.JSONDecodeError as e:
                    virhe = e
            raise MalliVirhe(f"Mallin {self.nimi} vastaus ei jäsenny JSONiksi kahdella yrityksellä: {virhe}")
        finally:
            if loki is not None:
                loki = Path(loki)
                loki.parent.mkdir(parents=True, exist_ok=True)
                loki.with_name(loki.name + ".kehote.txt").write_text(lokiteksti, encoding="utf-8")
                loki.with_name(loki.name + ".vastaus.txt").write_text(
                    "\n\n=== UUDELLEENYRITYS ===\n\n".join(vastaukset), encoding="utf-8")
