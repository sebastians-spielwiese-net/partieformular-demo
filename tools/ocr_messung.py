"""Misst GLM-OCR (zai-org, 0,9 Milliarden Parameter, MIT, frei, läuft lokal auf der GPU) an den Blättern des Datensatzes HCS, wie `messung_hcs.py blaetter`:
Raster automatisch aus den Linien, jede beschriebene Zelle wird einzeln gelesen, gezählt wird nur am regelkonformen Anfang der Beschriftung.

Läuft im eigenen venv `_venvs/ocr` (torch mit CUDA, transformers); die übrigen Module der Demo brauchen nur numpy und Pillow.
Aufruf: python tools/ocr_messung.py blaetter --anzahl 20 [--zuschnitt] [--ausgabe data/ocr_messung_blaetter.json]
        python tools/ocr_messung.py zellen --anzahl 300
GLM-OCR liefert nur Text, keine Wahrscheinlichkeiten: Es gibt keine Bildbewertung der legalen Züge wie beim Schach-Modell.
"""
import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "tools"))

import pf_pruefung as P  # noqa: E402
import pf_raster as R  # noqa: E402
from messung_hcs import DATEN, editierabstand, legaler_anfang  # noqa: E402

MODELL = "zai-org/GLM-OCR"
AUFFORDERUNG = "Text Recognition:"


class Glm:
    def __init__(self):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor
        self.torch = torch
        self.proc = AutoProcessor.from_pretrained(MODELL)
        self.modell = AutoModelForImageTextToText.from_pretrained(MODELL, dtype=torch.bfloat16, device_map="cuda")

    def lies(self, bild: Image.Image) -> str:
        msgs = [{"role": "user", "content": [{"type": "image", "image": bild.convert("RGB")}, {"type": "text", "text": AUFFORDERUNG}]}]
        eingabe = self.proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt").to(self.modell.device)
        eingabe.pop("token_type_ids", None)
        with self.torch.no_grad():
            aus = self.modell.generate(**eingabe, max_new_tokens=24, do_sample=False)
        return self.proc.decode(aus[0][eingabe["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def normiere(text: str) -> str:
    """Typische Abweichungen von Allgemein-OCR bereinigen: führende Zugnummer, Malzeichen, Leerzeichen, Groß-/Kleinschreibung (Figuren groß, Linien klein)."""
    t = re.sub(r"^\d+[.\s]+", "", text.strip())
    t = "".join(t.replace("×", "x").replace("X", "x").split())
    if not t:
        return t
    klein = lambda m: m.group(0).lower()  # noqa: E731
    if t[0] in "kqrn":
        t = t[0].upper() + t[1:]
    if t[0] in "KQRBN":
        return t[0] + re.sub(r"[A-H]", klein, t[1:])
    return re.sub(r"[A-H]", klein, t)


def messe_zellen(anzahl: int) -> dict:
    glm = Glm()
    pf = pq.ParquetFile(DATEN / "train-00000-of-00002.parquet")
    n = roh = norm = fehler = zeichen = 0
    for batch in pf.iter_batches(batch_size=anzahl, columns=["image", "label"]):
        for r in batch.to_pylist():
            text = glm.lies(Image.open(io.BytesIO(r["image"]["bytes"])).convert("RGB"))
            wahr = r["label"]
            n += 1
            roh += text.replace(" ", "") == wahr
            k = normiere(text)
            norm += k == wahr
            fehler += editierabstand(k, wahr)
            zeichen += len(wahr)
        break
    return {"zellen": n, "roh_richtig": roh, "normiert_richtig": norm, "cer_normiert": fehler / zeichen, "modell": MODELL}


def messe_blaetter(anzahl: int, zuschnitt: bool) -> dict:
    glm = Glm()
    pf = pq.ParquetFile(DATEN / "unprocessed-00000.parquet")
    z = {"blaetter": 0, "halbzuege": 0, "roh_richtig": 0, "basis_richtig": 0, "basis_still_falsch": 0, "basis_unklar": 0, "basis_nicht_pruefbar": 0, "modell": MODELL,
         "zuschnitt": zuschnitt, "sekunden": 0.0}
    t0 = time.time()
    for batch in pf.iter_batches(batch_size=8):
        for r in batch.to_pylist():
            if z["blaetter"] >= anzahl:
                break
            laenge = legaler_anfang(r["labels"])
            labels = [x.rstrip("+#") for x in r["labels"]][:laenge]
            bild = R.verkleinern(R.vorbereiten(Image.open(io.BytesIO(r["image"]["bytes"]))))
            raster, _ = R.raster_finden(bild)
            texte = []
            for paar in R.zellen(bild, raster):
                for zelle in paar:
                    if R.ist_leer(zelle):
                        texte.append("")
                        continue
                    if zuschnitt:
                        m = (R.modell_eingabe(zelle)[0, 0] * 0.5 + 0.5) * 255
                        zelle = Image.fromarray(m.astype("uint8"))
                    texte.append(normiere(glm.lies(zelle)))
            while texte and not texte[-1]:
                texte.pop()
            zeilen = [texte[i:i + 2] + [""] * (2 - len(texte[i:i + 2])) for i in range(0, len(texte), 2)]
            p = P.pruefe(zeilen)
            z["blaetter"] += 1
            for i, wahr in enumerate(labels):
                z["halbzuege"] += 1
                z["roh_richtig"] += i < len(texte) and texte[i].rstrip("+#") == wahr
                e = p.zuege[i] if i < len(p.zuege) else None
                if e is not None:
                    richtig = e.san.rstrip("+#") == wahr
                    z["basis_richtig"] += richtig
                    z["basis_still_falsch"] += e.status in ("ok", "hinweis") and not richtig
                    z["basis_unklar"] += e.status == "unklar"
                    z["basis_nicht_pruefbar"] += e.status in ("illegal", "nicht_pruefbar", "nach_ende")
        if z["blaetter"] >= anzahl:
            break
    z["sekunden"] = round(time.time() - t0, 1)
    return z


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("art", choices=["zellen", "blaetter"])
    ap.add_argument("--anzahl", type=int, default=20)
    ap.add_argument("--zuschnitt", action="store_true")
    ap.add_argument("--ausgabe", default="")
    a = ap.parse_args()
    erg = messe_zellen(a.anzahl) if a.art == "zellen" else messe_blaetter(a.anzahl, a.zuschnitt)
    text = json.dumps(erg, ensure_ascii=False, indent=1)
    print(text)
    if a.ausgabe:
        Path(a.ausgabe).write_text(text + "\n", encoding="utf-8")
