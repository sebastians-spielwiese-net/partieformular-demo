"""Trainingsdaten für das Schach-Erkennungsmodell: HCS-Zugbilder (nach Blättern geteilt), deutsche Varianten durch eingesetzte Handschrift-Glyphen (EMNIST) und gerenderte Zellen aus echten Partien.

Alle Bilder liegen am Ende als uint8 [64, 256] vor, wie das Modell sie bekommt (Schrift zugeschnitten, mittig, Weiß als Papier). Nur numpy und Pillow; Daten außerhalb des Repos unter `_daten_spielwiese/`.
"""
from __future__ import annotations

import gzip
import io
import random
import re
import struct
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

WURZEL = Path(__file__).resolve().parent.parent
DATEN = WURZEL.parent / "_daten_spielwiese"
HCS = DATEN / "hcs" / "dl"
HOEHE, BREITE = 64, 256
DEUTSCH = {"N": "S", "B": "L", "R": "T", "Q": "D"}              # englischer Figurenbuchstabe -> deutscher


# --------------------------------------------------------------------------- Vorverarbeitung (nach dem Notebook des Originals, v47)
def otsu(g: np.ndarray) -> float:
    hist = np.bincount(g.ravel(), minlength=256).astype(float)
    summe, n = float((np.arange(256) * hist).sum()), hist.sum()
    sb = wb = 0.0
    best, schwelle = -1.0, 127.0
    for t in range(256):
        wb += hist[t]
        if wb == 0 or wb == n:
            continue
        sb += t * hist[t]
        mb, mf = sb / wb, (summe - sb) / (n - wb)
        zw = wb * (n - wb) * (mb - mf) ** 2
        if zw > best:
            best, schwelle = zw, float(t)
    return schwelle


