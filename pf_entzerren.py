"""Das Raster eines Partieformulars im Foto selbst finden und die Perspektive entzerren (nur numpy und Pillow).

Ein gedrucktes Formular hat viele gleich weit entfernte waagerechte Linien. Sie werden mit einer Hough-Abstimmung gefunden (jede Linie mit eigenem Winkel, denn
bei einer schiefen Aufnahme laufen sie fächerförmig); die längste Folge gleichmäßig verteilter Linien ist das Zeilenraster. Die Enden der obersten und der untersten
Linie sind die vier Ecken der Tabelle, daraus entsteht die Entzerrung. Im entzerrten Bild liegen die senkrechten Linien aufrecht, ihre Lage ergibt Blöcke und Spaltenbreiten.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageFilter

ANALYSE_BREITE = 800


@dataclass
class Fund:
    ecken: tuple | None = None            # oben links, oben rechts, unten rechts, unten links als Anteile (x, y) des Bildes
    zeilen: int = 0
    bloecke: int = 0
    spalten: tuple | None = None          # Breite von Nummer, Weiß, Schwarz je Block (Anteile)
    linien: int = 0                       # Zahl der Linien im gefundenen Zeilenraster
    hinweise: list = field(default_factory=list)

    @property
    def gefunden(self) -> bool:
        return self.ecken is not None


def tinte(klein: Image.Image, radius: int = 12, schwelle: int = 10) -> np.ndarray:
    """Dunklere Punkte als ihre Umgebung (Linien und Schrift), unabhängig von der Beleuchtung."""
    g = klein.convert("L")
    mittel = np.asarray(g.filter(ImageFilter.BoxBlur(radius)), dtype=np.int16)
    return (mittel - np.asarray(g, dtype=np.int16)) > schwelle


def _lokale_maxima(acc: np.ndarray, rho_halb: int, minimum: float) -> list[tuple[float, int, int]]:
    """Spitzen der Abstimmungstabelle (Zeile = Winkel, Spalte = Abstand): je Abstand zählt der beste Winkel, dann Spitzen über den Abstand mit Unterdrückung der Nachbarn.
    So erzeugt eine Linie nur eine Spitze und keinen Kamm über viele Winkel."""
    glatt = acc + np.roll(acc, 1, axis=1) + np.roll(acc, -1, axis=1)                 # Linien sind einige Pixel dick
    wert = glatt.max(axis=0)
    winkel = glatt.argmax(axis=0)
    nachbarn = wert.copy()
    for dr in range(-rho_halb, rho_halb + 1):
        if dr:
            nachbarn = np.maximum(nachbarn, np.roll(wert, dr))
    minimum = max(minimum, 2.0 * float(np.median(wert)))                  # eine Linie muss sich deutlich vom Hintergrundrauschen abheben
    spitzen = np.nonzero((wert >= nachbarn) & (wert > minimum))[0]
    return sorted(((float(wert[r]), int(winkel[r]), int(r)) for r in spitzen), reverse=True)


def waagerechte_linien(maske: np.ndarray, winkel_max: float = 8.0, schritt: float = 0.5, mindest_anteil: float = 0.35) -> list[dict]:
    """Nahezu waagerechte Linien als {wert, t (Steigung), rho}: y = rho + x * t. Mindestens `mindest_anteil` der Bildbreite muss auf der Linie liegen."""
    h, w = maske.shape
    ys, xs = np.nonzero(maske)
    winkel = np.arange(-winkel_max, winkel_max + 1e-9, schritt)
    off = int(w * np.tan(np.radians(winkel_max))) + 3
    acc = np.zeros((len(winkel), h + 2 * off))
    for i, a in enumerate(winkel):
        rho = np.rint(ys - xs * np.tan(np.radians(a))).astype(int) + off
        acc[i] = np.bincount(rho, minlength=acc.shape[1])[:acc.shape[1]]
    out = []
    for wert, a, r in _lokale_maxima(acc, 5, mindest_anteil * w):
        out.append({"wert": wert, "t": float(np.tan(np.radians(winkel[a]))), "rho": float(r - off)})
    return out


def senkrechte_linien(streifen: np.ndarray, winkel_max: float = 8.0, mindest_anteil: float = 0.5) -> list[dict]:
    """Nahezu senkrechte Linien als {wert, t, rho}: x = rho + y * t (y im Streifen). Mindestens `mindest_anteil` der Streifenhöhe muss auf der Linie liegen."""
    return waagerechte_linien(streifen.T, winkel_max, 0.5, mindest_anteil)


def _schnitt(waag: dict, senk: dict) -> tuple[float, float]:
    """Schnittpunkt von y = rho + t x (waagerecht) und x = rho + t y (senkrecht), beide im selben Koordinatensystem."""
    x = (senk["rho"] + senk["t"] * waag["rho"]) / (1 - senk["t"] * waag["t"])
    return x, waag["rho"] + waag["t"] * x


def _aussenlinien(maske: np.ndarray, y0: float, y1: float, fund: Fund) -> tuple[dict, dict] | None:
    """Linke und rechte Außenlinie der Tabelle: die äußersten starken senkrechten Linien zwischen den Höhen y0 und y1."""
    h, w = maske.shape
    a, b = int(max(0, y0)), int(min(h, y1))
    if b - a < 0.3 * h:
        return None
    kandidaten = senkrechte_linien(maske[a:b])
    for lin in kandidaten:
        lin["rho"] -= lin["t"] * a                                   # Koordinaten des ganzen Bildes
        lin["x"] = lin["rho"] + lin["t"] * (a + b) / 2
    if not kandidaten:
        return None
    stark = [lin for lin in kandidaten if lin["wert"] >= 0.55 * max(k["wert"] for k in kandidaten)]
    stark.sort(key=lambda lin: lin["x"])
    if len(stark) < 2 or stark[-1]["x"] - stark[0]["x"] < 0.4 * w:
        fund.hinweise.append("Die Außenlinien der Tabelle wurden nicht gefunden: Die Ränder werden aus den Enden der Zeilenlinien geschätzt.")
        return None
    return stark[0], stark[-1]


def _zeilenraster(linien: list[dict], mitte_x: float, erwartet: int) -> list[dict]:
    """Längste Folge gleichmäßig verteilter Linien. Fehlende Linien (doppelter Abstand) werden aus den Nachbarn ergänzt."""
    for lin in linien:
        lin["y"] = lin["rho"] + mitte_x * lin["t"]
    linien = sorted(linien, key=lambda lin: lin["y"])
    entdoppelt: list[dict] = []
    for lin in linien:
        if entdoppelt and lin["y"] - entdoppelt[-1]["y"] < 4:
            if lin["wert"] > entdoppelt[-1]["wert"]:
                entdoppelt[-1] = lin
        else:
            entdoppelt.append(lin)
    beste: list[dict] = []
    for start in range(len(entdoppelt)):
        folge = [entdoppelt[start]]
        for lin in entdoppelt[start + 1:]:
            luecken = [b["y"] - a["y"] for a, b in zip(folge, folge[1:])]
            ref = float(np.median(luecken)) if luecken else None
            abstand = lin["y"] - folge[-1]["y"]
            if ref is None:
                if abstand < 12:
                    continue
                folge.append(lin)
            elif 0.75 * ref <= abstand <= 1.3 * ref:
                folge.append(lin)
            elif 1.7 * ref <= abstand <= 2.3 * ref:             # eine Linie nicht gefunden: aus den Nachbarn ergänzen
                halb = {"wert": 0.0, "t": (lin["t"] + folge[-1]["t"]) / 2, "rho": (lin["rho"] + folge[-1]["rho"]) / 2, "ergaenzt": True}
                halb["y"] = (lin["y"] + folge[-1]["y"]) / 2
                folge += [halb, lin]
            elif abstand > 2.3 * ref:
                break
        if len(folge) > len(beste):
            beste = folge
    return beste


def _ausdehnung(maske: np.ndarray, linie: dict, luecke: int = 8) -> tuple[float, float]:
    """Linkes und rechtes Ende einer Linie: längste Strecke von Tintenpunkten auf der Linie (Lücken bis `luecke` Pixel erlaubt)."""
    h, w = maske.shape
    xs = np.arange(w)
    ys = np.rint(linie["rho"] + xs * linie["t"]).astype(int)
    ok = (ys >= 1) & (ys < h - 1)
    auf = np.zeros(w, dtype=bool)
    for dy in (-1, 0, 1):
        auf[ok] |= maske[ys[ok] + dy, xs[ok]]
    idx = np.nonzero(auf)[0]
    if len(idx) == 0:
        return 0.0, float(w - 1)
    bruch = np.nonzero(np.diff(idx) > luecke)[0]
    starts = np.concatenate(([0], bruch + 1))
    enden = np.concatenate((bruch, [len(idx) - 1]))
    k = int(np.argmax(idx[enden] - idx[starts]))
    return float(idx[starts[k]]), float(idx[enden[k]])


def _spalten(entzerrt: Image.Image, erwartete_bloecke: int | None) -> tuple[int, tuple | None]:
    """Spaltenbreiten aus den senkrechten Linien des entzerrten Bildes (Spitzen des Spaltenprofils). Für das Formular mit zwei Blöcken zu je Nummer, Weiß, Schwarz:
    Die starken Linien liegen bei Weiß|Schwarz im ersten Block, an der Blockgrenze und bei Weiß|Schwarz im zweiten; die schmale Nummernspalte hat schwache Linien.
    Ergebnis: Blockzahl und Breite von Nummer, Weiß, Schwarz als Anteile des Blocks. Findet sich das nicht, (0, None)."""
    m = tinte(entzerrt, 6, 14)
    w = m.shape[1]
    profil = m.sum(axis=0).astype(float) / m.shape[0]
    spitzen: list[list[float]] = []
    for j in range(3, w - 3):
        if profil[j] >= profil[j - 3:j + 4].max() and profil[j] > 0.3:
            if not spitzen or j - spitzen[-1][0] > 0.012 * w:
                spitzen.append([j, profil[j]])
            elif profil[j] > spitzen[-1][1]:
                spitzen[-1] = [j, profil[j]]
    lage = [(p / w, v) for p, v in spitzen]

    def nahe(ziel: float, toleranz: float) -> float | None:
        c = [(abs(p - ziel), p) for p, _ in lage if abs(p - ziel) <= toleranz]
        return min(c)[1] if c else None

    mitte, links, rechts = nahe(0.5, 0.04), nahe(0.25, 0.05), nahe(0.75, 0.05)
    if None in (mitte, links, rechts) or erwartete_bloecke == 1:
        return 0, None
    schwarz = ((mitte - links) + (1.0 - rechts)) / 2 / 0.5
    nr1 = nahe(0.03, 0.025)
    nr2 = nahe(mitte + 0.02, 0.015)
    nummer = np.mean([x for x in ((nr1 or 0.03) - 0.0, (nr2 - mitte) if nr2 else 0.02)]) / 0.5
    weiss = 1.0 - schwarz - nummer
    if not (0.02 <= nummer <= 0.2 and 0.3 <= weiss <= 0.6 and 0.3 <= schwarz <= 0.6):
        return 0, None
    return 2, (round(float(nummer), 4), round(float(weiss), 4), round(float(schwarz), 4))


def perspektive_koeffizienten(ziel: list[tuple[float, float]], quelle: list[tuple[float, float]]) -> list[float]:
    """Koeffizienten für `Image.transform(..., Image.PERSPECTIVE)`: Punkte des Zielbilds -> Punkte des Quellbilds."""
    a, b = [], []
    for (x, y), (u, v) in zip(ziel, quelle):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return [float(c) for c in np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float))]


def entzerrt(bild: Image.Image, ecken: tuple, max_breite: int = 2400) -> Image.Image:
    """Tabelle aus den vier Ecken (Anteile des Bildes) zu einem Rechteck entzerren."""
    w, h = bild.size
    px = [(x * w, y * h) for x, y in ecken]
    (tl, tr, br, bl) = px
    breite = max(1, round((np.hypot(*np.subtract(tr, tl)) + np.hypot(*np.subtract(br, bl))) / 2))
    hoehe = max(1, round((np.hypot(*np.subtract(bl, tl)) + np.hypot(*np.subtract(br, tr))) / 2))
    if breite > max_breite:
        hoehe, breite = round(hoehe * max_breite / breite), max_breite
    koeff = perspektive_koeffizienten([(0, 0), (breite, 0), (breite, hoehe), (0, hoehe)], px)
    return bild.transform((breite, hoehe), Image.PERSPECTIVE, koeff, Image.BICUBIC, fillcolor=(255, 255, 255) if bild.mode == "RGB" else 255)


def _raster_hälfte(maske: np.ndarray, zeilen: int, fund: Fund, name: str) -> tuple[list[dict], float] | None:
    """Zeilenraster einer Bildhälfte (ein Block). Gibt die Linienfolge (mit ergänzten Randlinien) und den Zeilenabstand zurück."""
    h, w = maske.shape
    folge = _zeilenraster(waagerechte_linien(maske, mindest_anteil=0.6), w / 2, zeilen)
    if len(folge) < max(8, zeilen // 2):
        fund.hinweise.append(f"{name}: Nur {len(folge)} gleichmäßig verteilte Linien gefunden.")
        return None
    abstand = float(np.median([b["y"] - a["y"] for a, b in zip(folge, folge[1:])]))
    while len(folge) - 1 < zeilen:
        oben = folge[0]["y"] - abstand
        if folge[0]["y"] > 0.25 * abstand:         # über der ersten Linie ist mehr als eine Viertelzeile Bild: die erste Zeile ist zumindest teilweise im Bild
            folge.insert(0, dict(folge[0], y=oben, rho=folge[0]["rho"] - abstand, ergaenzt=True))
        else:
            folge.append(dict(folge[-1], y=folge[-1]["y"] + abstand, rho=folge[-1]["rho"] + abstand, ergaenzt=True))
        fund.hinweise.append(f"{name}: eine Linie am Rand wurde ergänzt.")
    if len(folge) - 1 > zeilen:
        fund.hinweise.append(f"{name}: {len(folge) - 1} Zeilen statt {zeilen}, die ersten {zeilen} gelten.")
        folge = folge[:zeilen + 1]
    return folge, abstand


def finde_raster(bild: Image.Image, zeilen: int = 30, bloecke: int | None = None) -> Fund:
    """Sucht das Zeilenraster im Bild, getrennt für die linke und die rechte Bildhälfte (die Blöcke können gegeneinander verschoben sein).
    `zeilen`: Zahl der Zeilen je Block (das Formular hat meist 30); fehlt am Rand eine Linie, wird sie ergänzt."""
    fund = Fund()
    klein = bild.convert("L")
    faktor = ANALYSE_BREITE / klein.width if klein.width > ANALYSE_BREITE else 1.0
    if faktor != 1.0:
        klein = klein.resize((ANALYSE_BREITE, round(klein.height * faktor)), Image.BILINEAR)
    maske = tinte(klein)
    h, w = maske.shape
    halb = w // 2
    links = _raster_hälfte(maske[:, :halb], zeilen, fund, "links")
    rechts = _raster_hälfte(maske[:, halb:], zeilen, fund, "rechts")
    if links is None or rechts is None:
        fund.hinweise.append("Das Zeilenraster ist nicht zu erkennen.")
        return fund
    fund.linien = len(links[0])

    def ende(folge: list[dict], maske_h: np.ndarray, oben: bool, links_ende: bool, versatz: int) -> tuple[float, float]:
        echt = [lin for lin in folge if not lin.get("ergaenzt")]
        lin = folge[0] if oben else folge[-1]
        quelle = lin if not lin.get("ergaenzt") else (min(echt, key=lambda e: e["y"]) if oben else max(echt, key=lambda e: e["y"]))
        xl, xr = _ausdehnung(maske_h, quelle)
        x = (xl if links_ende else xr) + versatz
        return x, lin["rho"] + (x - versatz) * lin["t"]

    aussen = _aussenlinien(maske, min(links[0][0]["y"], rechts[0][0]["y"]), max(links[0][-1]["y"], rechts[0][-1]["y"]), fund)
    if aussen is not None:
        def ganz(lin: dict, versatz: int) -> dict:
            return dict(lin, rho=lin["rho"] - lin["t"] * versatz)          # Linie der rechten Hälfte in Koordinaten des ganzen Bildes
        oben_l, oben_r = ganz(links[0][0], 0), ganz(rechts[0][0], halb)
        unten_l, unten_r = ganz(links[0][-1], 0), ganz(rechts[0][-1], halb)
        tl, tr = _schnitt(oben_l, aussen[0]), _schnitt(oben_r, aussen[1])
        bl, br = _schnitt(unten_l, aussen[0]), _schnitt(unten_r, aussen[1])
    else:
        tl = ende(links[0], maske[:, :halb], True, True, 0)
        bl = ende(links[0], maske[:, :halb], False, True, 0)
        tr = ende(rechts[0], maske[:, halb:], True, False, halb)
        br = ende(rechts[0], maske[:, halb:], False, False, halb)
    if min(tr[0], br[0]) - max(tl[0], bl[0]) < 0.4 * w:
        fund.hinweise.append("Die Linien sind zu kurz für eine Tabelle.")
        return fund
    fund.ecken = tuple((x / w, y / h) for x, y in (tl, tr, br, bl))
    fund.zeilen = zeilen
    ent = entzerrt(bild, fund.ecken, 1200)
    b, sp = _spalten(ent, bloecke)
    if sp is None:
        fund.hinweise.append("Die senkrechten Linien wurden nicht gefunden: Blöcke und Spalten bleiben auf der Voreinstellung.")
        fund.bloecke = bloecke or 2
    else:
        fund.bloecke, fund.spalten = b, sp
    return fund
