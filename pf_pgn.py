"""PGN: Kopfdaten des Formulars bereinigen, die Zugliste schreiben und abgetippten Text (auch ein ganzes PGN) in Formularzellen zerlegen.

Das PGN folgt dem Exportformat des Standards: sieben Pflichtkopfzeilen in fester Reihenfolge (Event, Site, Date, Round, White, Black, Result), dann
weitere Zeilen, eine Leerzeile, die Züge in SAN mit Zugnummern (Zeilen höchstens 80 Zeichen) und zum Schluss das Ergebnis. Bewertungszeichen
stehen als NAG ($1 bis $6), Rückfragen als Kommentar in geschweiften Klammern.
"""
from __future__ import annotations

import re
from datetime import date

from pf_notation import ERGEBNISSE
from pf_pruefung import Meldung

SIEBEN = ["Event", "Site", "Date", "Round", "White", "Black", "Result"]
OPTIONAL = ["WhiteElo", "BlackElo"]
STANDARD = {"Event": "?", "Site": "?", "Date": "????.??.??", "Round": "?", "White": "?", "Black": "?", "Result": "*"}  # lint-ok: doppelte-satzzeichen
TAG_ZEILE = re.compile(r'^\s*\[(\w+)\s+"((?:[^"\\]|\\.)*)"\]\s*$')
UMBRUCH = 80


def normiere_ergebnis(text: str) -> str:
    t = (text or "").strip().lower().replace("½", "1/2").replace("–", "-").replace(" ", "")
    return ERGEBNISSE.get(t, "") if t else ""


def normiere_datum(text: str) -> tuple[str, list[Meldung]]:
    """Datum in die PGN-Form JJJJ.MM.TT; unbekannte Teile werden zu Fragezeichen. Erkannt: 15.11.2026, 15.11.26, 2026-11-15, 2026.11.15, 11.2026, 2026."""
    t = (text or "").strip()
    if not t:
        return "????.??.??", [Meldung("info", "Kein Datum: „????.??.??“.")]  # lint-ok: doppelte-satzzeichen
    m = re.fullmatch(r"(\d{4})[.\-/](\d{1,2}|\?\?)[.\-/](\d{1,2}|\?\?)", t)
    if m:
        j, mo, d = m.groups()
    else:
        m = re.fullmatch(r"(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4}|\d{2})", t)
        if m:
            d, mo, j = m.groups()
            if len(j) == 2:
                j = ("19" if int(j) > date.today().year % 100 else "20") + j
        else:
            m = re.fullmatch(r"(\d{1,2})[.\-/](\d{4})", t)
            if m:
                mo, j = m.groups()
                d = "??"
            elif re.fullmatch(r"\d{4}", t):
                j, mo, d = t, "??", "??"
            else:
                return "????.??.??", [Meldung("warnung", f"Datum „{t}“ nicht erkannt: es steht „????.??.??“ im PGN.")]  # lint-ok: doppelte-satzzeichen
    mo = mo if mo == "??" else f"{int(mo):02d}"
    d = d if d == "??" else f"{int(d):02d}"
    out, meld = f"{j}.{mo}.{d}", []
    if mo != "??" and not 1 <= int(mo) <= 12 or d != "??" and not 1 <= int(d) <= 31:
        return "????.??.??", [Meldung("warnung", f"Datum „{t}“ ist kein gültiges Datum: es steht „????.??.??“ im PGN.")]  # lint-ok: doppelte-satzzeichen
    if "?" not in out:
        try:
            if date(int(j), int(mo), int(d)) > date.today():
                meld.append(Meldung("warnung", "Das Datum liegt in der Zukunft."))
        except ValueError:
            return "????.??.??", [Meldung("warnung", f"„{t}“ gibt es im Kalender nicht: es steht „????.??.??“ im PGN.")]  # lint-ok: doppelte-satzzeichen
    if "?" in out:
        meld.append(Meldung("info", "Datum unvollständig, fehlende Teile stehen als „??“."))  # lint-ok: doppelte-satzzeichen
    return out, meld


def normiere_kopf(kopf: dict) -> tuple[dict, list[Meldung]]:
    """Bereinigt die Kopfdaten fürs PGN. Gibt die Tags (Namen aus dem PGN-Standard) und Meldungen zurück."""
    meld: list[Meldung] = []
    out = dict(STANDARD)
    for k in ("Event", "Site", "Round", "White", "Black"):
        v = " ".join(str(kopf.get(k, "") or "").split())
        if v:
            out[k] = v
    out["Date"], dm = normiere_datum(str(kopf.get("Date", "") or ""))
    meld += dm
    roh = str(kopf.get("Result", "") or "")
    erg = normiere_ergebnis(roh)
    if roh.strip() and not erg:
        meld.append(Meldung("warnung", f"Ergebnis „{roh.strip()}“ nicht erkannt (erlaubt: 1-0, 0-1, 1/2-1/2, *): es steht „*“ im PGN."))
    out["Result"] = erg or "*"
    if out["White"] == "?" or out["Black"] == "?":
        meld.append(Meldung("warnung", "Name von Weiß oder Schwarz fehlt: in einer Datenbank lässt sich die Partie so schlecht wiederfinden."))
    for farbe in ("White", "Black"):
        n = out[farbe]
        if n != "?" and "," not in n and " " in n:
            meld.append(Meldung("info", f"{farbe}: Datenbanken führen Namen als „Nachname, Vorname“ („{n}“ steht so im PGN)."))
    for k in OPTIONAL:
        v = str(kopf.get(k, "") or "").strip()
        if not v:
            continue
        if re.fullmatch(r"\d{3,4}", v) and 0 < int(v) <= 3500:
            out[k] = v
        else:
            meld.append(Meldung("warnung", f"{k} „{v}“ ist keine Zahl zwischen 1 und 3500 und fehlt im PGN."))
    return out, meld


