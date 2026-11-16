"""Misst den Erkenner und die Dekodierung gegen die Regeln am Datensatz HCS (Handwritten Chess Scoresheet, Hugging Face `BenjaminKost/...`, Apache-2.0).

Zwei Messungen, beide mit dem echten Modell (onnxruntime) oder zum Ausprobieren des Ablaufs mit dem simulierten Erkenner:

  zellen   Zugbilder mit Beschriftung (`processed_hcs`): Anteil der Zellen, die der gierige Text genau richtig liest (MRA), und Zeichenfehlerrate (CER).
  blaetter ganze Blätter (`unprocessed_hcs`, 206 Aufnahmen mit der Zugliste): Raster nach Voreinstellung (automatisch geradegerichtet), alle Zellen lesen, dann die Prüfung
           ohne und mit Bildwahrscheinlichkeit; je Halbzug: stimmt der Zug am Ende mit der Beschriftung überein, wie viele sind „unklar“ oder nicht prüfbar, wie viele
           stehen sicher da, sind aber falsch (stille Fehler). Beschriftungen sind SAN der Spieler und können selbst Fehler oder Kritzel enthalten.

Aufruf (aus dem Ordner der Demo, Daten unter ../_daten_spielwiese/hcs/dl):
  python tools/messung_hcs.py zellen   --anzahl 500
  python tools/messung_hcs.py blaetter --anzahl 20 --oben 0.035 --unten 0.955
Die Daten und das Modell sind nicht im Repo; `tools/messung_hcs.py` liest sie nur.
"""
import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from PIL import Image

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import pf_ctc as C  # noqa: E402
import pf_erkenner as E  # noqa: E402
import pf_lesen as L  # noqa: E402
import pf_pruefung as P  # noqa: E402
import pf_raster as R  # noqa: E402

DATEN = WURZEL.parent / "_daten_spielwiese" / "hcs" / "dl"


def editierabstand(a: str, b: str) -> int:
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        neu = [i]
        for j, cb in enumerate(b, 1):
            neu.append(min(d[j] + 1, neu[j - 1] + 1, d[j - 1] + (ca != cb)))
        d = neu
    return d[-1]


def legaler_anfang(labels: list[str]) -> int:
    """So viele Halbzüge vom Anfang der Beschriftung sind eine regelkonforme Partie (die Beschriftung gibt wieder, was auf dem Blatt steht, auch Fehler und Kritzel)."""
    p = P.pruefe([labels[i:i + 2] for i in range(0, len(labels), 2)])
    n = 0
    for e in p.zuege:
        if e.status not in ("ok", "hinweis"):
            break
        n += 1
    return n


def messe_beschriftungen() -> dict:
    """Wie sauber sind die Beschriftungen der ganzen Blätter als Schachpartie?"""
    pf = pq.ParquetFile(DATEN / "unprocessed-00000.parquet")
    blaetter = voll = halbzuege = anfang = 0
    for batch in pf.iter_batches(batch_size=16, columns=["labels"]):
        for r in batch.to_pylist():
            n = legaler_anfang(r["labels"])
            blaetter += 1
            voll += n == len(r["labels"])
            halbzuege += len(r["labels"])
            anfang += n
    return {"blaetter": blaetter, "voll_legal": voll, "halbzuege": halbzuege, "legaler_anfang": anfang}


def erkenner_waehlen(art: str, wahrheit: dict | None = None) -> E.Erkenner:
    if art == "onnx":
        return E.OnnxErkenner(DATEN / "chess_ocr.onnx")
    return E.SimulierterErkenner(wahrheit or {}, unsicher=0.05, falsch=0.03, seed=0)


def messe_zellen(anzahl: int, art: str) -> dict:
    pf = pq.ParquetFile(DATEN / "train-00000-of-00002.parquet")
    n = richtig = fehler_zeichen = zeichen = 0
    for batch in pf.iter_batches(batch_size=64, columns=["image", "label"]):
        for r in batch.to_pylist():
            if n >= anzahl:
                break
            bild = Image.open(io.BytesIO(r["image"]["bytes"])).convert("L")
            er = erkenner_waehlen(art, {n: r["label"]})
            text, _ = C.gierig(er.logp(bild, n))
            richtig += text == r["label"]
            fehler_zeichen += editierabstand(text, r["label"])
            zeichen += len(r["label"])
            n += 1
        if n >= anzahl:
            break
    return {"zellen": n, "mra": richtig / n, "cer": fehler_zeichen / zeichen, "erkenner": art}


