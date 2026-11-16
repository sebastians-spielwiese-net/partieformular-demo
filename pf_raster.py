"""Ein Foto oder Scan des Partieformulars in Zellbilder zerlegen (Pillow und numpy, kein OpenCV).

Das Formular ist ein Raster: ein oder zwei Blöcke nebeneinander (Zug 1 bis 30 und 31 bis 60), je Block die Spalten Nummer, Weiß, Schwarz, darunter die Zeilen.
Der Nutzer legt am Bild fest, wo das Raster liegt (Ausschnitt, Drehung, Zeilen, Blöcke, Spaltenbreiten). Die Zeilengrenzen rasten auf die gedruckten Linien ein, wenn
sie sich im Bild finden lassen. Aus jeder Zelle für Weiß und Schwarz wird ein Bild für den Erkenner (`modell_eingabe`); leere Zellen erkennt `ist_leer`, damit der Erkenner
dort nichts erfindet.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from pf_entzerren import entzerrt, finde_raster

MODELL_HOEHE, MODELL_BREITE = 64, 256
LINKS_BESCHNITT = 0.05          # Anteil der Zellbreite, der links abgeschnitten wird (an 20 HCS-Blättern 238 statt 244 von 260 Zellen richtig gelesen: ohne 238, mit 5 % 244, mit 10 % 240)


@dataclass(frozen=True)
class Raster:
    links: float = 0.0              # Ausschnitt als Anteil des gedrehten Bildes
    oben: float = 0.0
    rechts: float = 1.0
    unten: float = 1.0
    drehung: float = 0.0            # Grad, positiv dreht gegen den Uhrzeigersinn (dreht eine schiefe Aufnahme gerade)
    zeilen: int = 30                # Zeilen je Block
    bloecke: int = 2                # Blöcke nebeneinander (Zug 1-30, 31-60)
    spalten: tuple = (0.10, 0.45, 0.45)   # Breite von Nummer, Weiß, Schwarz je Block (Anteile, werden auf 1 normiert)
    einrasten: bool = True          # Zeilengrenzen auf gedruckte Linien setzen
    ecken: tuple | None = None      # vier Ecken der Tabelle (oben links, oben rechts, unten rechts, unten links) als Anteile des Bildes: dann wird entzerrt, und Ausschnitt und Drehung gelten nicht

    def pruefe(self) -> None:
        if not (0 <= self.links < self.rechts <= 1 and 0 <= self.oben < self.unten <= 1):
            raise ValueError("Ausschnitt ungültig")
        if self.zeilen < 1 or self.bloecke < 1 or len(self.spalten) != 3 or min(self.spalten) <= 0:
            raise ValueError("Raster ungültig")


def vorbereiten(bild: Image.Image) -> Image.Image:
    """Lage nach den Exif-Angaben des Geräts korrigieren (Handyfotos), in Graustufen mit Farbe erhalten: RGB bleibt RGB, alles andere wird L."""
    bild = ImageOps.exif_transpose(bild)
    return bild.convert("RGB") if bild.mode in ("RGB", "RGBA", "P", "CMYK") else bild.convert("L")


def zugeschnitten(bild: Image.Image, r: Raster) -> Image.Image:
    """Gedrehtes und zugeschnittenes Bild (Weiß als Füllfarbe)."""
    r.pruefe()
    if r.ecken is not None:
        return entzerrt(bild, r.ecken)
    b = bild
    if abs(r.drehung) > 1e-9:
        b = b.rotate(r.drehung, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255) if b.mode == "RGB" else 255)
    w, h = b.size
    return b.crop((round(r.links * w), round(r.oben * h), round(r.rechts * w), round(r.unten * h)))


def grau(bild: Image.Image) -> np.ndarray:
    return np.asarray(bild.convert("L"), dtype=np.uint8)


def zeilengrenzen(block: np.ndarray, n: int, einrasten: bool = True, toleranz: float = 0.3) -> list[int]:
    """n+1 Zeilengrenzen (y-Werte) für einen Block. Ohne Einrasten gleichmäßig; mit Einrasten wird jede innere Grenze auf die dunkelste dünne Linie in der Nähe gesetzt."""
    h = block.shape[0]
    gleich = [round(i * h / n) for i in range(n + 1)]
    if not einrasten or n < 2 or h < 4 * n:
        return gleich
    dunkel = (255.0 - block.astype(float)).mean(axis=1)
    k = max(3, int(h / n) | 1)
    glatt = np.convolve(dunkel, np.ones(3) / 3, mode="same")
    grund = np.convolve(dunkel, np.ones(k) / k, mode="same")          # Zeilenmitte hat Schrift, Linien stehen als dünne Spitzen darüber
    kamm = glatt - grund
    schwelle = max(2.0, 0.5 * float(kamm.std()))
    out = [0]
    halb = max(1, int(toleranz * h / n))
    for i in range(1, n):
        lo, hi = max(out[-1] + 1, gleich[i] - halb), min(h - 1, gleich[i] + halb)
        if hi <= lo:
            out.append(min(h - 1, max(out[-1] + 1, gleich[i])))
            continue
        stelle = lo + int(np.argmax(kamm[lo:hi + 1]))
        out.append(stelle if kamm[stelle] > schwelle else gleich[i])
    out.append(h)
    return out


def zellboxen(breite: int, hoehe: int, r: Raster, bild_grau: np.ndarray | None = None) -> list[list[tuple[int, int, int, int]]]:
    """Alle Zellen als (links, oben, rechts, unten), geordnet nach Zugnummer: je Zug [Weiß, Schwarz]. Zug n steht im Block (n-1)//zeilen."""
    summe = sum(r.spalten)
    anteile = [s / summe for s in r.spalten]
    zuege: list[list[tuple[int, int, int, int]]] = []
    for b in range(r.bloecke):
        x0, x1 = round(b * breite / r.bloecke), round((b + 1) * breite / r.bloecke)
        bw = x1 - x0
        xs = [x0, x0 + round(anteile[0] * bw), x0 + round((anteile[0] + anteile[1]) * bw), x1]
        if bild_grau is not None:
            ys = zeilengrenzen(bild_grau[:, x0:x1], r.zeilen, r.einrasten)
        else:
            ys = [round(i * hoehe / r.zeilen) for i in range(r.zeilen + 1)]
        for i in range(r.zeilen):
            zuege.append([(xs[1], ys[i], xs[2], ys[i + 1]), (xs[2], ys[i], xs[3], ys[i + 1])])
    return zuege


