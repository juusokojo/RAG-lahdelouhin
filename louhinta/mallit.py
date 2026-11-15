"""Moduulien yhteiset tietorakenteet. Selitykset: docs/maarittely.md.

Tätä tiedostoa ei muuteta ilman koordinaattorin lupaa, koska kaikki moduulit
nojaavat siihen. Kaikki luokat ovat JSON-kelpoisia (dataclasses.asdict).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------- kysymykset

@dataclass
class Kysymys:
    nro: int                    # juokseva numero koko patterissa (1–34)
    ryhma: str                  # "K1"
    ryhma_otsikko: str          # "Ohjeistuksen ajoitus"
    merkinnat: list[str]        # ["P"] tai ["J", "E"]; tyhjä, jos ei merkintää
    teksti: str                 # kysymys yhtenä kappaleena, rivinvaihdot poistettu


@dataclass
class Patteri:
    tehtava: str                # TEHTÄVÄ-osion teksti ("" jos puuttuu)
    saannot: list[str]          # SÄÄNNÖT-osion kohdat ilman numerointia
    rakenne: list[str]          # RAPORTIN RAKENNE -osion kohdat ilman numerointia
    kysymykset: list[Kysymys]


# ---------------------------------------------------------------- haku

@dataclass
class Osuma:
    """Yksi /context-haun palauttama tekstinpätkä paikannettuna lähdetekstiin."""
    file_id: str
    tiedosto: str               # metadata.filename, esim. "kolbe_etal_2020.pdf"
    teksti: str                 # pätkä sellaisena kuin RAG sen palautti
    pisteet: float
    pdf_sivut: list[int]        # 1-pohjaiset PDF-sivut; [] jos paikannus epäonnistui


@dataclass
class Paikannus:
    """Lainaus leikattuna lähdetekstistä. Lainaus EI ole kielimallin tuottamaa tekstiä."""
    lainaus: str                # source_text[alku:loppu] siistittynä näyttöä varten
    alku: int                   # merkki-indeksit alkuperäisessä source_textissä
    loppu: int
    pdf_sivu_alku: int          # 1-pohjainen
    pdf_sivu_loppu: int
    tapa: str                   # "tarkka" | "sumea"
    pisteet: float              # 100.0 tarkalle, muuten rapidfuzz-pisteet


# ---------------------------------------------------------------- vastaukset

@dataclass
class Loydos:
    """Yksi tarkistettu väite lainauksineen. Syntyy vain onnistuneesta paikannuksesta."""
    tunnus: str                 # "L1", "L2" …, yksilöllinen kysymyksen sisällä
    kysymys_nro: int
    file_id: str
    tiedosto: str               # avain lähderekisteriin (lahteet.json)
    vaite: str                  # mitä lähde toteaa, suomeksi omin sanoin
    lainaus: str                # Paikannus.lainaus
    pdf_sivu_alku: int
    pdf_sivu_loppu: int
    nayton_vahvuus: str = ""    # "vahva" | "kohtalainen" | "alustava" | "asiantuntijan näkemys" | ""
    siirretty_alalta: str = ""  # esim. "hoitotyö"; "" jos ei siirretty
    tapa: str = "tarkka"        # Paikannus.tapa


@dataclass
class Osio:
    otsikko: str                # esim. "LÄHDE SANOO"; "" jos vastauksessa on vain yksi osio
    teksti: str                 # kappaleet erotettu "\n\n"; viittaukset löydöksiin muodossa [L1]


@dataclass
class Vastaus:
    kysymys_nro: int
    osiot: list[Osio] = field(default_factory=list)
    loydokset: list[Loydos] = field(default_factory=list)
    ei_vastausta: bool = False  # True -> tulostetaan "Ei vastausta liitetyissä lähteissä."
    huomiot: list[str] = field(default_factory=list)   # esim. "Nimettyä lähdettä X ei ole kirjastossa"


# ---------------------------------------------------------------- lähteet

@dataclass
class Tekija:
    suku: str                   # "Kolbe"; yhteisötekijällä koko nimi ja etu = ""
    etu: str                    # "Michaela" tai "M."; muotoilija tekee nimikirjaimet


@dataclass
class Lahde:
    """Yksi lähderekisterin (lahteet.json) rivi. Avaimena RAGin tiedostonimi."""
    tiedosto: str
    tyyppi: str = "artikkeli"   # "artikkeli" | "kirja" | "luku" | "raportti" | "verkkosivu"
    tekijat: list[Tekija] = field(default_factory=list)
    vuosi: str = ""             # "2020"; "n.d." jos ei tiedossa
    otsikko: str = ""
    julkaisu: str = ""          # lehden nimi (artikkeli) tai kirjan nimi (luku)
    vuosikerta: str = ""
    numero: str = ""
    sivut: str = ""             # "165–172"
    artikkelinumero: str = ""   # esim. "e0123456", jos lehdessä ei ole sivunumerointia
    toimittajat: list[Tekija] = field(default_factory=list)   # vain tyyppi "luku"
    kustantaja: str = ""
    doi: str = ""               # pelkkä tunniste ilman https://doi.org/
    url: str = ""
    aloitussivu: int | None = None   # painettu sivunumero PDF:n sivulla 1; None = ei painettua sivutusta
    tarkistettu: bool = False   # käyttäjä on tarkistanut rivin
    huomio: str = ""            # rakentajan havainnot, esim. "aloitussivu ja Crossrefin sivut ristiriidassa"
    aineisto: str = ""          # tutkimusaineisto käsin, esim. "11 haastattelua: 10 äitiä ja yksi pariskunta"
