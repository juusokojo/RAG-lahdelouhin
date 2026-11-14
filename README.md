# RAG-lahdelouhin

Työkalu, joka vastaa kysymysluetteloon RAG-tietokantaan ladattujen tieteellisten artikkelien perusteella ja kirjoittaa tuloksen Word-tiedostoon. Jokaisen vastauksen yhteydessä on sanatarkka lainaus artikkelista ja APA 7 -viite sivunumeroineen, ja dokumentin lopussa on lähdeluettelo.

Työkalu on tehty tutkijan omaan käyttöön aineistoille, joihin käyttäjällä on oikeus: yliopiston kirjaston kautta saadut tai avoimella lisenssillä julkaistut artikkelit. Repossa ei ole artikkeleita eikä niiden tekstiä.

> **Tila:** kehitysvaiheessa. Haku, lainausten paikannus, lähderekisteri ja docx-tulostus ovat valmiit ja testatut. Mallikutsut ja koko ajon yhdistävä putki ovat työn alla.

## Miksi lainauksiin voi luottaa

Kielimallin kirjoittama teksti ei koskaan päädy lainaukseksi.

1. Malli ehdottaa lainausta hakutuloksesta.
2. Ohjelma etsii ehdotuksen artikkelin lähdetekstistä ja leikkaa lainauksen sieltä.
3. Sivunumero lasketaan leikkauskohdasta, ja viite muodostetaan lähderekisteristä.
4. Jos ehdotusta ei löydy lähdetekstistä, se hylätään.

Lainaus, jota ei löytynyt merkilleen vaan pienin eroin, merkitään dokumenttiin tekstillä `[tarkista lainaus]`. Mallin kirjoittama vastausteksti on tulkintaa, ja se on tarkistettava lainauksia vasten.

## Mitä tarvitset

- Python 3.12 tai uudempi
- OpenAI-yhteensopiva kielimallirajapinta ja RAG-rajapinta. Työkalu on tehty Oulun yliopiston Lehmus AI -palvelulle (ConfidentialMind-alusta).
- Ympäristömuuttujat:

| Muuttuja | Tarkoitus |
|---|---|
| `LEHMUS_RAG_URL` | RAG-resurssin perusosoite portaalista |
| `LEHMUS_API_KEY` | lukuavain: haku ja mallikutsut |
| `LEHMUS_WRITE_API_KEY` | kirjoitusavain: vain artikkelien lataus RAGiin |

Avaimia ei tallenneta repoon.

## Asennus

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

## Käyttö

### 1. Lataa artikkelit RAGiin

PDF:n teksti poimitaan paikallisesti sivu kerrallaan, jotta sivunvaihdot säilyvät ja sivunumerot voidaan laskea.

```bash
.venv/bin/python -I scripts/lataa_rag.py --kansio ~/polku/pdf --kuiva
```

Skannattu PDF ilman tekstikerrosta ei lataudu.

### 2. Rakenna lähderekisteri

```bash
.venv/bin/python -I scripts/rakenna_lahteet.py
```

Skripti etsii jokaisesta artikkelista DOI:n, hakee viitetiedot Crossrefistä ja päättelee painetun aloitussivun. Tulos on `lahteet.json` ja tarkistuslista `lahteet-tarkistus.md`. **Tarkista rivit itse** ja merkitse ne `"tarkistettu": true`. Kirjat, opinnäytteet ja muut DOI:ttomat lähteet täytetään käsin.

### 3. Kirjoita kysymykset

Kysymykset ovat tekstitiedostossa, ks. [kysymykset/rooliharjoittelu.txt](kysymykset/rooliharjoittelu.txt). Tehtävänanto, säännöt ja ryhmäotsikot ovat valinnaisia; pelkkä numeroitu kysymyslista riittää.

```text
K1. Ohjeistuksen ajoitus

1. (P) Ensimmäinen kysymys, joka voi jatkua
   seuraavalle riville.
2. Toinen kysymys.
```

### 4. Aja louhinta

```bash
.venv/bin/python -I louhi.py kysymykset/rooliharjoittelu.txt --ryhma K1 --ajo koe
```

Tulos tulee tiedostoon `tulokset/<ajo>/<ajo>.docx`. Välitulokset tallennetaan kysymyksittäin, joten keskeytynyt ajo jatkuu siitä, mihin se jäi.

## Tulosdokumentin rakenne

- vastaukset ryhmittäin ja kysymyksittäin
- jokaisen vastauksen alla lainaukset alkukielellä ja tekstiviite, esim. `(Kolbe ym., 2020, s. 168)`
- lähdeluettelo APA 7 -muodossa
- taulukko siitä, mitä lähteitä käytettiin ja missä kysymyksissä
- huomiot: puuttuvat lähteet, hylätyt lainausehdotukset, puutteelliset viitetiedot

## Rajoitukset

- **Haku voi jättää kohtia löytämättä.** "Ei vastausta liitetyissä lähteissä" tarkoittaa, ettei haku löytänyt sopivaa kohtaa, ei sitä, ettei sellaista ole.
- **Sivunumero on laskettu.** Painettu sivu saadaan artikkelin aloitussivusta ja PDF-sivusta. Jos aloitussivu puuttuu rekisteristä, viitteessä lukee PDF-sivu.
- **Lainaus on poimittu PDF:n tekstikerroksesta.** Ylä- ja alatunnisteet, alaviitteet ja palstanvaihdot voivat näkyä lainauksessa.
- **Tarkista ennen käyttöä.** Työkalu nopeuttaa lähteiden läpikäyntiä, mutta ei korvaa lähteen lukemista.

## Tekijänoikeus ja tietosuoja

- Artikkeleita, niiden tekstiä tai ajojen tuloksia ei tallenneta repoon (ks. `.gitignore`).
- Käyttäjä vastaa siitä, että aineiston käyttö tekstinlouhintaan on sallittua.
- Aineisto käsitellään käyttäjän valitsemassa kielimallipalvelussa. Viitetietojen hakuun Crossrefistä lähetetään vain artikkelin DOI.

## Kehitys

```bash
.venv/bin/python -m pytest tests -q
```

Rakenne ja moduulien rajapinnat: [docs/maarittely.md](docs/maarittely.md).

## Lisenssi

Oma koodi: [MIT](LICENSE). Riippuvuuksista PyMuPDF on lisensoitu AGPL-3.0-ehdoin; sitä käyttävät vain `scripts/`-kansion PDF-skriptit.
