"""Beispielformulare (Schnellstart), Einstellungen und Texte der Demo.

Die Partien sind zwei bekannte, gemeinfreie Lehrpartien (Morphy und Herzog von Braunschweig mit Graf Isouard, Paris 1858; Légal gegen Saint Brie, 1750)
und zwei kurze Eigenbau-Folgen. Jede „abgeschrieben“ wirkende Zelle ist absichtlich so gewählt, dass sie genau einen Fall der Prüfung zeigt;
tests/test_beispiele.py prüft für jedes Beispiel, was die Prüfung daraus macht.
"""
from __future__ import annotations

ZEILEN_LEER = 40          # so viele Zeilen hat das leere Formular (ein Formular fasst meist 30 bis 40 Züge je Seite)

OPER_ZUEGE = [("e4", "e5"), ("Sf3", "d6"), ("d4", "Lg4"), ("dxe5", "Lxf3"), ("Dxf3", "dxe5"), ("Lc4", "Sf6"), ("Db3", "De7"), ("Sc3", "c6"),
              ("Lg5", "b5"), ("Sxb5", "cxb5"), ("Lxb5+", "Sbd7"), ("0-0-0", "Td8"), ("Txd7", "Txd7"), ("Td1", "De6"), ("Lxd7+", "Sxd7"),
              ("Db8+", "Sxb8"), ("Td8#", "")]
OPER_KOPF = {"Event": "Partie in der Oper", "Site": "Paris", "Date": "1858", "Round": "", "White": "Morphy, Paul",
             "Black": "Herzog von Braunschweig und Graf Isouard", "Result": "1-0"}

LEGAL_KOPF = {"Event": "Lehrbeispiel", "Site": "Paris", "Date": "1750", "Round": "", "White": "Légal, Sire de", "Black": "Saint Brie", "Result": "1-0"}


def auffuellen(zeilen: list, n: int = ZEILEN_LEER) -> list:
    zeilen = [list(z) for z in zeilen]
    while len(zeilen) < n:
        zeilen.append(["", ""])
    return zeilen


def _mit(zeilen: list, aenderungen: dict) -> list:
    """Kopie der Zeilen mit geänderten Zellen: {(Zeile ab 1, Spalte 0 oder 1): Text}."""
    z = [list(r) for r in zeilen]
    for (zeile, spalte), text in aenderungen.items():
        z[zeile - 1][spalte] = text
    return z


UNSCHARF = _mit(OPER_ZUEGE, {(1, 0): "e2-e4", (1, 1): "e7-e5", (2, 0): "Sg1-f3", (4, 0): "d:e5", (4, 1): "Lg4xf3", (5, 1): "de5", (11, 0): "Lb5",
                             (11, 1): "Sd7", (17, 0): "Td8"})
LEGAL_UNLESERLICH = [("e4", "e5"), ("Sf3", "d6"), ("Lc4", "Lg?"), ("Sc3", "?"), ("Sxe5", "Lxd1"), ("L?7+", "Ke7"), ("Sd5#", "")]
SCHACH_ZUG = [("e4", "e5"), ("Sf3", "d6"), ("Lb5+", "Sf6")]
HOCHSTAPLER = _mit(OPER_ZUEGE, {(12, 0): "0-0"})
MATT_ZUG = [("f3", "e5"), ("g4", "Dh4#"), ("Sc3", "")]

PRESETS = {
    "Saubere Partie": {"Kopf": OPER_KOPF, "Zeilen": auffuellen(OPER_ZUEGE)},
    "Unscharf geschrieben": {"Kopf": {**OPER_KOPF, "Date": "1858", "Black": "Herzog von Braunschweig und Graf Isouard"}, "Zeilen": auffuellen(UNSCHARF)},
    "Unleserliches Zeichen": {"Kopf": LEGAL_KOPF, "Zeilen": auffuellen(LEGAL_UNLESERLICH)},
    "Regelverstoß": {"Kopf": {"Event": "Vereinsabend", "Site": "", "Date": "15.11.2026", "Round": "2", "White": "Muster, Max", "Black": "Beispiel, Berta",
                              "Result": "*"}, "Zeilen": auffuellen(SCHACH_ZUG)},
    "Fehler früher": {"Kopf": OPER_KOPF, "Zeilen": auffuellen(HOCHSTAPLER)},
    "Zug nach dem Matt": {"Kopf": {"Event": "Vereinsabend", "Site": "", "Date": "15.11.2026", "Round": "3", "White": "Muster, Max", "Black": "Beispiel, Berta",
                                   "Result": "0-1"}, "Zeilen": auffuellen(MATT_ZUG)},
    "Leeres Formular": {"Kopf": {"Event": "", "Site": "", "Date": "", "Round": "", "White": "", "Black": "", "Result": ""}, "Zeilen": auffuellen([])},
}
STANDARD_PRESET = "Unscharf geschrieben"

