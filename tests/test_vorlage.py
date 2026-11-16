"""Linienformulare ohne senkrechte Linien (pf_vorlage): Prüfbild ist ein selbst gezeichnetes Ligaformular mit drei Blöcken zu 20 Zeilen, gedruckten Zeilenlinien und blasser Schrift.
Nichts davon ist ein echter Scan: Echte Formulare enthalten Namen und gehören nicht ins Repository."""
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

import pf_lesen as LS
import pf_raster as R
import pf_vorlage as V


def liga_formular(bloecke=3, zeilen=20, breite=1120, hoehe=1640, drehung=0.0, texte=None, blass=True, seed=0):
    """Gelbes Blatt, Kopfzeilen, je Block Zugnummern und je Zeile zwei aneinander stoßende Zellenlinien (Weiß, Schwarz; Schwarz leicht hinterlegt). Rückgabe: Bild und die Mitten
    der Zellen {(Zug, Spalte): (x, y)} im ungedrehten Blatt."""
    rng = np.random.default_rng(seed)
    papier = (250, 246, 190)
    bild = Image.new("RGB", (breite, hoehe), papier)
    d = ImageDraw.Draw(bild)
    schrift = ImageFont.load_default(size=40)
    zahl = ImageFont.load_default(size=26)
    linie = (150, 150, 140) if blass else (40, 40, 40)
    oben = 460
    schritt = (hoehe - 60 - oben) / zeilen
    for y in (250, 345, 400, oben):                                    # Kopfzeilen: eine lange Linie, nicht gleichmäßig mit der Tabelle
        d.line([(30, y), (1060, y)], fill=(30, 30, 30), width=3)
    pitch = 345
    mitten = {}
    for b in range(bloecke):
        x0 = 120 + b * pitch
        d.rectangle([x0 + 125, oben, x0 + 248, hoehe - 60], fill=(236, 232, 176))
        for i in range(zeilen):
            n = b * zeilen + i + 1
            y = oben + (i + 1) * schritt
            d.text((x0 - 55, y - 40), str(n), fill=(20, 20, 20), font=zahl)
            d.line([(x0, y), (x0 + 119, y)], fill=linie, width=2)
            d.line([(x0 + 125, y), (x0 + 248, y)], fill=linie, width=2)
            for spalte, xa in enumerate((x0, x0 + 125)):
                mitten[(n, spalte)] = (xa + 60, y - 30)
                t = (texte or {}).get((n, spalte))
                if t:
                    d.text((xa + 8, y - 48), t, fill=(120, 130, 100), font=schrift)
    rng.random()
    if drehung:
        bild = bild.rotate(drehung, resample=Image.BICUBIC, fillcolor=papier)
    return bild, mitten


def test_findet_drei_bloecke_zu_zwanzig_zeilen():
    bild, _ = liga_formular()
    gefunden = V.finde(bild)
    assert gefunden is not None
    raster, hinweise = gefunden
    assert (raster.bloecke, raster.zeilen) == (3, 20)
    assert raster.spaltenlage is not None and len(raster.spaltenlage) == 3 and len(raster.zeilenlinien) == 21
    assert not raster.bereinigen and not raster.einrasten
    assert "3 Blöcke zu 20 Zeilen" in hinweise[0]


def test_zellen_liegen_um_die_gezeichneten_mitten():
    bild, mitten = liga_formular()
    raster, _ = V.finde(bild)
    boxen = R.zellboxen(*bild.size, raster)
    assert len(boxen) == 60
    for n in (1, 7, 20, 21, 33, 40, 41, 60):
        for spalte in (0, 1):
            a, b, c, d = boxen[n - 1][spalte]
            x, y = mitten[(n, spalte)]
            assert a - 6 <= x <= c + 6 and b - 6 <= y <= d + 6, (n, spalte, (a, b, c, d), (x, y))


@pytest.mark.parametrize("winkel", [-1.0, 0.0, 0.8])
def test_leichte_drehung_wird_ausgeglichen(winkel):
    bild, _ = liga_formular(drehung=winkel)
    gefunden = V.finde(bild)
    assert gefunden is not None
    raster, _ = gefunden
    assert (raster.bloecke, raster.zeilen) == (3, 20) and abs(raster.drehung + winkel) <= 0.6


def test_zwei_bloecke_und_andere_zeilenzahl():
    bild, _ = liga_formular(bloecke=2, zeilen=30)
    raster, _ = V.finde(bild)
    assert (raster.bloecke, raster.zeilen) == (2, 30)


