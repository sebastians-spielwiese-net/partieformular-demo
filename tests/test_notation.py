"""Zellen lesen: jede in der README genannte Schreibweise, Joker, Ergebnisse, Unlesbares."""
import pytest

from pf_notation import lese


def kern(les):
    return (les.art, les.figur, les.von_datei + les.von_reihe, les.schlag, les.ziel_datei + les.ziel_reihe, les.umw, les.schach)


@pytest.mark.parametrize("roh,erwartet", [
    ("e4", ("zug", "P", "", False, "e4", "", "")),
    ("Sf3", ("zug", "N", "", False, "f3", "", "")),
    ("Nf3", ("zug", "N", "", False, "f3", "", "")),
    ("Lb5+", ("zug", "B", "", False, "b5", "", "+")),
    ("Td8#", ("zug", "R", "", False, "d8", "", "#")),
    ("Dxf3", ("zug", "Q", "", True, "f3", "", "")),
    ("Kg1", ("zug", "K", "", False, "g1", "", "")),
    ("exd5", ("zug", "P", "e", True, "d5", "", "")),
    ("ed5", ("zug", "P", "e", False, "d5", "", "")),
    ("e:d5", ("zug", "P", "e", True, "d5", "", "")),
    ("Lc4:", ("zug", "B", "", True, "c4", "", "")),
    ("e2-e4", ("zug", "P", "e2", False, "e4", "", "")),
    ("e2e4", ("zug", "P", "e2", False, "e4", "", "")),
    ("Sg1-f3", ("zug", "N", "g1", False, "f3", "", "")),
    ("Sbd7", ("zug", "N", "b", False, "d7", "", "")),
    ("S5d7", ("zug", "N", "5", False, "d7", "", "")),
    ("Sb8d7", ("zug", "N", "b8", False, "d7", "", "")),
    ("e8D", ("zug", "P", "", False, "e8", "Q", "")),
    ("e8=D", ("zug", "P", "", False, "e8", "Q", "")),
    ("e8=Q+", ("zug", "P", "", False, "e8", "Q", "+")),
    ("e7e8q", ("zug", "P", "e7", False, "e8", "Q", "")),
    ("axb8=S#", ("zug", "P", "a", True, "b8", "N", "#")),
    ("Lb5++", ("zug", "B", "", False, "b5", "", "+")),
    ("♘f3", ("zug", "N", "", False, "f3", "", "")),
    ("12.e4", ("zug", "P", "", False, "e4", "", "")),
    ("12...e5", ("zug", "P", "", False, "e5", "", "")),
    ("  Sf3  ", ("zug", "N", "", False, "f3", "", "")),
    ("S f3", ("zug", "N", "", False, "f3", "", "")),
    ("sf3", ("zug", "N", "", False, "f3", "", "")),
    ("Ed5", ("zug", "P", "e", False, "d5", "", "")),
    ("e5 e.p.", ("zug", "P", "", False, "e5", "", "")),
    ("Sg1–f3", ("zug", "N", "g1", False, "f3", "", "")),       # Gedankenstrich
    ("S×e5", ("zug", "N", "", True, "e5", "", "")),            # Malzeichen
    ("SXe5", ("zug", "N", "", True, "e5", "", "")),
])
def test_zugschreibweisen(roh, erwartet):
    les = lese(roh)
    assert kern(les) == erwartet, (roh, les)


@pytest.mark.parametrize("roh,seite", [("0-0", "K"), ("O-O", "K"), ("o-o", "K"), ("0-0-0", "Q"), ("O-O-O", "Q"), ("0–0–0", "Q"), ("O-O+", "K"), ("0-0!", "K")])
def test_rochade(roh, seite):
    les = lese(roh)
    assert les.art == "rochade" and les.rochade == seite, les


@pytest.mark.parametrize("roh,bewertung,nag", [("Sf3!", "!", 1), ("Sf3?", "?", 2), ("e4!!", "!!", 3), ("e4??", "??", 4), ("Dh5!?", "!?", 5), ("Dh5?!", "?!", 6),
                                              ("Lb5+!", "!", 1), ("0-0?", "?", 2)])
def test_bewertung_ist_keine_unleserliche_stelle(roh, bewertung, nag):
    les = lese(roh)
    assert les.bewertung == bewertung and les.nag == nag and not les.unsicher, les


@pytest.mark.parametrize("roh", ["S?3", "Sf?", "?f3", "e?", "S??", "?4", "?"])
def test_joker(roh):
    assert lese(roh).unsicher, roh


def test_joker_felder():
    les = lese("S?3")
    assert (les.figur, les.ziel_datei, les.ziel_reihe) == ("N", "?", "3")
    les = lese("Sf?")
    assert (les.ziel_datei, les.ziel_reihe) == ("f", "?")
    les = lese("?f3")
    assert (les.figur, les.ziel_datei, les.ziel_reihe) == ("?", "f", "3")
    assert lese("???").art == "unleserlich"


@pytest.mark.parametrize("roh,erg", [("1-0", "1-0"), ("0-1", "0-1"), ("1/2-1/2", "1/2-1/2"), ("½-½", "1/2-1/2"), ("remis", "1/2-1/2"), ("Remis", "1/2-1/2"),
                                    ("1:0", "1-0"), ("0:1", "0-1"), ("*", "*"), ("0,5-0,5", "1/2-1/2")])
def test_ergebnisse(roh, erg):
    les = lese(roh)
    assert les.art == "ergebnis" and les.ergebnis == erg


@pytest.mark.parametrize("roh", ["", "   ", None, "-", "...", "…", "_"])
def test_leer(roh):
    assert lese(roh).art == "leer"


@pytest.mark.parametrize("roh", ["xyz", "Sf3x", "e9", "Sj3", "zwei Züge", "Sf3 Sc6", "8", "Kx"])
def test_unlesbar(roh):
    assert lese(roh).art == "unlesbar", roh


def test_buchstabensystem():
    assert lese("Sf3").system == "de" and lese("Lb5").system == "de" and lese("Td1").system == "de" and lese("Dd1").system == "de"
    assert lese("Nf3").system == "en" and lese("Bb5").system == "en" and lese("Rd1").system == "en" and lese("Qd1").system == "en"
    assert lese("Kg1").system == "" and lese("e4").system == "" and lese("0-0").system == ""
    assert lese("e8=D").system == "de" and lese("e8=Q").system == "en"


def test_hinweise_zur_schreibweise():
    assert "ausführliche Schreibweise" in " ".join(lese("e2-e4").hinweise)
    assert lese("e4").hinweise == [] and lese("Sf3").hinweise == [] and lese("0-0").hinweise == []
    assert any("Groß-" in h for h in lese("sf3").hinweise)
    assert any("Zugnummer" in h for h in lese("12.e4").hinweise)


def test_anzeige_der_zelle_bleibt_erhalten():
    assert lese("  Sf3 ").roh == "  Sf3 "
