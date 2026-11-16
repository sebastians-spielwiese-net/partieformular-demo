"""Formulare mit gedruckten Zeilenlinien, aber ohne senkrechte Linien finden (Pillow und numpy).

Viele Ligaformulare haben keine Tabellenränder: Zu jeder Zelle gehört nur eine gedruckte Linie unter der Schrift, Weiß und Schwarz stehen nebeneinander (Schwarz oft hinterlegt),
und drei Blöcke zu je 20 Zügen füllen die Seite. Der Raster-Finder `pf_entzerren` sucht senkrechte Linien und scheitert hier. Dieses Modul liest die Struktur aus den Zeilenlinien:

1. Das Bild wird gerade gerichtet (`pf_raster.schaetze_drehung`).
2. Waagerechte Linien: Pixelzeilen mit einem langen dunklen Lauf; gleichmäßig verteilte Linien ergeben die Zeilen.
3. Spalten: Auf jeder Zeilenlinie stehen kurze Linienstücke, eines je Zelle. Stücke gleicher Lage bilden eine Spalte; zwei benachbarte Spalten sind Weiß und Schwarz eines Blocks.

Das Ergebnis ist ein `Raster` mit `zeilenlinien` und `spaltenlage`, die genau diese Lage festhalten (Blöcke dürfen Abstand haben, Zeilenlinien liegen, wo sie gedruckt sind).
`bereinigen` bleibt aus: Die Zellbereinigung (`pf_raster.bereinige_zelle`: Papierton abziehen, Linien löschen, Schrift aufrichten) verbesserte das Lesen mit dem jetzigen Modell nicht
(Beispielscan, 95 Zellen: ohne Bereinigung 15 exakt gelesen und der wahre Zug bei 71 % auf Rang 1, mit Papier und Linien 13 bis 14, mit allem 10 und 53 %).
"""
from __future__ import annotations

import numpy as np
from PIL import Image

import pf_raster as R
from pf_entzerren import tinte

MIN_ZEILEN = 8
MIN_LAUF_ANTEIL = 0.05          # Anteil der Bildbreite, den ein Lauf mindestens haben muss, um zur Zeilenlinie zu zählen (eine Zellenlinie ist etwa 11 % breit)
LAUF_TOLERANZ = 12              # Pixel: Abstand, bis zu dem Stücke gleicher Spalte zusammengehören


def _laeufe(zeile: np.ndarray, mindest: int) -> list[tuple[int, int]]:
    """Läufe von True (x0, x1) mit mindestens `mindest` Pixeln; Lücken bis zwei Pixel werden überbrückt."""
    z = zeile.astype(np.int8)
    d = np.diff(np.concatenate(([0], z, [0])))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0] - 1
    out: list[tuple[int, int]] = []
    for a, b in zip(starts, ends):
        if out and a - out[-1][1] <= 3:
            out[-1] = (out[-1][0], int(b))
        else:
            out.append((int(a), int(b)))
    return [(a, b) for a, b in out if b - a + 1 >= mindest]


def zeilenlinien_finden(maske: np.ndarray) -> list[tuple[float, list[tuple[int, int]]]]:
    """Waagerechte Linien als (y-Mitte, Linienstücke) von oben nach unten: Pixelzeilen mit mindestens einem Lauf von 5 % der Bildbreite, in Gruppen zusammengefasst.
    Die Stücke (x0, x1) stammen aus der Pixelzeile der Gruppe mit den meisten Stücken."""
    h, w = maske.shape
    mindest = max(40, int(MIN_LAUF_ANTEIL * w))
    gruppen: list[list[int]] = []
    laeufe = {}
    for y in range(h):
        stuecke = _laeufe(maske[y], mindest)
        if stuecke:
            laeufe[y] = stuecke
            if gruppen and y - gruppen[-1][-1] <= 3:
                gruppen[-1].append(y)
            else:
                gruppen.append([y])
    out = []
    for g in gruppen:
        beste = max(g, key=lambda y: len(laeufe[y]))
        out.append((float(np.mean(g)), laeufe[beste]))
    return out


def gleichmaessige_folge(ys: list[float], toleranz: float = 0.07, mindest: int = MIN_ZEILEN) -> list[float]:
    """Die längste Folge gleich weit voneinander entfernter Linien (Schritt p, jede Linie höchstens `toleranz` * p neben dem erwarteten Ort)."""
    bester: list[float] = []
    n = len(ys)
    for i in range(n - 1):
        for j in range(i + 1, min(n, i + 6)):
            p = ys[j] - ys[i]
            if p < 12:
                continue
            folge = [ys[i]]
            erwartet = ys[i]
            while True:
                erwartet += p
                nah = [y for y in ys if abs(y - erwartet) <= toleranz * p]
                if not nah:
                    break
                y = min(nah, key=lambda v: abs(v - erwartet))
                folge.append(y)
                erwartet = y
                p = (folge[-1] - folge[0]) / (len(folge) - 1)
            if len(folge) > len(bester):
                bester = folge
    return bester if len(bester) >= mindest else []


