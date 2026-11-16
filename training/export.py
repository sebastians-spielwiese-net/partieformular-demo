"""Exportiert ein trainiertes Modell als ONNX-Datei für die App: Temperatur und Log-Softmax stecken im Modell, die Ausgabe sind Log-Wahrscheinlichkeiten [T, B, C].

Aufruf (im venv _venvs/ocr): python training/export.py --modell C_alle --temperatur 1.8 --ausgabe models/chess_ocr_de.onnx
Prüft danach mit onnxruntime, dass die Ausgabe der Datei mit der von PyTorch übereinstimmt, und druckt Größe und SHA-256 für `pf_erkenner`.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train  # noqa: E402
from modell import ChessBiLSTM  # noqa: E402


class MitTemperatur(torch.nn.Module):
    def __init__(self, modell: ChessBiLSTM, temperatur: float):
        super().__init__()
        self.modell, self.temperatur = modell, temperatur

    def forward(self, x):
        return torch.log_softmax(self.modell(x) / self.temperatur, dim=-1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--modell", required=True)
    ap.add_argument("--temperatur", type=float, required=True)
    ap.add_argument("--ausgabe", required=True)
    a = ap.parse_args()
    z = torch.load(train.AUSGABE / f"modell_{a.modell}.pth", map_location="cpu")
    m = ChessBiLSTM(len(z["zeichen"]))
    m.load_state_dict(z["model_state_dict"])
    hülle = MitTemperatur(m.eval(), a.temperatur).eval()
    pfad = Path(a.ausgabe)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    x = torch.randn(1, 1, 64, 256).clamp(-1, 1)
    torch.onnx.export(hülle, (x,), str(pfad), input_names=["input"], output_names=["output"], dynamic_axes={"input": {0: "batch"}, "output": {1: "batch"}},
                      opset_version=17, dynamo=False)
    import onnxruntime as ort
    s = ort.InferenceSession(str(pfad), providers=["CPUExecutionProvider"])
    proben = torch.rand(3, 1, 64, 256) * 2 - 1
    erwartet = hülle(proben).detach().numpy()
    erhalten = np.concatenate([s.run(None, {"input": proben[i:i + 1].numpy()})[0] for i in range(3)], axis=1)
    print("größte Abweichung zu PyTorch:", float(np.abs(erwartet - erhalten).max()), "Form", erhalten.shape)
    h = hashlib.sha256(pfad.read_bytes()).hexdigest()
    print("Bytes", pfad.stat().st_size, "SHA256", h)
