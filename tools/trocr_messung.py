"""Messung: Hilft ein allgemeines Handschriftmodell (TrOCR-small-handwritten, Microsoft, MIT, ONNX-Gewichte von Xenova) bei den unsicheren Zellen?

Die Schach-Erkennung (chess-ocr-bilstm) liest alle Zellen und legt die unsicheren als „unklar“ mit höchstens acht Kandidaten vor. TrOCR bewertet nur diese Kandidaten: log P(Kandidat | Zellbild),
im Entschlüsseler mit vorgegebener Zeichenfolge berechnet (ein Durchlauf je Kandidat, kein Erzeugen). Gemessen wird, ob der wahre Zug unter den Kandidaten vorn liegt, mit der Bildwahrscheinlichkeit des Schach-Modells
allein, mit TrOCR allein und mit beiden gewichtet. Kein Torch, nur onnxruntime, numpy und Pillow; der Tokenizer (Unigram, SentencePiece) ist hier nachgebaut.

Aufruf (aus dem Ordner der Demo): python tools/trocr_messung.py zellen|blaetter --anzahl N [--quantisiert]
"""
import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

import pf_raster as R  # noqa: E402

DATEN = WURZEL.parent / "_daten_spielwiese" / "trocr"
HCS = WURZEL.parent / "_daten_spielwiese" / "hcs" / "dl"
START, BOS, EOS, PAD = 2, 0, 2, 1


class Unigram:
    """SentencePiece-Unigram-Tokenizer aus tokenizer.json (XLM-R-Wortschatz): Viterbi über die Wortstücke. Für einfachen ASCII-Text ohne Leerzeichen ist die Normalisierung die Identität."""

    def __init__(self, pfad: Path):
        m = json.loads(pfad.read_text(encoding="utf-8"))["model"]
        self.stuecke = {p: (i, s) for i, (p, s) in enumerate(m["vocab"])}
        self.unk = m["unk_id"]
        self.maxlen = max(len(p) for p in self.stuecke)

    def ids(self, text: str) -> list[int]:
        t = "▁" + text.replace(" ", "▁")
        n = len(t)
        best = [(-1e18, -1, -1)] * (n + 1)          # (Wert, Beginn, Token)
        best[0] = (0.0, 0, -1)
        for ende in range(1, n + 1):
            for beginn in range(max(0, ende - self.maxlen), ende):
                st = self.stuecke.get(t[beginn:ende])
                if st is not None and best[beginn][0] > -1e17:
                    wert = best[beginn][0] + st[1]
                    if wert > best[ende][0]:
                        best[ende] = (wert, beginn, st[0])
            if best[ende][0] < -1e17:                # unbekanntes Zeichen: ein <unk>
                best[ende] = (best[ende - 1][0] - 10.0, ende - 1, self.unk)
        out, pos = [], n
        while pos > 0:
            _, beginn, tok = best[pos]
            out.append(tok)
            pos = beginn
        return out[::-1]


