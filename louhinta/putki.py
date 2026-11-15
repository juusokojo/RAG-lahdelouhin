"""Putki: yksi kysymys -> Vastaus. Määrittely: docs/maarittely.md, luku 2.

Ydinperiaate: kielimallin tuottama teksti ei koskaan päädy lainaukseksi. Malli
ehdottaa lainausta, paikannus.py etsii ehdotuksen lähdetekstistä ja leikkaa
lainauksen sieltä. Ehdotus, jota ei löydy, hylätään. Viitteet muodostaa ohjelma.
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from louhinta.lahteet import lyhytviite
from louhinta.lehmus import Rag
from louhinta.malli import Malli, MalliVirhe
from louhinta.mallit import Kysymys, Lahde, Loydos, Osio, Osuma, Patteri, Vastaus
from louhinta.paikannus import laajenna_virkkeisiin, normalisoi, paikanna_lainaus, siisti, sivu

# ---------------------------------------------------------------- asetukset

HAKU_RAJAAMATON = 8        # max_chunks hakulausetta kohti
HAKU_NIMETTY = 6           # max_chunks nimettyä tiedostoa kohti
NIMETTY_ENINTAAN = 10      # nimetyn tiedoston osumia enintään (parhaat pisteet)
OSUMIA_ENINTAAN = 40
OSUMIA_KUTSUSSA = 12
MIN_LAINAUS = 40           # normalisoituja merkkejä (kirjaimet ja numerot)
LAINAUS_ENINTAAN = 700     # lainaus laajennetaan kokonaisiin virkkeisiin vain, jos tulos on enintään näin pitkä
LAMPOTILA = 0.0            # poiminta ja osuvuustarkistus

# ---------------------------------------------------------------- kehotteet

HAKU_JARJESTELMA = (
    "Olet tutkimuskirjaston hakuavustaja. Valmistelet hakuja kirjaston artikkelikokoelmaan. "
    "Vastaat aina pelkällä JSON-oliolla, et mitään muuta."
)
HAKU_KAYTTAJA = """Kysymys:
{kysymys}

Kirjaston lähteet (tiedostonimi: tekijät, vuosi, otsikko):
{luettelo}

Tehtävä:
1. Kirjoita 3–4 englanninkielistä hakulausetta, jotka löytävät kysymykseen vastaavat kohdat \
tieteellisistä artikkeleista. Hakulauseet ovat luonnollisen kielen lauseita tai lauseenosia, \
joita semanttinen haku ymmärtää (ei lainausmerkkejä, ei AND/OR-operaattoreita, ei tekijännimiä). \
Jokainen hakulause on itsenäinen, tarkka ja erilainen kuin muut (esimerkiksi eri käsitteet, \
synonyymit, eri näkökulmat).
2. "nimetyt": tiedostonimet luettelosta, joihin kysymys viittaa nimeltä (tekijä ja vuosi) \
tai joita sen perusteella kuuluu etsiä. Käytä tiedostonimiä täsmälleen luettelon mukaan.
3. "puuttuvat": kysymyksessä nimetyt lähteet (tekijä ja vuosi tekstinä), joita luettelossa ei ole.

Vastaa täsmälleen tässä muodossa:
{{"haut": ["...", "..."], "nimetyt": ["tiedosto.pdf"], "puuttuvat": ["Tekijä (2020)"]}}"""

POIMINTA_JARJESTELMA = (
    "Olet tarkka tutkimusavustaja. Poimit tieteellisten artikkelien tekstikatkelmista "
    "kysymykseen vastaavat kohdat ja kopioit niistä lainaukset merkilleen. "
    "Et keksi mitään, mikä ei ole katkelmissa. Vastaat aina pelkällä JSONilla."
)
POIMINTA_KAYTTAJA = """Kysymys:
{kysymys}

Alla on numeroituja katkelmia (O1, O2, …) artikkeleista. Lähde ja PDF-sivut on kerrottu \
jokaisen katkelman otsikossa.

{osumat}

Tehtävä: poimi katkelmista kohdat, jotka vastaavat kysymykseen tai valaisevat sitä selvästi \
(myös osittainen vastaus tai lähteen omat rajaukset ja varaukset käyvät, kunhan ne liittyvät \
kysymyksen aiheeseen). Älä poimi kohtia, jotka vain sivuavat aihetta. \
Palauta JSON-lista, jonka jokainen alkio on muotoa
{{"osuma": "O3", "vaite": "...", "lainaus": "..."{lisakentat}}}

