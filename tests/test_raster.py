"""Zellen schneiden: Geometrie, Einrasten auf Linien, Geraderichten, leere Zellen, Modelleingabe. Prüfbild: selbst gezeichnetes Formular mit Pillow."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

import pf_raster as R


def formular(zeilen=30, bloecke=2, breite=900, hoehe=1200, jitter=0, texte=None, seed=0, kopf=0) -> tuple[Image.Image, list[list[int]]]:
    """Weißes Blatt mit gedruckten Linien (Zeilen und Spalten); texte: {(Zug ab 1, Spalte 0/1): Text}. Gibt auch die gezeichneten y-Werte der Linien je Block zurück."""
    rng = np.random.default_rng(seed)
    bild = Image.new("RGB", (breite, hoehe), (255, 255, 255))
    d = ImageDraw.Draw(bild)
    schrift = ImageFont.load_default(size=30)
    ys_je_block = []
    for b in range(bloecke):
        x0, x1 = round(b * breite / bloecke), round((b + 1) * breite / bloecke)
        zeilenhoehe = (hoehe - kopf) / zeilen
        ys = [round(kopf + i * zeilenhoehe + (rng.integers(-jitter, jitter + 1) if 0 < i < zeilen and jitter else 0)) for i in range(zeilen + 1)]
        ys_je_block.append(ys)
        for y in ys:
            d.line([(x0, min(y, hoehe - 1)), (x1, min(y, hoehe - 1))], fill=(40, 40, 40), width=2)
        for a in (0.10, 0.55):
            d.line([(x0 + a * (x1 - x0), 0), (x0 + a * (x1 - x0), hoehe)], fill=(40, 40, 40), width=2)
        for i in range(zeilen):
            n = b * zeilen + i + 1
            for spalte, (xa, xb) in enumerate(((0.10, 0.55), (0.55, 1.0))):
                t = (texte or {}).get((n, spalte))
                if t:
                    d.text((x0 + (xa + 0.05) * (x1 - x0), ys[i] + 8), t, fill=(30, 30, 90), font=schrift)
    return bild, ys_je_block


def test_zellboxen_geometrie():
    r = R.Raster(zeilen=30, bloecke=2)
    boxen = R.zellboxen(900, 1200, r)
    assert len(boxen) == 60 and all(len(p) == 2 for p in boxen)
    w1, s1 = boxen[0]
    w31, s31 = boxen[30]
    assert w1[0] < w1[2] <= s1[0] < s1[2] and w1[1] == s1[1] == 0 and w1[3] - w1[1] == 40
    assert w31[0] >= 450 and s31[2] == 900 and w31[1] == 0              # Zug 31 steht oben im zweiten Block
    assert boxen[29][1][3] == 1200 and boxen[59][1][3] == 1200
    assert len(R.zellboxen(900, 1200, R.Raster(zeilen=20, bloecke=1))) == 20
    spalten = R.zellboxen(1000, 100, R.Raster(zeilen=1, bloecke=1, spalten=(1, 2, 2)))[0]
    assert spalten[0][0] == 200 and spalten[0][2] == spalten[1][0] == 600 and spalten[1][2] == 1000       # Anteile werden normiert


def test_raster_pruefung():
    for falsch in (R.Raster(links=0.6, rechts=0.5), R.Raster(zeilen=0), R.Raster(spalten=(0.1, 0.5)), R.Raster(oben=-0.1)):
        with pytest.raises(ValueError):
            falsch.pruefe()


def test_zeilengrenzen_rasten_auf_linien_ein():
    bild, ys = formular(zeilen=30, bloecke=1, jitter=5, seed=3, texte={(i, 0): "e4" for i in range(1, 31)})
    g = R.grau(bild)
    gefunden = R.zeilengrenzen(g, 30, True)
    fehler = [abs(a - b) for a, b in zip(gefunden[1:-1], ys[0][1:-1])]
    gleich = R.zeilengrenzen(g, 30, False)
    fehler_gleich = [abs(a - b) for a, b in zip(gleich[1:-1], ys[0][1:-1])]
    assert max(fehler) <= 2 and np.mean(fehler) < np.mean(fehler_gleich)
    assert gefunden[0] == 0 and gefunden[-1] == g.shape[0] and all(b > a for a, b in zip(gefunden, gefunden[1:]))


def test_zeilengrenzen_ohne_linien_gleichmaessig():
    leer = np.full((600, 300), 240, dtype=np.uint8)
    assert R.zeilengrenzen(leer, 20, True) == R.zeilengrenzen(leer, 20, False) == [round(i * 30) for i in range(21)]


def test_zellen_anzahl_und_leere():
    bild, _ = formular(texte={(1, 0): "e4", (1, 1): "e5", (2, 0): "Nf3", (31, 0): "Qd1", (60, 1): "Kh8"})
    z = R.zellen(bild, R.Raster())
    assert len(z) == 60
    voll = {(i + 1, s) for i, p in enumerate(z) for s, c in enumerate(p) if not R.ist_leer(c)}
    assert voll == {(1, 0), (1, 1), (2, 0), (31, 0), (60, 1)}


def test_leere_zelle_mit_linien_ist_leer():
    z = Image.new("L", (300, 40), 235)
    d = ImageDraw.Draw(z)
    d.line([(0, 1), (300, 1)], fill=60, width=2)
    d.line([(0, 38), (300, 38)], fill=60, width=2)
    d.line([(298, 0), (298, 40)], fill=60, width=2)
    assert R.ist_leer(z)
    d.text((60, 6), "Sf3", fill=70, font=ImageFont.load_default(size=26))
    assert not R.ist_leer(z)


def test_geraderichten():
    bild, _ = formular(texte={(i, 0): "e4" for i in range(1, 31)})
    for winkel in (-3.0, -1.5, 2.0, 4.0):
        schief = bild.rotate(winkel, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
        assert abs(R.schaetze_drehung(schief) - (-winkel)) <= 0.5, winkel
    assert R.schaetze_drehung(bild) == 0.0
    assert R.schaetze_drehung(Image.new("RGB", (400, 400), (250, 250, 250))) == 0.0


def test_vorschau_hat_die_groesse_des_ausschnitts():
    bild, _ = formular()
    v = R.vorschau(bild, R.Raster(oben=0.1, unten=0.9), breite=450)
    assert v.size == (450, round(1200 * 0.8 * 0.5)) and v.mode == "RGB"


def test_modell_eingabe_form_und_werte():
    zelle = Image.new("L", (400, 80), 235)
    d = ImageDraw.Draw(zelle)
    d.line([(0, 2), (400, 2)], fill=60, width=2)
    d.text((150, 20), "Nf3", fill=50, font=ImageFont.load_default(size=40))
    x = R.modell_eingabe(zelle)
    assert x.shape == (1, 1, 64, 256) and x.dtype == np.float32 and -1.0 <= x.min() < 0 and x.max() == pytest.approx(1.0)
    spalten = np.where((x[0, 0] < 0.0).any(axis=0))[0]
    assert abs((spalten[0] + spalten[-1]) / 2 - 128) < 40                  # Schrift liegt mittig
    leer = R.modell_eingabe(Image.new("L", (400, 80), 240))
    assert leer.shape == (1, 1, 64, 256) and leer.min() > 0.85
    assert R.modell_eingabe(Image.new("L", (2, 2), 0)).shape == (1, 1, 64, 256)


def test_otsu():
    g = np.concatenate([np.full(500, 40, dtype=np.uint8), np.full(500, 200, dtype=np.uint8)]).reshape(10, 100)
    assert 40 <= R.otsu(g) < 200
