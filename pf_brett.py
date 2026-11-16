"""Schachregeln für die Demo (nur Standardbibliothek): Stellung, legale Züge, Zug ausführen, SAN schreiben, Partieende erkennen.

Felder sind Zahlen von 0 (a1) bis 63 (h8): Feld = Spalte + 8 * Reihe. Ein Zug ist ein `Zug(von, nach, umw)`; die Rochade ist ein Königszug um zwei Felder
(e1g1), ein Schlag en passant ein Bauernzug auf das übersprungene Feld. Die Regeln sind die der FIDE für normales Schach (kein Schach960).
tests/test_brett.py prüft alles gegen python-chess (nur im Test, nicht in der App): bekannte Zählungen (Perft), Zuglisten, SAN und FEN in Zufallspartien.
"""
from __future__ import annotations

from typing import NamedTuple

FILES = "abcdefgh"
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FIGURNAMEN = {"P": "Bauer", "N": "Springer", "B": "Läufer", "R": "Turm", "Q": "Dame", "K": "König"}
SEITENNAMEN = {"w": "Weiß", "b": "Schwarz"}


class Zug(NamedTuple):
    von: int
    nach: int
    umw: str = ""      # "", "Q", "R", "B" oder "N"

    @property
    def uci(self) -> str:
        return name(self.von) + name(self.nach) + self.umw.lower()


def name(sq: int) -> str:
    return f"{FILES[sq % 8]}{sq // 8 + 1}"


def index(feld: str) -> int:
    if len(feld) != 2 or feld[0] not in FILES or feld[1] not in "12345678":
        raise ValueError(f"kein Feld: {feld!r}")
    return FILES.index(feld[0]) + 8 * (int(feld[1]) - 1)


def zug_aus_uci(uci: str) -> Zug:
    return Zug(index(uci[:2]), index(uci[2:4]), uci[4:5].upper())


def _schritt(sq: int, df: int, dr: int) -> int | None:
    f, r = sq % 8 + df, sq // 8 + dr
    return f + 8 * r if 0 <= f < 8 and 0 <= r < 8 else None


KNIGHT = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def _strahl(sq: int, df: int, dr: int) -> tuple[int, ...]:
    out, t = [], _schritt(sq, df, dr)
    while t is not None:
        out.append(t)
        t = _schritt(t, df, dr)
    return tuple(out)


SPRUNG = {"N": [tuple(t for t in (_schritt(s, *d) for d in KNIGHT) if t is not None) for s in range(64)],
          "K": [tuple(t for t in (_schritt(s, *d) for d in KING) if t is not None) for s in range(64)]}
STRAHLEN = {"R": [tuple(_strahl(s, *d) for d in ROOK_DIRS) for s in range(64)],
            "B": [tuple(_strahl(s, *d) for d in BISHOP_DIRS) for s in range(64)]}
STRAHLEN["Q"] = [STRAHLEN["R"][s] + STRAHLEN["B"][s] for s in range(64)]
# Rochaderechte, die verfallen, wenn ein Zug von oder auf dieses Feld geht
RECHTE_VERLUST = {index("e1"): "KQ", index("a1"): "Q", index("h1"): "K", index("e8"): "kq", index("a8"): "q", index("h8"): "k"}
ANDERE = {"w": "b", "b": "w"}