Säännöt:
- "osuma" on sen katkelman tunnus, josta lainaus on kopioitu.
- "vaite": mitä lähde tässä kohdassa toteaa, yhtenä tai kahtena lauseena suomeksi, omin sanoin. \
Älä lisää mitään, mitä katkelma ei sano.
- "lainaus": 1–3 virkettä, kopioitu katkelmasta merkilleen sellaisena kuin se siinä on: \
alkuperäinen kieli, ei käännöstä, ei korjauksia, ei lyhennysmerkkejä (… tai [...]), \
ei yhdistelyä eri kohdista. Lainauksen pitää olla vähintään noin 60 merkkiä pitkä ja \
yhtenäinen pätkä yhdestä katkelmasta.
- Sama kohta vain kerran. Jos katkelma ei vastaa kysymykseen, jätä se pois.
- Jos mikään katkelma ei vastaa kysymykseen, palauta tyhjä lista: []
{lisaohje}"""
LISAKENTAT_VAHVUUS = ', "nayton_vahvuus": "..."'
LISAKENTAT_ALASIIRTO = ', "siirretty_alalta": "..."'
LISAOHJE_VAHVUUS = """- "nayton_vahvuus": arvioi näytön vahvuus tämän lähdetyypin perusteella \
(vahva / kohtalainen / alustava / asiantuntijan näkemys) säännön mukaan:
  {saanto}"""
LISAOHJE_ALASIIRTO = """- "siirretty_alalta": jos lähteen tulos on peräisin toiselta alalta kuin kysymys \
(esim. hoitotyö, lääketiede, matematiikka), kirjoita ala; muuten tyhjä merkkijono "". Sääntö:
  {saanto}"""

OSUVUUS_JARJESTELMA = (
    "Olet tarkka tutkimusavustaja, joka arvioi, vastaavatko jo tarkistetut lainaukset kysymykseen. "
    "Et muuta lainauksia. Vastaat aina pelkällä JSONilla."
)
OSUVUUS_KAYTTAJA = """Kysymys:
{kysymys}

Löydökset (tunnus, lähde, väite, lainaus):
{loydokset}

Tehtävä: arvioi jokaisesta löydöksestä, kuinka hyvin lainaus liittyy kysymykseen. Arvio on yksi seuraavista:
- "suora": lainaus vastaa kysymykseen tai sen osaan suoraan.
- "osittainen": lainaus valaisee kysymyksen aihetta, antaa taustaa tai rajauksia tai vastaa vain osaan.
- "ei": lainaus ei käsittele kysymyksen aihetta lainkaan.
Anna "ei" vain, kun lainaus ei käsittele kysymyksen aihetta lainkaan; taustaa tai rajauksia antava kohta on "osittainen". \
Epäselvässä tapauksessa valitse "osittainen". Perustelu on yksi virke suomeksi.

Vastaa täsmälleen tässä muodossa, yksi alkio jokaisesta löydöksestä:
[{{"tunnus": "L1", "arvio": "suora", "perustelu": "..."}}]"""

KOONTI_JARJESTELMA = (
    "Olet tarkka tutkimusavustaja, joka kirjoittaa suomenkielisen vastauksen vain annettujen, "
    "jo tarkistettujen löydösten pohjalta. Vastaat aina pelkällä JSONilla."
)
KOONTI_KAYTTAJA = """Tehtävänanto:
{tehtava}

Säännöt:
{saannot}

Kysymys:
{kysymys}

Tarkistetut löydökset (tunnus, lähde, väite, lainaus{vahvuus_otsikko}):
{loydokset}

