"""Ein Formularbild lesen: Zellen schneiden, den Erkenner auf jede beschriebene Zelle anwenden, den Text mit „?“ bei unsicheren Zeichen liefern und
für jede Zelle die Wahrscheinlichkeit jedes legalen Zugs berechnen (Dekodierung gegen die Regeln, `Bewerter`).

Zwei Wege führen vom Bild zum Zug, und beide laufen in `pf_pruefung` zusammen:
* der **Text** der Zelle (gieriges Ergebnis des Erkenners, unsichere Zeichen als „?“) geht wie abgetippter Text durch die Lese- und Prüfregeln;
* die **Bildwahrscheinlichkeit** jedes legalen Zugs (CTC-Vorwärtsverfahren auf der Verteilung des Erkenners) ordnet Kandidaten bei Gleichstand, schlägt bei Regelverstößen
  Züge vor und meldet Zweifel, wenn ein legaler Zug zwar zum Text passt, aber ein anderer legaler Zug dem Bild fast ebenso gut entspricht.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

import pf_brett as B
import pf_ctc as C
import pf_raster as R
from pf_erkenner import Erkenner

SCHWELLE_ZEICHEN = 0.6        # Zeichen mit geringerer Sicherheit werden zu „?“


@dataclass
class ZellLesung:
    ply: int
    leer: bool
    text: str = ""
    logp: np.ndarray | None = field(default=None, repr=False)
    png: bytes = b""


@dataclass
class FormularLesung:
    zellen: list                 # eine ZellLesung je Halbzug, in Partiereihenfolge (Weiß, Schwarz, Weiß, …)

    def zeilen(self) -> list[list[str]]:
        z = []
        for i in range(0, len(self.zellen), 2):
            z.append([self.zellen[i].text, self.zellen[i + 1].text if i + 1 < len(self.zellen) else ""])
        return z

    def beschrieben(self) -> int:
        return sum(1 for c in self.zellen if not c.leer)


def als_png(bild: Image.Image, max_breite: int = 360) -> bytes:
    b = bild.convert("L")
    if b.width > max_breite:
        b = b.resize((max_breite, max(1, round(b.height * max_breite / b.width))), Image.BILINEAR)
    puffer = io.BytesIO()
    b.save(puffer, format="PNG")
    return puffer.getvalue()


def lese_formular(bild: Image.Image, raster: R.Raster, erkenner: Erkenner, schwelle: float = SCHWELLE_ZEICHEN, fortschritt=None) -> FormularLesung:
    """Schneidet das Formular nach `raster` und liest jede nicht leere Zelle. `fortschritt(i, n)` wird nach jeder Zelle aufgerufen."""
    paare = R.zellen(R.vorbereiten(bild), raster)
    n = 2 * len(paare)
    out: list[ZellLesung] = []
    for zug, paar in enumerate(paare):
        for spalte, zelle in enumerate(paar):
            ply = 2 * zug + spalte
            if R.ist_leer(zelle):
                out.append(ZellLesung(ply, True, png=als_png(zelle)))
            else:
                logp = erkenner.logp(zelle, ply)
                out.append(ZellLesung(ply, False, C.mit_joker(logp, schwelle, erkenner.zeichen), logp, als_png(zelle)))
            if fortschritt:
                fortschritt(ply + 1, n)
    while out and out[-1].leer:
        out.pop()
    return FormularLesung(out)


DEUTSCH = {"N": "S", "B": "L", "R": "T", "Q": "D"}


def deutsch(text: str) -> str:
    """Figurenbuchstaben deutsch: am Anfang (Figurenzug) und nach „=“ oder einer Ziffer (Umwandlung, auch ohne „=“). Das K bleibt, Bauernzüge beginnen mit einer Linie und ändern sich nicht."""
    z = list(text)
    for i, c in enumerate(z):
        if c in DEUTSCH and (i == 0 or z[i - 1] == "=" or z[i - 1].isdigit()):
            z[i] = DEUTSCH[c]
    return "".join(z)


def san_varianten(san: str) -> list[list[int]]:
    """Schreibweisen, in denen derselbe Zug auf dem Formular stehen kann (mit und ohne Schach- und Schlagzeichen, Umwandlung ohne „=“, englische und deutsche Figurenbuchstaben),
    als Klassennummern des Zeichensatzes."""
    kern = san.rstrip("+#")
    marken = san[len(kern):]
    ohne_x = kern.replace("x", "")
    texte = {san, kern, ohne_x, ohne_x + marken, kern.replace("=", ""), kern.replace("=", "") + marken}
    texte |= {deutsch(t) for t in texte}
    return [k for k in (C.kodiere(t) for t in sorted(texte)) if k]


def zug_logwahrscheinlichkeit(logp: np.ndarray, san: str) -> float:
    """log P(Bild zeigt diesen Zug): die Schreibweisen sind Alternativen für denselben Zug, ihre Wahrscheinlichkeiten werden addiert."""
    werte = [C.logwahrscheinlichkeit(logp, v) for v in san_varianten(san)]
    return float(np.logaddexp.reduce(werte)) if werte else C.NEG


class ZellBewerter:
    """Wahrscheinlichkeit jedes legalen Zugs einer Stellung für das Bild einer Zelle (normiert über die legalen Züge: das Bild zeigt einen davon)."""

    def __init__(self, logp: np.ndarray):
        self.logp = logp
        self._gemerkt: dict[str, dict[B.Zug, float]] = {}

    def wahrscheinlichkeiten(self, st: B.Stellung) -> dict[B.Zug, float]:
        schluessel = st.fen()
        if schluessel not in self._gemerkt:
            zuege = st.legale_zuege()
            werte = np.array([zug_logwahrscheinlichkeit(self.logp, st.san(z)) for z in zuege]) if zuege else np.array([])
            if len(werte):
                werte = werte - np.logaddexp.reduce(werte)
            self._gemerkt[schluessel] = {z: float(np.exp(w)) for z, w in zip(zuege, werte)}
        return self._gemerkt[schluessel]


class Bewerter:
    """Hält die Verteilungen aller Zellen eines gelesenen Formulars. `fuer(ply, roh)` gibt den ZellBewerter nur zurück, solange in der Zelle noch der vom Erkenner gelesene
    Text steht: Hat der Mensch die Zelle geändert, gilt seine Entscheidung und das Bild wird nicht mehr dagegen gehalten."""

    def __init__(self, lesung: FormularLesung):
        self.lesung = lesung
        self._zellen = {c.ply: ZellBewerter(c.logp) for c in lesung.zellen if not c.leer and c.logp is not None}
        self._texte = {c.ply: c.text for c in lesung.zellen}

    def fuer(self, ply: int, roh: str) -> ZellBewerter | None:
        if ply in self._zellen and (roh or "").strip() == self._texte.get(ply, "").strip():
            return self._zellen[ply]
        return None

    def png(self, ply: int) -> bytes:
        return self.lesung.zellen[ply].png if ply < len(self.lesung.zellen) else b""


# --------------------------------------------------------------------------- Raster suchen
def zell_guete(logp: np.ndarray) -> float:
    """Wie gut liest der Erkenner diese Zelle? Mittlere Sicherheit der Zeichen, aber nur wenn der gierige Text als Zug lesbar ist, sonst 0.
    Schlecht ausgerichtete Zellen (halbe Zeile, abgeschnittene Schrift) ergeben Zeichensalat, der nicht als Zug lesbar ist."""
    from pf_notation import lese
    text, sicher = C.gierig(logp)
    if not text or lese(text).art not in ("zug", "rochade"):
        return 0.0
    return float(np.mean(sicher))


def raster_guete(bild: Image.Image, raster: R.Raster, erkenner: Erkenner, proben: int = 12) -> float:
    """Güte eines Rasters aus den ersten `proben` Zeilen: Länge des regelkonformen Anfangs der gelesenen Züge (ein um eine Zeile verschobenes Raster liest lauter
    sichere, aber an der Stelle unmögliche Züge) plus mittlere Zellgüte (kleiner als 1) als Feinwertung."""
    import pf_pruefung as P
    texte, werte = [], []
    for zug, paar in enumerate(R.zellen(R.vorbereiten(bild), raster)[:proben]):
        for spalte, zelle in enumerate(paar):
            if R.ist_leer(zelle):
                texte.append("")
                continue
            logp = erkenner.logp(zelle, 2 * zug + spalte)
            texte.append(C.gierig(logp)[0])
            werte.append(zell_guete(logp))
    if not werte:
        return 0.0
    anfang = 0
    for e in P.pruefe([texte[i:i + 2] for i in range(0, len(texte), 2)]).zuege:
        if e.status not in ("ok", "hinweis"):
            break
        anfang += 1
    return anfang + float(np.mean(werte)) * 0.99


def suche_raster(bild: Image.Image, raster: R.Raster, erkenner: Erkenner, oben=(0.0, 0.01, 0.02, 0.03, 0.04), unten=(0.95, 0.97, 0.99, 1.0),
                 proben: int = 12) -> tuple[R.Raster, list[tuple[float, float, float]]]:
    """Probiert für die senkrechte Lage des Rasters (oben, unten) Werte durch und nimmt die mit der besten Zellgüte. Alles andere (Drehung, Zeilen, Blöcke, Spalten, links, rechts)
    bleibt, wie es ist. Gibt das Raster und alle Bewertungen (Güte, oben, unten) zurück, beste zuerst."""
    from dataclasses import replace
    bewertungen = []
    for o in oben:
        for u in unten:
            if u - o > 0.5:
                bewertungen.append((raster_guete(bild, replace(raster, oben=o, unten=u), erkenner, proben), o, u))
    bewertungen.sort(reverse=True)
    _, o, u = bewertungen[0]
    return replace(raster, oben=o, unten=u), bewertungen