PRESET_HELP = {
    "Saubere Partie": "Die Opernpartie von Morphy in deutscher Schreibweise, sauber abgeschrieben: alles ist in Ordnung, das PGN ist sofort fertig.",
    "Unscharf geschrieben": "Dieselbe Partie, so abgeschrieben, wie es auf echten Formularen vorkommt: ausführliche Schreibweise, fehlendes x und +, „d:e5“, und im 11. Zug „Sd7“ "
                            "bei zwei Springern, die das Feld erreichen. Die App löst das aus den Regeln und den Folgezügen auf.",
    "Unleserliches Zeichen": "Légals Mattfalle mit drei unleserlichen Stellen: „Lg?“ und „L?7+“ lassen sich aus den Regeln eindeutig ergänzen, ein ganz unleserlicher 4. Zug von Schwarz nicht: Dort bleiben mehrere Züge gleich gut, und die App fragt nach.",
    "Regelverstoß": "Der 3. Zug von Schwarz lässt den König im Schach stehen. Die App sagt, warum das nicht geht, und schlägt legale Züge vor.",
    "Fehler früher": "Im 12. Zug steht „0-0“ statt „0-0-0“. Das ist selbst legal, der Fehler zeigt sich erst im 13. Zug. Die App findet die frühere Ursache.",
    "Zug nach dem Matt": "Das Matt im zweiten Zug von Schwarz und danach noch ein Zug: Auf dem Formular steht mehr, als die Partie hergibt.",
    "Leeres Formular": "Ein leeres Formular mit 40 Zeilen zum Abtippen.",
}

BUCHSTABEN = {"auto": "automatisch erkennen", "de": "deutsch (K D T L S)", "en": "englisch (K Q R B N)"}

STATUS = {
    "ok": ("✅", "ok"),
    "hinweis": ("ℹ️", "bereinigt"),
    "unklar": ("⚠️", "unklar"),
    "illegal": ("❌", "Regelverstoß"),
    "nicht_pruefbar": ("⏸️", "nicht prüfbar"),
    "nach_ende": ("✋", "nach dem Ende"),
    "ergebnis": ("🏁", "Ergebnis"),
    "leer": ("·", "leer"),
}
FARBEN = {"ok": "rgba(40,167,69,0.18)", "hinweis": "rgba(23,162,184,0.18)", "unklar": "rgba(255,193,7,0.30)", "illegal": "rgba(220,53,69,0.28)",
          "nach_ende": "rgba(220,53,69,0.28)", "nicht_pruefbar": "rgba(128,128,128,0.22)", "ergebnis": "rgba(128,128,128,0.12)", "leer": "rgba(128,128,128,0.05)"}
STUFE_ICON = {"info": "ℹ️", "warnung": "⚠️", "fehler": "❌"}

LESEREGELN = """
| Auf dem Formular | Die App liest |
|---|---|
| `Sf3`, `Nf3` | Springer nach f3 (deutsche und englische Buchstaben: K D T L S oder K Q R B N, auch kleingeschrieben oder als Figurensymbol ♘) |
| `e2-e4`, `Sg1-f3`, `e2e4` | ausführliche Schreibweise (von-nach) |
| `Sxe5`, `Se5:`, `S:e5`, `Se5` | Schlag; das Schlagzeichen ist egal, wenn der Zug eindeutig ist |
| `ed5`, `exd5`, `e:d5` | Bauernschlag von der e-Linie nach d5 |
| `0-0`, `O-O`, `0-0-0`, `O-O-O` | kurze und lange Rochade (Nullen oder Buchstabe O) |
| `e8D`, `e8=D`, `e8Q` | Umwandlung; fehlt die Figur, fragt die App nach |
| `Sbd7`, `S5d7`, `Sb8d7` | Zusatz bei zwei gleichen Figuren; die App prüft, ob er nötig ist |
| `Lb5+`, `Td8#`, `Lb5++` | Schach und Matt; fehlen die Zeichen, ergänzt die App sie, stimmen sie nicht, warnt sie |
| `S?3`, `Sd?`, `?` | unleserliches Zeichen: die App sucht die legalen Züge, die dazu passen |
| `Sf3!`, `e4??`, `Dh5?!` | Bewertung, kommt als NAG ($1, $4, $6) ins PGN |
| `1-0`, `0-1`, `½-½`, `remis` | Ergebnis in einer Zelle: gilt als Ergebnis, nicht als Zug |
| leere Zelle zwischen Zügen | fehlender Zug: die App sucht den Zug, nach dem die Partie weiterhin regelkonform ist |
"""