def zellen(bild: Image.Image, r: Raster) -> list[list[Image.Image]]:
    """Zellbilder je Zug: [[Weiß, Schwarz], …] in Zugfolge. Ränder der Zellen reichen minimal über die Linien hinaus, wie in den Trainingsbildern des Erkenners."""
    z = zugeschnitten(bild, r)
    boxen = zellboxen(z.width, z.height, r, grau(z))
    rand = max(1, round(0.02 * z.height / r.zeilen))
    out = []
    for paar in boxen:
        zeile = []
        for (a, b, c, d) in paar:
            a = a + round(LINKS_BESCHNITT * (c - a))             # die Zugnummer der Nachbarspalte reicht oft ein Stück in die Zelle
            zeile.append(z.crop((max(0, a), max(0, b - rand), min(z.width, c), min(z.height, d + rand))))
        out.append(zeile)
    return out


def vorschau(bild: Image.Image, r: Raster, breite: int = 900) -> Image.Image:
    """Zugeschnittenes Bild mit dem Raster darüber (Weiß blau, Schwarz rot, Linien der Zeilen), zum Einstellen."""
    z = zugeschnitten(bild, r).convert("RGB")
    g = grau(z)
    boxen = zellboxen(z.width, z.height, r, g)
    faktor = breite / z.width if z.width > breite else 1.0
    if faktor != 1.0:
        z = z.resize((breite, max(1, round(z.height * faktor))), Image.BILINEAR)
    d = ImageDraw.Draw(z, "RGBA")
    for paar in boxen:
        for farbe, (a, b, c, e) in zip(((30, 90, 230, 60), (230, 50, 50, 60)), paar):
            d.rectangle([a * faktor, b * faktor, c * faktor, e * faktor], outline=farbe[:3] + (200,), fill=farbe)
    return z


def ist_leer(zelle: Image.Image, anteil: float = 0.012, kontrast: int = 25) -> bool:
    """Steht in der Zelle Schrift? Der Rand mit den gedruckten Linien bleibt außen vor; dunkel heißt um mehr als `kontrast` Graustufen dunkler als das Papier der Zelle
    (auch leichte Bleistiftschrift). Schwellen an den 206 Blättern des Datensatzes HCS gewählt: beschriebene Zellen haben im Mittel 12 % solcher Punkte, leere 0,7 %."""
    g = grau(zelle).astype(float)
    h, w = g.shape
    if h < 8 or w < 8:
        return True
    innen = g[round(0.2 * h):round(0.8 * h), round(0.04 * w):round(0.96 * w)]
    papier = float(np.percentile(innen, 70))
    tinte = innen < papier - kontrast
    return float(tinte.mean()) < anteil


def otsu(g: np.ndarray) -> float:
    hist = np.bincount(g.ravel(), minlength=256).astype(float)
    summe, n = float((np.arange(256) * hist).sum()), hist.sum()
    sb, wb, best, schwelle = 0.0, 0.0, -1.0, 127.0
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