class Trocr:
    def __init__(self, quantisiert: bool = False):
        import onnxruntime as ort
        suffix = "_quantized" if quantisiert else ""
        opt = ort.SessionOptions()
        opt.intra_op_num_threads = 2                  # so viele Kerne hat die Streamlit Cloud
        self.encoder = ort.InferenceSession(str(DATEN / "onnx" / f"encoder_model{suffix}.onnx"), opt, providers=["CPUExecutionProvider"])
        self.decoder = ort.InferenceSession(str(DATEN / "onnx" / f"decoder_model{suffix}.onnx"), opt, providers=["CPUExecutionProvider"])
        self.tok = Unigram(DATEN / "tokenizer.json")

    zuschneiden = True

    @classmethod
    def eingabe(cls, zelle: Image.Image) -> np.ndarray:
        if cls.zuschneiden:       # auf die Schrift zuschneiden wie für das Schach-Modell (pf_raster.modell_eingabe): Linien und Rand fallen weg
            m = (R.modell_eingabe(zelle)[0, 0] * 0.5 + 0.5) * 255
            zelle = Image.fromarray(m.astype(np.uint8))
        a = np.asarray(zelle.convert("RGB").resize((384, 384), Image.BICUBIC), dtype=np.float32) / 255.0
        return ((a - 0.5) / 0.5).transpose(2, 0, 1)[None]

    def kodiere(self, zelle: Image.Image) -> np.ndarray:
        return self.encoder.run(None, {"pixel_values": self.eingabe(zelle)})[0]

    def logps(self, hidden: np.ndarray, texte: list[str]) -> list[float]:
        """log P(Text | Bild) für jeden Text: Zeichenfolge <s> Stücke </s> mit dem Startzeichen </s> davor, in einem Durchlauf."""
        ziele = [[BOS] + self.tok.ids(t) + [EOS] for t in texte]
        laenge = max(len(z) for z in ziele)
        ein = np.full((len(ziele), laenge), PAD, dtype=np.int64)
        for i, z in enumerate(ziele):
            ein[i, 0] = START
            ein[i, 1:len(z)] = z[:-1]
        logits = self.decoder.run(["logits"], {"input_ids": ein, "encoder_hidden_states": np.repeat(hidden, len(ziele), axis=0)})[0]
        logits = logits - logits.max(axis=-1, keepdims=True)
        logp = logits - np.log(np.exp(logits).sum(axis=-1, keepdims=True))
        return [float(sum(logp[i, k, t] for k, t in enumerate(z))) for i, z in enumerate(ziele)]

    def lies(self, zelle: Image.Image, max_stuecke: int = 12) -> str:
        """Freies Erzeugen (gierig, ohne Zwischenspeicher): nur als Gegenprobe der Anbindung."""
        hidden = self.kodiere(zelle)
        ids = [START]
        for _ in range(max_stuecke):
            lg = self.decoder.run(["logits"], {"input_ids": np.array([ids], dtype=np.int64), "encoder_hidden_states": hidden})[0][0, -1]
            nxt = int(lg.argmax())
            if nxt == EOS:
                break
            ids.append(nxt)
        inv = {i: p for p, (i, _) in self.tok.stuecke.items()}
        return "".join(inv.get(i, "?") for i in ids[2:]).replace("▁", " ").strip()


def kandidaten_formen(san: str) -> list[str]:
    kern = san.rstrip("+#")
    return sorted({san, kern})


def bewerte_kandidaten(tr: Trocr, hidden: np.ndarray, kandidaten: list[str]) -> list[float]:
    """log P je Kandidat; die Schreibweisen mit und ohne Schach- und Mattzeichen sind Alternativen desselben Zugs (Summe der Wahrscheinlichkeiten)."""
    formen = [kandidaten_formen(k) for k in kandidaten]
    flach = [f for fs in formen for f in fs]
    lp = tr.logps(hidden, flach)
    out, i = [], 0
    for fs in formen:
        out.append(float(np.logaddexp.reduce(lp[i:i + len(fs)])))
        i += len(fs)
    return out


def gegenprobe(anzahl: int) -> dict:
    """Freies Lesen an Zugbildern des Datensatzes: Stimmt die Anbindung (Tokenizer, Bildaufbereitung, Entschlüsseler)?"""
    import pyarrow.parquet as pq
    tr = Trocr()
    pf = pq.ParquetFile(HCS / "train-00000-of-00002.parquet")
    n = richtig = 0
    proben = []
    for batch in pf.iter_batches(batch_size=anzahl, columns=["image", "label"]):
        for r in batch.to_pylist():
            bild = Image.open(io.BytesIO(r["image"]["bytes"])).convert("RGB")
            text = tr.lies(bild)
            n += 1
            richtig += text.replace(" ", "") == r["label"]
            if len(proben) < 12:
                proben.append((r["label"], text))
        break
    return {"zellen": n, "frei_gelesen_richtig": richtig, "proben": proben}


def editierabstand(a: str, b: str) -> int:
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        neu = [i]
        for j, cb in enumerate(b, 1):
            neu.append(min(d[j] + 1, neu[j - 1] + 1, d[j - 1] + (ca != cb)))
        d = neu
    return d[-1]


