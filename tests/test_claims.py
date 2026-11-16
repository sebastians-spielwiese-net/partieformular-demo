"""Jede Zahl der README steht hier: Tabellen werden aus data/messung.json und der Prüfung neu gebildet und zeilenweise in der README gesucht."""
import json
import sys
from pathlib import Path

import pf_brett as B
import pf_constants as C
import pf_pruefung as P

WURZEL = Path(__file__).resolve().parent.parent
README = (WURZEL / "README.md").read_text(encoding="utf-8")
M = json.loads((WURZEL / "data" / "messung.json").read_text(encoding="utf-8"))


def pct(a: int, b: int) -> str:
    return f"{100 * a / b:.1f} %".replace(".", ",")


def zahl(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def mittel(summe: int, n: int) -> str:
    return f"{summe / n:.1f}".replace(".", ",")


def zeile_unklar(name: str, d: dict) -> str:
    n = d["versuche"]
    return (f"| {name} | {n} | {d['unklar']} | {d['ohne_gleichstand']} ({pct(d['ohne_gleichstand'], n)}) | {d['ohne_gleichstand_richtig']} von {d['ohne_gleichstand']} | "
            f"{d['gleichstand']} ({pct(d['gleichstand'], n)}) | {mittel(d['gleichstand_kandidaten_summe'], d['gleichstand'])} | {d['wahrer_unter_kandidaten']} ({pct(d['wahrer_unter_kandidaten'], n)}) |")


def test_messung_ist_in_sich_stimmig():
    assert M["partien"] == 300 and M["mindestlaenge"] == 24
    for k in ("zusatz", "zeichen", "luecke"):
        d = M[k]
        assert d["unklar"] <= d["versuche"] and d["ohne_gleichstand"] + d["gleichstand"] == d["unklar"]
        assert d["ohne_gleichstand_richtig"] == d["ohne_gleichstand"], k       # ohne Gleichstand ist der erste Kandidat jedes Mal der wahre Zug
        assert d["gleichstand_wahrer_dabei"] <= d["gleichstand"] and d["wahrer_unter_kandidaten"] <= d["unklar"]
    assert M["zeichen"]["eindeutig"] + M["zeichen"]["mehrere"] == M["zeichen"]["unklar"] and M["zeichen"]["regelverstoss"] == 0


def test_tabelle_unklar_steht_in_der_readme():
    for name, k in (("Zusatz weggelassen (`Nbd7` → `Nd7`)", "zusatz"), ("ein Zeichen durch `?` ersetzt", "zeichen"), ("Zelle leer gelassen", "luecke")):
        assert zeile_unklar(name, M[k]) in README, k


def test_tabelle_regelverstoesse_steht_in_der_readme():
    e, zf, fr = M["erfunden"], M["zielfeld"], M["frueher"]
    zeilen = [
        f"| erfundene Figur-Feld-Angabe, die nicht geht | {e['versuche']} | {e['als_regelverstoss']} ({pct(e['als_regelverstoss'], e['versuche'])}) als Regelverstoß | "
        f"alle {e['vorschlaege_geprueft']} Vorschläge sind legale Züge |",
        f"| Ziellinie eines wahren Zugs um eins verschoben | {zf['versuche']} | {zf['regelverstoss']} ({pct(zf['regelverstoss'], zf['versuche'])}) als Regelverstoß | "
        f"in allen {zf['wahrer_unter_vorschlaegen']} steht der wahre Zug unter den Vorschlägen; in den übrigen {zf['versuche'] - zf['regelverstoss']} war der verschobene Zug selbst legal und ist nicht erkennbar |",
        f"| früherer Zug durch einen anderen legalen Zug derselben Figurenart ersetzt | {fr['versuche']} | {fr['spaeter_regelverstoss']} ({pct(fr['spaeter_regelverstoss'], fr['versuche'])}) später als Regelverstoß, "
        f"davon {fr['davon_im_fenster']} ({pct(fr['davon_im_fenster'], fr['spaeter_regelverstoss'])}) höchstens {P.FRUEHER_FENSTER} Halbzüge nach der Ursache | "
        f"in {fr['frueher_genannt']} dieser {fr['davon_im_fenster']} ({pct(fr['frueher_genannt'], fr['davon_im_fenster'])}) nennt die App die frühere Zelle mit dem wahren Zug |",
    ]
    for z in zeilen:
        assert z in README, z
    assert e["als_regelverstoss"] == e["versuche"] and e["vorschlaege_legal"] == e["vorschlaege_geprueft"] and zf["wahrer_unter_vorschlaegen"] == zf["regelverstoss"]


def test_saetze_mit_zahlen():
    fr, lk, c, zf = M["frueher"], M["luecke"], M["zeichen"], M["zielfeld"]
    assert f"{fr['spaeter_regelverstoss'] - fr['davon_im_fenster']} der {fr['spaeter_regelverstoss']} Verstöße zeigten sich später" in README
    assert f"in den {lk['unklar'] - lk['wahrer_unter_kandidaten']} Fällen ohne den wahren Zug" in README
    assert f"{c['eindeutig']} der {c['unklar']} Fälle" in README
    assert f"300 Zufallspartien (Zufalls-Seeds 0 bis {M['partien'] - 1}, mindestens {M['mindestlaenge']} Halbzüge" in README
    assert "zehn Halbzügen davor" in README and P.FRUEHER_FENSTER == 10
    assert zf["versuche"] - zf["regelverstoss"] == 29


def perft(st: B.Stellung, tiefe: int) -> int:
    zuege = st.legale_zuege()
    return len(zuege) if tiefe == 1 else sum(perft(st.ausfuehren(z), tiefe - 1) for z in zuege)


def test_perft_tabelle_steht_in_der_readme():
    sys.path.insert(0, str(WURZEL / "tests"))
    import test_brett as T
    namen = {"Grundstellung": "Grundstellung", "Kiwipete": "Kiwipete", "Stellung 3": "Stellung 3", "Stellung 4": "Stellung 4", "Stellung 5": "Stellung 5", "Stellung 6": "Stellung 6"}
    for name, fen, soll in T.PERFT:
        st = B.Stellung.aus_fen(fen)
        werte = [perft(st, d) for d in (1, 2, 3)]
        assert werte == soll, name
        assert f"| {namen[name]} | " + " | ".join(zahl(w) for w in werte) + " |" in README, name


def test_beispieltabelle_steht_in_der_readme():
    falle = {
        "Saubere Partie": "Opernpartie (Morphy, Paris 1858) in deutscher Schreibweise, alles in Ordnung",
        "Unscharf geschrieben": "dieselbe Partie mit `e2-e4`, `d:e5`, fehlendem x und +, und `Sd7` bei zwei Springern",
        "Unleserliches Zeichen": "Légals Mattfalle mit `Lg?`, `L?7+` und einem ganz unleserlichen 4. Zug von Schwarz",
        "Regelverstoß": "3. Zug von Schwarz lässt den König im Schach",
        "Fehler früher": "`0-0` statt `0-0-0` im 12. Zug, der Verstoß zeigt sich erst im 13.",
        "Zug nach dem Matt": "nach dem Matt von Schwarz steht noch ein Zug",
    }
    for name, text in falle.items():
        z = P.pruefe(C.PRESETS[name]["Zeilen"]).zaehlen()
        gesamt = sum(z.values())
        gegen = z["illegal"] + z["nach_ende"]
        zeile = f"| {name} | {text} | {gesamt} | {z['ok']} | {z['hinweis']} | {z['unklar']} | {gegen} | {z['nicht_pruefbar']} |"
        assert zeile in README, zeile
    assert set(falle) == set(C.PRESETS) - {"Leeres Formular"}


def test_stichprobe_der_messung_ist_reproduzierbar():
    """Die ersten 40 Partien der Messung ergeben jedes Mal dieselben Zahlen: Zufalls-Seeds, Regeln und Reihenfolge der Kandidaten sind deterministisch."""
    sys.path.insert(0, str(WURZEL / "tools"))
    import messung
    soll = json.loads((WURZEL / "data" / "messung_stichprobe.json").read_text(encoding="utf-8"))
    assert messung.messe(soll["partien"]) == soll


def test_foto_lesen_zahlen_der_readme():
    import pytest

    import pf_ctc
    import pf_erkenner as E
    import pf_lesen
    import pf_raster
    h = json.loads((WURZEL / "data" / "hcs_beschriftungen.json").read_text(encoding="utf-8"))
    assert f"nur {h['voll_legal']} von {h['blaetter']} Blättern vollständig regelkonform" in README
    assert f"{zahl(h['legaler_anfang'])} von {zahl(h['halbzuege'])} Halbzügen ({pct(h['legaler_anfang'], h['halbzuege'])})" in README
    assert h["voll_legal"] <= h["blaetter"] and h["legaler_anfang"] <= h["halbzuege"]
    assert f"Sicherheit unter {str(pf_lesen.SCHWELLE_ZEICHEN).replace('.', ',')}" in README
    assert f"{zahl(E.MODELL_BYTES)} Bytes" in README and f"{len(pf_ctc.ZEICHEN)} Klassen" in README
    assert f"{pf_raster.MODELL_HOEHE}×{pf_raster.MODELL_BREITE} Pixel" in README
    dl = WURZEL.parent / "_daten_spielwiese" / "hcs" / "dl"
    if (dl / "config.sjon").exists():                  # nur auf dem Rechner mit den heruntergeladenen Daten
        import pyarrow.parquet as pq
        konfig = json.loads((dl / "config.sjon").read_text(encoding="utf-8"))
        assert f"{konfig['performance']['move_recognition_accuracy'] * 100:.1f} %".replace(".", ",") in README
        zugbilder = sum(pq.ParquetFile(dl / f"train-0000{i}-of-00002.parquet").metadata.num_rows for i in (0, 1))
        assert f"{zahl(zugbilder)} Zugbilder" in README
        assert pq.ParquetFile(dl / "unprocessed-00000.parquet").metadata.num_rows == h["blaetter"] == 206
        assert pf_ctc.ZEICHEN_ORIGINAL == konfig["charset"]
        assert E.sha256(dl / "chess_ocr.onnx") == E.ORIGINAL_SHA256 and (dl / "chess_ocr.onnx").stat().st_size == E.ORIGINAL_BYTES
    else:
        pytest.skip("Datensatz liegt nur lokal")


def test_messung_echtes_modell_steht_in_der_readme():
    def lade(name):
        return json.loads((WURZEL / "data" / f"{name}.json").read_text(encoding="utf-8"))
    z, a60, a20 = lade("hcs_messung_zellen"), lade("hcs_messung_blaetter_auto60"), lade("hcs_messung_blaetter_auto20")
    suche, fest = lade("hcs_messung_blaetter"), lade("hcs_messung_blaetter_ohne_suche")
    assert z["erkenner"] == a60["erkenner"] == a20["erkenner"] == suche["erkenner"] == fest["erkenner"] == "onnx"
    assert a60["raster_automatisch"] and a20["raster_automatisch"] and suche["rastersuche"] and not fest["rastersuche"] and not fest.get("raster_automatisch", False)
    richtig = round(z["mra"] * z["zellen"])
    assert abs(richtig / z["zellen"] - z["mra"]) < 1e-9
    assert f"die ersten {z['zellen']} Zellen des Datensatzes, gieriger Text gegen die Beschriftung: {pct(richtig, z['zellen'])} der Zellen ganz richtig, Zeichenfehlerrate 0,22 %" in README
    assert f"{100 * z['cer']:.2f}".replace(".", ",") == "0,22"
    n = a60["halbzuege"]
    zeilen = [f"| Text des Erkenners allein | {a60['roh_richtig']} ({pct(a60['roh_richtig'], n)}) | | | |",
              f"| Text mit Regelprüfung | {a60['basis_richtig']} ({pct(a60['basis_richtig'], n)}) | {a60['basis_still_falsch']} ({pct(a60['basis_still_falsch'], n)}) | {a60['basis_unklar']} | {a60['basis_nicht_pruefbar']} |",
              f"| Text mit Regelprüfung und Bildwahrscheinlichkeit | {a60['bild_richtig']} ({pct(a60['bild_richtig'], n)}) | {a60['bild_still_falsch']} ({pct(a60['bild_still_falsch'], n)}) | {a60['bild_unklar']} | {a60['bild_nicht_pruefbar']} |"]
    for zeile in zeilen:
        assert zeile in README, zeile
    assert f"die ersten {a60['blaetter']} Blätter" in README and f"({n} Halbzüge;" in README
    assert f"({a60['bild_nicht_pruefbar']} nicht prüfbar)" in README and f"({a60['basis_nicht_pruefbar']} nicht prüfbar)" in README
    m = fest["halbzuege"]
    assert a20["halbzuege"] == suche["halbzuege"] == m == 262 and a20["blaetter"] == suche["blaetter"] == fest["blaetter"] == 20
    for zeile in (f"| feste Voreinstellung (Oberkante und Unterkante geraten) | {fest['roh_richtig']} ({pct(fest['roh_richtig'], m)}) |",
                  f"| mit dem Erkenner gesucht (Oberkante und Unterkante, Drehung geschätzt) | {suche['roh_richtig']} ({pct(suche['roh_richtig'], m)}) |",
                  f"| automatisch aus den gedruckten Linien, entzerrt | {a20['roh_richtig']} ({pct(a20['roh_richtig'], m)}) |"):
        assert zeile in README, zeile
    assert f"dieselben ersten {fest['blaetter']} Blätter, {m} Halbzüge" in README
    assert fest["roh_richtig"] < suche["roh_richtig"] < a20["roh_richtig"]


def test_trocr_vergleich_steht_in_der_readme():
    t = json.loads((WURZEL / "data" / "trocr_messung.json").read_text(encoding="utf-8"))
    n = t["zellen"]
    assert t["kandidaten_je_zelle"] == 8 and n % 8 == 0 or n // 8 == 12
    for zeile in (f"| Schach-Modell (Trainingsdaten, also optimistisch) | {t['schach_modell']} von {n} |",
                  f"| TrOCR, Bild auf 384×384 gestaucht (üblich) | {t['trocr_gestaucht']} von {n} |",
                  f"| TrOCR, Seitenverhältnis erhalten | {t['trocr_seitenverhaeltnis']} von {n} |",
                  f"| Schach-Modell plus {str(t['gewicht_trocr']).replace('.', ',')} × TrOCR | {t['schach_plus_trocr']} von {n} |"):
        assert zeile in README, zeile
    assert f"{n} Zugbilder; Zufall wäre 1 von 8, also {n // 8} Treffer" in README
    assert t["trocr_gestaucht"] <= 2 * (n // 8) and t["schach_plus_trocr"] <= t["schach_modell"] + 2         # TrOCR liegt im Bereich des Zufalls und verbessert nichts


def test_vision_angaben_der_readme():
    import pf_vision
    assert f"`{pf_vision.MODELL}`" in README and f"höchstens {pf_vision.MAX_SEITE} Pixel je Seite" in README


def test_glm_ocr_vergleich_steht_in_der_readme():
    def lade(name):
        return json.loads((WURZEL / "data" / f"{name}.json").read_text(encoding="utf-8"))
    b, bz, z, ch = lade("ocr_messung_blaetter"), lade("ocr_messung_blaetter_zuschnitt"), lade("ocr_messung_zellen"), lade("hcs_messung_blaetter_auto20")
    n = b["halbzuege"]
    assert n == bz["halbzuege"] == ch["halbzuege"] == 262 and b["blaetter"] == bz["blaetter"] == ch["blaetter"] == 20 and not b["zuschnitt"] and bz["zuschnitt"]
    for zeile in (f"| Schach-Modell (Trainingsdaten, also optimistisch) | {ch['roh_richtig']} ({pct(ch['roh_richtig'], n)}) | {ch['basis_richtig']} ({pct(ch['basis_richtig'], n)}) |",
                  f"| GLM-OCR, ganze Zelle | {b['roh_richtig']} ({pct(b['roh_richtig'], n)}) | {b['basis_richtig']} ({pct(b['basis_richtig'], n)}) |",
                  f"| GLM-OCR, auf die Schrift zugeschnitten | {bz['roh_richtig']} ({pct(bz['roh_richtig'], n)}) | {bz['basis_richtig']} ({pct(bz['basis_richtig'], n)}) |"):
        assert zeile in README, zeile
    assert f"An den {z['zellen']} Zugbildern des Datensatzes liest GLM-OCR {z['normiert_richtig']} ({pct(z['normiert_richtig'], z['zellen'])}) ganz richtig, die Zeichenfehlerrate liegt bei {100 * z['cer_normiert']:.0f} %" in README
    assert b["roh_richtig"] < ch["roh_richtig"] and bz["roh_richtig"] < ch["roh_richtig"]


def test_nachtraining_zahlen_der_readme():
    n = json.loads((WURZEL / "data" / "nachtraining.json").read_text(encoding="utf-8"))

    def p(x: float) -> str:
        return f"{100 * x:.1f} %".replace(".", ",")

    a, c = n["rezept_A_nur_echt"], n["rezept_C_mit_deutsch_und_gerendert"]
    assert n["epochen"] == 120 and n["trainingsblaetter"] + n["pruefblaetter"] == 195
    assert f"{n['trainingsblaetter']} Blätter ({zahl(n['zellen_training'])} Zellen) zum Training, {n['pruefblaetter']} Blätter ({zahl(n['zellen_pruefung'])} Zellen) nur zur Prüfung" in README
    assert f"({zahl(n['zellen_training'] + n['zellen_pruefung'])} Zellen)" in README
    assert f"| {p(a['echt_englisch']['mra'])} | {p(a['deutsch_eingesetzt']['mra'])} | {p(a['gerendert_unbekannte_schriften']['mra'])} |" in README
    assert f"| {p(c['echt_englisch']['mra'])} | {p(c['deutsch_eingesetzt']['mra'])} | {p(c['gerendert_unbekannte_schriften']['mra'])} |" in README
    assert f"Zeichenfehlerrate {p(c['echt_englisch']['cer'])}" in README and f"{zahl(c['gerendert_unbekannte_schriften']['n'])} Zellen aus echten Lichess" in README
    assert f"(Rezept B) lernt langsamer ({p(n['nach_30_epochen']['B']['echt_englisch']['mra'])} nach 30 Epochen)" in README
    a30, c30 = n["nach_30_epochen"]["A"]["echt_englisch"]["mra"], n["nach_30_epochen"]["C"]["echt_englisch"]["mra"]
    assert round(100 * a30) == round(100 * c30) and f"Nach 30 Epochen lagen beide bei {round(100 * a30)} % (echt)" in README
    k = n["kalibrierung_echt"]
    assert f"T = {str(n['temperatur']).replace('.', ',')}" in README and f"von {k['ohne_nll']:.2f} auf {k['mit_nll']:.2f}".replace(".", ",") in README
    z = {x["stufe"]: x for x in n["zuverlaessigkeit"]}
    assert f"ab 0,9 ({p(z[0.9]['anteil_der_zellen'])} der Zellen) stimmt der gelesene Text in {p(z[0.9]['trefferquote'])}" in README
    assert f"ab 0,97 ({p(z[0.97]['anteil_der_zellen'])} der Zellen) in {p(z[0.97]['trefferquote'])}" in README
    t = n["tta"]
    assert f"von {p(t['echt_mra_ohne'])} auf {p(t['echt_mra'])} und auf den deutschen von {p(t['deutsch_mra_ohne'])} auf {p(t['deutsch_mra'])}" in README