def messe_blaetter(anzahl: int, art: str, oben: float, unten: float, schwelle: float, suche: bool = False, auto: bool = False) -> dict:
    pf = pq.ParquetFile(DATEN / "unprocessed-00000.parquet")
    z = {"blaetter": 0, "halbzuege": 0, "roh_richtig": 0, "basis_richtig": 0, "bild_richtig": 0, "basis_still_falsch": 0, "bild_still_falsch": 0,
         "basis_unklar": 0, "bild_unklar": 0, "basis_nicht_pruefbar": 0, "bild_nicht_pruefbar": 0, "erkenner": art, "rastersuche": suche, "raster_automatisch": auto}
    for batch in pf.iter_batches(batch_size=8):
        for r in batch.to_pylist():
            if z["blaetter"] >= anzahl:
                break
            laenge = legaler_anfang(r["labels"])
            labels = [x.rstrip("+#") for x in r["labels"]][:laenge]          # gemessen wird nur am regelkonformen Anfang: dahinter ist die Beschriftung selbst fehlerhaft
            bild = R.verkleinern(R.vorbereiten(Image.open(io.BytesIO(r["image"]["bytes"]))))
            raster = R.raster_finden(bild)[0] if auto else R.Raster(oben=oben, unten=unten, drehung=R.schaetze_drehung(bild))
            er = erkenner_waehlen(art, dict(enumerate(r["labels"])))
            if suche:
                raster = L.suche_raster(bild, raster, er)[0]
            les = L.lese_formular(bild, raster, er, schwelle)
            zeilen = les.zeilen()
            basis, mit = P.pruefe(zeilen), P.pruefe(zeilen, bild=L.Bewerter(les))
            z["blaetter"] += 1
            for i, wahr in enumerate(labels):
                z["halbzuege"] += 1
                roh = les.zellen[i].text.rstrip("+#") if i < len(les.zellen) else ""
                z["roh_richtig"] += roh == wahr
                for name, p in (("basis", basis), ("bild", mit)):
                    e = p.zuege[i] if i < len(p.zuege) else None
                    if e is None:
                        continue
                    richtig = e.san.rstrip("+#") == wahr
                    z[f"{name}_richtig"] += richtig
                    z[f"{name}_still_falsch"] += e.status in ("ok", "hinweis") and not richtig
                    z[f"{name}_unklar"] += e.status == "unklar"
                    z[f"{name}_nicht_pruefbar"] += e.status in ("illegal", "nicht_pruefbar", "nach_ende")
        if z["blaetter"] >= anzahl:
            break
    return z


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("art", choices=["zellen", "blaetter", "beschriftungen"])
    ap.add_argument("--anzahl", type=int, default=200)
    ap.add_argument("--erkenner", choices=["onnx", "simuliert"], default="onnx")
    ap.add_argument("--oben", type=float, default=0.035)
    ap.add_argument("--unten", type=float, default=0.955)
    ap.add_argument("--schwelle", type=float, default=0.6)
    ap.add_argument("--auto", action="store_true", help="Raster samt Perspektive aus den gedruckten Linien bestimmen (ohne Modell)")
    ap.add_argument("--suche", action="store_true", help="Raster (oben, unten) je Blatt automatisch suchen")
    a = ap.parse_args()
    if a.art != "beschriftungen" and a.erkenner == "onnx" and not (E.onnxruntime_vorhanden() and (DATEN / "chess_ocr.onnx").exists()):
        sys.exit("onnxruntime fehlt oder die Modelldatei liegt nicht unter ../_daten_spielwiese/hcs/dl/chess_ocr.onnx")
    if a.art == "beschriftungen":
        erg = messe_beschriftungen()
    elif a.art == "zellen":
        erg = messe_zellen(a.anzahl, a.erkenner)
    else:
        erg = messe_blaetter(a.anzahl, a.erkenner, a.oben, a.unten, a.schwelle, a.suche, a.auto)
    print(json.dumps(erg, ensure_ascii=False, indent=1, default=lambda o: float(o) if isinstance(o, np.floating) else str(o)))


if __name__ == "__main__":
    main()
