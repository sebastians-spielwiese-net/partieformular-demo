"""Jedes Beispielformular zeigt genau den Fall, den sein Name verspricht. Die Zahlen sind die der Prüfung, nicht der README."""
import chess
import pytest

import pf_constants as C
import pf_logik as L
import pf_pruefung as P


def pruefe(name: str) -> P.Pruefung:
    return P.pruefe(C.PRESETS[name]["Zeilen"])


def test_alle_beispiele_haben_40_zeilen():
    assert all(len(p["Zeilen"]) == C.ZEILEN_LEER for p in C.PRESETS.values())
    assert set(C.PRESET_HELP) == set(C.PRESETS)


def test_saubere_partie_ist_gleich_python_chess():
    p = pruefe("Saubere Partie")
    assert p.datenbanktauglich() and p.zaehlen()["ok"] == 33 and p.ende == "matt"
    ref = chess.Board()
    for e in p.zuege:
        ref.push_san(e.san)
    assert ref.is_checkmate() and ref.fullmove_number == 17


def test_unscharf_geschrieben():
    p = pruefe("Unscharf geschrieben")
    assert p.zaehlen() == {"ok": 24, "hinweis": 8, "unklar": 1, "illegal": 0, "nicht_pruefbar": 0, "nach_ende": 0}
    e = p.zuege[21]
    assert (e.roh, e.status, e.san) == ("Sd7", "unklar", "Nbd7") and [k.san for k in e.kandidaten] == ["Nbd7", "Nfd7"]
    # Mit der Wahl der App ist es dieselbe Partie wie die saubere
    sauber = [x.san for x in pruefe("Saubere Partie").zuege]
    assert [x.san for x in p.zuege] == sauber
    # Übernimmt man den Vorschlag, ist die Partie datenbanktauglich
    zeilen = L.zelle_setzen(C.PRESETS["Unscharf geschrieben"]["Zeilen"], 21, "Sbd7")
    assert P.pruefe(zeilen).datenbanktauglich()


def test_unleserliches_zeichen():
    p = pruefe("Unleserliches Zeichen")
    assert p.zaehlen()["unklar"] == 3 and p.zaehlen()["ok"] == 10 and p.ende == "matt"
    eindeutig = [e for e in p.zuege if e.status == "unklar" and len(e.kandidaten) == 1]
    assert [(e.roh, e.san) for e in eindeutig] == [("Lg?", "Bg4"), ("L?7+", "Bxf7+")]
    offen = next(e for e in p.zuege if e.roh == "?")
    assert len(offen.kandidaten) == 8 and len({(k.fortsetzung, k.ganz) for k in offen.kandidaten}) == 1
    assert any("gleich lang" in m.text for m in offen.meldungen)
    # Mit dem Original ist die Partie sauber
    original = ["e4", "e5", "Sf3", "d6", "Lc4", "Lg4", "Sc3", "g6", "Sxe5", "Lxd1", "Lxf7+", "Ke7", "Sd5#"]
    z = [list(r) for r in C.PRESETS["Unleserliches Zeichen"]["Zeilen"]]
    for i, s in enumerate(original):
        z[i // 2][i % 2] = s
    assert P.pruefe(z).datenbanktauglich()


def test_regelverstoss():
    p = pruefe("Regelverstoß")
    e = p.zuege[-1]
    assert e.status == "illegal" and "steht im Schach" in e.meldungen[0].text and [k.san for k in e.kandidaten] == ["Nc6"]
    legal = {e.vor.san(z) for z in e.vor.legale_zuege()}
    assert legal == {"Nc6", "Nd7", "Bd7", "Qd7", "c6", "Ke7"}


def test_fehler_frueher():
    p = pruefe("Fehler früher")
    assert p.zaehlen() == {"ok": 24, "hinweis": 0, "unklar": 0, "illegal": 1, "nicht_pruefbar": 8, "nach_ende": 0}
    e = next(x for x in p.zuege if x.status == "illegal")
    assert e.beschriftung == "13. Weiß" and [(j, k.san, k.ganz) for j, k in e.frueher] == [(22, "O-O-O", True)]
    zeilen = L.zelle_setzen(C.PRESETS["Fehler früher"]["Zeilen"], 22, "0-0-0")
    assert P.pruefe(zeilen).datenbanktauglich()


def test_zug_nach_dem_matt():
    p = pruefe("Zug nach dem Matt")
    assert p.ende == "matt" and p.zuege[-1].status == "nach_ende" and not p.datenbanktauglich()
    assert P.pruefe(L.ab_ply_loeschen(C.PRESETS["Zug nach dem Matt"]["Zeilen"], 4)).datenbanktauglich()
    assert any(b.stufe == "fehler" for b in P.ergebnis_befunde(p, "1-0"))
    assert not any(b.stufe == "fehler" for b in P.ergebnis_befunde(p, "0-1"))


def test_leeres_formular():
    p = pruefe("Leeres Formular")
    assert p.zuege == [] and not p.datenbanktauglich() and L.export_modi(p) == []


@pytest.mark.parametrize("name", list(C.PRESETS))
def test_kein_beispiel_bricht_die_oberflaeche(name):
    p = pruefe(name)
    L.export_modi(p)
    if p.zuege:
        for modus in L.export_modi(p) or [L.EXPORT_TEIL]:
            L.pgn_text(C.PRESETS[name]["Kopf"], p, modus)
