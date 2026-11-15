# Louhintatyökalun määrittely

Työkalu vastaa kysymyspatteriin Lehmus-RAGin artikkeleiden perusteella ja tuottaa docx-tiedoston, jossa jokaisella vastauksella on sanatarkka lainaus ja APA7-viite sivunumeroineen. Yhteiset tietorakenteet: [louhinta/mallit.py](../louhinta/mallit.py).

## Ydinperiaate

**Kielimallin tuottama teksti ei koskaan päädy lainaukseksi.** Malli ehdottaa lainausta, ohjelma etsii ehdotuksen `source_text`-kentästä ja leikkaa lainauksen sieltä. Sivu lasketaan leikkauskohtaa edeltävistä `\f`-merkeistä. Jos ehdotusta ei löydy, löydös hylätään. Viitteet muodostaa ohjelma lähderekisteristä, ei malli.

## Putki

1. `kysymykset.py` lukee kysymystiedoston → `Patteri`.
2. `putki.py` (vaihe 2) pyytää mallilta hakulauseet, hakee `lehmus.py`:llä → `Osuma`-lista.
3. Malli poimii osumista väitteet ja lainausehdotukset.
4. `paikannus.py` tarkistaa ehdotukset → `Paikannus` → `Loydos`.
4b. Lainaus laajennetaan kokonaisiin virkkeisiin (`laajenna_virkkeisiin`, enintään 700 merkkiä), ja yksi osuvuuskutsu arvioi löydökset ("suora" | "osittainen" | "ei"); "ei" pudotetaan ennen tunnusten L1… antamista. Poiminta ja osuvuustarkistus ajetaan lämpötilalla 0.
5. Malli kirjoittaa vastauksen tarkistetuista löydöksistä ja viittaa niihin tunnuksilla `[L1]` → `Vastaus`.
6. `docx_tulostus.py` korvaa tunnukset APA-viitteillä (peräkkäiset tunnukset yhdeksi viitteeksi, `yhdista_tekstiviitteet`) (`lahteet.py`) ja kirjoittaa dokumentin.

## Moduulit ja omistajat

| Tiedostot | Vaihe | Sisältö |
|---|---|---|
| `louhinta/mallit.py` | 0 | tietorakenteet, **ei muuteta** |
| `louhinta/lahteet.py`, `scripts/rakenna_lahteet.py`, `tests/test_lahteet.py`, `lahteet.json`, `lahteet-tarkistus.md` | 1A | lähderekisteri ja APA7 |
| `louhinta/lehmus.py`, `louhinta/paikannus.py`, `tests/test_paikannus.py`, `tests/test_lehmus.py` | 1B | RAG-asiakas ja lainauksen paikannus |
| `louhinta/kysymykset.py`, `louhinta/docx_tulostus.py`, `tests/test_kysymykset.py`, `tests/test_docx.py`, `scripts/esimerkki_docx.py` | 1C | kysymystiedoston jäsennin ja docx |
| `louhinta/malli.py`, `louhinta/putki.py`, `louhi.py` | 2 | mallikutsut ja ajo |

## Yhteiset säännöt agenteille

- Koske vain omiin tiedostoihisi. Älä muuta `mallit.py`:tä, älä tee git-commiteja, älä asenna paketteja (asennettu: pymupdf, rapidfuzz, requests, python-docx, pytest). Jos tarvitset muutoksen toisen tiedostoon, kerro se raportissa.
- Python 3.14, ajo aina `.venv/bin/python -I …`; testit `.venv/bin/python -m pytest tests/<oma>.py -q` projektin juuresta.
- Koodin nimet, kommentit ja tulosteet suomeksi samaan tapaan kuin `scripts/ankkurikoe.py`. Ei turhia abstraktioita.
- Testit toimivat ilman verkkoa ja käyttävät itse keksittyä tekstiä, ei artikkelien tekstiä. Artikkelien tekstiä ei tulosteta päätteeseen eikä raporttiin.
- Lehmukseen saa tehdä vain lukukutsuja avaimella `LEHMUS_API_KEY` (ympäristömuuttuja). Avainta ei tulosteta. Kirjoitusavainta ei käytetä.
- Loppuraportti enintään 15 riviä: mitä tehtiin, testien tulos (läpäistyt/kaikki), poikkeamat määrittelystä, avoimet asiat.