def _spaltenenden(maske: np.ndarray, linien: list[float]) -> list[float]:
    """Rechte Enden der Linienstücke auf den Zeilenlinien, zu Spalten zusammengefasst (x1 je Spalte). Das rechte Ende bleibt an jeder Zeile gleich; der Anfang einer blassen Linie
    reißt dort ab, wo Schrift darüber liegt, und ein Strich über Weiß und Schwarz hat gar keine Lücke dazwischen. Gebraucht werden Enden auf mindestens einem Viertel der Linien."""
    h, w = maske.shape
    mindest = max(30, int(0.04 * w))
    enden: list[int] = []
    for y in linien:
        yi = int(round(y))
        band = maske[max(0, yi - 4):yi + 5].any(axis=0)
        enden += [b for _, b in _laeufe(band, mindest)]
    cluster: list[list[int]] = []
    for e in sorted(enden):
        if cluster and e - cluster[-1][-1] <= 0.7 * LAUF_TOLERANZ:
            cluster[-1].append(e)
        else:
            cluster.append([e])
    return [float(np.median(c)) for c in cluster if len(c) >= max(3, 0.25 * len(linien))]


def _bloecke(enden: list[float]) -> tuple[list[tuple[float, float]], float]:
    """Weiß und Schwarz eines Blocks sind zwei Spalten im Abstand einer Zellenbreite (die kleinste Differenz benachbarter Enden). Rückgabe: Paare (Ende Weiß, Ende Schwarz) und die Zellenbreite."""
    if len(enden) < 2:
        return [], 0.0
    diffs = [b - a for a, b in zip(enden, enden[1:])]
    pitch = min(diffs)
    paare = []
    i = 0
    while i < len(enden) - 1:
        if abs((enden[i + 1] - enden[i]) - pitch) <= 0.2 * pitch:
            paare.append((enden[i], enden[i + 1]))
            i += 2
        else:
            i += 1
    return paare, pitch


def finde(bild: Image.Image) -> tuple[R.Raster, list[str]] | None:
    """Raster eines Linienformulars (siehe Modul), oder None, wenn die Struktur nicht passt. Das Bild wird mit der geschätzten Drehung gerade gerichtet;
    das Raster gilt für `R.zugeschnitten(bild, raster)`, also für das gedrehte Bild."""
    hinweise: list[str] = []
    dreh = R.schaetze_drehung(bild)
    raster0 = R.Raster(drehung=dreh)
    gerade = R.zugeschnitten(bild, raster0)
    maske = tinte(gerade)
    h, w = maske.shape
    linien = zeilenlinien_finden(maske)
    if not linien:
        return None
    meiste = max(len(s) for _, s in linien)
    tabelle = [(y, s) for y, s in linien if len(s) >= max(4, 0.6 * meiste)]            # Zeilen der Tabelle: viele Stücke nebeneinander; Kopflinien haben ein oder zwei
    folge = gleichmaessige_folge([y for y, _ in tabelle])
    if not folge:
        return None
    bloecke, pitch = _bloecke(_spaltenenden(maske, folge))
    if not bloecke or len(bloecke) > 4 or pitch < 0.04 * w:
        return None
    schritt = (folge[-1] - folge[0]) / (len(folge) - 1)
    zeilen = len(folge)                                                                   # jede Tabellenlinie ist die Linie unter einer Zeile
    zeilen_ys = [folge[0] - schritt] + folge
    if zeilen < MIN_ZEILEN:
        return None
    lage = tuple(((ew - pitch + 3) / w, (ew - 1) / w, (es - pitch + 3) / w, (es - 1) / w) for ew, es in bloecke)
    linien = tuple(y / h for y in zeilen_ys)
    hinweise.append(f"Formular mit Zeilenlinien erkannt: {len(bloecke)} Blöcke zu {zeilen} Zeilen, Drehung {dreh:+.2f}°.")
    raster = R.Raster(drehung=dreh, zeilen=zeilen, bloecke=len(bloecke), einrasten=False, spaltenlage=lage, zeilenlinien=linien, bereinigen=False)
    return raster, hinweise
