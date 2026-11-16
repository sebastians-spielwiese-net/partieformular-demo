"""PGN-Export und Textimport: Kopfzeilen, Datum, Zeilenumbruch, NAG, Rundlauf mit python-chess."""
import io

import chess
import chess.pgn
import pytest

import pf_logik as L
import pf_pgn as G
import pf_pruefung as P


@pytest.mark.parametrize("roh,erwartet", [
    ("15.11.2026", "2026.11.15"), ("5.1.2026", "2026.01.05"), ("15.11.26", "2026.11.15"), ("2026-11-15", "2026.11.15"), ("2026.11.15", "2026.11.15"),
    ("11.2026", "2026.11.??"), ("2026", "2026.??.??"), ("2026.11.??", "2026.11.??"), ("", "????.??.??"), ("gestern", "????.??.??"),
    ("31.2.2026", "????.??.??"), ("15.13.2026", "????.??.??"), ("1858", "1858.??.??"),
])
def test_datum(roh, erwartet):
    assert G.normiere_datum(roh)[0] == erwartet


def test_datum_in_der_zukunft_warnt():
    assert any(m.stufe == "warnung" and "Zukunft" in m.text for m in G.normiere_datum("1.1.2999")[1])


@pytest.mark.parametrize("roh,erwartet", [("1-0", "1-0"), ("½-½", "1/2-1/2"), ("remis", "1/2-1/2"), ("0:1", "0-1"), ("*", "*"), ("", ""), ("gewonnen", "")])
def test_ergebnis(roh, erwartet):
    assert G.normiere_ergebnis(roh) == erwartet


def test_kopf_standardwerte_und_meldungen():
    kopf, meld = G.normiere_kopf({})
    assert kopf == {"Event": "?", "Site": "?", "Date": "????.??.??", "Round": "?", "White": "?", "Black": "?", "Result": "*"}
    assert any("Name von Weiß oder Schwarz" in m.text for m in meld)
    kopf, meld = G.normiere_kopf({"White": "  Max   Muster ", "Black": "Beispiel, Berta", "WhiteElo": "1984", "BlackElo": "abc", "Result": "x"})
    assert kopf["White"] == "Max Muster" and kopf["WhiteElo"] == "1984" and "BlackElo" not in kopf
    texte = " ".join(m.text for m in meld)
    assert "Nachname, Vorname" in texte and "BlackElo" in texte and "Ergebnis „x“" in texte


def test_tagwerte_werden_maskiert():
    kopf, _ = G.normiere_kopf({"White": 'Muster "Max" \\ Test', "Black": "B"})
    text = G.pgn(kopf, [])
    assert 'White "Muster \\"Max\\" \\\\ Test"' in text
    assert G.text_zu_zellen(text)[0]["White"] == 'Muster "Max" \\ Test'          # python-chess entmaskiert Tagwerte nicht, der Standard schon


def test_pgn_aufbau():
    p = P.pruefe([("e4", "e5"), ("Sf3", "Sc6")])
    text, _ = L.pgn_text({"White": "A, B", "Black": "C, D", "Result": "1/2-1/2", "Date": "2026"}, p, L.EXPORT_SAUBER)
    zeilen = text.split("\n")
    assert [z.split(" ")[0] for z in zeilen[:7]] == ["[Event", "[Site", "[Date", "[Round", "[White", "[Black", "[Result"]
    assert zeilen[7] == "" and zeilen[8] == "1. e4 e5 2. Nf3 Nc6 1/2-1/2" and text.endswith("\n")


def test_zeilen_haben_hoechstens_80_zeichen_und_ergebnis_schliesst_ab():
    sans = ["Nf3", "Nf6", "Ng1", "Ng8"] * 3
    p = P.pruefe([sans[i:i + 2] for i in range(0, len(sans), 2)])
    text, _ = L.pgn_text({"White": "A", "Black": "B"}, p, L.EXPORT_SAUBER)
    zuege = text.split("\n\n")[1].rstrip("\n").split("\n")
    assert all(len(z) <= 80 for z in zuege) and zuege[-1].endswith(" *")


def test_bewertung_als_nag():
    p = P.pruefe([("e4!", "e5??"), ("Sf3", "Sc6?!")])
    text, _ = L.pgn_text({"White": "A", "Black": "B"}, p, L.EXPORT_SAUBER)
    assert "1. e4 $1 e5 $4 2. Nf3 Nc6 $6" in text
    partie = chess.pgn.read_game(io.StringIO(text))
    assert [n.nags for n in partie.mainline()] == [{1}, {4}, set(), {6}]


