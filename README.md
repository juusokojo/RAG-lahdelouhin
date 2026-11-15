# RAG-lahdelouhin

Työkalu, joka vastaa kysymysluetteloon RAG-tietokantaan ladattujen tieteellisten artikkelien perusteella ja kirjoittaa tuloksen Word-tiedostoon. Vastaustekstin jokaisen viitatun virkkeen alla on sanatarkka lainaus artikkelista alkukielellä ja APA 7 -viite sivunumeroineen. Dokumentin lopussa on lähdeluettelo.

Työkalu on tehty tutkijan omaan käyttöön aineistoille, joihin käyttäjällä on oikeus: yliopiston kirjaston kautta saadut tai avoimella lisenssillä julkaistut artikkelit. Repossa ei ole artikkeleita eikä niiden tekstiä.

> **Tila:** toimiva ensimmäinen versio. Koko 34 kysymyksen patteri on ajettu (46 artikkelia, noin 40 minuuttia): 244 lainausta 39 lähteestä, kaikki tarkistettu lähdetekstiä vasten. Pistokokeessa 10/10 lainausta osui oikealle sivulle.

## Miksi lainauksiin voi luottaa

Kielimallin kirjoittama teksti ei koskaan päädy lainaukseksi.

1. Malli ehdottaa lainausta hakutuloksesta.
2. Ohjelma etsii ehdotuksen artikkelin lähdetekstistä ja leikkaa lainauksen sieltä. Leikkaus laajennetaan kokonaisiin virkkeisiin.
3. Sivunumero lasketaan leikkauskohdasta, ja viite muodostetaan lähderekisteristä.
4. Jos ehdotusta ei löydy lähdetekstistä, se hylätään.

Lainaus, jota ei löytynyt merkilleen vaan pienin eroin, merkitään dokumenttiin tekstillä `[tarkista lainaus]`. Jos PDF:n tekstikerroksessa on lukukelvoton merkki, se näkyy lainauksessa korvausmerkkinä `�`.

Mallin kirjoittama vastausteksti on tulkintaa, ja se on tarkistettava lainauksia vasten.

## Mitä tarvitset

- Python 3.12 tai uudempi
- OpenAI-yhteensopiva kielimallirajapinta ja RAG-rajapinta. Työkalu on tehty Oulun yliopiston Lehmus AI -palvelulle (ConfidentialMind-alusta).
- Ympäristömuuttujat:

| Muuttuja | Tarkoitus |
|---|---|
| `LEHMUS_RAG_URL` | RAG-resurssin perusosoite portaalista |
| `LEHMUS_API_KEY` | lukuavain: haku ja mallikutsut |
| `LEHMUS_WRITE_API_KEY` | kirjoitusavain: vain artikkelien lataus RAGiin |

Avaimia ja osoitetta ei tallenneta repoon. Lisää ne esimerkiksi tiedostoon `~/.zshrc`.

## Asennus

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

## Käyttö

### 1. Lataa artikkelit RAGiin

PDF:n teksti poimitaan paikallisesti sivu kerrallaan, jotta sivunvaihdot säilyvät ja sivunumerot voidaan laskea. Kokeile ensin ilman muutoksia:

```bash
.venv/bin/python -I scripts/lataa_rag.py --kansio ~/polku/pdf --kuiva
```

Jo ladatut tiedostot ohitetaan. Skannattu PDF ilman tekstikerrosta ei lataudu.

### 2. Rakenna lähderekisteri

```bash
.venv/bin/python -I scripts/rakenna_lahteet.py
```

Skripti etsii jokaisesta artikkelista DOI:n, hakee viitetiedot Crossrefistä ja päättelee painetun aloitussivun. Tulos on `lahteet.json` ja tarkistuslista `lahteet-tarkistus.md`.

**Tarkista rivit itse** ja merkitse ne `"tarkistettu": true`. Uusi ajo ei ylikirjoita tarkistettuja rivejä. Käsin täydennettäviä ovat yleensä:

