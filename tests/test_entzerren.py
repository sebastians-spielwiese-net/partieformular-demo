"""Raster im Foto selbst finden und Perspektive entzerren. Prüfbild: selbst gezeichnetes Formular nach der Vorlage (30 Zeilen, zwei Blöcke, Nummer, Weiß, Schwarz),
mit bekannter Perspektive in ein „Foto“ gelegt; die wahren Ecken sind bekannt."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

import pf_entzerren as Z
import pf_raster as R


def vorlage(breite=1000, hoehe=1300, zeilen=30, texte=None, ohne_oberste_linie=False, kopf=0) -> Image.Image:
    """Formular wie die Vorlage: Blöcke je Nummer (5 %), Weiß, Schwarz (Weiß|Schwarz in der Blockmitte), Linien rundum."""
    bild = Image.new("RGB", (breite, hoehe), (252, 252, 250))
    d = ImageDraw.Draw(bild)
    schrift = ImageFont.load_default(size=26)
    zh = (hoehe - kopf) / zeilen
    for b in range(2):
        x0, x1 = b * breite / 2, (b + 1) * breite / 2
        for i in range(zeilen + 1):
            if i == 0 and ohne_oberste_linie:
                continue
            y = kopf + i * zh
            d.line([(x0, y), (x1, y)], fill=(40, 40, 40), width=2)
        for a in (0.0, 0.05, 0.5):
            d.line([(x0 + a * (x1 - x0), kopf), (x0 + a * (x1 - x0), hoehe - 1)], fill=(40, 40, 40), width=2)
        d.line([(x1 - 1, kopf), (x1 - 1, hoehe - 1)], fill=(40, 40, 40), width=2)
        for i in range(zeilen):
            n = b * zeilen + i + 1
            for s, (xa, xb) in enumerate(((0.05, 0.5), (0.5, 1.0))):
                t = (texte or {}).get((n, s))
                if t:
                    d.text((x0 + (xa + 0.04) * (x1 - x0), kopf + i * zh + 6), t, fill=(30, 30, 110), font=schrift)
    return bild


def foto(form: Image.Image, viereck: list[tuple[float, float]], groesse=(1300, 1700)) -> Image.Image:
    """Legt das Formular so in ein Foto, dass seine Ecken (oben links, oben rechts, unten rechts, unten links) auf `viereck` (Pixel im Foto) liegen."""
    w, h = form.size
    koeff = Z.perspektive_koeffizienten(viereck, [(0, 0), (w, 0), (w, h), (0, h)])
    return form.transform(groesse, Image.PERSPECTIVE, koeff, Image.BICUBIC, fillcolor=(120, 110, 100))


SCHIEF = [(110, 160), (1180, 90), (1230, 1560), (60, 1500)]


def test_perspektive_bildet_die_ecken_ab():
    ziel = [(0, 0), (100, 0), (100, 60), (0, 60)]
    quelle = [(10, 5), (95, 12), (90, 70), (4, 58)]
    c = Z.perspektive_koeffizienten(ziel, quelle)
    for (x, y), (u, v) in zip(ziel, quelle):
        n = c[6] * x + c[7] * y + 1
        assert (c[0] * x + c[1] * y + c[2]) / n == pytest.approx(u, abs=1e-6) and (c[3] * x + c[4] * y + c[5]) / n == pytest.approx(v, abs=1e-6)


def test_entzerren_der_ganzen_flaeche_aendert_nichts():
    bild = vorlage(400, 300)
    e = Z.entzerrt(bild, ((0, 0), (1, 0), (1, 1), (0, 1)))
    assert e.size == (400, 300) and np.abs(np.asarray(e, dtype=int) - np.asarray(bild, dtype=int)).mean() < 2


@pytest.mark.parametrize("viereck", [SCHIEF, [(40, 60), (1250, 60), (1250, 1640), (40, 1640)], [(150, 100), (1150, 180), (1100, 1500), (100, 1650)]])
def test_findet_ecken_zeilen_und_spalten(viereck):
    form = vorlage(texte={(i, 0): "e4" for i in range(1, 31)} | {(i, 1): "e5" for i in range(1, 31)} | {(i, 0): "Nf3" for i in range(31, 61)})
    f = Z.finde_raster(foto(form, viereck))
    assert f.gefunden and f.zeilen == 30 and f.bloecke == 2 and f.linien == 31, f.hinweise
    wahr = [(x / 1300, y / 1700) for x, y in viereck]
    for (x, y), (wx, wy) in zip(f.ecken, wahr):
        assert abs(x - wx) < 0.012 and abs(y - wy) < 0.012, (f.ecken, wahr)
    nummer, weiss, schwarz = f.spalten
    assert nummer == pytest.approx(0.05, abs=0.015) and weiss == pytest.approx(0.45, abs=0.02) and schwarz == pytest.approx(0.5, abs=0.02)


def test_entzerrtes_bild_hat_gerade_zeilen():
    form = vorlage()
    ent = Z.entzerrt(foto(form, SCHIEF), Z.finde_raster(foto(form, SCHIEF)).ecken, 1000)
    z = R.zeilengrenzen(R.grau(ent)[:, :ent.width // 2], 30, True)
    erwartet = [round(i * ent.height / 30) for i in range(31)]
    assert max(abs(a - b) for a, b in zip(z, erwartet)) <= 4


def test_abgeschnittene_erste_zeile_wird_ergaenzt():
    """Das Foto beginnt mitten in der ersten Zeile: ihre obere Linie liegt außerhalb des Bildes. Es müssen trotzdem 30 Zeilen herauskommen, die obere Ecke liegt über dem Bild."""
    form = vorlage()
    f = Z.finde_raster(foto(form, [(60, -25), (1230, -25), (1230, 1650), (60, 1650)]))
    assert f.gefunden and f.zeilen == 30 and any("ergänzt" in h for h in f.hinweise), f.hinweise
    assert f.ecken[0][1] == pytest.approx(-25 / 1700, abs=0.015) and f.ecken[2][1] == pytest.approx(1650 / 1700, abs=0.012)


def test_kein_formular_wird_nicht_gefunden():
    rausch = Image.fromarray(np.random.default_rng(0).integers(100, 160, size=(900, 700, 3), dtype=np.uint8))
    f = Z.finde_raster(rausch)
    assert not f.gefunden and f.hinweise
    leer = Z.finde_raster(Image.new("RGB", (800, 600), (240, 240, 240)))
    assert not leer.gefunden


def test_raster_finden_liefert_ein_benutzbares_raster():
    texte = {(i, s): ("e4" if s == 0 else "Nf6") for i in range(1, 13) for s in (0, 1)}
    form = vorlage(texte=texte)
    raster, hinweise = R.raster_finden(foto(form, SCHIEF))
    assert raster.ecken is not None and raster.zeilen == 30 and raster.bloecke == 2 and raster.spalten[1] == pytest.approx(0.45, abs=0.02)
    paare = R.zellen(foto(form, SCHIEF), raster)
    assert len(paare) == 60
    voll = {(i + 1, s) for i, p in enumerate(paare) for s, c in enumerate(p) if not R.ist_leer(c)}
    assert voll == set(texte), sorted(voll ^ set(texte))[:6]


def test_ohne_formular_gibt_raster_finden_das_standardraster():
    raster, hinweise = R.raster_finden(Image.new("RGB", (500, 500), (250, 250, 250)))
    assert raster == R.Raster() and hinweise


def test_raster_mit_ecken_pruefung_und_vorschau():
    form = vorlage()
    bild = foto(form, SCHIEF)
    raster, _ = R.raster_finden(bild)
    v = R.vorschau(bild, raster, breite=500)
    assert v.width == 500 and v.mode == "RGB"
    assert R.zugeschnitten(bild, raster).size[0] > 800