def test_vorlaeufiges_pgn_mit_kommentar_und_teil_pgn():
    p = P.pruefe([("e4", "e5"), ("Sf3", "d6"), ("d4", "Lg4"), ("dxe5", "Lxf3"), ("Dxf3", "dxe5"), ("Lc4", "Sf6"), ("Db3", "De7"), ("Sc3", "c6"), ("Lg5", "b5"),
                  ("Sxb5", "cxb5"), ("Lxb5+", "Sd7")])
    assert not p.datenbanktauglich() and L.export_modi(p) == [L.EXPORT_TEIL, L.EXPORT_VORLAEUFIG]
    teil, _ = L.pgn_text({"White": "A", "Black": "B", "Result": "1-0"}, p, L.EXPORT_TEIL)
    assert teil.rstrip().endswith("11. Bxb5+ *") and 'Result "*"' in teil
    vor, _ = L.pgn_text({"White": "A", "Black": "B"}, p, L.EXPORT_VORLAEUFIG)
    assert "11. Bxb5+ Nbd7 {Formular: „Sd7“, unklar, Vorschlag der Regelprüfung}" in vor.replace("\n", " ")
    partie = chess.pgn.read_game(io.StringIO(vor))
    assert not partie.errors and len(list(partie.mainline_moves())) == 22


def test_export_modi():
    assert L.export_modi(P.pruefe([("e4", "e5")])) == [L.EXPORT_SAUBER]
    assert L.export_modi(P.pruefe([("Sc6", "")])) == []
    assert L.export_modi(P.pruefe([("e4", "e5"), ("Sc6", "")])) == [L.EXPORT_TEIL]


def test_text_zu_zellen():
    kopf, zeilen, meld = G.text_zu_zellen('[White "Muster, Max"]\n[Result "1-0"]\n\n1. e4 e5 2. Nf3 {Kommentar} d6 3. d4 Bg4 4. dxe5 5... Bxf3 (4... dxe5) 1-0')
    assert kopf == {"White": "Muster, Max", "Result": "1-0"}
    assert zeilen == [["e4", "e5"], ["Nf3", "d6"], ["d4", "Bg4"], ["dxe5", ""], ["", "Bxf3"]]
    assert len(meld) == 1 and "Variante" in meld[0].text
    assert G.text_zu_zellen("1.e4 e5 2.Sf3 Sc6 3.Lb5")[1] == [["e4", "e5"], ["Sf3", "Sc6"], ["Lb5", ""]]
    assert G.text_zu_zellen("e4 e5 Sf3")[1] == [["e4", "e5"], ["Sf3", ""]]
    assert G.text_zu_zellen("1. e4 e5 3. Sf3 Sc6 0-1")[1] == [["e4", "e5"], ["", ""], ["Sf3", "Sc6"]]
    assert G.text_zu_zellen("")[1] == []
    assert G.text_zu_zellen("1. e4 e5 ; Rest der Zeile\n2. Nf3 $1 Nc6")[1] == [["e4", "e5"], ["Nf3", "Nc6"]]


def test_rundlauf_pgn_text_pgn():
    """Aus dem eigenen PGN werden wieder dieselben Zellen und dasselbe PGN."""
    p = P.pruefe([("e4", "e5"), ("Sf3", "Sc6"), ("Lb5", "a6"), ("La4", "Sf6"), ("0-0", "Le7")])
    kopf = {"White": "A, B", "Black": "C, D", "Result": "*", "Date": "2026.11.15"}
    text, _ = L.pgn_text(kopf, p, L.EXPORT_SAUBER)
    k2, zeilen, _ = G.text_zu_zellen(text)
    assert k2["White"] == "A, B" and k2["Date"] == "2026.11.15"
    text2, _ = L.pgn_text({**kopf, **k2}, P.pruefe(zeilen), L.EXPORT_SAUBER)
    assert text2 == text


def test_dateiname():
    assert L.dateiname({"White": "Müller, Max", "Black": "Weiß, Berta", "Date": "15.11.2026"}) == "Mueller_Weiss_2026.11.15.pgn"
    assert L.dateiname({}) == "Weiss_Schwarz.pgn"
    assert L.dateiname({"White": "A", "Black": "B", "Date": "2026"}, L.EXPORT_TEIL) == "A_B_2026_teil.pgn"


def test_wirksames_ergebnis():
    matt = P.pruefe([("f3", "e5"), ("g4", "Dh4#")])
    assert L.wirksames_ergebnis("1-0", matt) == ("1-0", "Kopf des Formulars")
    assert L.wirksames_ergebnis("", matt) == ("0-1", "aus dem Matt abgeleitet")
    assert L.wirksames_ergebnis("", P.pruefe([("e4", "e5")])) == ("*", "nicht angegeben")
    assert L.wirksames_ergebnis("", P.pruefe([("e4", "e5"), ("1-0", "")])) == ("1-0", "Ergebnis in der Zugliste")
