"""Erkenner für Handschrift: Zellbild rein, Verteilung über die Zeichen je Bildspalte raus (`logp[t, c]`, siehe pf_ctc).

* `OnnxErkenner`: ein Modell nach der Architektur „chess-ocr-bilstm“ (CNN + BiLSTM + CTC, MIT) über onnxruntime. Das Modell der App ist mit dem Programm in `training/` nachtrainiert:
  32 Klassen (englische und deutsche Figurenbuchstaben), Temperatur und Log-Softmax stecken in der ONNX-Datei. Das Original (28 Klassen) liest der Erkenner ebenfalls, die
  deutschen Klassen haben dann die Wahrscheinlichkeit null.
* `SimulierterErkenner`: erzeugt aus bekannten Zügen Verteilungen mit einstellbarer Fehlerrate. Nur für Tests und zum Messen der Dekodierung, nie als Ersatz für ein Modell.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

import pf_ctc as C
import pf_raster as R

# Modell der App (nachtrainiert, 32 Klassen); Größe und Prüfsumme der ONNX-Datei
MODELL_QUELLE = "https://github.com/sebastians-spielwiese/partieformular-demo/releases/download/modell-1/chess_ocr_de.onnx"
MODELL_SHA256 = "17d722d65069d752ee0717e6f56e12271522d59b12dbb3d3f661bddefe0a9b3c"
MODELL_BYTES = 43276402
MODELL_ORDNER = Path(__file__).resolve().parent / "models"
MODELL_DATEI = MODELL_ORDNER / "chess_ocr_de.onnx"
# Original (28 Klassen, englisch): nur noch für Vergleichsmessungen in `tools/`
ORIGINAL_QUELLE = "https://huggingface.co/GerhardTrippen/chess-ocr-bilstm/resolve/main/chess_ocr.onnx"
ORIGINAL_SHA256 = "79b59131dc92eebba8d609ff950cd8af78de2214b037acc20432e904bbe96953"
ORIGINAL_BYTES = 43266310
# Test-Time-Augmentation: dieselbe Zelle leicht verschoben (Pixel) und gestreckt (Faktor) lesen, die Wahrscheinlichkeiten mitteln
TTA_VARIANTEN = [(0, 1.0), (-6, 1.0), (6, 1.0), (0, 0.92), (0, 1.08)]


class Erkenner:
    """Schnittstelle. `schluessel` (der Halbzug der Zelle) wird vom Simulierten Erkenner gebraucht, ein echtes Modell ignoriert ihn."""

    zeichen = C.ZEICHEN

    def logp(self, zelle: Image.Image, schluessel: int | None = None) -> np.ndarray:
        raise NotImplementedError


def modell_vorhanden(pfad: Path = MODELL_DATEI) -> bool:
    return pfad.is_file() and pfad.stat().st_size == MODELL_BYTES


def onnxruntime_vorhanden() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def sha256(pfad: Path) -> str:
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            h.update(stueck)
    return h.hexdigest()


def modell_holen(pfad: Path = MODELL_DATEI, quelle: str = MODELL_QUELLE) -> Path:
    """Lädt das Modell von Hugging Face (43 MB) und prüft Größe und SHA-256. Wird nur auf Wunsch des Nutzers aufgerufen. Ein Fehler löscht die Teildatei."""
    import urllib.request
    pfad.parent.mkdir(parents=True, exist_ok=True)
    teil = pfad.with_suffix(".teil")
    try:
        with urllib.request.urlopen(quelle, timeout=60) as r, open(teil, "wb") as f:
            while stueck := r.read(1 << 20):
                f.write(stueck)
        if teil.stat().st_size != MODELL_BYTES or sha256(teil) != MODELL_SHA256:
            raise ValueError("Die geladene Modelldatei hat nicht die erwartete Größe oder Prüfsumme.")
        teil.replace(pfad)
    finally:
        teil.unlink(missing_ok=True)
    return pfad


def verschieben(x: np.ndarray, dx: int, faktor: float) -> np.ndarray:
    """x [1, 1, 64, 256]: um dx Pixel nach rechts schieben und waagerecht um `faktor` um die Mitte strecken; der Rand wird mit der Randspalte aufgefüllt."""
    bild = x[0, 0]
    breite = bild.shape[1]
    if faktor != 1.0:
        neu_b = max(8, round(breite * faktor))
        klein = np.asarray(Image.fromarray(bild.astype(np.float32), mode="F").resize((neu_b, bild.shape[0]), Image.BILINEAR))
        if neu_b >= breite:
            links = (neu_b - breite) // 2
            bild = klein[:, links:links + breite]
        else:
            links = (breite - neu_b) // 2
            bild = np.pad(klein, ((0, 0), (links, breite - neu_b - links)), mode="edge")
    if dx:
        bild = np.pad(bild, ((0, 0), (abs(dx), abs(dx))), mode="edge")
        bild = bild[:, abs(dx) - dx:abs(dx) - dx + breite]
    return bild[None, None].astype(np.float32)


class OnnxErkenner(Erkenner):
    """`tta=True` liest jede Zelle fünfmal (verschoben und gestreckt) und mittelt die Wahrscheinlichkeiten: gemessen etwas besser, aber fünfmal so langsam."""

    def __init__(self, pfad: Path = MODELL_DATEI, tta: bool = False):
        import onnxruntime as ort
        self.sitzung = ort.InferenceSession(str(pfad), providers=["CPUExecutionProvider"])
        self.eingabe = self.sitzung.get_inputs()[0].name
        self.tta = tta

    def _lies(self, x: np.ndarray) -> np.ndarray:
        return C.als_logp(self.sitzung.run(None, {self.eingabe: x})[0])

    def logp(self, zelle: Image.Image, schluessel: int | None = None) -> np.ndarray:
        x = R.modell_eingabe(zelle)
        if self.tta:
            p = sum(np.exp(self._lies(verschieben(x, dx, f))) for dx, f in TTA_VARIANTEN) / len(TTA_VARIANTEN)
            logp = np.log(np.maximum(p, 1e-12))
        else:
            logp = self._lies(x)
        if logp.shape[1] < len(C.ZEICHEN):                     # Original mit 28 Klassen: deutsche Klassen unmöglich
            logp = np.concatenate([logp, np.full((logp.shape[0], len(C.ZEICHEN) - logp.shape[1]), -30.0)], axis=1)
        return logp


# Verwechslungen, die bei Handschrift vorkommen: Zeichen -> Zeichen, mit denen es der Erkenner verwechselt
VERWECHSLUNG = {"b": "h6", "h": "b", "e": "c", "c": "e", "a": "d", "d": "a", "g": "9", "1": "7", "7": "1", "3": "5", "5": "3", "6": "b", "8": "3", "4": "9",
                "2": "z", "N": "K", "B": "8", "R": "K", "Q": "O", "x": "+", "f": "t", "O": "0"}


class SimulierterErkenner(Erkenner):
    """Verteilungen für bekannte Texte. `wahrheit`: Halbzug -> Zeichenfolge, die in der Zelle steht. Je Zeichen wird (mit festem Zufalls-Seed je Halbzug) gezogen:
    sicher richtig (Wahrscheinlichkeit 0,97), unsicher (richtig 0,5, Verwechslung 0,3) oder falsch vorn (Verwechslung 0,5, richtig 0,35). Spaltenzahl T wie beim echten Modell nicht fest vorgegeben."""

    def __init__(self, wahrheit: dict[int, str], unsicher: float = 0.0, falsch: float = 0.0, seed: int = 0, T: int = 64):
        self.wahrheit, self.unsicher, self.falsch, self.seed, self.T = wahrheit, unsicher, falsch, seed, T

    def logp(self, zelle: Image.Image | None = None, schluessel: int | None = None) -> np.ndarray:
        text = "".join(c for c in self.wahrheit.get(schluessel, "") if c in C.ZEICHEN[1:])
        rng = np.random.default_rng([self.seed, schluessel])
        K = len(C.ZEICHEN)
        p = np.full((self.T, K), 0.002)
        p[:, 0] = 0.95
        n = len(text)
        positionen = [int((i + 0.5) * (self.T - 8) / n) + 4 for i in range(n)]
        for pos, ch in zip(positionen, text):
            richtig = C.ZEICHEN.index(ch)
            alt = C.ZEICHEN.index(VERWECHSLUNG.get(ch, "x")[0]) if VERWECHSLUNG.get(ch, "x")[0] in C.ZEICHEN else 22
            u = rng.random()
            zeile = np.full(K, 0.002)
            if u < self.falsch:
                zeile[alt], zeile[richtig], zeile[0] = 0.5, 0.35, 0.1
            elif u < self.falsch + self.unsicher:
                zeile[richtig], zeile[alt], zeile[0] = 0.5, 0.3, 0.15
            else:
                zeile[richtig], zeile[0] = 0.97, 0.02
            p[pos] = zeile
        p /= p.sum(axis=1, keepdims=True)
        return np.log(p)