## 1A: lähderekisteri ja APA7 (`lahteet.py`)

```python
def lataa_lahteet(polku: Path) -> dict[str, Lahde]            # avain = tiedosto
def tallenna_lahteet(lahteet: dict[str, Lahde], polku: Path)  # JSON, ensure_ascii=False, indent=2
def painettu_sivu(lahde: Lahde, pdf_sivu: int) -> int | None  # aloitussivu + pdf_sivu - 1; None jos aloitussivu None
def vuositunnukset(lahteet: Iterable[Lahde]) -> dict[str, str]  # tiedosto -> "2020" tai "2020a"/"2020b", kun sama tekijäjoukko ja vuosi
def tekstiviite(lahde: Lahde, pdf_sivu_alku: int, pdf_sivu_loppu: int, vuosi: str | None = None) -> str
def lahdeluettelorivi(lahde: Lahde, vuosi: str | None = None) -> list[tuple[str, bool]]  # (teksti, kursiivi)
def lajitteluavain(lahde: Lahde) -> tuple
```

Suomenkielinen APA7:

- Tekstiviite: `(Kolbe ym., 2020, s. 168)`, sivuväli `ss. 168–169` (ajatusviiva). Yksi tekijä `(Brame, 2016, s. 3)`, kaksi `(Gerich & Schmitz, 2016, s. 50)`, kolme tai useampi `ym.`. Jos `aloitussivu` on `None`, sivun tilalle PDF-sivu muodossa `PDF-sivu 5`. Yhteisötekijä kokonaisena nimenä.
- Lähdeluettelo, artikkeli: `Kolbe, M., Eppich, W., Rudolph, J., Meguerdichian, M., Catena, H., Cripps, A., Grant, V., & Cheng, A. (2020). Otsikko. *Lehti*, *6*(3), 164–171. https://doi.org/…`. Lehden nimi ja vuosikerta kursiivilla, numero ja sivut ei. Enintään 20 tekijää kokonaan; 21+ → 19 ensimmäistä, `…`, viimeinen. Nimikirjaimet etunimistä (`Jean-Luc` → `J.-L.`). Muut tyypit (kirja, luku, raportti, verkkosivu) APA7:n mukaan; luvussa `Teoksessa E. Toimittaja (toim.), *Kirja* (ss. x–y). Kustantaja.`
- Lajittelu: ensimmäisen tekijän sukunimi, sitten muut tekijät, sitten vuosi; kirjainkoosta ja tarkkeista riippumatta.

`scripts/rakenna_lahteet.py` rakentaa rekisterin:

1. Hakee RAGin tiedostolistan ja jokaisen `source_text`-kentän (`GET /content/{id}`, lukuavain). Käytä `louhinta/lehmus.py`:n asiakasta, jos se on jo olemassa; muuten kopioi pieni asiakas `scripts/ankkurikoe.py`:stä skriptin sisään.
2. Etsii DOI:n kahdelta ensimmäiseltä sivulta ja hakee tiedot Crossrefistä (`https://api.crossref.org/works/{doi}`). Pyyntöön vain DOI, `User-Agent: artikkelien-louhinta/0.1`, ei sähköpostia eikä muita käyttäjätietoja. Enintään yksi pyyntö sekunnissa.
3. Päättelee painetun aloitussivun: etsii sivujen ensimmäisiltä ja viimeisiltä riveiltä yksinäisiä sivunumeroita ja tarkistaa, että ne kasvavat yhdellä sivulta toiselle. Vertaa Crossrefin `page`-kenttään. Ristiriita tai epävarmuus kirjataan `huomio`-kenttään, eikä arvoa arvata.
4. Kirjoittaa `lahteet.json` (kaikki `tarkistettu: false`) ja `lahteet-tarkistus.md`: taulukko, jossa tiedosto, muotoiltu lähdeluettelorivi, aloitussivu ja huomio, jotta käyttäjä voi tarkistaa rivit yhdellä silmäyksellä. Tiedostot ilman DOI:ta tai Crossref-osumaa jäävät rekisteriin tyhjin kentin ja huomiolla.
5. Uusi ajo ei ylikirjoita rivejä, joissa `tarkistettu: true`.