- kirjat, opinnäytteet, oppaat ja muut DOI:ttomat lähteet
- PDF:t, joiden ensimmäinen sivu on kustantajan kansilehti: aloitussivu on silloin ensimmäisen artikkelisivun numero miinus yksi
- rinnakkaistallenteet, joiden sivutus ei vastaa lehden sivuja

Kentän `aloitussivu` arvo on PDF:n ensimmäisen sivun painettu sivunumero. Se saa olla nolla tai negatiivinen, jos alussa on numeroimattomia sivuja.

### 3. Kirjoita kysymykset

Kysymykset ovat tekstitiedostossa, ks. [kysymykset/rooliharjoittelu.txt](kysymykset/rooliharjoittelu.txt). Tehtävänanto, säännöt ja ryhmäotsikot ovat valinnaisia; pelkkä numeroitu kysymyslista riittää.

```text
K1. Ohjeistuksen ajoitus

1. (P) Ensimmäinen kysymys, joka voi jatkua
   seuraavalle riville.
2. Toinen kysymys.
```

Jos säännöissä nimetään vastauksen osiot (esim. `LÄHDE SANOO` ja `EHDOTUS VIDEOON`), malli käyttää niitä. Säännöt näytön vahvuudesta ja toiselta alalta siirretyistä päätelmistä näkyvät lainausten perässä.

### 4. Aja louhinta

Koko patteri:

```bash
.venv/bin/python -I louhi.py kysymykset/rooliharjoittelu.txt --ajo patteri --rinnakkain 2
```

Valitut ryhmät tai kysymykset:

```bash
.venv/bin/python -I louhi.py kysymykset/rooliharjoittelu.txt --ryhma K1 --kysymys 25 --ajo koe
```

| Valinta | Merkitys |
|---|---|
| `--ryhma K1 K3` | ajettavat ryhmät |
| `--kysymys 4 25` | ajettavat kysymykset (yhdessä `--ryhma`n kanssa ajetaan molemmat) |
| `--malli` | `gemma31` (oletus, Gemma 4 31B), `gptoss` (GPT OSS 120B) tai suora Model ID |
| `--ajo` | ajon nimi; tulokset kansioon `tulokset/<ajo>/` |
| `--rinnakkain` | samanaikaisten kysymysten määrä |
| `--uudelleen` | ajaa myös jo valmiit kysymykset uudelleen |
| `--vain-docx` | ei mallikutsuja: tekee dokumentin tallennetuista vastauksista, esim. lähderekisterin korjausten jälkeen |
| `--lahteet` | lähderekisterin polku (oletus `lahteet.json`) |

Tulos tulee tiedostoon `tulokset/<ajo>/<ajo>.docx`. Välitulokset tallennetaan kysymyksittäin, joten keskeytynyt ajo jatkuu siitä, mihin se jäi. Ajon lopussa tulostuu taulukko: osumat, lainausehdotukset, hyväksytyt, hylätyt ja kesto kysymyksittäin.

## Miten yksi kysymys käsitellään

1. **Hakulauseet.** Malli muotoilee kysymyksestä 3–4 englanninkielistä hakulausetta ja tunnistaa kysymyksessä nimetyt lähteet. Puuttuvat nimetyt lähteet kirjataan dokumentin huomioihin.
2. **Haku.** Jokainen hakulause haetaan koko kirjastosta ja lisäksi rajattuna nimettyihin lähteisiin.
3. **Poiminta.** Malli poimii osumista väitteet ja lainausehdotukset.
4. **Tarkistus.** Lainaukset paikannetaan lähdetekstiin ja leikataan sieltä; löytymättömät hylätään.
5. **Osuvuus.** Malli arvioi, käsitteleekö lainaus kysymyksen aihetta. Aiheeseen kuulumattomat pudotetaan.
6. **Koonti.** Malli kirjoittaa vastauksen vain tarkistetuista löydöksistä. Jos löydöksiä ei ole, vastaus on "Ei vastausta liitetyissä lähteissä."