Kirjoita vastaus kysymykseen. Vaatimukset:
- Käytä vain löydösten tietoa. Älä lisää tietoa, jota löydöksissä ei ole.
- Viittaa jokaiseen väitteeseen löydöksen tunnuksella hakasulkeissa, esim. [L1]. Useampi tunnus \
omina hakasulkeinaan: [L1] [L2]. Käytä vain yllä lueteltuja tunnuksia.
- Älä kirjoita tekstiin tekijöitä, vuosilukuja, sivunumeroita tai lainauksia: ohjelma korvaa \
tunnukset viitteillä ja liittää lainaukset erikseen.
- Jos löydökset ovat ristiriidassa, esitä molemmat kannat ja viittaa kumpaankin.
- Osiot: jos säännöt määräävät vastaukseen tietyt osat (esim. "LÄHDE SANOO" ja "EHDOTUS VIDEOON"), \
tee täsmälleen ne osiot samassa järjestyksessä ja käytä niiden nimiä sellaisenaan otsikkoina. \
Älä keksi omia osio-otsikoita äläkä toista osan nimeä tekstin alussa. Jaa osion sisältö tarvittaessa \
kappaleisiin (aiheen tai kysymyksen alakohdan mukaan). Osio, jossa pyydetään ehdotusta tai \
soveltamista, saa sisältää omaa päättelyäsi, mutta sen on perustuttava löydöksiin ja viitattava \
niihin tunnuksilla; kirjoita se ehdotuksena, ei tosiasiana. Jos säännöt eivät määrää osioita, \
tee yksi osio, jonka otsikko on "".
- Jätä huomiotta säännöt, jotka koskevat lähdeluetteloa, sivunumeroita tai sitä, miten lähteet \
luettiin: ohjelma hoitaa ne.
- Kappaleet erotetaan tyhjällä rivillä (\\n\\n osion tekstissä). Kirjoita suomeksi; menetelmien ja \
mallien alkuperäiset nimet säilytetään.