Aja skripti oikeasti ja raportoi: montako tiedostoa, monelleko löytyi DOI, monelleko aloitussivu, montako ristiriitaa.

## 1B: RAG-asiakas ja paikannus

`lehmus.py`:

```python
class Rag:
    def __init__(self, url: str = OLETUS_RAG_URL, avain: str | None = None, valimuisti: Path = Path(".valimuisti"))
    def tiedostot(self) -> list[dict]                 # {"id", "tiedosto"}; sivutus cursorilla
    def lahdeteksti(self, file_id: str) -> str        # source_text; levyvälimuisti .valimuisti/lahdetekstit/<id>.txt
    def hae(self, kysely: str, max_chunks: int = 8, filter_ids: list[str] | None = None) -> list[Osuma]
```

- `avain` oletuksena `LEHMUS_API_KEY`; puuttuva avain → selkeä virhe.
- `hae` paikantaa jokaisen pätkän lähdetekstiin ja täyttää `pdf_sivut`. `/context`-vastauksessa `chunks[i]`, `scores[i]` ja `files[i]` kuuluvat yhteen.
- Verkkovirheet ja 5xx/429: enintään 3 uudelleenyritystä kasvavalla viiveellä. Aikakatkaisu 60 s.
- Välimuistitiedostot kirjoitetaan `newline=""`, jotta `\f` ja rivinvaihdot säilyvät merkilleen.

`paikannus.py`:

```python
def sivu(source_text: str, indeksi: int) -> int                     # 1 + \f-merkkien määrä ennen indeksiä
def paikanna_lainaus(ehdotus: str, source_text: str, sumea_raja: float = 92.0, min_pituus: int = 20) -> Paikannus | None
def paikanna_patka(patka: str, source_text: str) -> list[int]       # pätkän PDF-sivut, [] jos ei löydy
def siisti(teksti: str) -> str
```

`paikanna_lainaus`:

- Vertailu tehdään normalisoidulla tekstillä (NFKC, pienaakkoset, vain kirjaimet ja numerot, kuten `ankkurikoe.py`:n `normalisoi`), mutta normalisoinnin on säilytettävä **indeksikartta alkuperäiseen tekstiin**, jotta tulos voidaan leikata alkuperäisestä `source_text`-kentästä. Huomaa, että NFKC voi muuttaa merkkimäärää (`ﬁ` → `fi`).
- Tarkka osuma: normalisoitu ehdotus löytyy normalisoidusta lähteestä. Jos se löytyy useasta kohdasta, valitaan ensimmäinen.
- Mallin lyhentämä lainaus (`…`, `...`, `[...]`): ehdotus jaetaan osiin, ja lainaukseksi otetaan pisin osa, joka täyttää `min_pituus`-rajan (normalisoituina merkkeinä).
- Sumea osuma, jos tarkkaa ei löydy: `rapidfuzz.fuzz.partial_ratio_alignment`; hyväksytään, jos pisteet ≥ `sumea_raja`. Lainaukseksi leikataan lähteen vastaava kohta, ja se laajennetaan sanarajoihin. `tapa="sumea"`.
- Liian lyhyt ehdotus tai ei osumaa → `None`.
- `alku` ja `loppu` laajennetaan kokonaisiin sanoihin. `lainaus = siisti(source_text[alku:loppu])`.