## Tulosdokumentin rakenne

- vastaukset ryhmittäin ja kysymyksittäin
- vastaustekstin jokaisen viitatun virkkeen alla sen lainaukset kursiivilla ja sisennettyinä, perässä viite, esim. `(Kolbe ym., 2020, s. 168)`
- peräkkäiset viitteet yhdistettyinä, esim. `(Loibl ym., 2017, s. 703; Sinha & Kapur, 2021, ss. 768, 783)`
- sama lainaus kerran kussakin vastauksen osiossa; lainaukset, joihin vastausteksti ei viittaa, otsikon *Muut lainaukset* alla
- lähdeluettelo APA 7 -muodossa
- taulukko siitä, mitä lähteitä käytettiin ja missä kysymyksissä
- huomiot: puuttuvat lähteet, hylätyt ja pudotetut lainaukset, puutteelliset viitetiedot

## Rajoitukset

- **Haku voi jättää kohtia löytämättä.** "Ei vastausta liitetyissä lähteissä" tarkoittaa, ettei haku löytänyt sopivaa kohtaa, ei sitä, ettei sellaista ole.
- **Tulokset vaihtelevat ajosta toiseen.** Sama kysymys voi tuottaa eri määrän lainauksia. Jos vastaus jää ohueksi, aja kysymys uudelleen: `--kysymys 4 --uudelleen`.
- **Osuvuustarkistus on salliva.** Se karsii selvästi aiheeseen kuulumattomat lainaukset, mutta aihetta sivuavia jää mukaan.
- **Sivunumero on laskettu.** Painettu sivu saadaan aloitussivusta ja PDF-sivusta. Jos aloitussivu puuttuu rekisteristä, viitteessä lukee `PDF-sivu`.
- **Lainaus on poimittu PDF:n tekstikerroksesta.** Ylä- ja alatunnisteet, alaviitenumerot ja palstanvaihdot voivat näkyä lainauksessa.
- **Mallikutsu voi viipyä.** Kutsun aikaraja on 5 minuuttia, ja aikakatkaisun jälkeen kutsu yritetään kerran uudelleen.
- **Tarkista ennen käyttöä.** Työkalu nopeuttaa lähteiden läpikäyntiä, mutta ei korvaa lähteen lukemista.

## Tekijänoikeus ja tietosuoja

- Artikkeleita, niiden tekstiä tai ajojen tuloksia ei tallenneta repoon (ks. `.gitignore`). Lähderekisteri `lahteet.json` sisältää vain viitetietoja.
- Käyttäjä vastaa siitä, että aineiston käyttö tekstinlouhintaan on sallittua.
- Aineisto käsitellään käyttäjän valitsemassa kielimallipalvelussa. Viitetietojen hakuun Crossrefistä lähetetään vain artikkelin DOI.

## Kehitys

```bash
.venv/bin/python -m pytest tests -q
```

Testit (188) toimivat ilman verkkoa. Rakenne ja moduulien rajapinnat: [docs/maarittely.md](docs/maarittely.md).

| Moduuli | Tehtävä |
|---|---|
| `louhinta/kysymykset.py` | kysymystiedoston jäsennys |
| `louhinta/lehmus.py` | RAG-asiakas ja lähdetekstien välimuisti |
| `louhinta/paikannus.py` | lainauksen paikannus, virkerajat ja sivunlaskenta |
| `louhinta/malli.py` | kielimallikutsut |
| `louhinta/putki.py` | yhden kysymyksen käsittely |
| `louhinta/lahteet.py` | lähderekisteri ja APA 7 -muotoilu |
| `louhinta/docx_tulostus.py` | Word-dokumentti |

## Lisenssi

Oma koodi: [MIT](LICENSE). Riippuvuuksista PyMuPDF on lisensoitu AGPL-3.0-ehdoin; sitä käyttävät vain `scripts/`-kansion PDF-skriptit.