def modell_eingabe(zelle: Image.Image) -> np.ndarray:
    """Zelle wie für das Modell „chess-ocr-bilstm“ aufbereiten: auf die Schrift zuschneiden (Linien bleiben, wie beim Training), Kontrast spreizen,
    auf Höhe 64 skalieren (Breite höchstens 256), mittig auf Weiß setzen, Werte in [-1, 1]. Rückgabe [1, 1, 64, 256], float32."""
    g = grau(zelle)
    h, w = g.shape
    leer = np.full((MODELL_HOEHE, MODELL_BREITE), 255, dtype=np.uint8)
    if h < 4 or w < 4:
        ergebnis = leer
    else:
        schwelle = otsu(g)
        tinte = g < schwelle
        spalten = np.convolve(tinte.sum(axis=0).astype(float), np.ones(3) / 3, mode="same")
        cols = np.where(spalten > 0.03 * h)[0]
        a, b = (int(cols[0]), int(cols[-1])) if len(cols) else (0, w - 1)
        rand = max(8, int((b - a) * 0.05))
        x0, x1 = max(0, a - rand), min(w - 1, b + rand)
        zeilen = np.where(tinte[:, x0:x1].any(axis=1))[0]
        if len(zeilen) >= 5:
            y0, y1 = max(0, int(zeilen[0]) - 3), min(h - 1, int(zeilen[-1]) + 3)
        else:
            y0, y1 = 0, h - 1
        ausschnitt = g[y0:y1 + 1, x0:x1 + 1].astype(float)
        lo, hi = ausschnitt.min(), ausschnitt.max()
        if hi > lo:
            ausschnitt = (ausschnitt - lo) / (hi - lo) * 255
        ch, cw = ausschnitt.shape
        neu_b = max(1, min(int(MODELL_HOEHE * cw / ch), MODELL_BREITE))
        klein = Image.fromarray(ausschnitt.astype(np.uint8)).resize((neu_b, MODELL_HOEHE), Image.BOX)
        ergebnis = leer.copy()
        x_start = max(0, (MODELL_BREITE - neu_b) // 2)
        ergebnis[:, x_start:x_start + neu_b] = np.asarray(klein)
    return ((ergebnis.astype(np.float32) / 255.0 - 0.5) / 0.5)[None, None]


def schaetze_drehung(bild: Image.Image, bereich: float = 6.0, schritt: float = 0.25, breite: int = 500) -> float:
    """Wie viel Grad muss das Bild gedreht werden, damit die gedruckten Zeilenlinien waagerecht liegen? Probiert Winkel durch und nimmt den mit der schärfsten Zeilenprofilkurve
    (waagerechte Linien machen die Summe dunkler Punkte je Zeile am ungleichmäßigsten). Gibt 0 zurück, wenn kein Winkel deutlich besser ist als 0 Grad."""
    g = bild.convert("L")
    if g.width > breite:
        g = g.resize((breite, round(g.height * breite / g.width)), Image.BILINEAR)
    g = ImageOps.autocontrast(g, cutoff=2)

    def schaerfe(winkel: float) -> float:
        r = g.rotate(winkel, resample=Image.BILINEAR, expand=False, fillcolor=255)
        a = 255.0 - np.asarray(r, dtype=float)
        a = a[round(0.05 * a.shape[0]):round(0.95 * a.shape[0]), round(0.05 * a.shape[1]):round(0.95 * a.shape[1])]
        profil = a.mean(axis=1)
        return float(np.var(np.diff(profil)))

    winkel = np.arange(-bereich, bereich + 1e-9, schritt)
    werte = np.array([schaerfe(w) for w in winkel])
    bester = float(winkel[int(werte.argmax())])
    return bester if werte.max() > 1.05 * werte[int(np.argmin(np.abs(winkel)))] else 0.0


def verkleinern(bild: Image.Image, max_seite: int = 2400) -> Image.Image:
    """Große Aufnahmen auf eine handliche Größe bringen (Speicher, Geschwindigkeit); die Schrift bleibt bei 2400 Pixeln Seitenlänge gut lesbar."""
    if max(bild.size) <= max_seite:
        return bild
    f = max_seite / max(bild.size)
    return bild.resize((round(bild.width * f), round(bild.height * f)), Image.LANCZOS)


def raster_finden(bild: Image.Image, zeilen: int = 30) -> tuple[Raster, list[str]]:
    """Findet das Raster selbst (siehe pf_entzerren): Ecken, Zeilen, Blöcke und Spaltenbreiten. Gibt das Raster und Hinweise zurück; wird nichts gefunden, ist es das
    Standardraster."""
    fund = finde_raster(vorbereiten(bild), zeilen)
    if not fund.gefunden:
        return Raster(), fund.hinweise
    return Raster(zeilen=fund.zeilen, bloecke=fund.bloecke or 2, spalten=fund.spalten or Raster().spalten, ecken=fund.ecken), fund.hinweise
