"""Verbindung zwischen Prüfung, PGN und Oberfläche ohne Streamlit: Zellen ändern, Ergebnis ableiten, Export wählen, Dateiname bilden.

Alle Änderungen an den Zellen laufen über Text: Ein Vorschlag wird übernommen, indem seine SAN in die Zelle geschrieben wird. So steht die Entscheidung des Menschen
im Formular selbst, und die Prüfung läuft danach auf demselben Weg wie bei jeder anderen Eingabe.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import pf_lesen as LS
import pf_pgn as G
import pf_pruefung as P

EXPORT_SAUBER = "sauber"
EXPORT_TEIL = "teil"
EXPORT_VORLAEUFIG = "vorlaeufig"


def zellen_tupel(zeilen: list) -> tuple:
    return tuple((str(w or ""), str(s or "")) for w, s in zeilen)


@lru_cache(maxsize=64)
def pruefe_gemerkt(zellen: tuple, buchstaben: str = "auto", bild=None) -> P.Pruefung:
    """Gemerkte Prüfung. `bild` (ein pf_lesen.Bewerter) wird über seine Identität verglichen: ein neu gelesenes Foto ist ein neuer Eintrag."""
    return P.pruefe(list(zellen), buchstaben, bild)


EN_ZU_DE = {"N": "S", "B": "L", "R": "T", "Q": "D"}


def in_schreibweise(san: str, system: str) -> str:
    """SAN in der Schreibweise des Formulars: für ein deutsches Formular S L T D statt N B R Q (auch bei der Umwandlung, „=D“)."""
    if system != "de":
        return san
    kopf = EN_ZU_DE.get(san[:1], san[:1]) if san[:1].isupper() and san[:1] != "O" else san[:1]
    return kopf + re.sub(r"=([NBRQ])", lambda m: "=" + EN_ZU_DE[m.group(1)], san[1:])


def schreibweise_des_formulars(p: P.Pruefung, einstellung: str) -> str:
    """„de“ oder „en“: wie Vorschläge ins Formular geschrieben werden. Auf einem Formular ohne Figurenbuchstaben gilt deutsch, wie die Seite."""
    if einstellung in ("de", "en"):
        return einstellung
    return "en" if p.system == "en" else "de"


def zelle_setzen(zeilen: list, ply: int, text: str) -> list:
    """Kopie der Zeilen mit geändertem Halbzug (0 = erster Zug von Weiß); fehlende Zeilen werden angehängt."""
    z = [list(r) for r in zeilen]
    while len(z) <= ply // 2:
        z.append(["", ""])
    z[ply // 2][ply % 2] = text
    return z


def ab_ply_loeschen(zeilen: list, ply: int) -> list:
    """Leert den Halbzug `ply` und alle folgenden."""
    z = [list(r) for r in zeilen]
    for i in range(ply, 2 * len(z)):
        z[i // 2][i % 2] = ""
    return z


def wirksames_ergebnis(kopf_ergebnis: str, p: P.Pruefung) -> tuple[str, str]:
    """Ergebnis fürs PGN und woher es kommt: Kopf des Formulars, sonst Zelle, sonst aus der Endstellung (Matt, Patt), sonst „*“."""
    erg = G.normiere_ergebnis(kopf_ergebnis)
    if erg:
        return erg, "Kopf des Formulars"
    if p.ergebnis_zelle:
        return p.ergebnis_zelle, "Ergebnis in der Zugliste"
    if p.ende == "matt":
        return ("0-1" if p.endstellung.am_zug == "w" else "1-0"), "aus dem Matt abgeleitet"
    if p.ende in ("patt", "material"):
        return "1/2-1/2", "aus der Endstellung abgeleitet (Remis)"
    return "*", "nicht angegeben"


@dataclass
class PgnZug:
    ply: int
    san: str
    nag: int | None = None
    kommentar: str = ""


def pgn_zuege(p: P.Pruefung, modus: str) -> list[PgnZug]:
    """Die Züge fürs PGN: sauber und teil nehmen nur gesicherte Zellen (teil: bis vor die erste offene Stelle), vorläufig auch die gewählten Vorschläge mit Kommentar."""
    if modus == EXPORT_VORLAEUFIG:
        eintraege = p.san_liste(bis_zum_problem=False)
    else:
        eintraege = p.san_liste(bis_zum_problem=True)
    out = []
    for e in eintraege:
        kommentar = ""
        if e.status == "unklar":
            kommentar = f"Formular: „{e.roh.strip() or 'leer'}“, unklar, Vorschlag der Regelprüfung"
        out.append(PgnZug(e.ply, e.san, e.nag, kommentar))
    return out


def export_modi(p: P.Pruefung) -> list[str]:
    """Welche PGN-Arten sich für diese Prüfung anbieten."""
    if p.datenbanktauglich():
        return [EXPORT_SAUBER]
    modi = []
    z = p.zaehlen()
    if any(e.status in ("ok", "hinweis") for e in p.zuege):
        modi.append(EXPORT_TEIL)
    if z["unklar"] and not z["illegal"] and not z["nach_ende"]:
        modi.append(EXPORT_VORLAEUFIG)
    return modi


def pgn_text(kopf_roh: dict, p: P.Pruefung, modus: str) -> tuple[str, list]:
    """PGN-Text und die Meldungen zum Kopf. Bei „teil“ und „vorläufig“ steht das Ergebnis des Formulars nur, wenn die Partie bis dahin vollständig ist, sonst „*“."""
    kopf, meld = G.normiere_kopf(kopf_roh)
    erg, _ = wirksames_ergebnis(kopf_roh.get("Result", ""), p)
    vollstaendig = modus in (EXPORT_SAUBER, EXPORT_VORLAEUFIG)
    kopf["Result"] = erg if vollstaendig else "*"
    zuege = pgn_zuege(p, modus)
    return G.pgn(kopf, zuege, kommentare=modus == EXPORT_VORLAEUFIG), meld


def dateiname(kopf_roh: dict, modus: str = EXPORT_SAUBER) -> str:
    def teil(s: str) -> str:
        s = (s or "").split(",")[0]
        s = s.translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}))
        s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
        return s[:24]
    datum, _ = G.normiere_datum(str(kopf_roh.get("Date", "")))
    teile = [teil(kopf_roh.get("White", "")) or "Weiss", teil(kopf_roh.get("Black", "")) or "Schwarz", datum.replace("?", "").strip(".").replace("..", ".")]
    name = "_".join(t for t in teile if t)
    return name + ("" if modus == EXPORT_SAUBER else f"_{modus}") + ".pgn"


def _prozent(x: float) -> str:
    return f"{100 * x:.0f} %"


def bild_hinweis(u: LS.Entscheidung, schreibweise: str = "en") -> str:
    """Ein Satz zu einer markierten Zelle, passend zum Grund der Markierung: schlechte Passung, Bildanteil unter der Schwelle oder uneinige Suche.
    Züge stehen in der Schreibweise des Formulars (`schreibweise`: "de" oder "en")."""
    san = in_schreibweise(u.san, schreibweise)
    nach_bild = [(in_schreibweise(s, schreibweise), a) for s, a in u.bild_alternativen if a >= 0.02]
    liste = ", ".join(f"{s} ({_prozent(a)})" for s, a in nach_bild)
    if u.passt_schlecht():
        satz = f"Die Zelle sieht deutlich anders aus, als {san} aussehen müsste"
        if nach_bild and nach_bild[0][1] > u.zellanteil:
            satz += f"; nach dem Bild allein wäre eher {liste} gemeint"
        return satz + "."
    if u.zellanteil < LS.SCHWELLE_UNSICHER:
        if liste:
            return f"Das Bild ist nicht eindeutig: {san} ({_prozent(u.zellanteil)}), daneben {liste}."
        return f"Das Bild ist nicht eindeutig: {san} bekommt {_prozent(u.zellanteil)} unter den legalen Zügen, der Rest verteilt sich auf viele andere."
    alternativen = ", ".join(f"{in_schreibweise(s, schreibweise)} ({_prozent(a)})" for s, a in u.alternativen if a >= 0.02)
    return f"Die Suche war sich hier nicht einig: {san} ({_prozent(u.wahrscheinlichkeit)})" + (f", daneben {alternativen}" if alternativen else "") + "."