`siisti`: rivin lopun tavutus yhdistetään (`commu-\nnication` → `communication`; ei kosketa, jos seuraava rivi alkaa isolla kirjaimella tai numerolla), `\f` ja rivinvaihdot välilyönneiksi, peräkkäiset välilyönnit yhdeksi, reunat siistitään. Ylä- ja alatunnisteita ei yritetä poistaa.

Testit keksityllä monisivuisella tekstillä: tarkka osuma, sivurajan ylittävä lainaus, ligatuuri, tavutus, lyhennetty ehdotus, yhden sanan virhe (sumea), keksitty lainaus (→ `None`), indeksikartan oikeellisuus. `Rag` testataan väärennetyllä `requests.Session`-oliolla. Lopuksi yksi savutesti oikeaa RAGia vastaan: `tiedostot()`, yksi `hae()`; raportoi vain lukumäärät ja montako osumaa sai sivun.

## 1C: kysymystiedosto ja docx

`kysymykset.py`:

```python
def lue_patteri(polku: Path) -> Patteri
```

Esimerkki: `kysymykset/rooliharjoittelu.txt`. Muoto:

- Osio-otsikot omalla rivillään isoin kirjaimin: `TEHTÄVÄ:`, `SÄÄNNÖT`, `RAPORTIN RAKENNE`, `KYSYMYSPATTERI …`. Kaikki paitsi kysymykset ovat valinnaisia. Tiedosto, jossa on pelkkiä kysymyksiä, kelpaa.
- Ryhmäotsikko: `K1. Ohjeistuksen ajoitus` (kirjain + numero + piste). Ilman ryhmäotsikoita kaikki kysymykset kuuluvat ryhmään `K1` otsikolla `Kysymykset`.
- Kysymys: `12. (E) teksti`, `6. (J, E) teksti` tai `3. teksti`; jatkorivit sisennetty. Numero otetaan tiedostosta. Kysymyspatterin johdantokappale ennen ensimmäistä ryhmää ohitetaan.
- Säännöt ja rakenne: numeroidut kohdat jatkoriveineen ja alaluetteloineen yhdeksi merkkijonoksi per kohta.
- Virheellinen tiedosto (ei yhtään kysymystä, sama numero kahdesti) → `ValueError`, jossa rivinumero.

`docx_tulostus.py`:

```python
def kirjoita_docx(patteri: Patteri, vastaukset: list[Vastaus], lahteet: dict[str, Lahde], polku: Path, otsikko: str = "Teoriakoonti") -> None
```

Dokumentin rakenne:

1. Otsikko ja päiväys, tehtävänanto lyhyenä kappaleena.
2. Jokainen ryhmä tason 1 otsikkona (`K1. Ohjeistuksen ajoitus`), jokainen kysymys tason 2 otsikkona (`1. (P)`), kysymysteksti kursiivilla.
3. Vastauksen osiot: osion otsikko lihavoituna, teksti kappaleina. Tunnukset `[L1]` korvataan tekstiviitteellä `(Kolbe ym., 2020, s. 168)`. Tuntematon tunnus jätetään näkyviin ja kirjataan dokumentin loppuun kohtaan *Huomiot*.
4. Osioiden jälkeen *Lainaukset*: jokainen löydös omana lohkonaan: väite, lainaus sisennettynä lohkolainauksena lainausmerkeissä alkukielellä, perässä tekstiviite. Lisäksi näytön vahvuus ja siirtomerkintä, jos annettu. Sumeasti paikannettu lainaus (`tapa="sumea"`) merkitään tekstillä `[tarkista lainaus]`.
5. `ei_vastausta` → kappale `Ei vastausta liitetyissä lähteissä.` Kysymys ilman `Vastaus`-oliota → `Ei ajettu.`
6. *Lähteet*: vain viitatut lähteet, aakkosjärjestys (`lajitteluavain`), riippuva sisennys 1,27 cm, kursiivit `lahdeluettelorivi`n mukaan. DOI linkkinä tekstimuodossa.
7. *Lähteiden käyttö*: taulukko, jossa lähde, lainausten määrä ja kysymykset, joissa lähdettä käytettiin.
8. *Huomiot*: `Vastaus.huomiot` ja puuttuvat lähderekisterin rivit.

