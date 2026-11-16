"""Tests der Foto-App mit AppTest: die Prüf- und Nacharbeit-Abschnitte laufen auf Beispielpartien (pf_constants.PRESETS), die hier direkt in den Zustand der App geschrieben werden,
denn die App selbst bietet nur noch die Foto-Funktion. (AppTest rendert kein SVG und bedient die Tabelle nicht; das prüft die Browser-Verifikation.)"""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import pf_constants as C

PFAD = str(Path(__file__).resolve().parent.parent / "app.py")


def neu() -> AppTest:
    at = AppTest.from_file(PFAD, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def laden(at: AppTest, name: str) -> AppTest:
    """Legt eine Beispielpartie so in den Zustand der App, wie das Lesen eines Fotos es täte (Kopf, Zeilen, frische Tabelle)."""
    p = C.PRESETS[name]
    for k in ("White", "Black", "Result", "Event", "Site", "Date", "Round", "WhiteElo", "BlackElo"):
        at.session_state[f"kopf_{k}"] = p["Kopf"].get(k, "")
    zeilen = C.auffuellen(p["Zeilen"])
    at.session_state["pf_zeilen"] = zeilen
    at.session_state["pf_basis"] = zeilen
    at.session_state["pf_v"] = at.session_state["pf_v"] + 1
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def metriken(at: AppTest) -> dict:
    return {m.label: m.value for m in at.metric}


def test_standard_ist_ein_leeres_formular_nur_mit_foto():
    at = neu()
    assert at.title[0].value.startswith("📷")
    assert not at.sidebar.button and not at.sidebar.header, "keine Seitenleiste mit Beispielen und Einstellungen mehr"
    assert [h.value for h in at.main.header] == ["1 · Foto", "2 · Prüfung gegen die Schachregeln", "3 · PGN für die Datenbank"]
    assert not at.metric and any("Noch keine Züge" in i.value for i in at.info)
    assert [c.label for c in at.checkbox] == ["Ich bestätige: Ich schwärze die Namen auf dem Foto, oder die Spieler sind mit dem Hochladen einverstanden."]
    assert not at.text_area, "kein Textfeld zum Einfügen mehr"


@pytest.mark.parametrize("name,erwartet", [
    ("Saubere Partie", {"Halbzüge gelesen": "33", "in Ordnung": "33", "unklar": "0", "Regelverstöße": "0", "nicht prüfbar": "0"}),
    ("Unscharf geschrieben", {"Halbzüge gelesen": "33", "in Ordnung": "32", "unklar": "1", "Regelverstöße": "0", "nicht prüfbar": "0"}),
    ("Unleserliches Zeichen", {"Halbzüge gelesen": "13", "in Ordnung": "10", "unklar": "3", "Regelverstöße": "0", "nicht prüfbar": "0"}),
    ("Regelverstoß", {"Halbzüge gelesen": "6", "in Ordnung": "5", "unklar": "0", "Regelverstöße": "1", "nicht prüfbar": "0"}),
    ("Fehler früher", {"Halbzüge gelesen": "33", "in Ordnung": "24", "unklar": "0", "Regelverstöße": "1", "nicht prüfbar": "8"}),
    ("Zug nach dem Matt", {"Halbzüge gelesen": "5", "in Ordnung": "4", "unklar": "0", "Regelverstöße": "1", "nicht prüfbar": "0"}),
])
def test_jedes_beispiel(name, erwartet):
    at = laden(neu(), name)
    assert metriken(at) == erwartet
    assert at.session_state["kopf_White"] == C.PRESETS[name]["Kopf"]["White"]


def test_leeres_formular_zeigt_hinweis():
    at = laden(neu(), "Leeres Formular")
    assert not at.metric and any("Noch keine Züge" in i.value for i in at.info)


def test_saubere_partie_ist_datenbanktauglich_mit_pgn():
    at = laden(neu(), "Saubere Partie")
    assert any(s.value.startswith("Datenbanktauglich") for s in at.success)
    pgn = next(c.value for c in at.code if c.value.startswith("[Event"))
    assert pgn.endswith("17. Rd8# 1-0") and '[White "Morphy, Paul"]' in pgn


def test_vorschlag_uebernehmen_macht_die_partie_sauber():
    at = laden(neu(), "Unscharf geschrieben")
    v = at.session_state["pf_v"]
    next(b for b in at.button if b.key == f"pf_k_{v}_21_0").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["pf_zeilen"][10][1] == "Sbd7"           # auf einem deutschen Formular schreibt die App deutsch
    assert metriken(at)["unklar"] == "0" and any(s.value.startswith("Datenbanktauglich") for s in at.success)


def test_fruehere_ursache_uebernehmen():
    at = laden(neu(), "Fehler früher")
    knopf = next(b for b in at.button if b.label.startswith("↩"))
    assert knopf.label == "↩ O-O-O"
    knopf.click().run()
    assert not at.exception and at.session_state["pf_zeilen"][11][0] == "O-O-O"
    assert any(s.value.startswith("Datenbanktauglich") for s in at.success)


def test_zug_nach_dem_matt_loeschen():
    at = laden(neu(), "Zug nach dem Matt")
    next(b for b in at.button if b.label == "Diese Zelle und alle folgenden leeren").click().run()
    assert not at.exception and at.session_state["pf_zeilen"][2] == ["", ""]
    assert any(s.value.startswith("Datenbanktauglich") for s in at.success)


def test_zelle_selbst_aendern_per_formular():
    at = laden(neu(), "Regelverstoß")
    v = at.session_state["pf_v"]
    at.text_input(key=f"pf_txt_{v}_5").set_value("Sc6")
    next(b for b in at.button if b.label == "Zelle ändern").click().run()
    assert not at.exception and at.session_state["pf_zeilen"][2][1] == "Sc6"
    assert metriken(at)["Regelverstöße"] == "0"


def test_legalen_zug_aus_liste_waehlen():
    at = laden(neu(), "Regelverstoß")
    v = at.session_state["pf_v"]
    box = at.selectbox(key=f"pf_sel_{v}_5")
    assert "Sc6" in box.options and "Sd7" in box.options and "Sf6" not in box.options        # deutsche Schreibweise, nur legale Züge
    box.select("Sc6").run()
    assert not at.exception and at.session_state["pf_zeilen"][2][1] == "Sc6"


def test_buchstabenwahl_aus_dem_zustand_warnt_bei_falscher_schreibweise():
    at = laden(neu(), "Saubere Partie")
    at.session_state["pf_buchstaben"] = "en"
    at.run()
    assert not at.exception
    assert any("deutschen" in m.value for m in at.markdown)


def tabelle_aendern(at: AppTest, aenderungen: dict, neue_zeilen: list | None = None) -> AppTest:
    """Simuliert eine Eingabe in der Tabelle über den Widget-Zustand des data_editor (AppTest kann die Zellen nicht anklicken)."""
    at.session_state[f"pf_editor_{at.session_state['pf_v']}"] = {"edited_rows": aenderungen, "added_rows": neue_zeilen or [], "deleted_rows": []}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_tabelle_bearbeiten_wirkt_auf_die_pruefung():
    at = laden(neu(), "Regelverstoß")
    assert metriken(at)["Regelverstöße"] == "1"
    tabelle_aendern(at, {2: {"Schwarz": "Sc6"}})
    assert at.session_state["pf_zeilen"][2] == ["Lb5+", "Sc6"] and metriken(at)["Regelverstöße"] == "0" and metriken(at)["Halbzüge gelesen"] == "6"
    tabelle_aendern(at, {2: {"Schwarz": "Sc6"}, 3: {"Weiß": "d4"}})
    assert metriken(at)["Halbzüge gelesen"] == "7"


def test_neue_zeilen_in_der_tabelle():
    at = laden(neu(), "Regelverstoß")
    n = len(at.session_state["pf_zeilen"])
    tabelle_aendern(at, {2: {"Schwarz": "Sc6"}}, [{"Weiß": "d4", "Schwarz": "exd4"}])
    assert len(at.session_state["pf_zeilen"]) == n + 1 and at.session_state["pf_zeilen"][-1] == ["d4", "exd4"]


def test_tabellenbearbeitung_nach_einem_vorschlag_beginnt_neu():
    """Nach einem übernommenen Vorschlag bekommt die Tabelle einen frischen Zustand: alte Bearbeitungen werden nicht ein zweites Mal angewandt."""
    at = laden(neu(), "Unscharf geschrieben")
    tabelle_aendern(at, {0: {"Weiß": "e4"}})
    v = at.session_state["pf_v"]
    next(b for b in at.button if b.key == f"pf_k_{v}_21_0").click().run()
    assert at.session_state["pf_v"] == v + 1 and at.session_state["pf_zeilen"][0][0] == "e4" and at.session_state["pf_zeilen"][10][1] == "Sbd7"


# ------------------------------------------------------------------------------------------------- Datenschutz beim Foto
def test_foto_auswahl_erscheint_erst_nach_der_bestaetigung(monkeypatch):
    import pf_schwaerzen as SW

    aufrufe = []
    monkeypatch.setattr(SW, "foto_schwaerzen", lambda key: aufrufe.append(key))
    at = AppTest.from_file(PFAD, default_timeout=60)
    at.run()
    assert not at.exception
    assert at.checkbox(key="pf_foto_ok").value is False and aufrufe == []
    at.checkbox(key="pf_foto_ok").check().run()
    assert not at.exception and aufrufe == ["pf_foto"]
    at.checkbox(key="pf_foto_ok").uncheck().run()
    assert not at.exception and aufrufe == ["pf_foto"] and "pf_bild" not in at.session_state


def test_foto_wird_nicht_in_einem_sitzungsuebergreifenden_cache_gehalten():
    text = (Path(PFAD)).read_text(encoding="utf-8")
    assert "@st.cache_data" not in text, "st.cache_data würde hochgeladene Bilder für andere Sitzungen im Server-Speicher behalten"
    assert "cache_resource" in text                                          # nur das Erkennungsmodell (keine Nutzerdaten)
    assert "_bild_laden(foto)" in text and "session_state" in text
    assert "file_uploader" not in text, "das Original darf den Browser nicht verlassen: nur die Schwärzen-Komponente liefert ein Bild"
