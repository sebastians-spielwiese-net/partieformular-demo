"""Kalibrierung (Temperatur) und Test-Time-Augmentation (TTA) für ein trainiertes Modell, gemessen an den Prüfmengen, die das Training nie sieht.

Temperatur: ein einziger Wert T, durch den die Logits geteilt werden; gewählt so, dass die CTC-Verlustfunktion (negative Log-Wahrscheinlichkeit der richtigen Beschriftung) auf der einen Hälfte der Prüfzellen minimal wird,
gemessen auf der anderen Hälfte (Hälften nach Blatt getrennt, nicht nach Zelle). Die Zweifelschwelle der App (Wahrscheinlichkeit des gelesenen Zeichens) bekommt dadurch eine Bedeutung.
TTA: dieselbe Zelle leicht verschoben und gestreckt lesen und die Wahrscheinlichkeiten je Zeitschritt mitteln (die Zeitschritte entsprechen sich, weil das Modell die Zeichen über die ganze Breite verteilt ausgibt).
Aufruf (im venv _venvs/ocr): python training/kalibrieren.py --rezept C
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train  # noqa: E402
from modell import ChessBiLSTM  # noqa: E402

GERAET = train.GERAET


def lade(rezept: str) -> ChessBiLSTM:
    z = torch.load(train.AUSGABE / f"modell_{rezept}.pth", map_location=GERAET)
    m = ChessBiLSTM(len(z["zeichen"])).to(GERAET)
    m.load_state_dict(z["model_state_dict"])
    return m.eval()


def als_tensor(x: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(x).float().div(255).sub(0.5).div(0.5).unsqueeze(1).to(GERAET)


def verschieben(x: torch.Tensor, dx: float, faktor: float) -> torch.Tensor:
    """x [B,1,64,256]: um dx Pixel nach rechts schieben, waagerecht um `faktor` strecken (Mitte bleibt)."""
    B = x.shape[0]
    theta = torch.zeros(B, 2, 3, device=x.device)
    theta[:, 0, 0] = 1 / faktor
    theta[:, 1, 1] = 1
    theta[:, 0, 2] = -dx / 128
    grid = F.affine_grid(theta, x.shape, align_corners=False)
    return F.grid_sample(x, grid, mode="bilinear", padding_mode="border", align_corners=False)


VARIANTEN = [(0, 1.0), (-6, 1.0), (6, 1.0), (0, 0.92), (0, 1.08)]


@torch.no_grad()
def logits_batches(modell, x: np.ndarray, tta: bool, temperatur: float) -> list[torch.Tensor]:
    """Gemittelte Log-Wahrscheinlichkeiten [T,B,C] je Stapel."""
    out = []
    for i in range(0, len(x), 256):
        xb = als_tensor(x[i:i + 256])
        if not tta:
            out.append(F.log_softmax(modell(xb) / temperatur, -1))
            continue
        p = sum(F.softmax(modell(verschieben(xb, dx, f)) / temperatur, -1) for dx, f in VARIANTEN) / len(VARIANTEN)
        out.append(p.clamp_min(1e-9).log())
    return out


def messen(modell, x, labels, tta=False, temperatur=1.0) -> dict:
    treffer = fehler = zeichen = 0
    nll = 0.0
    stapel = logits_batches(modell, x, tta, temperatur)
    for k, lp in enumerate(stapel):
        lb = labels[k * 256:(k + 1) * 256]
        for t, w in zip(train.gieriger_text(lp), lb):
            treffer += t == w
            fehler += train.editierabstand(t, w)
            zeichen += len(w)
        ziele = [torch.tensor(train.kodiere(w)) for w in lb]
        nll += float(F.ctc_loss(lp, torch.cat(ziele).to(GERAET), torch.full((len(ziele),), lp.shape[0], dtype=torch.long),
                                torch.tensor([len(z) for z in ziele]), blank=0, reduction="sum", zero_infinity=True))
    return {"n": len(x), "mra": round(treffer / len(x), 4), "cer": round(fehler / max(1, zeichen), 4), "nll_je_zelle": round(nll / len(x), 4)}


def beste_temperatur(modell, x, labels) -> float:
    kandidaten = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0]
    nll = {t: messen(modell, x, labels, False, t)["nll_je_zelle"] for t in kandidaten}
    return min(nll, key=nll.get)


def zuverlaessigkeit(modell, x, labels, temperatur: float, schwelle_stufen=(0.5, 0.7, 0.9, 0.97)) -> list[dict]:
    """Wie oft stimmt die Lesung, wenn die Zuversicht (Produkt der gelesenen Zeichen-Wahrscheinlichkeiten, gierig) über einer Stufe liegt? Bei guter Kalibrierung etwa so oft wie die Stufe."""
    zuv, richtig = [], []
    for k, lp in enumerate(logits_batches(modell, x, False, temperatur)):
        p = lp.exp()
        beste, idx = p.max(-1)
        texte = train.gieriger_text(lp)
        for j, t in enumerate(texte):
            frames = idx[:, j]
            gewaehlt = beste[:, j][frames != 0]
            zuv.append(float(gewaehlt.prod()) if len(gewaehlt) else 0.0)
            richtig.append(t == labels[k * 256 + j])
    zuv, richtig = np.array(zuv), np.array(richtig)
    return [{"stufe": s, "anteil_der_zellen": round(float((zuv >= s).mean()), 3), "trefferquote": round(float(richtig[zuv >= s].mean()), 3) if (zuv >= s).any() else None} for s in schwelle_stufen]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rezept", choices=["A", "B", "C"], required=True)
    a = ap.parse_args()
    d = train.alle_daten()
    modell = lade(a.rezept)
    mengen = train.pruefmengen(d)
    # Temperatur auf der einen Hälfte der Prüfblätter wählen, auf der anderen messen
    va = np.array(d["va"])
    xe, le = mengen["echt_englisch"]
    blatt_va = np.array([int(d["blatt"][i]) for i in va])
    halb_a = np.isin(blatt_va, sorted(set(blatt_va.tolist()))[::2])
    T = beste_temperatur(modell, xe[halb_a], [x for x, h in zip(le, halb_a) if h])
    out = {"rezept": a.rezept, "temperatur": T}
    for name, (xs, ls) in mengen.items():
        out[name] = {"ohne": messen(modell, xs, ls), "kalibriert": messen(modell, xs, ls, False, T), "tta": messen(modell, xs, ls, True, T)}
    xb, lb = xe[~halb_a], [x for x, h in zip(le, halb_a) if not h]
    out["zuverlaessigkeit_andere_haelfte"] = {"ohne_temperatur": zuverlaessigkeit(modell, xb, lb, 1.0), "mit_temperatur": zuverlaessigkeit(modell, xb, lb, T)}
    text = json.dumps(out, indent=1, ensure_ascii=False)
    print(text)
    (train.AUSGABE / f"kalibrierung_{a.rezept}.json").write_text(text + "\n", encoding="utf-8")
