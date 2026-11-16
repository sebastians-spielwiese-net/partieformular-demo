"""CTC-Rechnung mit numpy: gieriges Dekodieren mit Sicherheit je Zeichen und die Wahrscheinlichkeit einer vorgegebenen Zeichenfolge (Vorwärtsverfahren).

Ein Erkenner für Handschrift (CNN + BiLSTM + CTC) gibt je Bildspalte eine Verteilung über die Zeichen und einen Leerschritt („blank“, Klasse 0) aus: `logp[t, c]`.
Die Wahrscheinlichkeit, dass das Bild eine bestimmte Zeichenfolge zeigt, ist die Summe über alle Ausrichtungen, die auf diese Folge zusammenfallen. Damit lässt sich jeder
**legale Zug** der Stellung als Zeichenfolge bewerten, statt nur die wahrscheinlichste Lesung hinzunehmen (siehe `pf_pruefung`: Zug-Kandidaten nach dem Bild).
"""
from __future__ import annotations

import numpy as np

# Zeichensatz des Modells: Klasse 0 ist der Leerschritt. Die ersten 28 Klassen sind die des Originals „chess-ocr-bilstm“ (Hugging Face, MIT, englische Notation),
# dahinter die deutschen Figurenbuchstaben S (Springer), L (Läufer), T (Turm), D (Dame); K steht für beide Sprachen.
ZEICHEN_ORIGINAL = ["", "K", "Q", "R", "B", "N", "a", "b", "c", "d", "e", "f", "g", "h", "1", "2", "3", "4", "5", "6", "7", "8", "x", "+", "#", "=", "O", "-"]
ZEICHEN = ZEICHEN_ORIGINAL + ["S", "L", "T", "D"]
NEG = -1e30


def log_softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=-1, keepdims=True)
    return x - np.log(np.exp(x).sum(axis=-1, keepdims=True))


def als_logp(roh: np.ndarray) -> np.ndarray:
    """Bringt die Ausgabe eines Modells in die Form [T, C] aus Log-Wahrscheinlichkeiten. Akzeptiert [T, C], [T, 1, C] und [1, T, C]; Rohwerte (Logits) werden normiert."""
    a = np.asarray(roh, dtype=np.float64)
    if a.ndim == 3:
        a = a[:, 0, :] if a.shape[1] == 1 else a[0]
    if a.ndim != 2:
        raise ValueError(f"Ausgabe mit Form {np.shape(roh)} nicht lesbar")
    zeilensumme = np.exp(a).sum(axis=-1)
    if np.allclose(zeilensumme, 1.0, atol=1e-3):
        return a
    return log_softmax(a)


def kodiere(text: str, zeichen: list[str] = ZEICHEN) -> list[int] | None:
    """Zeichenfolge als Klassennummern; None, wenn ein Zeichen nicht im Zeichensatz steht."""
    index = {c: i for i, c in enumerate(zeichen) if c}
    try:
        return [index[c] for c in text]
    except KeyError:
        return None


def gierig(logp: np.ndarray, zeichen: list[str] = ZEICHEN) -> tuple[str, list[float]]:
    """Gieriges Dekodieren: je Spalte das wahrscheinlichste Zeichen, Wiederholungen zusammenfassen, Leerschritte streichen.
    Zweiter Wert: je Zeichen die höchste Wahrscheinlichkeit, die es in seiner Spaltengruppe hatte."""
    beste = logp.argmax(axis=1)
    text, sicher = [], []
    vorher = 0
    lauf_max = 0.0
    for t, c in enumerate(beste):
        p = float(np.exp(logp[t, c]))
        if c == vorher and c != 0:
            lauf_max = max(lauf_max, p)
            sicher[-1] = lauf_max
        elif c != 0:
            text.append(zeichen[c])
            sicher.append(p)
            lauf_max = p
        vorher = c
    return "".join(text), sicher


def mit_joker(logp: np.ndarray, schwelle: float = 0.6, zeichen: list[str] = ZEICHEN) -> str:
    """Gieriges Ergebnis, aber jedes Zeichen, dessen Sicherheit unter der Schwelle liegt, wird zu „?“. Das „?“ liest `pf_notation` als unleserliches Zeichen."""
    text, sicher = gierig(logp, zeichen)
    return "".join(c if p >= schwelle else "?" for c, p in zip(text, sicher))


def logwahrscheinlichkeit(logp: np.ndarray, ziel: list[int], leer: int = 0) -> float:
    """log P(Zeichenfolge `ziel` | Bild): Summe über alle CTC-Ausrichtungen (Vorwärtsverfahren im Logarithmus)."""
    T = logp.shape[0]
    if not ziel:
        return float(logp[:, leer].sum())
    ext = np.full(2 * len(ziel) + 1, leer, dtype=int)
    ext[1::2] = ziel
    S = len(ext)
    if T < len(ziel):
        return NEG
    darf_springen = np.zeros(S, dtype=bool)                       # Übergang s-2 -> s nur zwischen verschiedenen echten Zeichen
    darf_springen[2:] = (ext[2:] != leer) & (ext[2:] != ext[:-2])
    alpha = np.full(S, NEG)
    alpha[0] = logp[0, leer]
    alpha[1] = logp[0, ext[1]]
    for t in range(1, T):
        neu = np.logaddexp(alpha, np.concatenate(([NEG], alpha[:-1])))
        sprung = np.concatenate(([NEG, NEG], alpha[:-2]))
        neu = np.logaddexp(neu, np.where(darf_springen, sprung, NEG))
        alpha = neu + logp[t, ext]
    return float(np.logaddexp(alpha[-1], alpha[-2]))