def test_kein_formular_ergibt_none():
    assert V.finde(Image.new("RGB", (800, 1100), (250, 246, 190))) is None
    zufall = Image.fromarray(np.random.default_rng(3).integers(0, 255, (600, 500, 3), dtype=np.uint8))
    assert V.finde(zufall) is None


def test_raster_finden_nimmt_den_linienweg_ohne_senkrechte_linien():
    bild, _ = liga_formular()
    raster, hinweise = R.raster_finden(bild, 30)
    assert raster.spaltenlage is not None and (raster.bloecke, raster.zeilen) == (3, 20)


def test_raster_prueft_zusammengehoerende_felder():
    with pytest.raises(ValueError):
        R.Raster(spaltenlage=((0.1, 0.2, 0.2, 0.3),)).pruefe()                                   # Zeilenlinien fehlen
    with pytest.raises(ValueError):
        R.Raster(zeilen=2, bloecke=1, spaltenlage=((0.1, 0.2, 0.2, 0.3),), zeilenlinien=(0.1, 0.2)).pruefe()   # zu wenige Linien


def test_bereinigung_hebt_blasse_schrift_auf_vollen_kontrast_und_entfernt_die_linie():
    zelle = Image.new("L", (130, 60), 235)
    d = ImageDraw.Draw(zelle)
    d.line([(0, 57), (130, 57)], fill=60, width=2)                                              # gedruckte Linie
    d.text((20, 10), "e4", fill=205, font=ImageFont.load_default(size=36))                      # blasser Strich, kaum dunkler als das Papier
    sauber = np.asarray(R.bereinige_zelle(zelle, aufrichten=False))
    assert sauber[:50].min() < 40, "Schrift ist nach der Bereinigung kräftig"
    assert sauber[55:].min() > 200, "die gedruckte Linie ist gelöscht"
    assert R.ist_leer(zelle) is False and R.ist_leer(R.bereinige_zelle(Image.new("L", (130, 60), 235))) is True


def test_schraege_wird_geschaetzt_und_aufgerichtet():
    tinte = np.zeros((60, 120))
    for x in (30, 60, 90):                                                                       # senkrechte Striche, um 20 Grad geneigt
        for y in range(60):
            tinte[y, int(x + (30 - y) * np.tan(np.radians(20)))] = 1.0
    winkel = R._scheren(tinte, 0.0)
    assert abs(R.schraege_schaetzen(tinte)) > 10                                                 # eine deutliche Neigung wird erkannt
    assert winkel.shape[0] == 60


def test_dekodiere_findet_die_legale_partie_aus_unsicheren_zellen():
    """Zellen, deren Bild nur grob zum Zug passt (der Wahre bekommt die höchste, aber keine eindeutige Wahrscheinlichkeit), ergeben die Partie, wenn die Folge legal sein muss."""
    import pf_ctc as C

    partie = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]
    zellen = []
    for ply, san in enumerate(partie):
        logp = np.full((8, len(C.ZEICHEN)), -9.0)
        for t, ziffer in enumerate(C.kodiere(san)[:8]):
            logp[t, ziffer] = -0.3
        for t in range(len(C.kodiere(san)), 8):
            logp[t, 0] = -0.1
        zellen.append(LS.ZellLesung(ply, False, san, logp))
    ent = LS.dekodiere(LS.FormularLesung(zellen), strahl=50)
    assert [e.san for e in ent] == partie
    assert all(0.0 < e.wahrscheinlichkeit <= 1.0 for e in ent)


def test_dekodiere_behaelt_das_matt_auch_wenn_danach_eine_leere_aussehende_zelle_folgt():
    """Eine Zelle nach dem Matt (Rauschen, ein Strich) darf die richtige Partie nicht aus dem Rennen werfen: Die beendete Partie zahlt nur, was die Zelle als leer unwahrscheinlich ist."""
    import pf_ctc as C

    partie = ["f3", "e5", "g4", "Qh4#"]
    zellen = []
    for ply, san in enumerate(partie + [""]):
        logp = np.full((8, len(C.ZEICHEN)), -9.0)
        ziffern = C.kodiere(san)[:8] if san else []
        for t, ziffer in enumerate(ziffern):
            logp[t, ziffer] = -0.3
        for t in range(len(ziffern), 8):
            logp[t, 0] = -0.1
        zellen.append(LS.ZellLesung(ply, False, san, logp))
    ent = LS.dekodiere(LS.FormularLesung(zellen), strahl=50)
    assert [e.san for e in ent] == partie