Vastaa täsmälleen tässä muodossa:
{{"osiot": [{{"otsikko": "...", "teksti": "..."}}]}}"""

# ---------------------------------------------------------------- tulosrakenteet


@dataclass
class Tilasto:
    osumia: int = 0
    ehdotuksia: int = 0
    hyvaksyttyja: int = 0       # paikannus onnistui (ennen päällekkäisten yhdistämistä)
    sumeita: int = 0            # lopullisista löydöksistä
    hylattyja: int = 0
    osuvuus_pudotettuja: int = 0   # osuvuustarkistuksessa ("ei") pudotetut löydökset
    loydoksia: int = 0          # lopulliset löydökset yhdistämisen jälkeen
    syyt: dict[str, int] = field(default_factory=dict)   # hylkäyssyy -> lukumäärä
    kesto_s: float = 0.0


_tiedostot_lukko = threading.Lock()


def _tiedostot(rag: Rag) -> dict[str, str]:
    """Kirjaston tiedostot tiedostonimi -> id; haetaan kerran per Rag-olio (turvallinen rinnakkaisajossa)."""
    with _tiedostot_lukko:
        if not hasattr(rag, "_putki_tiedostot"):
            rag._putki_tiedostot = {t["tiedosto"]: t["id"] for t in rag.tiedostot()}
        return rag._putki_tiedostot


def _lahdenimi(tiedosto: str, lahteet: dict[str, Lahde]) -> str:
    lahde = lahteet.get(tiedosto)
    if lahde is None or not lahde.tekijat:
        return tiedosto
    return lyhytviite(lahde)


def _kirjastoluettelo(tiedostot: dict[str, str], lahteet: dict[str, Lahde]) -> str:
    rivit = []
    for nimi in sorted(tiedostot):
        lahde = lahteet.get(nimi)
        if lahde is not None and lahde.tekijat:
            tekijat = ", ".join(t.suku for t in lahde.tekijat[:4]) + (" ym." if len(lahde.tekijat) > 4 else "")
            rivit.append(f"- {nimi}: {tekijat}, {lahde.vuosi or 'n.d.'}, {lahde.otsikko}")
        else:
            rivit.append(f"- {nimi}")
    return "\n".join(rivit)


def _vaaditaan(patteri: Patteri, malli: str) -> str | None:
    """Patterin sääntö, joka vaatii näytön vahvuuden ("vahvuu…") tai alasiirron ("toiselta alalta"); muuten None."""
    for saanto in patteri.saannot:
        if re.search(malli, saanto, re.IGNORECASE):
            return " ".join(saanto.split())
    return None


# ---------------------------------------------------------------- vaiheet

def _hakulauseet(kysymys: Kysymys, tiedostot: dict[str, str], lahteet: dict[str, Lahde],
                 malli: Malli, loki: Path | None, huomiot: list[str]) -> tuple[list[str], list[str]]:
    kayttaja = HAKU_KAYTTAJA.format(kysymys=kysymys.teksti, luettelo=_kirjastoluettelo(tiedostot, lahteet))
    vastaus = malli.kysy_json(HAKU_JARJESTELMA, kayttaja, loki=_lokipolku(loki, kysymys, "1_haut"))
    if not isinstance(vastaus, dict):
        raise MalliVirhe("hakulauseiden vastaus ei ole JSON-olio")
    haut = [h.strip() for h in vastaus.get("haut") or [] if isinstance(h, str) and h.strip()]
    if not haut:
        haut = [kysymys.teksti]
        huomiot.append("Malli ei antanut hakulauseita; haussa käytettiin kysymystekstiä.")
    nimetyt = []
    for nimi in vastaus.get("nimetyt") or []:
        if not isinstance(nimi, str):
            continue
        if nimi in tiedostot:
            if nimi not in nimetyt:
                nimetyt.append(nimi)
        else:
            huomiot.append(f"Malli nimesi tiedoston {nimi}, jota ei ole kirjastossa.")
    for puuttuva in vastaus.get("puuttuvat") or []:
        if isinstance(puuttuva, str) and puuttuva.strip():
            huomiot.append(f"Kysymyksessä nimettyä lähdettä ei ole kirjastossa: {puuttuva.strip()}")
    return haut[:4], nimetyt


def _hae(rag: Rag, haut: list[str], nimetyt: list[str], tiedostot: dict[str, str]) -> list[Osuma]:
    """Rajaamattomat haut + nimettyihin rajatut haut. Sama pätkä vain kerran; enintään OSUMIA_ENINTAAN."""
    nimetyt_idt = {tiedostot[n] for n in nimetyt}
    ainutkertaiset: dict[tuple[str, str], Osuma] = {}
    for haku in haut:
        for osuma in rag.hae(haku, max_chunks=HAKU_RAJAAMATON):
            ainutkertaiset.setdefault((osuma.file_id, osuma.teksti), osuma)
    nimettyja: dict[tuple[str, str], Osuma] = {}
    for nimi in nimetyt:
        omat: dict[tuple[str, str], Osuma] = {}
        for haku in haut:
            for osuma in rag.hae(haku, max_chunks=HAKU_NIMETTY, filter_ids=[tiedostot[nimi]]):
                avain = (osuma.file_id, osuma.teksti)
                if avain not in omat or omat[avain].pisteet < osuma.pisteet:
                    omat[avain] = osuma
        parhaat = sorted(omat.items(), key=lambda p: -p[1].pisteet)[:NIMETTY_ENINTAAN]
        nimettyja.update(parhaat)
    # nimettyjen osumat säilytetään aina; loput täydennetään pisteiden mukaan
    nimetyt_lista = sorted(nimettyja.values(), key=lambda o: -o.pisteet)[:OSUMIA_ENINTAAN]
    muut = sorted((o for k, o in ainutkertaiset.items() if k not in nimettyja),
                  key=lambda o: -o.pisteet)
    return nimetyt_lista + muut[:OSUMIA_ENINTAAN - len(nimetyt_lista)]


def _sivuteksti(sivut: list[int]) -> str:
    if not sivut:
        return "PDF-sivu tuntematon"
    if len(sivut) == 1:
        return f"PDF-sivu {sivut[0]}"
    return f"PDF-sivut {sivut[0]}–{sivut[-1]}"


def _poimi(kysymys: Kysymys, patteri: Patteri, osumat: list[Osuma], lahteet: dict[str, Lahde],
           malli: Malli, loki: Path | None, huomiot: list[str]) -> list[tuple[dict, Osuma]]:
    """Mallin lainausehdotukset (ei vielä tarkistettu), pareina (ehdotus, osuma). Ehdotus voi olla virheellinen."""
    vahvuus = _vaaditaan(patteri, r"näytön\s+vahvuu")
    alasiirto = _vaaditaan(patteri, r"toiselta\s+alalta|siirretty")
    lisakentat = (LISAKENTAT_VAHVUUS if vahvuus else "") + (LISAKENTAT_ALASIIRTO if alasiirto else "")
    lisaohje = "\n".join(
        ([LISAOHJE_VAHVUUS.format(saanto=vahvuus)] if vahvuus else [])
        + ([LISAOHJE_ALASIIRTO.format(saanto=alasiirto)] if alasiirto else []))

    ehdotukset: list[tuple[dict, Osuma]] = []
    onnistuneita = 0
    virheet: list[str] = []
    erat = [osumat[i:i + OSUMIA_KUTSUSSA] for i in range(0, len(osumat), OSUMIA_KUTSUSSA)]
    for era_nro, era in enumerate(erat, 1):
        tunnukset = {f"O{i}": o for i, o in enumerate(era, 1)}
        osumateksti = "\n\n".join(
            f"[{tunnus}] Lähde: {_lahdenimi(o.tiedosto, lahteet)} ({o.tiedosto}), {_sivuteksti(o.pdf_sivut)}\n"
            f"{o.teksti}" for tunnus, o in tunnukset.items())
        kayttaja = POIMINTA_KAYTTAJA.format(kysymys=kysymys.teksti, osumat=osumateksti,
                                            lisakentat=lisakentat, lisaohje=lisaohje)
        try:
            vastaus = malli.kysy_json(POIMINTA_JARJESTELMA, kayttaja,
                                      loki=_lokipolku(loki, kysymys, f"2_poiminta{era_nro}"), max_tokens=6000, lampotila=LAMPOTILA)
        except MalliVirhe as virhe:
            virheet.append(f"poimintakutsu {era_nro}/{len(erat)} epäonnistui: {virhe}")
            huomiot.append(virheet[-1][0].upper() + virheet[-1][1:])
            continue
        onnistuneita += 1
        if isinstance(vastaus, dict):       # malli palautti yhden alkion tai kietoi listan olioon
            vastaus = [vastaus] if "osuma" in vastaus else next(
                (v for v in vastaus.values() if isinstance(v, list)), [])
        if not isinstance(vastaus, list):
            huomiot.append(f"Poimintakutsu {era_nro}/{len(erat)}: vastaus ei ollut lista.")
            continue
        for alkio in vastaus:
            osuma = tunnukset.get(str(alkio.get("osuma", "")).strip()) if isinstance(alkio, dict) else None
            ehdotukset.append((alkio if isinstance(alkio, dict) else {"lainaus": str(alkio)}, osuma))
    if erat and not onnistuneita:
        raise MalliVirhe("kaikki poimintakutsut epäonnistuivat: " + "; ".join(virheet))
    return ehdotukset


def _tarkista(kysymys: Kysymys, ehdotukset: list[tuple[dict, Osuma | None]], rag: Rag,
              lahteet: dict[str, Lahde], tilasto: Tilasto, loki: Path | None) -> list[Loydos]:
    """Paikantaa ehdotukset lähdetekstiin, hylkää löytymättömät, yhdistää päällekkäiset ja numeroi."""
    ehdokkaat: list[dict] = []
    hylatyt: list[dict] = []

    def hylkaa(syy: str, ehdotus: dict) -> None:
        tilasto.hylattyja += 1
        tilasto.syyt[syy] = tilasto.syyt.get(syy, 0) + 1
        hylatyt.append({"syy": syy, "ehdotus": ehdotus})

    for ehdotus, osuma in ehdotukset:
        tilasto.ehdotuksia += 1
        lainaus = ehdotus.get("lainaus")
        if osuma is None:
            hylkaa("tuntematon osumatunnus", ehdotus)
            continue
        if not isinstance(lainaus, str) or not lainaus.strip():
            hylkaa("tyhjä lainaus", ehdotus)
            continue
        try:
            teksti = rag.lahdeteksti(osuma.file_id)
        except (ValueError, OSError) as virhe:
            hylkaa(f"lähdetekstiä ei saatu ({virhe})", ehdotus)
            continue
        p = paikanna_lainaus(lainaus, teksti, min_pituus=MIN_LAINAUS)
        if p is None:
            hylkaa("liian lyhyt" if len(normalisoi(lainaus)) < MIN_LAINAUS else "ei löydy lähdetekstistä", ehdotus)
            continue
        tilasto.hyvaksyttyja += 1
        tapa = p.tapa
        sivut = set(range(p.pdf_sivu_alku, p.pdf_sivu_loppu + 1))
        # lainaus kokonaisiksi virkkeiksi, jos tulos ei veny liian pitkäksi
        alku, loppu = laajenna_virkkeisiin(teksti, p.alku, p.loppu)
        if (alku, loppu) == (p.alku, p.loppu) or len(siisti(teksti[alku:loppu])) > LAINAUS_ENINTAAN:
            alku, loppu = p.alku, p.loppu
        if osuma.pdf_sivut and not sivut & set(osuma.pdf_sivut):
            tapa = "sumea"          # lainaus löytyi, mutta ei osuman sivuilta: merkitään tarkistettavaksi
        ehdokkaat.append({
            "file_id": osuma.file_id, "tiedosto": osuma.tiedosto, "teksti": teksti,
            "alku": alku, "loppu": loppu, "tapa": tapa,
            "vaite": str(ehdotus.get("vaite") or "").strip(),
            "vahvuus": str(ehdotus.get("nayton_vahvuus") or "").strip(),
            "alasiirto": str(ehdotus.get("siirretty_alalta") or "").strip(),
        })

    # päällekkäiset (sama tiedosto, leikkaava väli) yhdistetään; yhdistetty lainaus leikataan uudelleen lähteestä
    yhdistetyt: list[dict] = []
    for e in ehdokkaat:
        for y in yhdistetyt:
            if y["file_id"] == e["file_id"] and e["alku"] < y["loppu"] and y["alku"] < e["loppu"]:
                y["alku"], y["loppu"] = min(y["alku"], e["alku"]), max(y["loppu"], e["loppu"])
                if e["vaite"] and e["vaite"] not in y["vaite"]:
                    y["vaite"] = f"{y['vaite']} {e['vaite']}".strip()
                y["vahvuus"] = y["vahvuus"] or e["vahvuus"]
                y["alasiirto"] = y["alasiirto"] or e["alasiirto"]
                if e["tapa"] == "sumea":
                    y["tapa"] = "sumea"
                break
        else:
            yhdistetyt.append(dict(e))

    loydokset = []
    for i, y in enumerate(yhdistetyt, 1):
        teksti = y["teksti"]
        loydokset.append(Loydos(
            tunnus=f"L{i}", kysymys_nro=kysymys.nro, file_id=y["file_id"], tiedosto=y["tiedosto"],
            vaite=y["vaite"], lainaus=siisti(teksti[y["alku"]:y["loppu"]]),
            pdf_sivu_alku=sivu(teksti, y["alku"]), pdf_sivu_loppu=sivu(teksti, y["loppu"] - 1),
            nayton_vahvuus=y["vahvuus"], siirretty_alalta=y["alasiirto"], tapa=y["tapa"]))
    tilasto.loydoksia = len(loydokset)
    tilasto.sumeita = sum(1 for l in loydokset if l.tapa == "sumea")
    if loki is not None and hylatyt:
        _kirjoita_loki(loki, kysymys, "3_hylatyt.json", json.dumps(hylatyt, ensure_ascii=False, indent=2))
    return loydokset


def _osuvuus(kysymys: Kysymys, loydokset: list[Loydos], lahteet: dict[str, Lahde], malli: Malli,
             tilasto: Tilasto, loki: Path | None, huomiot: list[str]) -> list[Loydos]:
    """Yksi mallikutsu: pudottaa löydökset, joiden arvio on "ei"; numeroi loput uudelleen L1…

    Jos kutsu epäonnistuu, löydökset säilytetään ja asia kirjataan huomioihin.
    """
    if loydokset:
        rivit = [f"[{l.tunnus}] Lähde: {_lahdenimi(l.tiedosto, lahteet)}\n  väite: {l.vaite}\n"
                 f"  lainaus: ”{l.lainaus}”" for l in loydokset]
        kayttaja = OSUVUUS_KAYTTAJA.format(kysymys=kysymys.teksti, loydokset="\n\n".join(rivit))
        try:
            vastaus = malli.kysy_json(OSUVUUS_JARJESTELMA, kayttaja, loki=_lokipolku(loki, kysymys, "3b_osuvuus"),
                                      max_tokens=6000, lampotila=LAMPOTILA)
            if isinstance(vastaus, dict):
                vastaus = [vastaus] if "tunnus" in vastaus else next(
                    (v for v in vastaus.values() if isinstance(v, list)), [])
            if not isinstance(vastaus, list):
                raise MalliVirhe("osuvuusvastaus ei ollut lista")
        except Exception as virhe:     # myös verkkovirheet: löydökset säilytetään
            huomiot.append(f"Osuvuustarkistus epäonnistui ({str(virhe)[:200]}); löydökset säilytettiin "
                           "ilman osuvuusarviota.")
            vastaus = []
        arviot = {str(a.get("tunnus", "")).strip(): str(a.get("arvio", "")).strip().lower()
                  for a in vastaus if isinstance(a, dict)}
        pudotetut = [l for l in loydokset if arviot.get(l.tunnus) == "ei"]
        if pudotetut:
            tilasto.osuvuus_pudotettuja = len(pudotetut)
            nimet = ", ".join(l.tiedosto for l in pudotetut)
            huomiot.append(f"{len(pudotetut)} löydöstä pudotettiin osuvuustarkistuksessa "
                           f"(lainaus ei käsitellyt kysymyksen aihetta): {nimet}.")
            if loki is not None:
                perustelut = {str(a.get("tunnus", "")).strip(): str(a.get("perustelu", "")).strip()
                              for a in vastaus if isinstance(a, dict)}
                _kirjoita_loki(loki, kysymys, "3b_pudotetut.json", json.dumps(
                    [{"tunnus": l.tunnus, "tiedosto": l.tiedosto, "vaite": l.vaite, "lainaus": l.lainaus,
                      "perustelu": perustelut.get(l.tunnus, "")} for l in pudotetut],
                    ensure_ascii=False, indent=2))
            loydokset = [l for l in loydokset if arviot.get(l.tunnus) != "ei"]
    tulos = [replace(l, tunnus=f"L{i}") for i, l in enumerate(loydokset, 1)]
    tilasto.loydoksia = len(tulos)
    tilasto.sumeita = sum(1 for l in tulos if l.tapa == "sumea")
    return tulos


_TUNNUS = re.compile(r"\[(L\d+)\]")
_TUNNUSRYHMA = re.compile(r"\[\s*(L\d+(?:\s*(?:,|;|&|ja|–|-)\s*L\d+)+)\s*\]")


def _siisti_tunnukset(teksti: str) -> str:
    """[L1, L2] -> [L1] [L2]; docx-tulostus tunnistaa vain yksittäiset tunnukset."""
    return _TUNNUSRYHMA.sub(lambda m: " ".join(f"[{t}]" for t in re.findall(r"L\d+", m.group(1))), teksti)


def _kokoa(kysymys: Kysymys, patteri: Patteri, loydokset: list[Loydos], lahteet: dict[str, Lahde],
           malli: Malli, loki: Path | None, huomiot: list[str]) -> list[Osio]:
    vahvuus = any(l.nayton_vahvuus or l.siirretty_alalta for l in loydokset)
    rivit = []
    for l in loydokset:
        lisa = []
        if l.nayton_vahvuus:
            lisa.append(f"näytön vahvuus: {l.nayton_vahvuus}")
        if l.siirretty_alalta:
            lisa.append(f"siirretty alalta: {l.siirretty_alalta}")
        rivit.append(f"[{l.tunnus}] Lähde: {_lahdenimi(l.tiedosto, lahteet)}\n"
                     f"  väite: {l.vaite}\n  lainaus: ”{l.lainaus}”"
                     + (f"\n  {'; '.join(lisa)}" if lisa else ""))
    kayttaja = KOONTI_KAYTTAJA.format(
        tehtava=patteri.tehtava or "(ei annettu)",
        saannot="\n".join(f"{i}. {s}" for i, s in enumerate(patteri.saannot, 1)) or "(ei sääntöjä)",
        kysymys=kysymys.teksti, vahvuus_otsikko=", näytön vahvuus ja alasiirto" if vahvuus else "",
        loydokset="\n\n".join(rivit))
    vastaus = malli.kysy_json(KOONTI_JARJESTELMA, kayttaja, loki=_lokipolku(loki, kysymys, "4_koonti"),
                              max_tokens=6000)
    raaka = vastaus.get("osiot") if isinstance(vastaus, dict) else vastaus
    osiot = []
    for alkio in raaka if isinstance(raaka, list) else []:
        if isinstance(alkio, dict) and str(alkio.get("teksti") or "").strip():
            osiot.append(Osio(str(alkio.get("otsikko") or "").strip(), _siisti_tunnukset(str(alkio["teksti"]).strip())))
    if not osiot:
        raise MalliVirhe("koontivastauksessa ei ollut yhtään osiota")
    tunnetut = {l.tunnus for l in loydokset}
    for osio in osiot:
        for tunnus in dict.fromkeys(_TUNNUS.findall(osio.teksti)):
            if tunnus not in tunnetut:
                huomiot.append(f"tuntematon tunnus [{tunnus}] jätettiin tekstiin")
    return osiot


# ---------------------------------------------------------------- loki

def _lokipolku(loki: Path | None, kysymys: Kysymys, vaihe: str) -> Path | None:
    return None if loki is None else Path(loki) / f"k{kysymys.nro}_{vaihe}"


def _kirjoita_loki(loki: Path, kysymys: Kysymys, nimi: str, sisalto: str) -> None:
    loki = Path(loki)
    loki.mkdir(parents=True, exist_ok=True)
    (loki / f"k{kysymys.nro}_{nimi}").write_text(sisalto, encoding="utf-8")


# ---------------------------------------------------------------- julkinen rajapinta

def vastaa_tilastoin(kysymys: Kysymys, patteri: Patteri, rag: Rag, malli: Malli,
                     lahteet: dict[str, Lahde], loki: Path | None = None) -> tuple[Vastaus, Tilasto]:
    alku = time.monotonic()
    tilasto = Tilasto()
    huomiot: list[str] = []
    vastaus = Vastaus(kysymys_nro=kysymys.nro, huomiot=huomiot)
    try:
        tiedostot = _tiedostot(rag)
        haut, nimetyt = _hakulauseet(kysymys, tiedostot, lahteet, malli, loki, huomiot)
        osumat = _hae(rag, haut, nimetyt, tiedostot)
        tilasto.osumia = len(osumat)
        if loki is not None:
            _kirjoita_loki(loki, kysymys, "1_osumat.json", json.dumps(
                {"haut": haut, "nimetyt": nimetyt,
                 "osumat": [{"tiedosto": o.tiedosto, "pisteet": o.pisteet, "pdf_sivut": o.pdf_sivut,
                             "merkkeja": len(o.teksti)} for o in osumat]}, ensure_ascii=False, indent=2))
        if osumat:
            ehdotukset = _poimi(kysymys, patteri, osumat, lahteet, malli, loki, huomiot)
            vastaus.loydokset = _tarkista(kysymys, ehdotukset, rag, lahteet, tilasto, loki)
            vastaus.loydokset = _osuvuus(kysymys, vastaus.loydokset, lahteet, malli, tilasto, loki, huomiot)
        if tilasto.hylattyja:
            syyt = ", ".join(f"{s}: {n}" for s, n in sorted(tilasto.syyt.items()))
            huomiot.append(f"{tilasto.hylattyja} lainausehdotusta hylättiin ({syyt}).")
        if vastaus.loydokset:
            vastaus.osiot = _kokoa(kysymys, patteri, vastaus.loydokset, lahteet, malli, loki, huomiot)
        else:
            vastaus.ei_vastausta = True       # ei mallikutsua
    finally:
        tilasto.kesto_s = round(time.monotonic() - alku, 1)
    return vastaus, tilasto


def vastaa(kysymys: Kysymys, patteri: Patteri, rag: Rag, malli: Malli,
           lahteet: dict[str, Lahde], loki: Path | None = None) -> Vastaus:
    return vastaa_tilastoin(kysymys, patteri, rag, malli, lahteet, loki)[0]


def _lataa_luokka(luokka, d: dict):
    nimet = {f.name for f in fields(luokka)}
    return luokka(**{k: v for k, v in d.items() if k in nimet})


def tallenna_vastaus(v: Vastaus, polku: Path) -> None:
    polku = Path(polku)
    polku.parent.mkdir(parents=True, exist_ok=True)
    polku.write_text(json.dumps(asdict(v), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lataa_vastaus(polku: Path) -> Vastaus:
    d = json.loads(Path(polku).read_text(encoding="utf-8"))
    return Vastaus(
        kysymys_nro=d["kysymys_nro"],
        osiot=[_lataa_luokka(Osio, o) for o in d.get("osiot", [])],
        loydokset=[_lataa_luokka(Loydos, l) for l in d.get("loydokset", [])],
        ei_vastausta=d.get("ei_vastausta", False),
        huomiot=list(d.get("huomiot", [])),
    )