Fontti Times New Roman 12 pt, riviväli 1,5, otsikot Wordin omilla tyyleillä (`Heading 1/2`), jotta sisällysluettelo toimii.

`lahteet.py` valmistuu samaan aikaan (1A). Tuo sen funktiot normaalisti (`from louhinta.lahteet import tekstiviite, lahdeluettelorivi, lajitteluavain, vuositunnukset`) ja käytä testeissä `monkeypatch`-korvikkeita, kunnes oikea moduuli on olemassa. Tuonti tehdään funktion sisällä tai niin, että testit toimivat ilman oikeaa moduulia.

`scripts/esimerkki_docx.py` tekee keksitystä datasta tiedoston `tulokset/esimerkki.docx` (2 ryhmää, 3 kysymystä, yksi ilman vastausta, yksi sumea lainaus). Testit avaavat tuotetun tiedoston python-docx:llä ja tarkistavat otsikot, viitteen korvautumisen, lähdeluettelon järjestyksen ja kursiivit.

## 2: mallikutsut ja putki

Omat tiedostot: `louhinta/malli.py`, `louhinta/putki.py`, `louhi.py`, `tests/test_malli.py`, `tests/test_putki.py`. Lisäksi saa tehdä alla nimetyt pienet korjaukset tiedostoihin `louhinta/docx_tulostus.py` ja `louhinta/lahteet.py` testeineen.

### `malli.py`

```python
MALLIT = {"gemma31": "jwwqblcgkizlhxjjbkcp", "gptoss": "azsydsttjnlbfjbgqnwd"}

class Malli:
    def __init__(self, malli: str = "gemma31", url: str = "https://api.lehmus-ai.oulu.fi/v1", avain: str | None = None, aikakatkaisu: int = 300)
    def kysy(self, jarjestelma: str, kayttaja: str, max_tokens: int = 4000, lampotila: float = 0.1) -> str
    def kysy_json(self, jarjestelma: str, kayttaja: str, **kw) -> dict | list
```

