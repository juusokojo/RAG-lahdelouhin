"""Docx-tulostus: koontidokumentti kysymyksistä, vastauksista, lainauksista ja lähteistä.

Määrittely: docs/maarittely.md, kohta 1C. Viitteet muodostaa lahteet.py, ei malli.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from louhinta.mallit import Kysymys, Lahde, Loydos, Patteri, Vastaus

TUNNUS_RE = re.compile(r"\[(L\d+)\]")
TUNNUSJONO_RE = re.compile(r"\[L\d+\](?:[\s,]*\[L\d+\])*")     # peräkkäiset tunnukset, välissä tyhjää tai pilkku
VIRKKEEN_LOPPU_RE = re.compile(r"[.!?](?=\s|$)")
FONTTI = "Times New Roman"


def _aseta_fontti(tyyli, koko: float | None = None) -> None:
    tyyli.font.name = FONTTI
    rfonts = tyyli.element.get_or_add_rPr().get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), FONTTI)
    for teema in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        rfonts.attrib.pop(qn(teema), None)      # Wordin teemafontit ohittavat nimen muuten
    if koko:
        tyyli.font.size = Pt(koko)


def _tyylit(doc: Document) -> None:
    normaali = doc.styles["Normal"]
    _aseta_fontti(normaali, 12)
    normaali.paragraph_format.line_spacing = 1.5
    normaali.paragraph_format.space_after = Pt(6)
    for nimi, koko in (("Title", 18), ("Heading 1", 14), ("Heading 2", 12)):
        tyyli = doc.styles[nimi]
        _aseta_fontti(tyyli, koko)
        tyyli.font.color.rgb = RGBColor(0, 0, 0)
    doc.styles["Heading 2"].font.bold = True


def _ryhmat(patteri: Patteri) -> list[tuple[str, str, list[Kysymys]]]:
    """Ryhmät tiedoston järjestyksessä: (ryhmän tunnus, otsikko, kysymykset)."""
    jarjestys: dict[str, tuple[str, list[Kysymys]]] = {}
    for kysymys in patteri.kysymykset:
        otsikko, kysymykset = jarjestys.setdefault(kysymys.ryhma, (kysymys.ryhma_otsikko, []))
        kysymykset.append(kysymys)
    return [(tunnus, otsikko, kysymykset) for tunnus, (otsikko, kysymykset) in jarjestys.items()]


def _puuttuvat_viitetiedot(lahde: Lahde) -> list[str]:
    puuttuu = []
    if not lahde.tekijat:
        puuttuu.append("tekijät")
    if not lahde.vuosi.strip() or lahde.vuosi.strip() == "n.d.":
        puuttuu.append("vuosi")
    if not lahde.otsikko:
        puuttuu.append("otsikko")
    if lahde.aloitussivu is None:
        puuttuu.append("painettu aloitussivu (viitteessä PDF-sivu)")
    return puuttuu


def kirjoita_docx(patteri: Patteri, vastaukset: list[Vastaus], lahteet: dict[str, Lahde],
                  polku: Path, otsikko: str = "Teoriakoonti") -> None:
    from louhinta.lahteet import (
        lahdeluettelorivi, lajitteluavain, lyhytviite, tekstiviite, vuositunnukset, yhdista_tekstiviitteet)

    vuodet = vuositunnukset(list(lahteet.values()))
    vastaus_nro = {v.kysymys_nro: v for v in vastaukset}
    huomiot: list[str] = []
    viitatut: set[str] = set()          # lähteet, joihin lainauksia on viitattu

    for vastaus in vastaukset:
        huomiot.extend(f"Kysymys {vastaus.kysymys_nro}: {h}" for h in vastaus.huomiot)

    def viite(loydos: Loydos, vastaus: Vastaus) -> str:
        lahde = lahteet.get(loydos.tiedosto)
        if lahde is None:
            huomiot.append(f"Kysymys {vastaus.kysymys_nro}: lähderekisteristä puuttuu rivi {loydos.tiedosto}")
            return f"({loydos.tiedosto})"
        viitatut.add(loydos.tiedosto)
        return tekstiviite(lahde, loydos.pdf_sivu_alku, loydos.pdf_sivu_loppu, vuodet.get(loydos.tiedosto))

    def korvaa_tunnukset(teksti: str, vastaus: Vastaus) -> str:
        tunnukset = {l.tunnus: l for l in vastaus.loydokset}

        def korvaa(osuma: re.Match) -> str:
            """Tunnusjono -> yksi yhdistetty viite; tuntemattomat tunnukset jätetään tekstiin."""
            viitteet: list[tuple[Lahde, int, int]] = []
            jaljelle: list[str] = []
            for tunnus in dict.fromkeys(TUNNUS_RE.findall(osuma.group(0))):
                loydos = tunnukset.get(tunnus)
                if loydos is None:
                    huomiot.append(f"Kysymys {vastaus.kysymys_nro}: tuntematon tunnus [{tunnus}] jätettiin tekstiin")
                    jaljelle.append(f"[{tunnus}]")
                    continue
                lahde = lahteet.get(loydos.tiedosto)
                if lahde is None:
                    jaljelle.append(viite(loydos, vastaus))     # kirjaa huomion ja palauttaa "(tiedosto)"
                    continue
                viitatut.add(loydos.tiedosto)
                viitteet.append((lahde, loydos.pdf_sivu_alku, loydos.pdf_sivu_loppu))
            osat = ([yhdista_tekstiviitteet(viitteet, vuodet)] if viitteet else []) + jaljelle
            return " ".join(osat)

        return TUNNUSJONO_RE.sub(korvaa, teksti)

    doc = Document()
    _tyylit(doc)
    doc.add_heading(otsikko, level=0)
    doc.add_paragraph(f"Päiväys: {date.today():%d.%m.%Y}")
    if patteri.tehtava:
        doc.add_paragraph(patteri.tehtava)

    def kirjoita_lainaus(loydos: Loydos, vastaus: Vastaus) -> None:
        """Sanatarkka lainaus kursiivilla ja sisennettynä, perässä viite pystyyn."""
        lohko = doc.add_paragraph()
        lohko.paragraph_format.left_indent = Cm(1.27)
        lohko.paragraph_format.right_indent = Cm(1.27)
        lohko.add_run(f"”{loydos.lainaus}”").italic = True
        viiteteksti = " " + viite(loydos, vastaus)
        if loydos.tapa == "sumea":
            viiteteksti += " [tarkista lainaus]"
        lisat = []
        if loydos.nayton_vahvuus:
            lisat.append(f"Näytön vahvuus: {loydos.nayton_vahvuus}.")
        if loydos.siirretty_alalta:
            lisat.append(f"Siirretty alalta: {loydos.siirretty_alalta}.")
        if lisat:
            viiteteksti += " " + " ".join(lisat)
        lohko.add_run(viiteteksti)

    def kirjoita_kappale(kappale: str, vastaus: Vastaus, kaytetyt: set[str]) -> None:
        """Kappale paloiteltuna viitteiden kohdalta: jokaisen viitatun virkkeen alle sen lainaukset.

        Pala päättyy ensimmäiseen virkkeen loppuun tunnusjonon jälkeen, ellei ennen sitä tule
        uutta tunnusjonoa (silloin lainaukset kerätään saman palan alle).
        """
        tunnukset = {l.tunnus: l for l in vastaus.loydokset}
        jonot = list(TUNNUSJONO_RE.finditer(kappale))
        palat: list[tuple[str, list[str]]] = []
        alku, kerätyt = 0, []
        for i, jono in enumerate(jonot):
            kerätyt.extend(TUNNUS_RE.findall(jono.group(0)))
            loppu = VIRKKEEN_LOPPU_RE.search(kappale, jono.end())
            leikkaus = loppu.end() if loppu else len(kappale)
            if i + 1 < len(jonot) and jonot[i + 1].start() < leikkaus:
                continue
            palat.append((kappale[alku:leikkaus], kerätyt))
            alku, kerätyt = leikkaus, []
        if kappale[alku:].strip():
            palat.append((kappale[alku:], []))
        for teksti, pala_tunnukset in palat:
            if teksti.strip():
                doc.add_paragraph(korvaa_tunnukset(teksti.strip(), vastaus))
            for tunnus in dict.fromkeys(pala_tunnukset):
                loydos = tunnukset.get(tunnus)
                if loydos is not None and tunnus not in kaytetyt:
                    kaytetyt.add(tunnus)
                    kirjoita_lainaus(loydos, vastaus)

    def kirjoita_muut_lainaukset(vastaus: Vastaus, kaytetyt: set[str]) -> None:
        """Löydökset, joihin vastausteksti ei viittaa: väite ja lainaus vastauksen loppuun."""
        muut = [l for l in vastaus.loydokset if l.tunnus not in kaytetyt]
        if not muut:
            return
        doc.add_paragraph().add_run("Muut lainaukset").bold = True
        for loydos in muut:
            doc.add_paragraph(loydos.vaite)
            kirjoita_lainaus(loydos, vastaus)

    # Kysymykset ja vastaukset ryhmittäin
    for ryhma_tunnus, ryhma_otsikko, kysymykset in _ryhmat(patteri):
        doc.add_heading(f"{ryhma_tunnus}. {ryhma_otsikko}", level=1)
        for kysymys in kysymykset:
            merkinnat = f" ({', '.join(kysymys.merkinnat)})" if kysymys.merkinnat else ""
            doc.add_heading(f"{kysymys.nro}.{merkinnat}", level=2)
            doc.add_paragraph().add_run(kysymys.teksti).italic = True

            vastaus = vastaus_nro.get(kysymys.nro)
            if vastaus is None:
                doc.add_paragraph("Ei ajettu.")
            elif vastaus.ei_vastausta:
                doc.add_paragraph("Ei vastausta liitetyissä lähteissä.")
            else:
                kaytetyt: set[str] = set()
                for osio in vastaus.osiot:
                    if osio.otsikko:
                        doc.add_paragraph().add_run(osio.otsikko).bold = True
                    osiossa: set[str] = set()     # sama lainaus kerran osiota kohden
                    for kappale in osio.teksti.split("\n\n"):
                        if kappale.strip():
                            kirjoita_kappale(kappale.strip(), vastaus, osiossa)
                    kaytetyt |= osiossa
                kirjoita_muut_lainaukset(vastaus, kaytetyt)


    # Lähteet: vain viitatut, aakkosjärjestys, riippuva sisennys
    doc.add_heading("Lähteet", level=1)
    if not viitatut:
        doc.add_paragraph("Ei lähteitä.")
    for tiedosto in sorted(viitatut, key=lambda t: lajitteluavain(lahteet[t])):
        kappale = doc.add_paragraph()
        kappale.paragraph_format.left_indent = Cm(1.27)
        kappale.paragraph_format.first_line_indent = Cm(-1.27)
        for teksti, kursiivi in lahdeluettelorivi(lahteet[tiedosto], vuodet.get(tiedosto)):
            kappale.add_run(teksti).italic = kursiivi

    # Lähteiden käyttö: taulukko
    doc.add_heading("Lähteiden käyttö", level=1)
    kaytto: dict[str, tuple[int, set[int]]] = {}
    for vastaus in vastaukset:
        for loydos in vastaus.loydokset:
            if loydos.tiedosto not in lahteet:
                continue
            maara, nrot = kaytto.get(loydos.tiedosto, (0, set()))
            kaytto[loydos.tiedosto] = (maara + 1, nrot | {vastaus.kysymys_nro})
    if kaytto:
        taulu = doc.add_table(rows=1, cols=3)
        taulu.style = doc.styles["Table Grid"]
        taulu.alignment = WD_TABLE_ALIGNMENT.CENTER
        for solu, teksti in zip(taulu.rows[0].cells, ("Lähde", "Lainauksia", "Kysymykset")):
            solu.paragraphs[0].add_run(teksti).bold = True
        for tiedosto in sorted(kaytto, key=lambda t: lajitteluavain(lahteet[t])):
            maara, nrot = kaytto[tiedosto]
            solut = taulu.add_row().cells
            solut[0].text = lyhytviite(lahteet[tiedosto], vuodet.get(tiedosto))
            solut[1].text = str(maara)
            solut[2].text = ", ".join(str(n) for n in sorted(nrot))
    else:
        doc.add_paragraph("Ei viitattuja lähteitä.")

    # Huomiot
    doc.add_heading("Huomiot", level=1)
    for tiedosto in sorted(viitatut, key=lambda t: lajitteluavain(lahteet[t])):
        puuttuu = _puuttuvat_viitetiedot(lahteet[tiedosto])
        if puuttuu:
            huomiot.append(f"Lähteen {tiedosto} viitetiedoista puuttuu: {', '.join(puuttuu)}")
    huomiot = list(dict.fromkeys(huomiot))      # poistaa toistot säilyttäen järjestyksen
    if huomiot:
        for huomio in huomiot:
            doc.add_paragraph(huomio, style="List Bullet")
    else:
        doc.add_paragraph("Ei huomioita.")

    polku.parent.mkdir(parents=True, exist_ok=True)
    doc.save(polku)