def nummernfeld_ende(gray: np.ndarray) -> tuple[bool, int]:
    """Wo endet das graue Feld der Zugnummer links im Bild des Originals (nur bei Bildern ab 250 Pixel Breite)?"""
    h, w = gray.shape
    if w < 250:
        return False, 0
    streifen = gray[h // 3:2 * h // 3, :]
    spalte = np.convolve(streifen.max(axis=0).astype(float), np.ones(5) / 5, mode="same")
    verlauf = np.gradient(spalte)
    if w < 200:
        return False, 0
    suche = verlauf[160:200]
    i = int(np.argmax(suche)) + 160
    if suche.max() < 0.8 or spalte[195:220].mean() - spalte[140:170].mean() < 5:
        return False, 0
    ende = i + 10
    for x in range(i, min(i + 25, w)):
        if verlauf[x] < 0.3:
            ende = x
            break
    return True, ende


def vorverarbeitung(gray: np.ndarray, nummernfeld: bool = True) -> np.ndarray:
    """Zuschneiden auf die Schrift, Kontrast spreizen, auf Höhe 64 (Breite höchstens 256) skalieren, mittig auf Weiß setzen. Wie im Training des Originals (Linien bleiben)."""
    h, w = gray.shape
    hat, grenze = nummernfeld_ende(gray) if nummernfeld else (False, 0)
    start = grenze if hat else 0
    region = gray[:, start:]
    schwelle = otsu(region)
    spalten = np.convolve((region < schwelle).sum(axis=0).astype(float), np.ones(3) / 3, mode="same")
    cols = np.where(spalten > 0.03 * h)[0]
    a, b = (start + int(cols[0]), start + int(cols[-1])) if len(cols) else (start, w - 1)
    rand = max(8, int((b - a) * 0.05))
    x0, x1 = max(0, a - rand), min(w - 1, b + rand)
    if hat:
        x0 = max(x0, grenze - 5)
    teil = gray[:, x0:x1 + 1]
    s2 = otsu(teil)
    zeilen = np.where((gray[:, x0:x1] < s2).any(axis=1))[0]
    if len(zeilen) >= 5:
        y0, y1 = max(0, int(zeilen[0]) - 3), min(h - 1, int(zeilen[-1]) + 3)
    else:
        y0, y1 = 0, h - 1
    ausschnitt = gray[y0:y1 + 1, x0:x1 + 1].astype(float)
    lo, hi = ausschnitt.min(), ausschnitt.max()
    if hi > lo:
        ausschnitt = (ausschnitt - lo) / (hi - lo) * 255
    ch, cw = ausschnitt.shape
    nb = max(1, min(int(HOEHE * cw / ch), BREITE))
    klein = np.asarray(Image.fromarray(ausschnitt.astype(np.uint8)).resize((nb, HOEHE), Image.BOX))
    aus = np.full((HOEHE, BREITE), 255, dtype=np.uint8)
    x = max(0, (BREITE - nb) // 2)
    aus[:, x:x + nb] = klein
    return aus


# --------------------------------------------------------------------------- HCS
def lade_zellen(cache: Path | None = None) -> dict:
    """Zellen der ganzen HCS-Blätter, so geschnitten wie in der App (automatisches Raster, Zellen ohne Schrift fallen weg), vorverarbeitet, mit Beschriftung und Blattnummer.
    Die fertigen Zugbilder des Datensatzes sind gemischt und lassen sich keinem Blatt zuordnen; ohne Blattnummer gäbe es keine saubere Trennung von Training und Prüfung.
    Nur Blätter, deren Raster ohne ergänzte Linien gefunden wurde (sauber): Dort ist die Zuordnung Zelle zu Beschriftung verlässlich.
    Beschriftungen mit Zeichen außerhalb des Zeichensatzes fallen weg."""
    import sys
    sys.path.insert(0, str(WURZEL))
    import pf_raster as R
    import pyarrow.parquet as pq
    cache = cache or DATEN / "training" / "hcs_zellen.npz"
    if cache.exists():
        z = np.load(cache, allow_pickle=True)
        return {"x": z["x"], "label": list(z["label"]), "blatt": z["blatt"], "sauber": int(z["sauber"]), "blaetter": int(z["blaetter"])}
    erlaubt = set("KQRBNabcdefgh12345678x+#=O-")
    x, labels, blatt = [], [], []
    sauber = n_blaetter = 0
    for batch in pq.ParquetFile(HCS / "unprocessed-00000.parquet").iter_batches(batch_size=8):
        for r in batch.to_pylist():
            n_blaetter += 1
            bild = R.verkleinern(R.vorbereiten(Image.open(io.BytesIO(r["image"]["bytes"]))))
            raster, hinweise = R.raster_finden(bild)
            if raster.ecken is None or any("ergänzt" in h for h in hinweise):
                continue
            sauber += 1
            ply = 0
            for paar in R.zellen(bild, raster):
                for zelle in paar:
                    if ply < len(r["labels"]) and not R.ist_leer(zelle) and r["labels"][ply] and set(r["labels"][ply]) <= erlaubt:
                        x.append(vorverarbeitung(np.asarray(zelle.convert("L")), nummernfeld=False))
                        labels.append(r["labels"][ply])
                        blatt.append(n_blaetter - 1)
                    ply += 1
    cache.parent.mkdir(parents=True, exist_ok=True)
    arr = np.stack(x)
    np.savez_compressed(cache, x=arr, label=np.array(labels, dtype=object), blatt=np.array(blatt, dtype=np.int32), sauber=sauber, blaetter=n_blaetter)
    return {"x": arr, "label": labels, "blatt": np.array(blatt, dtype=np.int32), "sauber": sauber, "blaetter": n_blaetter}


def teilung(blatt: np.ndarray, anteil_pruefung: float = 0.2, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Index-Listen (Training, Prüfung): ganze Blätter wandern zusammen in eine Seite."""
    ids = np.unique(blatt)
    rng = np.random.default_rng(seed)
    pruef = set(rng.choice(ids, size=max(1, round(anteil_pruefung * len(ids))), replace=False).tolist())
    m = np.array([b in pruef for b in blatt])
    return np.where(~m)[0], np.where(m)[0]


# --------------------------------------------------------------------------- EMNIST-Glyphen
def lade_emnist(buchstaben: str = "SLTD") -> dict[str, np.ndarray]:
    """Handschrift-Großbuchstaben aus EMNIST (ByClass, NIST SD19): {Buchstabe: [n, 28, 28] uint8, Tinte hell auf dunkel}. Bilder sind gegenüber MNIST transponiert."""
    pfad = DATEN / "emnist"
    with gzip.open(pfad / "emnist-byclass-train-labels-idx1-ubyte.gz") as f:
        _, n = struct.unpack(">II", f.read(8))
        labels = np.frombuffer(f.read(), dtype=np.uint8)
    with gzip.open(pfad / "emnist-byclass-train-images-idx3-ubyte.gz") as f:
        _, n, h, w = struct.unpack(">IIII", f.read(16))
        bilder = np.frombuffer(f.read(), dtype=np.uint8).reshape(n, h, w)
    abbildung = {int(a): int(b) for a, b in (z.split() for z in (pfad / "emnist-byclass-mapping.txt").read_text().splitlines())}
    out = {}
    for b in buchstaben:
        klasse = next(k for k, v in abbildung.items() if v == ord(b))
        out[b] = np.ascontiguousarray(bilder[labels == klasse].transpose(0, 2, 1))
    return out


# --------------------------------------------------------------------------- Ausrichtung und Glyphen einsetzen
def ctc_ausrichtung(logp: np.ndarray, ziel: list[int]) -> list[tuple[int, int]] | None:
    """Beste CTC-Ausrichtung (Viterbi): je Zeichen der erste und letzte Spaltenindex. logp [T, C]. None, wenn die Folge nicht passt."""
    T, L = logp.shape[0], len(ziel)
    ext = [0]
    for z in ziel:
        ext += [z, 0]
    S = len(ext)
    if T < L:
        return None
    NEG = -1e30
    dp = np.full((T, S), NEG)
    rueck = np.zeros((T, S), dtype=np.int8)
    dp[0, 0] = logp[0, 0]
    if S > 1:
        dp[0, 1] = logp[0, ext[1]]
    for t in range(1, T):
        for s in range(S):
            kand = [(dp[t - 1, s], 0)]
            if s >= 1:
                kand.append((dp[t - 1, s - 1], 1))
            if s >= 2 and ext[s] != 0 and ext[s] != ext[s - 2]:
                kand.append((dp[t - 1, s - 2], 2))
            wert, schritt = max(kand)
            dp[t, s] = wert + logp[t, ext[s]]
            rueck[t, s] = schritt
    s = S - 1 if dp[T - 1, S - 1] >= dp[T - 1, S - 2] else S - 2
    pfad = [0] * T
    for t in range(T - 1, -1, -1):
        pfad[t] = s
        s -= int(rueck[t, s])
    spannen: dict[int, list[int]] = {}
    for t, s in enumerate(pfad):
        if s % 2 == 1:
            spannen.setdefault(s // 2, []).append(t)
    return [(min(spannen[i]), max(spannen[i])) for i in range(L)] if len(spannen) == L else None


def praefix_variante(bild: np.ndarray, label: str, glyphen: dict[str, np.ndarray], rng: np.random.Generator) -> tuple[np.ndarray, str] | None:
    """Deutsche Variante aus einem echten Bauernzug: Vor dem Feld („f3“, „c4+“) wird eine Handschrift-Glyphe (S, L, T oder D, EMNIST) in die Schrift der Zelle gesetzt, aus „f3“ wird „Sf3“.
    Der Rest bleibt echte Handschrift desselben Schreibers. Nur bei einfachen Zügen (kein Schlag), weil dort vor dem Feld nichts steht; Schläge und Zusätze kommen aus den gerenderten Zellen.
    Linien bleiben stehen, die Glyphe hat Farbe und Höhe der Schrift, das Ganze wird wieder mittig gesetzt."""
    if not re.fullmatch(r"[a-h][1-8][+#]?", label):
        return None
    zeilen_dunkel = bild.mean(axis=1)
    linie = zeilen_dunkel < 0.55 * np.median(zeilen_dunkel)
    tinte = (bild < otsu(bild)) & (~linie[:, None])
    tinte[:, :14] = False                                                    # Zellränder (Reste der Gitterlinien) sind keine Schrift
    tinte[:, -14:] = False
    if tinte.sum() < 40:
        return None
    ys, xs = np.where(tinte)
    sx0, sx1 = int(np.percentile(xs, 1)), int(np.percentile(xs, 99))
    y0, y1 = int(np.percentile(ys, 2)), int(np.percentile(ys, 98))
    hoehe = int(np.clip(y1 - y0 + 1, 22, 56))
    buchstabe = str(rng.choice(list("SLTD"), p=[0.35, 0.3, 0.25, 0.1]))
    roh = glyphen[buchstabe][int(rng.integers(len(glyphen[buchstabe])))]
    gys, gxs = np.where(roh > 40)
    if len(gys) < 10:
        return None
    g = Image.fromarray(roh[gys.min():gys.max() + 1, gxs.min():gxs.max() + 1])          # EMNIST lässt Rand um den Buchstaben: auf die Tinte zuschneiden
    hoehe = int(np.clip(hoehe * rng.uniform(0.85, 1.1), 20, 56))
    breite = int(np.clip(round(hoehe * g.width / g.height * rng.uniform(0.85, 1.15)), 10, 48))
    luecke = int(rng.integers(3, 12))
    text_breite = sx1 - sx0 + 1
    f = min(1.0, (BREITE - 16 - luecke - breite) / text_breite)          # die Zelle füllt die Breite: Schrift samt Linien so weit stauchen, dass die Glyphe davorpasst
    if f < 0.6:
        return None
    schmal = np.asarray(Image.fromarray(bild).resize((max(8, round(BREITE * f)), HOEHE), Image.BICUBIC)).astype(np.float32)
    tx0, tx1 = int(round(sx0 * f)), int(round(sx1 * f))
    rand = BREITE
    breit = np.pad(schmal, ((0, 0), (rand, rand)), mode="reflect")
    m = np.asarray(g.resize((breite, hoehe), Image.BICUBIC), dtype=np.float32) / 255.0
    if rng.random() < 0.5:
        m = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3)), dtype=np.float32) / 255.0
    m = np.clip((m - 0.15) / 0.6, 0, 1)
    farbe = float(np.percentile(bild[tinte], 10))
    gx = tx0 + rand - luecke - breite
    gy = int(np.clip(y1 - hoehe + 1 + int(rng.integers(-2, 3)), 0, HOEHE - hoehe))
    ziel = breit[gy:gy + hoehe, gx:gx + breite]
    breit[gy:gy + hoehe, gx:gx + breite] = ziel * (1 - m) + farbe * m
    mitte = (gx + tx1 + rand) // 2
    start = int(np.clip(mitte - BREITE // 2, 0, breit.shape[1] - BREITE))
    out = breit[:, start:start + BREITE]
    return np.clip(out, 0, 255).astype(np.uint8), buchstabe + label


# --------------------------------------------------------------------------- gerenderte Zellen aus echten Partien
SYSTEMSCHRIFTEN = ["Inkfree.ttf", "segoepr.ttf", "segoesc.ttf", "comic.ttf", "Gabriola.ttf"]


def schriften_liste() -> list[Path]:
    liste = sorted((DATEN / "schriften").glob("*.ttf"))
    for n in SYSTEMSCHRIFTEN:
        p = Path("C:/Windows/Fonts") / n
        if p.exists():
            liste.append(p)
    return liste


def render_zelle(text: str, rng: np.random.Generator, schrift: Path) -> np.ndarray:
    """Eine Zelle wie von einem Formular: Papier mit Rauschen, Linien oben und unten, Text in einer Handschriftschrift mit Neigung, Strichstärke, Tintenfarbe, Unschärfe;
    dann dieselbe Vorverarbeitung wie für echte Zellen (ohne Nummernfeld)."""
    w, h = int(rng.integers(300, 560)), int(rng.integers(56, 100))
    papier = int(rng.integers(170, 240))
    bild = Image.new("L", (w, h), papier)
    d = ImageDraw.Draw(bild)
    lichtlinie = int(rng.integers(40, 120))
    d.line([(0, int(rng.integers(0, 4))), (w, int(rng.integers(0, 4)))], fill=lichtlinie, width=int(rng.integers(1, 4)))
    d.line([(0, h - 1 - int(rng.integers(0, 4))), (w, h - 1 - int(rng.integers(0, 4)))], fill=lichtlinie, width=int(rng.integers(1, 4)))
    schriftgroesse = int(h * rng.uniform(0.45, 0.8))
    font = ImageFont.truetype(str(schrift), schriftgroesse)
    breite_text = d.textlength(text, font=font)
    x = rng.uniform(0.05, 0.4) * max(10, w - breite_text)
    y = rng.uniform(0.05, 0.3) * h
    tinte = int(rng.integers(20, 130))
    d.text((x, y), text, fill=tinte, font=font)
    if rng.random() < 0.5:                                           # Strichstärke
        bild = bild.filter(ImageFilter.MinFilter(3)) if rng.random() < 0.6 else bild.filter(ImageFilter.MaxFilter(3))
    scher = rng.uniform(-0.3, 0.3)
    bild = bild.transform(bild.size, Image.AFFINE, (1, scher, -scher * h / 2, 0, 1, 0), Image.BICUBIC, fillcolor=papier)
    bild = bild.rotate(rng.uniform(-3, 3), Image.BICUBIC, fillcolor=papier)
    a = np.asarray(bild, dtype=np.float32) + rng.normal(0, rng.uniform(1, 6), size=(h, w))
    bild = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if rng.random() < 0.5:
        bild = bild.filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.3)))
    return vorverarbeitung(np.asarray(bild), nummernfeld=False)


SAN_MUSTER = re.compile(r"\b(?:O-O-O|O-O|[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?)[+#]?")


def san_aus_lichess(n: int, seed: int = 0, datei: str = "lichess_2026-10_erste1GB.pgn.zst.teil", max_byte: int = 30_000_000) -> list[str]:
    """Zufällige Züge (SAN) aus echten Partien der Lichess-Monatsdatei (CC0): die ersten `max_byte` Bytes, Kommentare in Klammern entfernt."""
    from compression import zstd
    roh = bytearray()
    with zstd.open(DATEN / datei, "rb") as f:
        try:
            while len(roh) < max_byte:
                stueck = f.read(1 << 20)
                if not stueck:
                    break
                roh += stueck
        except Exception:                                           # abgebrochener letzter Block der Teildatei
            pass
    zuege = []
    for zeile in roh.decode("utf-8", "ignore").splitlines():
        if zeile.startswith("1.") and "{" in zeile:
            t = re.sub(r"\{[^}]*\}", " ", zeile)
            t = re.sub(r"\d+\.(\.\.)?", " ", t)
            zuege += [m.group(0) for m in SAN_MUSTER.finditer(t) if m.group(0)]
    rng = random.Random(seed)
    return [rng.choice(zuege) for _ in range(n)]


def handschrift_variante(san: str, rng: np.random.Generator) -> tuple[str, str]:
    """(Text der gezeichnet wird, Beschriftung für das Training): wie Spieler wirklich schreiben, mit deutschen oder englischen Buchstaben, mit und ohne Schach- und Schlagzeichen.
    Beschriftung und Zeichnung unterscheiden sich nur in „0“ statt „O“ bei der Rochade."""
    text = san
    if rng.random() < 0.55 and text[:1] in DEUTSCH:
        text = DEUTSCH[text[0]] + text[1:]
    if rng.random() < 0.35:
        text = text.rstrip("+#")
    if rng.random() < 0.04 and "x" in text:
        text = text.replace("x", "", 1)
    label = text
    if text.startswith("O-O") and rng.random() < 0.5:
        text = text.replace("O", "0")
    return text, label