- `POST /chat/completions`, avain `LEHMUS_API_KEY`. Vastaus luetaan kentästä `choices[0].message.content`, ei kentästä `reasoning_content`. Tyhjä `content` → selkeä virhe (ajattelu söi tokenit).
- `malli` on joko `MALLIT`-avain tai suora Model ID.
- Uudelleenyritys kuten `lehmus.py`:ssä (verkkovirhe, 5xx, 429; 3 kertaa).
- `kysy_json` poistaa mahdolliset koodiaidat (```` ```json ````), jäsentää JSONin ja yrittää kerran uudelleen virheilmoituksen kanssa, jos jäsennys epäonnistuu.

### `putki.py`

```python
def vastaa(kysymys: Kysymys, patteri: Patteri, rag: Rag, malli: Malli, lahteet: dict[str, Lahde], loki: Path | None = None) -> Vastaus
def tallenna_vastaus(v: Vastaus, polku: Path) -> None
def lataa_vastaus(polku: Path) -> Vastaus
```

Vaiheet yhdelle kysymykselle:

1. **Hakulauseet.** Malli saa kysymyksen ja kirjaston lähdeluettelon (tiedostonimi + tekijät + vuosi + otsikko rekisteristä). Palauttaa JSONin `{"haut": [3–4 englanninkielistä hakulausetta], "nimetyt": [tiedostonimet, joihin kysymys nimeltä viittaa], "puuttuvat": [kysymyksessä nimetyt lähteet, joita kirjastossa ei ole]}`. Tiedostonimet, joita kirjastossa ei ole, pudotetaan. `puuttuvat` kirjataan `Vastaus.huomiot`-kenttään.
2. **Haku.** Jokainen hakulause rajaamattomana (`max_chunks=8`) ja lisäksi jokaiseen nimettyyn tiedostoon rajattuna (`max_chunks=6`). Sama pätkä vain kerran. Enintään 40 osumaa: nimettyjen lähteiden osumat säilytetään aina, loput pisteiden mukaan.
3. **Poiminta.** Osumat numeroidaan `O1…`, ja jokaisen yhteydessä on lähde ja sivut. Enintään 12 osumaa per mallikutsu. Malli palauttaa listan `{"osuma": "O3", "vaite": "…suomeksi…", "lainaus": "1–3 virkettä kopioituna osumasta merkilleen", "nayton_vahvuus": "…", "siirretty_alalta": "…"}`. Kehote vaatii: vain kysymykseen vastaavat kohdat, lainaus kopioidaan muuttamatta eikä sitä käännetä, tyhjä lista on sallittu vastaus. Näytön vahvuuden ja alasiirron arvot pyydetään vain, jos patterin säännöt niitä edellyttävät.
4. **Tarkistus.** `paikanna_lainaus(lainaus, rag.lahdeteksti(file_id), min_pituus=40)`. `None` → hylätään. Jos paikannetut sivut eivät osu osuman `pdf_sivut`-listaan (kun lista ei ole tyhjä), löydös hyväksytään mutta `tapa="sumea"`. Samaan kohtaan osuvat löydökset (sama tiedosto, päällekkäinen `alku–loppu`) yhdistetään. Hyväksytyt saavat tunnukset `L1…`. Hylättyjen määrä kirjataan huomioihin.
5. **Koonti.** Ei löydöksiä → `ei_vastausta=True` ilman mallikutsua. Muuten malli saa tehtävänannon, säännöt, kysymyksen ja löydökset (tunnus, lähde, väite, lainaus, vahvuus) ja palauttaa `{"osiot": [{"otsikko", "teksti"}]}`. Kehote vaatii: vain löydösten tieto, jokainen väite viitataan tunnuksella `[L1]`, ei tekijä–vuosi-viitteitä eikä sivunumeroita tekstiin, osioiden otsikot patterin säännöistä (jos säännöt eivät määrää osioita, yksi osio otsikolla `""`). Tuntemattomat tunnukset kirjataan huomioihin.
6. `loki`-kansioon tallennetaan kehotteet ja mallin raakavastaukset vianetsintää varten.

Kehotteet kirjoitetaan suomeksi ja pidetään tiedoston alussa vakioina.

### `louhi.py`

```
.venv/bin/python -I louhi.py kysymykset/rooliharjoittelu.txt [--ryhma K1 …] [--kysymys 3 …] [--malli gemma31] [--ajo nimi] [--rinnakkain 2] [--uudelleen] [--vain-docx]
```

- Välitulokset `tulokset/<ajo>/vastaukset/k<nro>.json`, loki `tulokset/<ajo>/loki/`, lopputulos `tulokset/<ajo>/<ajo>.docx`. Valmis kysymys ohitetaan, ellei `--uudelleen`. Docx tehdään aina kaikista ajon tallennetuista vastauksista.
- `--rinnakkain` = samanaikaisten kysymysten määrä (`ThreadPoolExecutor`). Yhden kysymyksen virhe ei kaada ajoa.
- Lopuksi taulukko: kysymys, osumia, lainausehdotuksia, hyväksyttyjä, sumeita, hylättyjä, kesto.

### Korjaukset vaiheen 1 koodiin

- `docx_tulostus.py`: *Lähteiden käyttö* -taulukossa lähde lyhyenä viitteenä (`Kolbe ym., 2020`), ei tiedostonimenä.
- `lahteet.py`: lähde, jolla ei ole tekijöitä (rekisterin tyhjä rivi), saa tekstiviitteeseen ja lähdeluetteloon tiedostonimen ilman päätettä, ja docx:n *Huomiot* mainitsee puuttuvat viitetiedot.
