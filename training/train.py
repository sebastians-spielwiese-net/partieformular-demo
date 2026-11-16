"""Training des Schach-Erkennungsmodells mit drei Rezepten, verglichen an Prüfblättern, die das Training nie sieht.

  A  nur echte HCS-Zellen, leichte Verfremdung (wie das Original)
  B  nur echte HCS-Zellen, starke Verfremdung (Neigung, Verzerrung, Strichstärke, Unschärfe, Rauschen)
  C  wie B, dazu deutsche Varianten echter Bauernzüge (Handschrift-Glyphe aus EMNIST vor dem Feld: aus „f3“ wird „Sf3“) und gerenderte Zellen aus echten Lichess-Partien

Alle Modelle starten ohne Vorwissen (Zufallsgewichte), damit der Vergleich sauber ist: Das Original hat alle Blätter des Datensatzes gesehen.
Aufruf (im venv _venvs/ocr): python training/train.py --rezept C --epochen 30
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).resolve().parent))
import daten  # noqa: E402
from modell import ZEICHEN_DEUTSCH, ChessBiLSTM  # noqa: E402

GERAET = "cuda" if torch.cuda.is_available() else "cpu"
AUSGABE = daten.DATEN / "training"
VAL_SCHRIFTEN = ["coveredbyyourgrace", "handlee", "gochihand", "comic"]           # nie im Training gesehen
ID = {c: i for i, c in enumerate(ZEICHEN_DEUTSCH) if c}


def kodiere(label: str) -> list[int]:
    return [ID[c] for c in label]


# --------------------------------------------------------------------------- Daten
def synth_pool(n: int, schriften: list[Path], seed: int, name: str) -> dict:
    cache = AUSGABE / f"synth_{name}.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return {"x": z["x"], "label": list(z["label"])}
    rng = np.random.default_rng(seed)
    zuege = daten.san_aus_lichess(n, seed)
    x, labels = [], []
    for san in zuege:
        text, label = daten.handschrift_variante(san, rng)
        try:
            x.append(daten.render_zelle(text, rng, schriften[int(rng.integers(len(schriften)))]))
        except Exception:                                   # Schrift ohne ein Zeichen (zum Beispiel „#“): Probe überspringen
            continue
        labels.append(label)
    AUSGABE.mkdir(parents=True, exist_ok=True)
    arr = np.stack(x)
    np.savez_compressed(cache, x=arr, label=np.array(labels, dtype=object))
    return {"x": arr, "label": labels}


def alle_daten() -> dict:
    d = daten.lade_zellen()
    tr, va = daten.teilung(d["blatt"])
    schriften = daten.schriften_liste()
    val_s = [s for s in schriften if s.stem in VAL_SCHRIFTEN]
    train_s = [s for s in schriften if s.stem not in VAL_SCHRIFTEN]
    gl = daten.lade_emnist()
    rng = np.random.default_rng(1)
    glyphen_tr, glyphen_va = {}, {}
    for b, arr in gl.items():
        i = rng.permutation(len(arr))
        k = int(0.9 * len(arr))
        glyphen_tr[b], glyphen_va[b] = arr[i[:k]], arr[i[k:]]
    return {"x": d["x"], "label": d["label"], "blatt": d["blatt"], "tr": tr, "va": va, "glyph_tr": glyphen_tr, "glyph_va": glyphen_va,
            "synth_tr": synth_pool(40000, train_s, 11, "train"), "synth_va": synth_pool(3000, val_s, 12, "val")}


def deutsche_pruefmenge(x, labels, idx, glyphen, seed=5):
    rng = np.random.default_rng(seed)
    xs, ls = [], []
    for i in idx:
        r = daten.praefix_variante(x[i], labels[i], glyphen, rng)
        if r:
            xs.append(r[0])
            ls.append(r[1])
    return np.stack(xs), ls


# --------------------------------------------------------------------------- Verfremdung auf der GPU
def verfremden(x: torch.Tensor, stark: bool) -> torch.Tensor:
    """x [B, 1, 64, 256] in [-1, 1] (Weiß = 1). Neigung, Drehung, Streckung, Verschiebung; Helligkeit und Kontrast; bei stark zusätzlich Verzerrung, Strichstärke, Unschärfe, Rauschen."""
    B = x.shape[0]
    d = x.device
    rot = (torch.rand(B, device=d) * 2 - 1) * math.radians(5 if stark else 3)
    scher = (torch.rand(B, device=d) * 2 - 1) * (0.3 if stark else 0.15)
    sx = 1 + (torch.rand(B, device=d) * 2 - 1) * 0.15
    ty = (torch.rand(B, device=d) * 2 - 1) * (3 / 32)
    tx = (torch.rand(B, device=d) * 2 - 1) * (8 / 128)
    cos, sin = torch.cos(rot), torch.sin(rot)
    theta = torch.zeros(B, 2, 3, device=d)
    theta[:, 0, 0] = cos / sx
    theta[:, 0, 1] = -sin * 0.25 + scher
    theta[:, 1, 0] = sin * 4
    theta[:, 1, 1] = cos
    theta[:, 0, 2], theta[:, 1, 2] = tx, ty
    grid = F.affine_grid(theta, x.shape, align_corners=False)
    if stark:                                                    # glatte Verzerrung des Gitters
        fluss = F.interpolate((torch.rand(B, 2, 4, 16, device=d) * 2 - 1) * 0.04, size=x.shape[2:], mode="bicubic", align_corners=False)
        grid = grid + fluss.permute(0, 2, 3, 1)
    x = F.grid_sample(x, grid, mode="bilinear", padding_mode="border", align_corners=False)
    kontrast = 1 + (torch.rand(B, 1, 1, 1, device=d) * 2 - 1) * (0.3 if stark else 0.15)
    hell = (torch.rand(B, 1, 1, 1, device=d) * 2 - 1) * (0.2 if stark else 0.1)
    x = ((x * kontrast) + hell).clamp(-1, 1)
    if stark:
        dick = torch.rand(B, device=d)
        dicker = -F.max_pool2d(-x, 3, 1, 1)
        duenner = F.max_pool2d(x, 3, 1, 1)
        x = torch.where((dick < 0.25).view(B, 1, 1, 1), dicker, torch.where((dick > 0.8).view(B, 1, 1, 1), duenner, x))
        sigma = torch.rand(B, device=d) * 1.0
        k = torch.arange(-2, 3, device=d).float()
        gk = torch.exp(-(k[None, :] ** 2) / (2 * (sigma[:, None] + 1e-3) ** 2))
        gk = gk / gk.sum(1, keepdim=True)
        unscharf = (torch.rand(B, device=d) < 0.4)
        w = gk[:, None, None, :]
        xb = F.conv2d(F.pad(x.permute(1, 0, 2, 3), (2, 2, 0, 0), mode="replicate"), w.reshape(B, 1, 1, 5), groups=B).permute(1, 0, 2, 3)
        x = torch.where(unscharf.view(B, 1, 1, 1), xb, x)
        x = (x + torch.randn_like(x) * (torch.rand(B, 1, 1, 1, device=d) * 0.08)).clamp(-1, 1)
    return x


# --------------------------------------------------------------------------- Messen
def gieriger_text(logits: torch.Tensor) -> list[str]:
    """Gieriges Dekodieren; logits [T, B, C]."""
    beste = logits.argmax(-1).T.cpu().numpy()
    out = []
    for zeile in beste:
        s, vor = [], 0
        for c in zeile:
            if c != vor and c != 0:
                s.append(ZEICHEN_DEUTSCH[c])
            vor = c
        out.append("".join(s))
    return out


def editierabstand(a: str, b: str) -> int:
    d = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        neu = [i]
        for j, cb in enumerate(b, 1):
            neu.append(min(d[j] + 1, neu[j - 1] + 1, d[j - 1] + (ca != cb)))
        d = neu
    return d[-1]


@torch.no_grad()
def bewerte(modell: ChessBiLSTM, x: np.ndarray, labels: list[str], temperatur: float = 1.0) -> dict:
    modell.eval()
    treffer = fehler = zeichen = 0
    nll = 0.0
    for i in range(0, len(x), 256):
        xb = torch.from_numpy(x[i:i + 256]).float().div(255).sub(0.5).div(0.5).unsqueeze(1).to(GERAET)
        lg = modell(xb) / temperatur
        for t, w in zip(gieriger_text(lg), labels[i:i + 256]):
            treffer += t == w
            fehler += editierabstand(t, w)
            zeichen += len(w)
        ziele = [torch.tensor(kodiere(w)) for w in labels[i:i + 256]]
        nll += float(F.ctc_loss(F.log_softmax(lg, -1), torch.cat(ziele).to(GERAET), torch.full((len(ziele),), lg.shape[0], dtype=torch.long),
                                torch.tensor([len(z) for z in ziele]), blank=0, reduction="sum", zero_infinity=True))
    return {"n": len(x), "mra": treffer / len(x), "cer": fehler / max(1, zeichen), "nll_je_zelle": nll / len(x)}


# --------------------------------------------------------------------------- Training
def trainiere(rezept: str, epochen: int, d: dict, seed: int = 0, speichern: bool = True, name: str = "") -> dict:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    modell = ChessBiLSTM(len(ZEICHEN_DEUTSCH)).to(GERAET)
    x, labels, tr = d["x"], d["label"], d["tr"]
    stark = rezept in ("B", "C")
    opt = torch.optim.AdamW(modell.parameters(), lr=1e-3, weight_decay=1e-2)
    batch = 64
    max_lr = 1e-3

    def lernrate(fortschritt: float) -> float:                  # kurzes Aufwärmen, dann Kosinus bis fast null
        return max_lr * (fortschritt / 0.05 if fortschritt < 0.05 else 0.5 * (1 + math.cos(math.pi * (fortschritt - 0.05) / 0.95)) * 0.98 + 0.02)
    st_x, st_l = d["synth_tr"]["x"], d["synth_tr"]["label"]
    verlauf = []
    t0 = time.time()
    for ep in range(epochen):
        modell.train()
        beispiele = [(x[i], labels[i]) for i in tr]
        if rezept == "C":
            for i in rng.permutation(tr)[: len(tr)]:
                r = daten.praefix_variante(x[i], labels[i], d["glyph_tr"], rng)
                if r:
                    beispiele.append(r)
            for j in rng.choice(len(st_x), size=12000, replace=False):
                beispiele.append((st_x[j], st_l[j]))
        perm = rng.permutation(len(beispiele))
        gesamt = 0.0
        for b0 in range(0, len(perm), batch):
            teil = [beispiele[k] for k in perm[b0:b0 + batch]]
            xb = torch.from_numpy(np.stack([t[0] for t in teil])).float().div(255).sub(0.5).div(0.5).unsqueeze(1).to(GERAET)
            xb = verfremden(xb, stark)
            ziele = [torch.tensor(kodiere(t[1])) for t in teil]
            lg = modell(xb)
            loss = F.ctc_loss(F.log_softmax(lg, -1), torch.cat(ziele).to(GERAET), torch.full((len(teil),), lg.shape[0], dtype=torch.long),
                              torch.tensor([len(z) for z in ziele]), blank=0, reduction="mean", zero_infinity=True)
            for g in opt.param_groups:
                g["lr"] = lernrate((ep + b0 / len(perm)) / epochen)
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(modell.parameters(), 5.0)
            opt.step()
            gesamt += float(loss) * len(teil)
        if ep % 5 == 4 or ep == epochen - 1:
            m = bewerte(modell, x[d["va"]], [labels[i] for i in d["va"]])
            verlauf.append({"epoche": ep + 1, "loss": gesamt / len(perm), "val_mra": m["mra"], "val_cer": m["cer"], "sekunden": round(time.time() - t0)})
            print(rezept, verlauf[-1], flush=True)
    if speichern:
        AUSGABE.mkdir(parents=True, exist_ok=True)
        torch.save({"model_state_dict": modell.state_dict(), "zeichen": ZEICHEN_DEUTSCH, "rezept": rezept, "epochen": epochen}, AUSGABE / f"modell_{name or rezept}.pth")
    return {"modell": modell, "verlauf": verlauf}


def pruefmengen(d: dict) -> dict:
    va = d["va"]
    xd, ld = deutsche_pruefmenge(d["x"], d["label"], va, d["glyph_va"])
    return {"echt_englisch": (d["x"][va], [d["label"][i] for i in va]), "deutsch_eingesetzt": (xd, ld),
            "gerendert_unbekannte_schriften": (d["synth_va"]["x"], d["synth_va"]["label"])}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rezept", choices=["A", "B", "C"], required=True)
    ap.add_argument("--epochen", type=int, default=30)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--alle", action="store_true", help="auch die Prüfblätter trainieren (für das Modell der App); die Prüfmengen sind dann nicht mehr ungesehen")
    a = ap.parse_args()
    d = alle_daten()
    name = a.rezept + ("_alle" if a.alle else "")
    if a.alle:
        d["tr"] = np.concatenate([d["tr"], d["va"]])
    erg = trainiere(a.rezept, a.epochen, d, a.seed, name=name)
    out = {"rezept": name, "alle_blaetter": a.alle, "epochen": a.epochen, "seed": a.seed, "verlauf": erg["verlauf"]}
    for name, (xs, ls) in pruefmengen(d).items():
        out[name] = bewerte(erg["modell"], xs, ls)
    AUSGABE.mkdir(parents=True, exist_ok=True)
    (AUSGABE / f"ergebnis_{name}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "verlauf"}, indent=1))