def _tagwert(wert: str) -> str:
    return wert.replace("\\", "\\\\").replace('"', '\\"')


def _kommentar(text: str) -> str:
    return " ".join(text.replace("{", "(").replace("}", ")").split())


def zugtext(eintraege: list, kommentare: bool = False) -> str:
    """Zugliste im PGN-Exportformat. `eintraege`: Objekte mit ply, san, nag und kommentar (ZugErgebnis oder Ersatz)."""
    teile: list[str] = []
    zuvor_kommentar = True
    for e in eintraege:
        w = e.ply % 2 == 0
        if w:
            teile.append(f"{e.ply // 2 + 1}.")
        elif zuvor_kommentar:
            teile.append(f"{e.ply // 2 + 1}...")
        teile.append(e.san)
        if getattr(e, "nag", None):
            teile.append(f"${e.nag}")
        text = getattr(e, "kommentar", "") if kommentare else ""
        zuvor_kommentar = bool(text)
        if text:
            teile.append("{" + _kommentar(text) + "}")
    return teile_zu_zeilen(teile)


def teile_zu_zeilen(teile: list[str]) -> str:
    zeilen, zeile = [], ""
    for t in teile:
        if zeile and len(zeile) + 1 + len(t) > UMBRUCH:
            zeilen.append(zeile)
            zeile = t
        else:
            zeile = f"{zeile} {t}" if zeile else t
    if zeile:
        zeilen.append(zeile)
    return "\n".join(zeilen)


def pgn(kopf: dict, eintraege: list, kommentare: bool = False, ergebnis: str | None = None) -> str:
    """Ganzes PGN. `kopf` ist schon bereinigt (siehe normiere_kopf)."""
    tags = [(k, kopf[k]) for k in SIEBEN + OPTIONAL if k in kopf]
    ergebnis = ergebnis or kopf["Result"]
    kopfzeilen = "\n".join(f'[{k} "{_tagwert(v)}"]' for k, v in tags)
    zuege = zugtext(eintraege, kommentare)
    # Das Ergebnis schließt die Zugliste ab; passt es nicht mehr in die Zeile, kommt es in die nächste.
    letzte = zuege.split("\n")[-1] if zuege else ""
    zuege = (zuege + (" " if letzte and len(letzte) + 1 + len(ergebnis) <= UMBRUCH else "\n" if zuege else "") + ergebnis)
    return f"{kopfzeilen}\n\n{zuege}\n"


# --------------------------------------------------------------------------- Text -> Formularzellen
def _ohne_klammern(text: str) -> tuple[str, int]:
    """Entfernt Kommentare {…}, Zeilenkommentare ;… und Varianten (…); zählt die entfernten Varianten."""
    text = re.sub(r"\{[^}]*\}", " ", text)
    text = re.sub(r";[^\n]*", " ", text)
    varianten = 0
    while True:
        neu, n = re.subn(r"\([^()]*\)", " ", text)
        varianten += n
        if n == 0:
            break
        text = neu
    return text, varianten


def text_zu_zellen(text: str) -> tuple[dict, list[list[str]], list[Meldung]]:
    """Zerlegt abgetippten Text (nur Züge oder ein ganzes PGN) in Kopfdaten und Zeilen (Weiß, Schwarz). Zugnummern bestimmen die Zeile;
    fehlt eine Antwort, bleibt die Zelle leer."""
    meld: list[Meldung] = []
    kopf: dict = {}
    zeilen = []
    for z in text.splitlines():
        m = TAG_ZEILE.match(z)
        if m:
            kopf[m.group(1)] = m.group(2).replace('\\"', '"').replace("\\\\", "\\")
        else:
            zeilen.append(z)
    rumpf, varianten = _ohne_klammern("\n".join(zeilen))
    if varianten:
        meld.append(Meldung("warnung", f"{varianten} Variante(n) in Klammern entfernt: das Formular kennt nur die Hauptlinie."))
    rumpf = re.sub(r"\$\d+", " ", rumpf)
    rumpf = re.sub(r"(?<![\w.])(\d{1,3})(\.{1,3})(?!\d)", r"\1\2 ", rumpf)
    rows: list[list[str]] = []
    nr, spalte = 1, 0
    for tok in rumpf.split():
        mn = re.fullmatch(r"(\d+)(\.{1,3})", tok)
        if mn:
            nr, spalte = int(mn.group(1)), 0 if len(mn.group(2)) == 1 else 1
            continue
        if tok.lower() in ERGEBNISSE:
            kopf.setdefault("Result", ERGEBNISSE[tok.lower()])
            continue
        while len(rows) < nr:
            rows.append(["", ""])
        rows[nr - 1][spalte] = tok
        if spalte == 0:
            spalte = 1
        else:
            nr, spalte = nr + 1, 0
    return kopf, rows, meld


def zellen_zu_text(zellen: list) -> str:
    """Zellen als lesbarer Zugtext („1. e4 e5 2. Sf3“), zum Kopieren."""
    teile = []
    for i, (w, s) in enumerate(zellen, start=1):
        if (w or "").strip() or (s or "").strip():
            teile.append(f"{i}. {(w or '').strip()} {(s or '').strip()}".rstrip())
    return " ".join(teile)