def _zelle(ply, san, alternativ=None, breite=10):
    """Zellbild als Verteilung: Zeichen von `san`; steht `alternativ` daneben, teilen sich beide Schreibweisen jede abweichende Stelle zur Hälfte."""
    import pf_ctc as C

    a = C.kodiere(san)
    b = C.kodiere(alternativ) if alternativ else a
    logp = np.full((breite, len(C.ZEICHEN)), -9.0)
    for t in range(breite):
        if t < len(a):
            if a[t] == b[t]:
                logp[t, a[t]] = -0.05
            else:
                logp[t, a[t]] = logp[t, b[t]] = -0.7
        else:
            logp[t, 0] = -0.05
    return LS.ZellLesung(ply, False, san, logp)


PARTIE = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"]


def _lesung_mit_zweifel():
    zellen = [_zelle(i, s) for i, s in enumerate(PARTIE)]
    zellen[3] = _zelle(3, "Nc6", "Nf6")                          # Zelle 3: das Bild kann Nc6 oder Nf6 sein
    return LS.FormularLesung(zellen)


def test_unsichere_zelle_wird_markiert_sichere_nicht():
    ent = LS.dekodiere(_lesung_mit_zweifel(), strahl=50)
    assert [e.unsicher() for e in ent] == [False, False, False, True, False, False]
    assert ent[3].zellanteil == pytest.approx(0.5, abs=0.05) and ent[3].bild_alternativen[0][0] in ("Nf6", "Nc6")
    assert all(e.zellanteil > 0.95 for i, e in enumerate(ent) if i != 3)


def test_passt_schlecht_wenn_der_zug_nicht_zum_bild_passt():
    partie = ["e4", "e6", "Qh5", "Nc6", "Qxe5+"]                  # Zelle 1 zeigt e6, aber Qxe5+ gibt es nur, wenn Schwarz e5 gezogen hat
    zellen = [_zelle(i, s) for i, s in enumerate(partie)]
    ent = LS.dekodiere(LS.FormularLesung(zellen), strahl=50, strafdeckel=2.0)
    assert ent[1].san == "e5" and ent[1].passt_schlecht() and not ent[0].passt_schlecht()


def test_bestaetigte_zelle_entscheidet_und_der_rest_folgt():
    les = _lesung_mit_zweifel()
    ent = LS.dekodiere(les, strahl=50, fest={3: "Sf6"})            # deutsche Schreibweise, wie sie auf dem Formular steht
    assert [e.san for e in ent][3] == "Nf6"
    assert not ent[3].unsicher() or ent[3].zellanteil < 0.95       # die Zelle selbst bleibt im Ergebnis, sie wird nur nicht mehr als Zweifel gezeigt (das macht die App)


def test_nachsuche_mit_gedaechtnis_gibt_dasselbe_wie_eine_neue_suche():
    les = _lesung_mit_zweifel()
    d = LS.Dekodierer(les, strahl=50)
    erste = [e.san for e in d.lauf()]
    zweite = [e.san for e in d.lauf({3: "Nf6"})]
    frisch = [e.san for e in LS.dekodiere(les, strahl=50, fest={3: "Nf6"})]
    assert zweite == frisch and zweite[3] == "Nf6" and erste[:3] == zweite[:3]
    assert len(d.strahlen) == len(PARTIE) + 1
    zurueck = [e.san for e in d.lauf({})]                          # Bestätigung wieder weg: wie die erste Suche
    assert zurueck == erste


def test_bestaetigte_zelle_ohne_passenden_zug_meldet_scheitern():
    d = LS.Dekodierer(_lesung_mit_zweifel(), strahl=50)
    d.lauf({2: "Sc3"})                                             # nach 1. e4 e5 geht Sc3, nach 3. ... aber Nf3 verlangen die Folgezellen nicht: lauf bleibt gültig
    assert d.gescheitert is None
    d.lauf({0: "Dh5"})                                             # im ersten Zug gibt es kein Dh5
    assert d.gescheitert == 0


def test_folgefehler_zone():
    assert LS.folgefehler_ab([False] * 20) is None
    assert LS.folgefehler_ab([False] * 5 + [True] * 10) == 5       # Beginn der Kette = erste unsichere Zelle
    einzeln = [False, True, False, False, True, False, False, False, False, False]
    assert LS.folgefehler_ab(einzeln) is None                      # einzelne Zweifel sind keine Kette
    assert LS.folgefehler_ab([True, True, True]) is None           # zu wenige Zellen, um von einer Kette zu sprechen
