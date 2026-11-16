"""Misst das Vision-Modell (Claude, Anthropic-API) an den ganzen Blättern des Datensatzes HCS, wie `messung_hcs.py blaetter`: nur am regelkonformen Anfang der Beschriftung,
Raster automatisch aus den Linien, dann Text des Modells allein und nach der Regelprüfung.

Die Anfragen kosten Geld und schicken Bilder an Anthropic. Ohne `--ausfuehren` läuft nur eine Trockenübung: Sie zeigt je Blatt, was gesendet würde (Bilder, geschätzte Eingabe-Token)
und rechnet eine grobe Obergrenze der Kosten aus. Mit `--ausfuehren` und dem Schlüssel in ANTHROPIC_API_KEY werden die Anfragen gesendet.
HCS hat englische Notation: Deutsche Buchstaben (S, L, T, D), der Hauptgrund für das Vision-Modell, lassen sich damit nicht messen.

Aufruf: python tools/messung_vision.py --anzahl 5 [--ausfuehren] [--ausgabe data/vision_messung.json]
"""
import argparse
import io
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "tools"))

import pf_pruefung as P  # noqa: E402
import pf_raster as R  # noqa: E402
import pf_vision as V  # noqa: E402
from messung_hcs import DATEN, legaler_anfang  # noqa: E402

PREIS_EIN, PREIS_AUS = 4.0, 20.0               # Dollar je Million Token (claude-opus-5-5, Preisliste der Anthropic-Dokumentation)
AUSGABE_TOKEN_SCHAETZUNG = 4000                # Obergrenze je Blatt: Zeilen als JSON plus Denken


def bild_token(b: Image.Image) -> int:
    f = min(1.0, V.MAX_SEITE / max(b.size))
    return round(b.width * f * b.height * f / 750)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anzahl", type=int, default=5)
    ap.add_argument("--ausfuehren", action="store_true", help="Anfragen wirklich senden (kostet Geld, Bilder gehen an Anthropic)")
    ap.add_argument("--ausgabe", default="")
    a = ap.parse_args()
    pf = pq.ParquetFile(DATEN / "unprocessed-00000.parquet")
    summe = {"blaetter": 0, "halbzuege": 0, "roh_richtig": 0, "geprueft_richtig": 0, "still_falsch": 0, "unklar": 0, "nicht_pruefbar": 0, "modell": V.MODELL}
    ein_token = 0
    for batch in pf.iter_batches(batch_size=8):
        for r in batch.to_pylist():
            if summe["blaetter"] >= a.anzahl:
                break
            bild = R.verkleinern(R.vorbereiten(Image.open(io.BytesIO(r["image"]["bytes"]))))
            raster, _ = R.raster_finden(bild)
            bilder, beschreibung = V.bilder_fuer_anfrage(bild, raster)
            ein_token += sum(bild_token(b) for b in bilder) + 600
            summe["blaetter"] += 1
            if not a.ausfuehren:
                print(f"Blatt {summe['blaetter']}: {len(bilder)} Bild(er), Raster {'gefunden' if raster.ecken else 'nicht gefunden (ganzes Foto)'}")
                continue
            laenge = legaler_anfang(r["labels"])
            labels = [x.rstrip("+#") for x in r["labels"]][:laenge]
            zeilen, _ = V.lies_zeilen(bild, raster, V.schluessel_aus_umgebung())
            flach = [c for z in zeilen for c in z]
            p = P.pruefe(zeilen)
            for i, wahr in enumerate(labels):
                summe["halbzuege"] += 1
                summe["roh_richtig"] += i < len(flach) and flach[i].rstrip("+#") == wahr
                e = p.zuege[i] if i < len(p.zuege) else None
                if e is not None:
                    richtig = e.san.rstrip("+#") == wahr
                    summe["geprueft_richtig"] += richtig
                    summe["still_falsch"] += e.status in ("ok", "hinweis") and not richtig
                    summe["unklar"] += e.status == "unklar"
                    summe["nicht_pruefbar"] += e.status in ("illegal", "nicht_pruefbar", "nach_ende")
        if summe["blaetter"] >= a.anzahl:
            break
    kosten = ein_token / 1e6 * PREIS_EIN + summe["blaetter"] * AUSGABE_TOKEN_SCHAETZUNG / 1e6 * PREIS_AUS
    if not a.ausfuehren:
        print(f"Trockenübung: etwa {ein_token} Eingabe-Token für {summe['blaetter']} Blätter, Obergrenze der Kosten etwa {kosten:.2f} Dollar. Mit --ausfuehren senden.")
        return
    text = json.dumps(summe, ensure_ascii=False, indent=1)
    print(text)
    if a.ausgabe:
        Path(a.ausgabe).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
