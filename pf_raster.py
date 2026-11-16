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
    spaltenlage: tuple | None = None    # je Block (Weiß links, Weiß rechts, Schwarz links, Schwarz rechts) als Anteile der Breite des zugeschnittenen Bildes (Formulare ohne senkrechte Linien, siehe pf_vorlage)
    zeilenlinien: tuple | None = None   # zeilen + 1 y-Werte als Anteile der Höhe des zugeschnittenen Bildes; gilt zusammen mit spaltenlage
    bereinigen: bool = False            # Zellen vor dem Lesen bereinigen (blasse Schrift, gedruckte Linien, Schrägschrift), siehe bereinige_zelle

    def pruefe(self) -> None:
        if not (0 <= self.links < self.rechts <= 1 and 0 <= self.oben < self.unten <= 1):
            raise ValueError("Ausschnitt ungültig")
        if self.zeilen < 1 or self.bloecke < 1 or len(self.spalten) != 3 or min(self.spalten) <= 0:
            raise ValueError("Raster ungültig")
        if (self.spaltenlage is None) != (self.zeilenlinien is None):
            raise ValueError("Spaltenlage und Zeilenlinien gehören zusammen")
        if self.spaltenlage is not None and (len(self.spaltenlage) != self.bloecke or len(self.zeilenlinien) != self.zeilen + 1):
            raise ValueError("Spaltenlage oder Zeilenlinien passen nicht zu Blöcken und Zeilen")


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
    zuege: list[list[tuple[int, int, int, int]]] = []
    if r.spaltenlage is not None and r.zeilenlinien is not None:            # gedruckte Lage (Formular ohne senkrechte Linien)
        ys = [round(y * hoehe) for y in r.zeilenlinien]
        for w0, w1, s0, s1 in r.spaltenlage:
            for i in range(r.zeilen):
                zuege.append([(round(w0 * breite), ys[i], round(w1 * breite), ys[i + 1]), (round(s0 * breite), ys[i], round(s1 * breite), ys[i + 1])])
        return zuege
    summe = sum(r.spalten)
    anteile = [s / summe for s in r.spalten]
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
            ausschnitt = z.crop((max(0, a), max(0, b - rand), min(z.width, c), min(z.height, d + rand)))
            zeile.append(bereinige_zelle(ausschnitt) if r.bereinigen else ausschnitt)
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
    bild = vorbereiten(bild)
    fund = finde_raster(bild, zeilen)
    if any("senkrechten Linien wurden nicht gefunden" in h for h in fund.hinweise):     # Formular ohne Tabellenränder: Struktur aus den Zeilenlinien lesen
        from pf_vorlage import finde as finde_linienformular
        gefunden = finde_linienformular(bild)
        if gefunden is not None:
            return gefunden
    if not fund.gefunden:
        return Raster(), fund.hinweise
    return Raster(zeilen=fund.zeilen, bloecke=fund.bloecke or 2, spalten=fund.spalten or Raster().spalten, ecken=fund.ecken), fund.hinweise


# --------------------------------------------------------------------------- Zellen bereinigen (blasse Bleistiftschrift, gedruckte Linien, Schrägschrift)
def _scheren(tinte: np.ndarray, winkel_grad: float) -> np.ndarray:
    """Tinte (0 bis 1, Zeilen x Spalten) waagerecht scheren: Schräge Schrift wird aufgerichtet. Positiver Winkel kippt die Oberkante nach links."""
    h, w = tinte.shape
    k = np.tan(np.radians(winkel_grad))
    versatz = (np.arange(h) - h / 2.0) * k
    breite = w + int(abs(k) * h) + 2
    out = np.zeros((h, breite), dtype=tinte.dtype)
    for y in range(h):
        s = int(round(versatz[y] + (breite - w) / 2.0))
        out[y, max(0, s):min(breite, s + w)] = tinte[y, max(0, -s):w - max(0, s + w - breite)]
    return out


def schraege_schaetzen(tinte: np.ndarray, bereich: float = 30.0, schritt: float = 2.5) -> float:
    """Neigung der Schrift in Grad (positiv: Oberkante nach rechts geneigt): der Scherwinkel, bei dem die senkrechten Striche am schärfsten stehen
    (größte Streuung der Spaltensummen)."""
    if tinte.sum() < 1:
        return 0.0
    bester, winkel = -1.0, 0.0
    for a in np.arange(-bereich, bereich + 1e-9, schritt):
        s = _scheren(tinte, a).sum(axis=0)
        wert = float((s ** 2).sum())
        if wert > bester:
            bester, winkel = wert, float(a)
    return winkel


def bereinige_zelle(zelle: Image.Image, linien_entfernen: bool = True, aufrichten: bool = True) -> Image.Image:
    """Zelle für den Erkenner vorbereiten, wenn die Schrift blass ist oder gedruckte Linien im Bild liegen: Papierton abziehen, gedruckte Zeilenlinien (Pixelzeilen, die fast über die
    ganze Breite dunkel sind) löschen, die Tinte auf vollen Kontrast spreizen und schräge Schrift aufrichten. Rückgabe: Graustufenbild, dunkle Tinte auf Weiß."""
    g = grau(zelle).astype(float)
    h, w = g.shape
    if h < 8 or w < 8:
        return zelle.convert("L")
    papier = float(np.percentile(g, 75))
    tinte = np.clip(papier - g, 0.0, None)
    ref = float(np.percentile(tinte, 99.5))
    if ref < 6.0:                                    # praktisch leer: nichts spreizen
        return zelle.convert("L")
    if linien_entfernen:                             # gedruckte Linie zuerst löschen: Sie ist oft dunkler als die Schrift und bestimmte sonst den Kontrast
        stark = (tinte > 0.5 * ref).mean(axis=1)
        for y in np.where(stark > 0.6)[0]:           # fast die ganze Zeile dunkel
            tinte[max(0, y - 1):y + 2, :] = 0.0
        ref = float(np.percentile(tinte, 99.5))
        if ref < 6.0:
            return Image.new("L", zelle.size, 255)
    tinte = tinte / ref
    tinte = np.clip(tinte, 0.0, 1.0)
    tinte[tinte < 0.12] = 0.0                       # Papierrauschen
    if aufrichten:
        winkel = schraege_schaetzen(tinte)
        if abs(winkel) > 1.0:
            tinte = _scheren(tinte, winkel)
    return Image.fromarray((255.0 * (1.0 - tinte)).astype(np.uint8), mode="L")