def rangprobe(anzahl: int, zuschneiden: bool, quantisiert: bool = False) -> dict:
    """Je Zugbild: der wahre Zug gegen die sieben ähnlichsten anderen Beschriftungen des Datensatzes (kleinster Editierabstand). Liegt er bei TrOCR vorn?"""
    import pyarrow.parquet as pq
    Trocr.zuschneiden = zuschneiden
    tr = Trocr(quantisiert)
    pf = pq.ParquetFile(HCS / "train-00000-of-00002.parquet")
    alle = pq.read_table(HCS / "train-00000-of-00002.parquet", columns=["label"]).column("label").to_pylist()
    pool = sorted(set(alle))
    n = vorn = 0
    zeit = 0.0
    for batch in pf.iter_batches(batch_size=anzahl, columns=["image", "label"]):
        for r in batch.to_pylist():
            wahr = r["label"]
            ander = sorted((editierabstand(wahr, x), x) for x in pool if x != wahr)[:7]
            kand = [wahr] + [x for _, x in ander]
            bild = Image.open(io.BytesIO(r["image"]["bytes"])).convert("RGB")
            t = time.time()
            lp = bewerte_kandidaten(tr, tr.kodiere(bild), kand)
            zeit += time.time() - t
            n += 1
            vorn += int(np.argmax(lp)) == 0
        break
    return {"zellen": n, "wahrer_zug_vorn": vorn, "zugeschnitten": zuschneiden, "quantisiert": quantisiert, "sekunden_je_zelle": round(zeit / n, 3)}


def vergleich(anzahl: int, gewicht: float = 0.3) -> dict:
    """Dieselben Zugbilder und Kandidaten (der wahre Zug und die sieben ähnlichsten anderen Beschriftungen): Schach-Modell, TrOCR gestaucht auf 384×384 (wie für TrOCR üblich),
    TrOCR mit erhaltenem Seitenverhältnis, und Schach-Modell plus gewichtetes TrOCR. Gezählt: wie oft der wahre Zug vorn liegt (Zufall: 1 von 8)."""
    import pyarrow.parquet as pq

    import pf_erkenner as E
    import pf_lesen as L
    er = E.OnnxErkenner(HCS / "chess_ocr.onnx")
    pf = pq.ParquetFile(HCS / "train-00000-of-00002.parquet")
    pool = sorted(set(pq.read_table(HCS / "train-00000-of-00002.parquet", columns=["label"]).column("label").to_pylist()))
    Trocr.zuschneiden = True
    tr = Trocr()
    z = {"zellen": 0, "kandidaten_je_zelle": 8, "schach_modell": 0, "trocr_gestaucht": 0, "trocr_seitenverhaeltnis": 0, "schach_plus_trocr": 0, "gewicht_trocr": gewicht}
    for batch in pf.iter_batches(batch_size=anzahl, columns=["image", "label"]):
        for r in batch.to_pylist():
            wahr = r["label"]
            kand = [wahr] + [x for _, x in sorted((editierabstand(wahr, x), x) for x in pool if x != wahr)[:7]]
            bild = Image.open(io.BytesIO(r["image"]["bytes"])).convert("RGB")
            cp = np.array([L.zug_logwahrscheinlichkeit(er.logp(bild), k) for k in kand])
            tp = np.array(bewerte_kandidaten(tr, tr.kodiere(bild), kand))
            m = (R.modell_eingabe(bild)[0, 0] * 0.5 + 0.5) * 255
            quadrat = Image.new("RGB", (256, 256), (255, 255, 255))
            quadrat.paste(Image.fromarray(m.astype(np.uint8)).convert("RGB"), (0, 96))
            px = ((np.asarray(quadrat.resize((384, 384), Image.BICUBIC), dtype=np.float32) / 255 - 0.5) / 0.5).transpose(2, 0, 1)[None]
            tq = np.array(bewerte_kandidaten(tr, tr.encoder.run(None, {"pixel_values": px})[0], kand))
            z["zellen"] += 1
            z["schach_modell"] += int(cp.argmax()) == 0
            z["trocr_gestaucht"] += int(tp.argmax()) == 0
            z["trocr_seitenverhaeltnis"] += int(tq.argmax()) == 0
            z["schach_plus_trocr"] += int((cp + gewicht * tp).argmax()) == 0
        break
    return z


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("art", choices=["gegenprobe", "rang", "vergleich"])
    ap.add_argument("--roh", action="store_true", help="ohne Zuschnitt auf die Schrift")
    ap.add_argument("--quantisiert", action="store_true")
    ap.add_argument("--anzahl", type=int, default=30)
    a = ap.parse_args()
    t = time.time()
    erg = gegenprobe(a.anzahl) if a.art == "gegenprobe" else vergleich(a.anzahl) if a.art == "vergleich" else rangprobe(a.anzahl, not a.roh, a.quantisiert)
    print(json.dumps(erg, ensure_ascii=False, indent=1), round(time.time() - t, 1), "s")
