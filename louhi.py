#!/usr/bin/env python3
"""Louhintatyökalun komentorivi: vastaa kysymyspatteriin RAGin artikkeleiden perusteella.

Käyttö (projektin juuresta):
    export RAG_URL=... RAG_API_KEY=... MALLI_URL=... MALLI=...   # omassa päätteessä
    .venv/bin/python -I louhi.py kysymykset/rooliharjoittelu.txt --ryhma K1 --ajo koe-k1

Välitulokset: tulokset/<ajo>/vastaukset/k<nro>.json, loki: tulokset/<ajo>/loki/,
lopputulos: tulokset/<ajo>/<ajo>.docx. Valmis kysymys ohitetaan, ellei anneta --uudelleen.
Määrittely: docs/maarittely.md, luku 2.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

JUURI = Path(__file__).resolve().parent
sys.path.insert(0, str(JUURI))

from louhinta.docx_tulostus import kirjoita_docx          # noqa: E402
from louhinta.kysymykset import lue_patteri               # noqa: E402
from louhinta.lahteet import lataa_lahteet                # noqa: E402
from louhinta.malli import Malli                          # noqa: E402
from louhinta.rag import Rag                              # noqa: E402
from louhinta.putki import Tilasto, lataa_vastaus, tallenna_vastaus, vastaa_tilastoin  # noqa: E402

_tulostuslukko = threading.Lock()


def tulosta(teksti: str = "") -> None:
    with _tulostuslukko:
        print(teksti, flush=True)


def lue_tilasto(polku: Path) -> Tilasto | None:
    if not polku.is_file():
        return None
    d = json.loads(polku.read_text(encoding="utf-8"))
    return Tilasto(**{k: v for k, v in d.items() if k in Tilasto.__dataclass_fields__})


def valitse(patteri, ryhmat: list[str] | None, numerot: list[int] | None):
    if not ryhmat and not numerot:
        return list(patteri.kysymykset)
    ryhmat = {r.upper() for r in ryhmat or []}
    numerot = set(numerot or [])
    return [k for k in patteri.kysymykset if k.ryhma.upper() in ryhmat or k.nro in numerot]


def aja_kysymys(kysymys, patteri, rag, malli, lahteet, kansio: Path):
    """Yksi kysymys: tallentaa vastauksen ja tilaston. Palauttaa (nro, tilasto tai None, virheilmoitus tai None)."""
    tulosta(f"  kysymys {kysymys.nro}: alkaa")
    try:
        vastaus, tilasto = vastaa_tilastoin(kysymys, patteri, rag, malli, lahteet, kansio / "loki")
    except Exception as virhe:  # yhden kysymyksen virhe ei kaada ajoa
        (kansio / "loki").mkdir(parents=True, exist_ok=True)
        (kansio / "loki" / f"k{kysymys.nro}_virhe.txt").write_text(traceback.format_exc(), encoding="utf-8")
        tulosta(f"  kysymys {kysymys.nro}: VIRHE {type(virhe).__name__}: {str(virhe)[:300]}")
        return kysymys.nro, None, f"{type(virhe).__name__}: {str(virhe)[:300]}"
    tallenna_vastaus(vastaus, kansio / "vastaukset" / f"k{kysymys.nro}.json")
    polku = kansio / "tilastot" / f"k{kysymys.nro}.json"
    polku.parent.mkdir(parents=True, exist_ok=True)
    polku.write_text(json.dumps(asdict(tilasto), ensure_ascii=False, indent=2), encoding="utf-8")
    tulosta(f"  kysymys {kysymys.nro}: valmis ({tilasto.kesto_s:.0f} s, löydöksiä {tilasto.loydoksia})")
    return kysymys.nro, tilasto, None


def tulosta_taulukko(valitut, kansio: Path, virheet: dict[int, str]) -> None:
    otsikko = ["Kysymys", "Osumia", "Ehdotuksia", "Hyväksyttyjä", "Sumeita", "Hylättyjä", "Osuvuus-pudotettuja", "Löydöksiä", "Kesto"]
    rivit = []
    syyt: dict[str, int] = {}
    for k in valitut:
        t = lue_tilasto(kansio / "tilastot" / f"k{k.nro}.json")
        if k.nro in virheet:
            rivit.append([str(k.nro), "VIRHE", "", "", "", "", "", "", ""])
        elif t is None:
            rivit.append([str(k.nro), "–", "", "", "", "", "", "", ""])
        else:
            rivit.append([str(k.nro), str(t.osumia), str(t.ehdotuksia), str(t.hyvaksyttyja), str(t.sumeita),
                          str(t.hylattyja), str(t.osuvuus_pudotettuja), str(t.loydoksia), f"{t.kesto_s:.0f} s"])
            for syy, n in t.syyt.items():
                syyt[syy] = syyt.get(syy, 0) + n
    leveys = [max(len(otsikko[i]), *(len(r[i]) for r in rivit)) for i in range(len(otsikko))]
    tulosta()
    tulosta("  ".join(o.ljust(w) for o, w in zip(otsikko, leveys)))
    for r in rivit:
        tulosta("  ".join(c.rjust(w) for c, w in zip(r, leveys)))
    if syyt:
        tulosta("Hylkäyssyyt: " + ", ".join(f"{s}: {n}" for s, n in sorted(syyt.items(), key=lambda p: -p[1])))
    for nro, virhe in virheet.items():
        tulosta(f"Kysymys {nro} epäonnistui: {virhe}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Vastaa kysymyspatteriin RAGin artikkeleiden perusteella.")
    ap.add_argument("kysymystiedosto", type=Path)
    ap.add_argument("--ryhma", nargs="+", metavar="K1", help="ajettavat ryhmät")
    ap.add_argument("--kysymys", nargs="+", type=int, metavar="NRO", help="ajettavat kysymykset")
    ap.add_argument("--malli", default=os.environ.get("MALLI"),
                    help="mallin tunnus rajapinnassa (oletus: ympäristömuuttuja MALLI)")
    ap.add_argument("--ajo", default=None, help="ajon nimi (oletus: ajo-<aika>)")
    ap.add_argument("--rinnakkain", type=int, default=1, help="samanaikaisten kysymysten määrä")
    ap.add_argument("--uudelleen", action="store_true", help="ajaa myös valmiiksi tallennetut kysymykset")
    ap.add_argument("--vain-docx", action="store_true", help="ei mallikutsuja: tehdään docx tallennetuista vastauksista")
    ap.add_argument("--lahteet", type=Path, default=JUURI / "lahteet.json")
    args = ap.parse_args(argv)

    patteri = lue_patteri(args.kysymystiedosto)
    lahteet = lataa_lahteet(args.lahteet)
    valitut = valitse(patteri, args.ryhma, args.kysymys)
    if not valitut:
        ap.error("ei yhtään kysymystä valinnan (--ryhma / --kysymys) perusteella")
    ajo = args.ajo or datetime.now().strftime("ajo-%Y%m%d-%H%M")
    kansio = JUURI / "tulokset" / ajo
    vastauskansio = kansio / "vastaukset"
    virheet: dict[int, str] = {}

    if not args.vain_docx:
        if not args.malli:
            ap.error("malli puuttuu: anna --malli tai aseta ympäristömuuttuja MALLI")
        tehtavat = [k for k in valitut if args.uudelleen or not (vastauskansio / f"k{k.nro}.json").is_file()]
        ohitetut = [k.nro for k in valitut if k not in tehtavat]
        tulosta(f"Ajo {ajo}: malli {args.malli}, {len(tehtavat)} kysymystä ajetaan"
                + (f", {len(ohitetut)} valmista ohitetaan ({', '.join(map(str, ohitetut))})" if ohitetut else ""))
        if tehtavat:
            rag = Rag(valimuisti=JUURI / ".valimuisti")
            malli = Malli(args.malli)
            with ThreadPoolExecutor(max_workers=max(1, args.rinnakkain)) as pooli:
                toita = [pooli.submit(aja_kysymys, k, patteri, rag, malli, lahteet, kansio) for k in tehtavat]
                for t in as_completed(toita):
                    nro, _, virhe = t.result()
                    if virhe:
                        virheet[nro] = virhe

    # docx kaikista ajon tallennetuista vastauksista
    vastaukset = [lataa_vastaus(p) for p in sorted(vastauskansio.glob("k*.json"),
                  key=lambda p: int(p.stem[1:]))] if vastauskansio.is_dir() else []
    docx = kansio / f"{ajo}.docx"
    kirjoita_docx(patteri, vastaukset, lahteet, docx, otsikko=f"Teoriakoonti ({ajo})")
    tulosta_taulukko(valitut, kansio, virheet)
    tulosta(f"\nDocx: {docx} ({len(vastaukset)} vastausta)")
    return 1 if virheet else 0


if __name__ == "__main__":
    sys.exit(main())
