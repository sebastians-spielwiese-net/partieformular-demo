"""Eine Zelle des Partieformulars lesen: aus dem, was jemand abgeschrieben hat, wird eine strukturierte `Lesung` (noch ohne Stellung).

Die Lesung erkennt deutsche (K D T L S) und englische (K Q R B N) Figurenbuchstaben, ausführliche Schreibweise (e2-e4, Sg1-f3), Schlagzeichen x und :, die Rochade
mit Nullen oder dem Buchstaben O, Umwandlung mit und ohne „=“, Schach- und Mattzeichen, Bewertungszeichen (! ?) und Figurensymbole. Ein „?“ mitten im Zug steht
für ein unleserliches Zeichen (Joker): „S?3“ heißt Springer auf irgendeine Linie, Reihe 3. Ob der Zug in der Stellung geht, entscheidet erst `pf_pruefung`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

ERGEBNISSE = {"1-0": "1-0", "1:0": "1-0", "0-1": "0-1", "0:1": "0-1", "1/2-1/2": "1/2-1/2", "1/2:1/2": "1/2-1/2", "1/2": "1/2-1/2",
              "0.5-0.5": "1/2-1/2", "0,5-0,5": "1/2-1/2", "remis": "1/2-1/2", "*": "*"}
FIGUR_BUCHSTABE = {"K": "K", "Q": "Q", "D": "Q", "R": "R", "T": "R", "B": "B", "L": "B", "N": "N", "S": "N"}
DEUTSCH, ENGLISCH = set("DTLS"), set("QRNB")                 # Buchstaben, die nur in der einen Schreibweise vorkommen (B: Läufer englisch; Bauern schreibt man nicht)
BEWERTUNG_NAG = {"!": 1, "?": 2, "!!": 3, "??": 4, "!?": 5, "?!": 6}
SYMBOLE = {"♔": "K", "♕": "Q", "♖": "R", "♗": "B", "♘": "N", "♙": "", "♚": "K", "♛": "Q", "♜": "R", "♝": "B", "♞": "N", "♟": ""}
ERSATZ = str.maketrans({"–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-", "×": "x", "X": "x", "†": "+", "‡": "#", "½": "1/2", "\u00a0": " ", "\u200b": ""})

BEWEGUNG = re.compile(r"^(?P<fig>[KQRBNDTLS?])?(?P<vd>[a-h?])?(?P<vr>[1-8?])?(?P<x>[x:\-])?(?P<zd>[a-h?])(?P<zr>[1-8?])(?:=?(?P<u>[QRBNDTLSqrbn?]))?$")
ROCHADE = re.compile(r"^([0oO])-?([0oO])(?:-?([0oO]))?$")


@dataclass
class Lesung:
    roh: str
    art: str = "zug"                 # leer, zug, rochade, unleserlich, ergebnis oder unlesbar (nicht als Zug zu erkennen)
    figur: str = "P"                 # P N B R Q K, „?“ bei unleserlichem Buchstaben
    von_datei: str = ""              # leer = nicht angegeben, „?“ = unleserlich
    von_reihe: str = ""
    ziel_datei: str = ""
    ziel_reihe: str = ""
    schlag: bool = False             # Schlagzeichen (x oder :) stand da
    umw: str = ""                    # Q R B N, „?“ = unleserlich
    schach: str = ""                 # „+“ oder „#“, wie abgeschrieben
    bewertung: str = ""              # ! ? !! ?? !? ?!
    rochade: str = ""                # „K“ kurz, „Q“ lang
    ergebnis: str = ""               # bei art == ergebnis
    ep: bool = False                 # Vermerk „e.p.“ stand da
    system: str = ""                 # „de“, „en“, „gemischt“ oder leer: welche Figurenbuchstaben standen da
    ausfuehrlich: bool = False       # von- und nach-Feld standen da (e2-e4)
    hinweise: list = field(default_factory=list)

    @property
    def unsicher(self) -> bool:
        """Enthält mindestens ein unleserliches Zeichen („?“)."""
        return self.art == "unleserlich" or "?" in (self.figur + self.von_datei + self.von_reihe + self.ziel_datei + self.ziel_reihe + self.umw)

    @property
    def nag(self) -> int | None:
        return BEWERTUNG_NAG.get(self.bewertung)


def _normieren(roh: str) -> tuple[str, list[str]]:
    hinweise: list[str] = []
    s = roh.strip()
    if any(c in s for c in SYMBOLE):
        s = "".join(SYMBOLE.get(c, c) for c in s)
        hinweise.append("Figurensymbole in Buchstaben umgesetzt")
    s = s.translate(ERSATZ)
    s = re.sub(r"\s+", "", s)
    m = re.match(r"^\d+\.{1,3}(?=.)", s)                       # „12.e4“ oder „12...e5“: Zugnummer im Feld
    if m:
        s = s[m.end():]
        hinweise.append("Zugnummer im Feld ignoriert")
    s = s.strip(".,;")
    return s, hinweise


def _locker(s: str) -> str:
    """Zweiter Leseversuch: erster Buchstabe in die übliche Groß-/Kleinschreibung (s -> S, E -> e). b und d bleiben, sie sind auch Linien."""
    if s[:1] in "kqrntls":
        return s[:1].upper() + s[1:]
    if s[:1] in "ACEFGH":
        return s[:1].lower() + s[1:]
    return s


def _ohne_joker(m: re.Match) -> bool:
    return "?" not in "".join(v or "" for v in m.groupdict().values())


def _rumpf(roh: str, t: str, schach: str, bewertung: str, hinweise: list[str]) -> Lesung | None:
    """Liest einen Zugrumpf ohne Schach- und Bewertungszeichen: Rochade oder Bewegung."""
    h = list(hinweise)
    ep = False
    mp = re.match(r"^(.*\d)e\.?p\.?$", t)
    if mp:
        t, ep = mp.group(1), True
        h.append("Vermerk „e.p.“ ignoriert")
    nachgestellt = t.endswith(":") and len(t) > 2         # ältere deutsche Schreibweise „Lc4:“
    if nachgestellt:
        t = t[:-1]
    r = ROCHADE.match(t)
    if r:
        return Lesung(roh, "rochade", rochade="Q" if r.group(3) else "K", schach=schach, bewertung=bewertung, hinweise=h)
    bm = BEWEGUNG.match(t)
    if bm is None:
        return None
    g = bm.groupdict()
    buchstaben = {c for c in (g["fig"] or "") + (g["u"] or "").upper() if c in FIGUR_BUCHSTABE}
    system = "gemischt" if buchstaben & DEUTSCH and buchstaben & ENGLISCH else "de" if buchstaben & DEUTSCH else "en" if buchstaben & ENGLISCH else ""
    fig = "P" if not g["fig"] else "?" if g["fig"] == "?" else FIGUR_BUCHSTABE[g["fig"]]
    umw = "" if not g["u"] else "?" if g["u"] == "?" else FIGUR_BUCHSTABE[g["u"].upper()]
    ausfuehrlich = bool(g["vd"] and g["vr"] and "?" not in (g["vd"], g["vr"]))
    if ausfuehrlich:
        h.append("ausführliche Schreibweise (von-nach) gelesen")
    if g["x"] == ":" or nachgestellt:
        h.append("„:“ als Schlagzeichen gelesen")
    return Lesung(roh, "zug", fig, g["vd"] or "", g["vr"] or "", g["zd"], g["zr"], g["x"] in ("x", ":") or nachgestellt, umw, schach, bewertung, "", "", ep,
                  system, ausfuehrlich, h)


def _zug_lesen(roh: str, t: str, hinweise: list[str]) -> Lesung | None:
    schach, bew = "", ""
    m = re.search(r"([+#]{1,2})([!?]{0,2})$", t)
    if m:
        schach, bew, t = ("+" if m.group(1)[0] == "+" else "#"), m.group(2), t[:m.start()]
        if m.group(1) == "++":
            hinweise = hinweise + ["„++“ als Schach gelesen"]
    kandidaten = []
    tr = re.search(r"[!?]{1,2}$", t)
    if tr and not bew:
        kandidaten.append((t[:tr.start()], tr.group(), True))       # „Sf3?“: Bewertung, wenn der Rest ein vollständiger Zug ohne Joker ist
    kandidaten.append((t, bew, False))
    for rumpf, b, abgetrennt in kandidaten:
        erg = _rumpf(roh, rumpf, schach, b, hinweise)
        if erg is not None and not (abgetrennt and erg.unsicher):
            return erg
    return None


def lese(roh: str | None) -> Lesung:
    """Liest eine Zelle. Gibt immer eine Lesung zurück; `art` sagt, was erkannt wurde."""
    roh = "" if roh is None else str(roh)
    s, hinweise = _normieren(roh)
    if not s or set(s) <= set("-_…."):
        return Lesung(roh, "leer")
    if set(s) <= set("?"):
        return Lesung(roh, "unleserlich", figur="?", ziel_datei="?", ziel_reihe="?", hinweise=["Zug als unleserlich markiert"])
    if s.lower() in ERGEBNISSE:
        return Lesung(roh, "ergebnis", ergebnis=ERGEBNISSE[s.lower()], hinweise=hinweise)
    erg = _zug_lesen(roh, s, hinweise)
    if erg is None and _locker(s) != s:
        erg = _zug_lesen(roh, _locker(s), hinweise + ["Groß-/Kleinschreibung angepasst"])
    return erg if erg is not None else Lesung(roh, "unlesbar", hinweise=["Zeichenfolge nicht als Zug erkannt"])