class Stellung:
    """Stellung mit Zugrecht, Rochaderechten, en-passant-Feld, Zähler für die 50-Züge-Regel und die Zugnummer. Unveränderlich benutzt."""

    __slots__ = ("figuren", "am_zug", "rochade", "ep", "halbzuege", "zugnummer", "_legal", "_schach")

    def __init__(self, figuren: dict, am_zug: str = "w", rochade: str = "KQkq", ep: int | None = None, halbzuege: int = 0, zugnummer: int = 1):
        self.figuren = figuren          # Feld -> (Farbe "w"/"b", Buchstabe PNBRQK)
        self.am_zug = am_zug
        self.rochade = rochade          # Teilmenge von "KQkq", in dieser Reihenfolge
        self.ep = ep                    # Feld, das der letzte Doppelschritt eines Bauern übersprungen hat (immer gesetzt, auch ohne Schlagmöglichkeit)
        self.halbzuege = halbzuege
        self.zugnummer = zugnummer
        self._legal: list[Zug] | None = None
        self._schach: bool | None = None

    # ------------------------------------------------------------------ FEN
    @staticmethod
    def start() -> "Stellung":
        return Stellung.aus_fen(START_FEN)

    @staticmethod
    def aus_fen(fen: str) -> "Stellung":
        teile = fen.split()
        reihen = teile[0].split("/")
        if len(reihen) != 8:
            raise ValueError(f"FEN braucht 8 Reihen: {fen!r}")
        figuren = {}
        for i, reihe in enumerate(reihen):
            rank, col = 7 - i, 0
            for ch in reihe:
                if ch.isdigit():
                    col += int(ch)
                    continue
                if ch.upper() not in FIGURNAMEN or col > 7:
                    raise ValueError(f"ungültige FEN-Reihe {reihe!r}")
                figuren[col + 8 * rank] = ("w" if ch.isupper() else "b", ch.upper())
                col += 1
            if col != 8:
                raise ValueError(f"FEN-Reihe {reihe!r} hat {col} statt 8 Felder")
        am_zug = teile[1] if len(teile) > 1 else "w"
        rochade = "".join(c for c in "KQkq" if len(teile) > 2 and c in teile[2])
        ep = index(teile[3]) if len(teile) > 3 and teile[3] != "-" else None
        return Stellung(figuren, am_zug, rochade, ep, int(teile[4]) if len(teile) > 4 else 0, int(teile[5]) if len(teile) > 5 else 1)

    def platzierung(self) -> str:
        reihen = []
        for rank in range(7, -1, -1):
            s, leer = "", 0
            for col in range(8):
                p = self.figuren.get(col + 8 * rank)
                if p is None:
                    leer += 1
                    continue
                s += (str(leer) if leer else "") + (p[1] if p[0] == "w" else p[1].lower())
                leer = 0
            reihen.append(s + (str(leer) if leer else ""))
        return "/".join(reihen)

    def fen(self) -> str:
        """FEN; das en-passant-Feld steht nur, wenn ein Schlag en passant wirklich möglich ist (wie bei python-chess)."""
        ep = name(self.ep) if self.ep is not None and self._ep_moeglich() else "-"
        return f"{self.platzierung()} {self.am_zug} {self.rochade or '-'} {ep} {self.halbzuege} {self.zugnummer}"

    def _ep_moeglich(self) -> bool:
        return any(z.nach == self.ep and self.figuren[z.von][1] == "P" and z.von % 8 != z.nach % 8 and z.nach not in self.figuren for z in self.legale_zuege())

    def schluessel(self) -> tuple:
        """Stellungsschlüssel für Wiederholungen: Figuren, Zugrecht, Rochaderechte, en passant nur wenn möglich."""
        return (self.platzierung(), self.am_zug, self.rochade, self.ep if self.ep is not None and self._ep_moeglich() else None)

    # ------------------------------------------------------------ Angriffe
    def angegriffen(self, sq: int, von: str) -> bool:
        """Greift eine Figur der Farbe `von` das Feld `sq` an? (Figuren auf dem Feld selbst spielen keine Rolle.)"""
        f = self.figuren
        for t in SPRUNG["N"][sq]:
            if f.get(t) == (von, "N"):
                return True
        for t in SPRUNG["K"][sq]:
            if f.get(t) == (von, "K"):
                return True
        dr = -1 if von == "w" else 1          # ein weißer Bauer greift von unten an: er steht eine Reihe unter dem Ziel
        for df in (-1, 1):
            t = _schritt(sq, df, dr)
            if t is not None and f.get(t) == (von, "P"):
                return True
        for ray in STRAHLEN["R"][sq]:
            for t in ray:
                p = f.get(t)
                if p is not None:
                    if p[0] == von and p[1] in "RQ":
                        return True
                    break
        for ray in STRAHLEN["B"][sq]:
            for t in ray:
                p = f.get(t)
                if p is not None:
                    if p[0] == von and p[1] in "BQ":
                        return True
                    break
        return False

    def koenig(self, farbe: str) -> int | None:
        for s, p in self.figuren.items():
            if p == (farbe, "K"):
                return s
        return None

    def im_schach(self) -> bool:
        if self._schach is None:
            k = self.koenig(self.am_zug)
            self._schach = k is not None and self.angegriffen(k, ANDERE[self.am_zug])
        return self._schach

    # ------------------------------------------------------------- Züge
    def _pseudo(self) -> list[Zug]:
        f, farbe = self.figuren, self.am_zug
        out: list[Zug] = []
        for sq, (c, art) in f.items():
            if c != farbe:
                continue
            if art == "P":
                dr = 1 if farbe == "w" else -1
                start, letzte = (1, 7) if farbe == "w" else (6, 0)
                ein = _schritt(sq, 0, dr)
                if ein is not None and ein not in f:
                    self._bauer_zug(out, sq, ein, letzte)
                    zwei = _schritt(sq, 0, 2 * dr)
                    if sq // 8 == start and zwei not in f:
                        out.append(Zug(sq, zwei))
                for df in (-1, 1):
                    t = _schritt(sq, df, dr)
                    if t is None:
                        continue
                    if (t in f and f[t][0] != farbe) or t == self.ep:
                        self._bauer_zug(out, sq, t, letzte)
            elif art in "NK":
                for t in SPRUNG[art][sq]:
                    if t not in f or f[t][0] != farbe:
                        out.append(Zug(sq, t))
            else:
                for ray in STRAHLEN[art][sq]:
                    for t in ray:
                        if t in f:
                            if f[t][0] != farbe:
                                out.append(Zug(sq, t))
                            break
                        out.append(Zug(sq, t))
        out.extend(self._rochaden())
        return out

    @staticmethod
    def _bauer_zug(out: list[Zug], von: int, nach: int, letzte: int) -> None:
        if nach // 8 == letzte:
            out.extend(Zug(von, nach, u) for u in "QRBN")
        else:
            out.append(Zug(von, nach))

    def _rochaden(self) -> list[Zug]:
        farbe, gegner, f = self.am_zug, ANDERE[self.am_zug], self.figuren
        reihe = 0 if farbe == "w" else 7
        koenig = 4 + 8 * reihe
        if f.get(koenig) != (farbe, "K") or self.im_schach():
            return []
        out = []
        for recht, turm, leer, weg in (("K" if farbe == "w" else "k", 7, (5, 6), (5, 6)), ("Q" if farbe == "w" else "q", 0, (1, 2, 3), (3, 2))):
            if recht not in self.rochade or f.get(turm + 8 * reihe) != (farbe, "R"):
                continue
            if any(c + 8 * reihe in f for c in leer):
                continue
            if any(self.angegriffen(c + 8 * reihe, gegner) for c in weg):
                continue
            out.append(Zug(koenig, weg[1] + 8 * reihe))
        return out

    def pseudolegale_zuege(self) -> list[Zug]:
        """Alle Züge nach der Zugform, ohne zu prüfen, ob der eigene König danach im Schach steht (für die Begründungen)."""
        return self._pseudo()

    def legale_zuege(self) -> list[Zug]:
        if self._legal is None:
            self._legal = [z for z in self._pseudo() if self._koenig_sicher(z)]
        return self._legal

    def _koenig_sicher(self, zug: Zug) -> bool:
        nxt = self.ausfuehren(zug)
        k = nxt.koenig(self.am_zug)
        return k is not None and not nxt.angegriffen(k, nxt.am_zug)

    def ist_schlag(self, zug: Zug) -> bool:
        art = self.figuren[zug.von][1]
        return zug.nach in self.figuren or (art == "P" and zug.nach == self.ep and zug.von % 8 != zug.nach % 8)

    def ausfuehren(self, zug: Zug) -> "Stellung":
        """Führt einen Zug aus. Es wird nicht geprüft, ob er legal ist."""
        farbe, art = self.figuren[zug.von]
        neu = dict(self.figuren)
        del neu[zug.von]
        schlag = zug.nach in neu
        ep = None
        if art == "P":
            if zug.nach == self.ep and zug.von % 8 != zug.nach % 8 and not schlag:
                del neu[zug.nach - 8 if farbe == "w" else zug.nach + 8]
                schlag = True
            if abs(zug.nach - zug.von) == 16:
                ep = (zug.von + zug.nach) // 2
        if art == "K" and abs(zug.nach - zug.von) == 2:
            if zug.nach > zug.von:
                neu[zug.nach - 1] = neu.pop(zug.nach + 1)
            else:
                neu[zug.nach + 1] = neu.pop(zug.nach - 2)
        neu[zug.nach] = (farbe, zug.umw or art)
        verlust = RECHTE_VERLUST.get(zug.von, "") + RECHTE_VERLUST.get(zug.nach, "")
        rochade = "".join(c for c in self.rochade if c not in verlust)
        halb = 0 if art == "P" or schlag else self.halbzuege + 1
        return Stellung(neu, ANDERE[farbe], rochade, ep, halb, self.zugnummer + (1 if farbe == "b" else 0))

    # ------------------------------------------------------------- SAN
    def san(self, zug: Zug) -> str:
        """Zug in der Standardnotation SAN (englische Buchstaben), mit Zusatz bei Mehrdeutigkeit und mit + oder #."""
        farbe, art = self.figuren[zug.von]
        if art == "K" and abs(zug.nach - zug.von) == 2:
            s = "O-O" if zug.nach > zug.von else "O-O-O"
        else:
            ziel, schlag = name(zug.nach), self.ist_schlag(zug)
            if art == "P":
                s = (FILES[zug.von % 8] + "x" if schlag else "") + ziel + (f"={zug.umw}" if zug.umw else "")
            else:
                andere = [z for z in self.legale_zuege() if z.nach == zug.nach and z.von != zug.von and self.figuren[z.von][1] == art]
                zusatz = ""
                if andere:
                    if all(z.von % 8 != zug.von % 8 for z in andere):
                        zusatz = FILES[zug.von % 8]
                    elif all(z.von // 8 != zug.von // 8 for z in andere):
                        zusatz = str(zug.von // 8 + 1)
                    else:
                        zusatz = name(zug.von)
                s = art + zusatz + ("x" if schlag else "") + ziel
        nxt = self.ausfuehren(zug)
        if nxt.im_schach():
            s += "#" if not nxt.legale_zuege() else "+"
        return s

    # ---------------------------------------------------------- Partieende
    def ende(self) -> str | None:
        """„matt“, „patt“, „material“ (kein Matt mehr möglich) oder None. Wiederholungen und 75 Züge prüft die Partie (siehe `partieende`)."""
        if not self.legale_zuege():
            return "matt" if self.im_schach() else "patt"
        if self.zu_wenig_material():
            return "material"
        return None

    def zu_wenig_material(self) -> bool:
        """Keine Seite kann mattsetzen: König gegen König, König und ein Leichtfigur gegen König, Läufer nur auf Feldern einer Farbe."""
        rest = [(s, p[1]) for s, p in self.figuren.items() if p[1] != "K"]
        if not rest:
            return True
        if any(art in "PRQ" for _, art in rest):
            return False
        if len(rest) == 1:
            return True                                    # ein Läufer oder ein Springer
        if all(art == "B" for _, art in rest):
            return len({(s % 8 + s // 8) % 2 for s, _ in rest}) == 1
        return False

    def material(self) -> dict:
        z: dict = {}
        for _, (c, art) in self.figuren.items():
            z[(c, art)] = z.get((c, art), 0) + 1
        return z


def partieende(stellung: Stellung, wiederholungen: int, halbzuege: int | None = None) -> str | None:
    """Ende nach FIDE-Regel, die ohne Antrag gilt: matt, patt, material, „fuenffach“ (fünfmal dieselbe Stellung), „75“ (75 Züge ohne Bauernzug und Schlag)."""
    e = stellung.ende()
    if e:
        return e
    if wiederholungen >= 5:
        return "fuenffach"
    if (stellung.halbzuege if halbzuege is None else halbzuege) >= 150:
        return "75"
    return None
