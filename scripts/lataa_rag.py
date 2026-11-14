"""Lataa kansion PDF:t Lehmus-RAGiin valmiina tekstinä ja ohittaa jo ladatut.

PDF:n teksti poimitaan paikallisesti sivu kerrallaan (PyMuPDF) ja lähetetään
polulla POST /files/content niin, että sivut erottaa sivunvaihtomerkki \\f.
Lehmuksen oma PDF-jäsennys (POST /files) ei alustapäivityksen jälkeen (todettu
14.11.2026) enää tuota sivunvaihtoja, joihin sivunumeroiden laskenta perustuu.

Jo ladatuksi katsotaan tiedosto, jonka nimi löytyy RAGin tiedostolistasta.

Käyttö:
    export LEHMUS_WRITE_API_KEY=...  # kirjoitusoikeudellinen avain, omassa päätteessä, ei keskusteluun
    .venv/bin/python -I scripts/lataa_rag.py --kansio ~/polku/pdf [--kuiva]
        [--ohita nimi1 nimi2] [--korvaa nimi3 nimi4]
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import pymupdf
import requests

OLETUS_RAG_URL = os.environ.get("LEHMUS_RAG_URL", "")   # RAG-resurssin perusosoite portaalista


def tiedostonimi(f: dict) -> str | None:
    return (f.get("metadata") or {}).get("filename") or f.get("filename")


def rag_tiedostot(s: requests.Session, url: str) -> list[dict]:
    kaikki, cursor = [], None
    while True:
        params = {"limit": 500}
        if cursor:
            params["cursor"] = cursor
        r = s.get(f"{url}/files", params=params, timeout=60)
        r.raise_for_status()
        d = r.json()
        rivit = d.get("files") or d.get("data") or d.get("items") or []
        kaikki.extend(rivit)
        cursor = d.get("next_cursor") or d.get("cursor")
        if not cursor or not rivit:
            return kaikki


def pdf_teksti(polku: Path) -> tuple[str, int, int]:
    """Palauttaa (teksti sivunvaihdoin, sivumäärä, tekstittömien sivujen määrä)."""
    with pymupdf.open(polku) as doc:
        # Nollatavu (\x00) kaataa Lehmuksen tallennuksen (PostgreSQL: invalid byte sequence 0x00).
        sivut = [sivu.get_text().replace("\x00", "") for sivu in doc]
    tyhjia = sum(1 for t in sivut if not t.strip())
    return "\f".join(sivut), len(sivut), tyhjia


def nimet(arvot: list[str]) -> set[str]:
    return {n if n.lower().endswith(".pdf") else f"{n}.pdf" for n in arvot}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kansio", required=True, type=Path, help="kansio, jonka *.pdf ladataan (ei alikansioita)")
    p.add_argument("--rag-url", default=OLETUS_RAG_URL)
    p.add_argument("--kuiva", action="store_true", help="näytä vain, mitä tehtäisiin")
    p.add_argument("--ohita", nargs="*", default=[], metavar="TIEDOSTO",
                   help="tiedostot, joita ei ladata (nimi .pdf-päätteellä tai ilman)")
    p.add_argument("--korvaa", nargs="*", default=[], metavar="TIEDOSTO",
                   help="jo RAGissa olevat tiedostot, jotka poistetaan ja ladataan uudelleen")
    a = p.parse_args()
    if not a.rag_url:
        print("Ympäristömuuttuja LEHMUS_RAG_URL puuttuu (RAG-resurssin perusosoite portaalista).", file=sys.stderr)
        return 2
    ohita, korvaa = nimet(a.ohita), nimet(a.korvaa)

    avain = os.environ.get("LEHMUS_WRITE_API_KEY")   # lukuavain (LEHMUS_API_KEY) ei salli latausta
    if not avain:
        print("Ympäristömuuttuja LEHMUS_WRITE_API_KEY puuttuu.", file=sys.stderr)
        return 2
    url = a.rag_url.rstrip("/")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {avain}", "Accept": "application/json"})

    pdft = sorted(a.kansio.expanduser().glob("*.pdf"))
    puuttuvat = (ohita | korvaa) - {pdf.name for pdf in pdft}
    if puuttuvat:
        print(f"--ohita/--korvaa: kansiossa ei ole tiedostoja {sorted(puuttuvat)}", file=sys.stderr)
        return 2
    if ohita & korvaa:
        print(f"Sama tiedosto sekä --ohita- että --korvaa-listalla: {sorted(ohita & korvaa)}", file=sys.stderr)
        return 2
    try:
        olemassa: dict[str, list[str]] = {}
        for f in rag_tiedostot(s, url):
            olemassa.setdefault(tiedostonimi(f), []).append(f["id"])
    except requests.HTTPError as e:
        print(f"RAGin tiedostolistaa ei saatu: {e.response.status_code} {e.response.text[:200]}", file=sys.stderr)
        return 1
    print(f"Kansiossa {len(pdft)} PDF:ää, RAGissa {sum(len(v) for v in olemassa.values())} tiedostoa.")

    virheita = 0
    for pdf in pdft:
        if pdf.name in ohita:
            print(f"  ohitettu (--ohita): {pdf.name}")
            continue
        vanhat = olemassa.get(pdf.name, [])
        if vanhat and pdf.name not in korvaa:
            print(f"  ohitettu (jo RAGissa): {pdf.name}")
            continue
        teksti, sivuja, tyhjia = pdf_teksti(pdf)
        if tyhjia == sivuja:
            virheita += 1
            print(f"  VIRHE: {pdf.name} ei sisällä tekstiä (skannattu?), ei ladattu")
            continue
        huomio = f", {tyhjia} tekstitöntä sivua" if tyhjia else ""
        toimi = "korvattaisiin" if vanhat else "ladattaisiin"
        if a.kuiva:
            print(f"  {toimi}: {pdf.name}  ({sivuja} sivua, {len(teksti)} merkkiä{huomio})")
            continue
        poistettu = True
        for vanha_id in vanhat:
            r = s.delete(f"{url}/files/{vanha_id}", timeout=120)
            if not r.ok:
                poistettu = False
                print(f"  VIRHE {r.status_code}: {pdf.name} vanhan version poisto epäonnistui  {r.text[:200]}")
        if not poistettu:
            virheita += 1
            continue
        uusi_id = str(uuid.uuid4())
        runko = {"contents": [{"id": uusi_id, "txt": teksti, "metadata": {"filename": pdf.name}}]}
        r = s.post(f"{url}/files/content", json=runko, timeout=600)
        if r.ok and uusi_id in (r.json().get("processed_ids") or []):
            tehty = "korvattu" if vanhat else "ladattu"
            print(f"  {tehty}: {pdf.name}  id={uusi_id}  ({sivuja} sivua, {len(teksti)} merkkiä{huomio})")
        else:
            virheita += 1
            print(f"  VIRHE {r.status_code}: {pdf.name}  {r.text[:200]}")
    return 1 if virheita else 0


if __name__ == "__main__":
    sys.exit(main())
