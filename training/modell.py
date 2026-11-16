"""Das Schach-Erkennungsmodell (CNN + BiLSTM + CTC) nach der Architektur von „chess-ocr-bilstm“ (Hugging Face, MIT), mit erweiterbarem Zeichensatz.

Eingabe [B, 1, 64, 256] in [-1, 1], Ausgabe [T=63, B, C] Logits (Zeit zuerst). Spalte t liegt etwa bei den Pixeln 4t bis 4t+8.
Zeichensatz des Originals: Leerschritt, K Q R B N, a bis h, 1 bis 8, x + # = O -  (28 Klassen). Erweiterung: S L T D (deutsche Figurenbuchstaben) hinten angehängt,
damit die Klassen 0 bis 27 ihre Bedeutung behalten und die Gewichte des Originals übernommen werden können.
"""
from __future__ import annotations

import torch
import torch.nn as nn

ZEICHEN_ORIGINAL = ["", "K", "Q", "R", "B", "N", "a", "b", "c", "d", "e", "f", "g", "h", "1", "2", "3", "4", "5", "6", "7", "8", "x", "+", "#", "=", "O", "-"]
ZEICHEN_DEUTSCH = ZEICHEN_ORIGINAL + ["S", "L", "T", "D"]
SPALTEN = 63
BREITE_JE_SPALTE = 4


class ChessBiLSTM(nn.Module):
    def __init__(self, klassen: int = 28, hidden: int = 256):
        super().__init__()

        def block(ein, aus, k=3, p=1):
            return [nn.Conv2d(ein, aus, kernel_size=k, padding=p), nn.BatchNorm2d(aus), nn.ReLU(inplace=True)]

        self.cnn = nn.Sequential(
            *block(1, 64), nn.MaxPool2d(2, 2),
            *block(64, 128), nn.MaxPool2d(2, 2),
            *block(128, 256), *block(256, 256), nn.MaxPool2d((2, 1), (2, 1)),
            *block(256, 512), *block(512, 512), nn.MaxPool2d((2, 1), (2, 1)),
            *block(512, 512, 2, 0),
        )
        self.rnn = nn.LSTM(input_size=512 * 3, hidden_size=hidden, num_layers=2, bidirectional=True, batch_first=True, dropout=0.3)
        self.fc = nn.Linear(hidden * 2, klassen)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        conv = self.cnn(x)
        b, c, h, w = conv.size()
        conv = conv.permute(0, 3, 1, 2).reshape(b, w, c * h)
        aus, _ = self.rnn(conv)
        return self.fc(aus).permute(1, 0, 2)


def laden_original(pfad: str, klassen: int = 28) -> ChessBiLSTM:
    """Gewichte des Originals; bei mehr als 28 Klassen bekommen die neuen Zeilen der letzten Schicht kleine Zufallswerte (Bias 0), die alten bleiben."""
    c = torch.load(pfad, map_location="cpu", weights_only=False)
    m = ChessBiLSTM(28)
    m.load_state_dict(c["model_state_dict"])
    if klassen == 28:
        return m
    neu = ChessBiLSTM(klassen)
    sd = {k: v for k, v in m.state_dict().items() if not k.startswith("fc.")}
    neu.load_state_dict(sd, strict=False)
    with torch.no_grad():
        neu.fc.weight[:28] = m.fc.weight
        neu.fc.bias[:28] = m.fc.bias
        nn.init.normal_(neu.fc.weight[28:], std=0.02)
        neu.fc.bias[28:] = float(m.fc.bias.min())
    return neu
