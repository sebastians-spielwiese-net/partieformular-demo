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
SCHWELLE_PASSUNG = -3.0       # Passung (log P des Zugs zum Zellbild minus log P des besten Zeichenpfads) darunter: der Zug passt schlecht zur Zelle
SCHWELLE_UNSICHER = 0.95      # Zug, den das Bild der Zelle allein mit weniger Anteil unter den legalen Zügen sieht, gilt als unsicher (siehe `Entscheidung.unsicher`)


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


# --------------------------------------------------------------------------- Partie aus dem Bild entschlüsseln
@dataclass
class Entscheidung:
    ply: int
    san: str
    wahrscheinlichkeit: float                          # Anteil der Hypothesen am Ende der Suche, die diesen Zug an dieser Stelle haben (nach `temperatur` abgeflacht)
    alternativen: list = field(default_factory=list)   # [(SAN, Wahrscheinlichkeit)] der nächsten Züge
    zellanteil: float = 1.0                            # Anteil des Zugs unter allen legalen Zügen der Stellung, wenn nur das Bild dieser Zelle zählt
    bild_alternativen: list = field(default_factory=list)   # [(SAN, Anteil)] die nächsten Züge nach dem Bild dieser Zelle allein
    passung: float = 0.0                               # log P(Zug | Zellbild) minus log P des wahrscheinlichsten Zeichenpfads der Zelle: nahe 0 heißt, der Zug ist genau das, was das Bild zeigt

    def passt_schlecht(self) -> bool:
        """Der gewählte Zug weicht deutlich von dem ab, was das Bild der Zelle zeigt. An einem eigenen Scan waren 15 von 16 so markierten Halbzügen falsch (mit der Stufe „unsicher“ allein: 52 von 58 falschen, aber auch viele richtige)."""
        return self.passung < SCHWELLE_PASSUNG

    def unsicher(self) -> bool:
        """Zu markieren, wenn das Bild den Zug nicht klar vor allen anderen legalen Zügen sieht. Die Anteile der Hypothesen taugen dafür nicht: Sie sind überzuversichtlich
        (an einem eigenen Scan fielen mit ihnen 8 von 58 falschen Halbzügen auf, mit dem Zellanteil unter 0,95 waren es 52)."""
        return self.zellanteil < SCHWELLE_UNSICHER or self.wahrscheinlichkeit < 0.8


def _stellungsschluessel(st: B.Stellung) -> tuple:
    return (tuple(sorted(st.figuren.items())), st.am_zug, st.rochade, st.ep)


class Dekodierer:
    """Strahlsuche über die Halbzüge (Beschreibung bei `dekodiere`) mit Gedächtnis, damit eine Nachsuche nach einer Korrektur schnell ist:
    * Die Strahlen aller Halbzüge bleiben erhalten; ändert sich eine bestätigte Zelle, setzt `lauf` beim Strahl vor dieser Zelle wieder an, alles davor wird nicht neu gerechnet.
    * Die legalen Züge samt SAN je Stellung und die Bildwerte je (Halbzug, Zug) werden gemerkt und über alle Läufe wiederverwendet."""

    def __init__(self, lesung: FormularLesung, strahl: int = 100, strafdeckel: float | None = 12.0):
        self.zellen = []
        for c in lesung.zellen:
            if c.leer or c.logp is None:
                break
            self.zellen.append(c)
        self.strahl, self.strafdeckel = strahl, strafdeckel
        self._punkte: dict[tuple[int, str], float] = {}
        self._zuege: dict[tuple, list] = {}
        self._leer: dict[int, float] = {}
        self.strahlen: list[list] = [[(0.0, B.Stellung.start(), ())]]       # strahlen[p]: Hypothesen (Punktzahl, Stellung, Zugfolge) nach p Halbzügen
        self._fest: dict[int, str] = {}
        self.gescheitert: int | None = None                                # Halbzug, an dem eine bestätigte Zelle zu keiner Hypothese passte

    def punkte(self, ply: int, san: str) -> float:
        k = (ply, san)
        if k not in self._punkte:
            self._punkte[k] = zug_logwahrscheinlichkeit(self.zellen[ply].logp, san)
        return self._punkte[k]

    def zuege(self, st: B.Stellung) -> list:
        k = _stellungsschluessel(st)
        if k not in self._zuege:
            self._zuege[k] = [(st.san(z), z) for z in st.legale_zuege()]
        return self._zuege[k]

    def _schritt(self, hyp: list, ply: int, fest: dict[int, str]) -> list | None:
        import pf_notation as N
        import pf_pruefung as P

        kandidaten = []                                     # (Punktzahl, Index der Hypothese, Zug, SAN)
        for h, (score, st, folge) in enumerate(hyp):
            if st.ende() in ("matt", "patt", "material"):   # die Partie ist zu Ende: eine weitere Zelle muss leer aussehen, sonst kostet sie die Hypothese Punkte
                if ply not in self._leer:
                    self._leer[ply] = C.logwahrscheinlichkeit(self.zellen[ply].logp, [])
                leer = self._leer[ply]
                kandidaten.append((score + (max(leer, -self.strafdeckel) if self.strafdeckel is not None else leer), h, None, None))
                continue
            zuege = self.zuege(st)
            if ply in fest:                                 # bestätigte Zelle: nur Züge, die zum Text passen, und die Zelle kostet nichts
                passend = set(P.passende(st, N.lese(fest[ply]))[0])
                for s, z in zuege:
                    if z in passend:
                        kandidaten.append((score, h, z, s))
                continue
            werte = [self.punkte(ply, s) for s, _ in zuege]
            boden = (max(werte) - self.strafdeckel) if (self.strafdeckel is not None and werte) else None
            for (s, z), w in zip(zuege, werte):
                kandidaten.append((score + (max(w, boden) if boden is not None else w), h, z, s))
        if not kandidaten:
            return None
        kandidaten.sort(key=lambda k: -k[0])
        return [(score, hyp[h][1] if z is None else hyp[h][1].ausfuehren(z), hyp[h][2] if z is None else hyp[h][2] + (s,)) for score, h, z, s in kandidaten[:self.strahl]]

    def lauf(self, fest: dict[int, str] | None = None, temperatur: float = 1.0) -> list[Entscheidung]:
        """Sucht (weiter) mit den bestätigten Zellen `fest` (Halbzug -> Zelltext). Rückgabe: je Halbzug die Entscheidung der besten Hypothese."""
        if not self.zellen:
            return []
        fest = {k: v for k, v in (fest or {}).items() if k < len(self.zellen)}
        geaendert = [k for k in set(fest) | set(self._fest) if fest.get(k) != self._fest.get(k)]
        if geaendert:
            del self.strahlen[min(geaendert) + 1:]
        self.gescheitert = None
        for ply in range(len(self.strahlen) - 1, len(self.zellen)):
            neu = self._schritt(self.strahlen[ply], ply, fest)
            if neu is None:
                self.gescheitert = ply
                break
            self.strahlen.append(neu)
        self._fest = dict(fest)
        return self._entscheidungen(temperatur)

    def _entscheidungen(self, temperatur: float) -> list[Entscheidung]:
        hyp = self.strahlen[-1]
        scores = np.array([h[0] for h in hyp]) / temperatur
        w = np.exp(scores - np.logaddexp.reduce(scores))
        beste = hyp[int(np.argmax(scores))][2]
        st = B.Stellung.start()
        out = []
        for ply in range(len(beste)):
            summen: dict[str, float] = {}
            for wi, h in zip(w, hyp):
                if len(h[2]) > ply:
                    summen[h[2][ply]] = summen.get(h[2][ply], 0.0) + float(wi)
            rang = sorted(summen.items(), key=lambda t: -t[1])
            zuege = self.zuege(st)
            werte = np.array([self.punkte(ply, s) for s, _ in zuege]) if zuege else np.array([])
            anteil = float(np.exp(self.punkte(ply, beste[ply]) - np.logaddexp.reduce(werte))) if len(werte) else 1.0
            if len(werte):
                nach_bild = sorted(((s, float(np.exp(wert - np.logaddexp.reduce(werte)))) for (s, _), wert in zip(zuege, werte) if s != beste[ply]), key=lambda t: -t[1])[:3]
            else:
                nach_bild = []
            passung = float(self.punkte(ply, beste[ply]) - self.zellen[ply].logp.max(axis=1).sum())
            out.append(Entscheidung(ply, beste[ply], summen.get(beste[ply], 0.0), [(s, p) for s, p in rang if s != beste[ply]][:3], min(1.0, anteil), nach_bild, passung))
            st = st.ausfuehren(next(z for s, z in zuege if s == beste[ply]))
        return out


def dekodiere(lesung: FormularLesung, strahl: int = 100, strafdeckel: float | None = 12.0, temperatur: float = 1.0, fest: dict[int, str] | None = None) -> list[Entscheidung]:
    """Die wahrscheinlichste legale Partie zu den gelesenen Zellen: Strahlsuche über die Halbzüge. Jede Hypothese ist eine legale Zugfolge; ihre Punktzahl ist die Summe der
    Logwahrscheinlichkeiten, mit denen das Bild jeder Zelle zum jeweiligen Zug passt. Ein falsch gelesener Zug, der zu einer Stellung führt, in der die Folgezellen nicht mehr passen,
    verliert gegen den richtigen. `strafdeckel` begrenzt den Abzug für eine Zelle: Kein Zug wird in einer Stellung um mehr als diesen Wert schlechter gewertet als der beste Zug dort,
    damit eine unleserliche Zelle die Partie nicht abbricht und die Folgezellen den richtigen Zug bestimmen können (None: kein Deckel). Die Suche endet bei der ersten leeren Zelle;
    eine beendete Partie (Matt, Patt) bleibt im Rennen und zahlt für weitere nicht leere Zellen nur, was die Zelle als leer unwahrscheinlich ist; `strahl` Hypothesen bleiben je Halbzug erhalten.
    `fest` (Halbzug -> Zelltext): vom Nutzer bestätigte Zellen. Dort zählen nur Züge, die zum Text passen, und die Zelle kostet nichts. `temperatur` > 1 flacht die Anteile ab.
    Rückgabe: je Halbzug der Zug der besten Hypothese, sein Anteil an den Hypothesen am Ende und die stärksten Alternativen. Für mehrere Läufe nacheinander: `Dekodierer`."""
    return Dekodierer(lesung, strahl, strafdeckel).lauf(fest, temperatur)


def folgefehler_ab(unsicher: list[bool], fenster: int = 8, anteil: float = 0.75) -> int | None:
    """Fehler ziehen spätere Züge mit: Ab der ersten unsicheren Zelle eines Fensters, in dem mindestens drei Viertel der `fenster` Zellen unsicher sind (am Ende der Partie weniger Zellen, mindestens vier),
    ist ein früherer Fehler die wahrscheinlichste Ursache. `unsicher`: je Halbzug, ob die Zelle markiert ist (bestätigte Zellen gelten als sicher).
    An einem eigenen Scan war vor dem ersten Fehler (Halbzug 16) kein Zug falsch, danach 58 von 79."""
    n = len(unsicher)
    for i in range(n):
        teil = unsicher[i:i + fenster]
        if len(teil) >= min(fenster, 4) and sum(teil) >= anteil * len(teil):
            return next(j for j in range(i, n) if unsicher[j])
    return None
