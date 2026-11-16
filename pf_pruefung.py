"""Die abgeschriebenen Zellen gegen die Schachregeln prüfen: Zug für Zug in der Stellung auflösen, Unklarheiten sammeln, Regelverstöße begründen.

Eine Zelle ist nach der Prüfung:
* ok: genau ein legaler Zug passt, und er steht in Standardnotation da (deutsche Buchstaben zählen mit),
* hinweis: genau ein legaler Zug passt, aber die Schreibweise wurde bereinigt (ausführliche Schreibweise, fehlendes x oder +, Zusatz, der nicht nötig ist),
* unklar: mehrere legale Züge passen (zwei Springer auf d2), die Umwandlungsfigur fehlt, ein Zeichen ist unleserlich oder der Zug fehlt. Die App wählt den Zug, nach dem
  die übrige Partie am längsten regelkonform bleibt, und nennt alle Kandidaten; der Mensch bestätigt, indem er die Zelle ändert,
* illegal: kein legaler Zug passt; die App begründet das und schlägt ähnliche legale Züge vor,
* nicht_pruefbar: steht hinter einem Regelverstoß, die Stellung ist ab da unbekannt.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pf_brett as B
from pf_notation import Lesung, lese

LOOKAHEAD = 40            # so viele Folgezüge prüft der Fortsetzungstest höchstens
MAX_KANDIDATEN = 8
ZWEIFEL_SICHER = 0.6       # ein Zug, der zum Text passt, gilt nach dem Bild als sicher, wenn er mindestens diese Wahrscheinlichkeit hat
ZWEIFEL_ANDERER = 0.15     # ... oder wenn kein anderer legaler Zug diese Wahrscheinlichkeit erreicht
BILD_MINDEST = 0.05        # Züge mit weniger Bildwahrscheinlichkeit werden nicht als Kandidaten nach dem Bild vorgeschlagen
BILD_ANZAHL = 4
FRUEHER_FENSTER = 10        # so viele Halbzüge vor einem Regelverstoß sucht die App nach einer früheren Ursache
FRUEHER_ANZAHL = 6


@dataclass
class Meldung:
    stufe: str            # info, warnung, fehler
    text: str


@dataclass
class Kandidat:
    zug: B.Zug
    san: str
    fortsetzung: int = 0          # so viele der folgenden Züge bleiben mit diesem Kandidaten eindeutig und legal
    ganz: bool = False            # die ganze übrige Partie bleibt regelkonform
    grund: str = ""
    bild: float | None = None     # Wahrscheinlichkeit dieses Zugs nach dem Bild der Zelle (unter den legalen Zügen), wenn die Zelle von einem Erkenner gelesen wurde


@dataclass
class ZugErgebnis:
    ply: int                      # 0 = erster Halbzug von Weiß
    roh: str
    lesung: Lesung
    status: str = "ok"            # ok, hinweis, unklar, illegal, nicht_pruefbar, leer, ergebnis, nach_ende
    zug: B.Zug | None = None
    san: str = ""
    meldungen: list = field(default_factory=list)
    kandidaten: list = field(default_factory=list)
    vor: B.Stellung | None = None          # Stellung vor dem Zug (für das Brett bei Problemen)
    nach: B.Stellung | None = None
    nag: int | None = None
    frueher: list = field(default_factory=list)   # bei Regelverstoß: (Halbzug, Kandidat) früherer Zellen, mit denen die Partie weiter hält

    @property
    def seite(self) -> str:
        return "w" if self.ply % 2 == 0 else "b"

    @property
    def zugnummer(self) -> int:
        return self.ply // 2 + 1

    @property
    def beschriftung(self) -> str:
        return f"{self.zugnummer}. {'Weiß' if self.ply % 2 == 0 else 'Schwarz'}"


@dataclass
class Pruefung:
    zuege: list
    endstellung: B.Stellung | None
    ende: str | None                      # matt, patt, material, fuenffach, 75
    ende_ply: int | None
    ergebnis_zelle: str                   # Ergebnis, das in einer Zelle stand („1-0“), sonst leer
    befunde: list = field(default_factory=list)      # Meldungen zur ganzen Partie
    system: str = ""                      # de, en, gemischt oder leer
    zaehler: dict = field(default_factory=dict)      # Stellungsschlüssel -> wie oft die Stellung vorkam
    schluessel_ende: tuple = ()

    def zaehlen(self) -> dict:
        z = {"ok": 0, "hinweis": 0, "unklar": 0, "illegal": 0, "nicht_pruefbar": 0, "nach_ende": 0}
        for e in self.zuege:
            if e.status in z:
                z[e.status] += 1
        return z

    @property
    def halbzuege(self) -> int:
        return sum(1 for e in self.zuege if e.status not in ("ergebnis",))

    def probleme(self) -> list:
        """Zellen, die Nacharbeit brauchen, in Partiereihenfolge: unklar, illegal, nach dem Ende. (nicht_pruefbar kommt erst nach dem Beheben der Vorgänger.)"""
        return [e for e in self.zuege if e.status in ("unklar", "illegal", "nach_ende")]

    def fehler_befunde(self) -> list:
        return [m for m in self.befunde if m.stufe == "fehler"]

    def datenbanktauglich(self) -> bool:
        z = self.zaehlen()
        return bool(self.zuege) and z["unklar"] == z["illegal"] == z["nicht_pruefbar"] == z["nach_ende"] == 0 and not self.fehler_befunde()

    def san_liste(self, bis_zum_problem: bool = False) -> list:
        """SAN aller aufgelösten Halbzüge; mit bis_zum_problem nur bis vor die erste Stelle, die nicht sauber ist."""
        out = []
        for e in self.zuege:
            if e.status in ("ok", "hinweis"):
                out.append(e)
            elif e.status in ("ergebnis", "leer"):
                continue
            elif bis_zum_problem:
                break
            elif e.status == "unklar" and e.san:
                out.append(e)
            else:
                break
        return out


# --------------------------------------------------------------------------- Abgleich einer Lesung mit den legalen Zügen
def _passt(st: B.Stellung, z: B.Zug, les: Lesung, schlag_streng: bool) -> bool:
    art = st.figuren[z.von][1]
    if les.figur != "?" and art != les.figur:
        return False
    ziel = B.name(z.nach)
    if les.ziel_datei not in ("?", ziel[0]) or les.ziel_reihe not in ("?", ziel[1]):
        return False
    von = B.name(z.von)
    if les.von_datei not in ("", "?") and les.von_datei != von[0]:
        return False
    if les.von_reihe not in ("", "?") and les.von_reihe != von[1]:
        return False
    if les.umw not in ("", "?"):
        if z.umw != les.umw:
            return False
    elif les.umw == "?" and not z.umw:
        return False
    if schlag_streng:
        schlag = st.ist_schlag(z)
        if art == "P" and les.von_datei not in ("", "?") and les.von_datei != ziel[0]:
            return schlag                                  # „ed5“: der Dateiwechsel zeigt den Schlag an
        if les.schlag != schlag:
            return False
    return True


def passende(st: B.Stellung, les: Lesung) -> tuple[list[B.Zug], bool]:
    """Legale Züge, die zur Lesung passen, und ob sie streng passen (Schlagzeichen stimmt). Streng zuerst, sonst ohne das Schlagzeichen."""
    if les.art == "rochade":
        koenig = 4 if st.am_zug == "w" else 60
        ziel = koenig + (2 if les.rochade == "K" else -2)
        return [z for z in st.legale_zuege() if z.von == koenig and z.nach == ziel and st.figuren[z.von][1] == "K"], True
    if les.art != "zug":
        return [], True
    legal = st.legale_zuege()
    streng = [z for z in legal if _passt(st, z, les, True)]
    if streng:
        return streng, True
    return [z for z in legal if _passt(st, z, les, False)], False


def eindeutig(st: B.Stellung, les: Lesung) -> B.Zug | None:
    """Der einzige passende Zug oder None. Fehlt die Umwandlungsfigur, gilt der Zug als nicht eindeutig."""
    z, _ = passende(st, les)
    if len(z) != 1:
        return None
    return z[0]


def fortsetzung(st: B.Stellung, rest: list[Lesung]) -> tuple[int, bool]:
    """Wie viele der folgenden Zellen sich eindeutig und legal ausführen lassen; zweiter Wert: die ganze Restpartie ging durch."""
    n = 0
    for les in rest:
        if les.art in ("leer", "ergebnis"):
            return n, all(r.art in ("leer", "ergebnis") for r in rest[n:])
        if n >= LOOKAHEAD:
            return n, False
        z = eindeutig(st, les)
        if z is None:
            return n, False
        st = st.ausfuehren(z)
        if les.schach and (not st.im_schach() or (les.schach == "#" and st.legale_zuege())):
            return n, False                            # das abgeschriebene Schach- oder Mattzeichen stimmt nicht: diese Linie passt nicht zum Formular
        n += 1
        if st.ende():
            return n, all(r.art in ("leer", "ergebnis") for r in rest[n:])
    return n, True


def _kandidat(st: B.Stellung, z: B.Zug, rest: list[Lesung], grund: str = "", bp: dict | None = None) -> Kandidat:
    n, ganz = fortsetzung(st.ausfuehren(z), rest)
    return Kandidat(z, st.san(z), n, ganz, grund, None if bp is None else bp.get(z, 0.0))


def _sortiert(kandidaten: list[Kandidat], les: Lesung) -> list[Kandidat]:
    def schluessel(k: Kandidat):
        passt_marke = les.schach == "" or k.san.endswith(les.schach)
        return (-k.fortsetzung, -(k.bild or 0.0), not passt_marke, k.san)
    return sorted(kandidaten, key=schluessel)


# --------------------------------------------------------------------------- Begründung bei Regelverstoß
def _feld_der(les: Lesung) -> int | None:
    if les.ziel_datei in ("", "?") or les.ziel_reihe in ("", "?"):
        return None
    return B.index(les.ziel_datei + les.ziel_reihe)


def _grund_rochade(st: B.Stellung, les: Lesung) -> str:
    farbe, gegner = st.am_zug, B.ANDERE[st.am_zug]
    reihe = 0 if farbe == "w" else 7
    lang = les.rochade == "Q"
    turm, zwischen, weg = (0, (1, 2, 3), (3, 2)) if lang else (7, (5, 6), (5, 6))
    art = "lange" if lang else "kurze"
    if st.figuren.get(4 + 8 * reihe) != (farbe, "K"):
        return f"{art.capitalize()} Rochade: Der König steht nicht mehr auf {B.name(4 + 8 * reihe)}."
    if st.figuren.get(turm + 8 * reihe) != (farbe, "R"):
        return f"{art.capitalize()} Rochade: Auf {B.name(turm + 8 * reihe)} steht kein Turm (mehr)."
    recht = ("Q" if lang else "K") if farbe == "w" else ("q" if lang else "k")
    if recht not in st.rochade:
        return f"{art.capitalize()} Rochade: Das Recht ist verfallen, weil sich König oder Turm schon einmal bewegt haben."
    belegt = [B.name(c + 8 * reihe) for c in zwischen if c + 8 * reihe in st.figuren]
    if belegt:
        return f"{art.capitalize()} Rochade: Zwischen König und Turm steht noch eine Figur ({', '.join(belegt)})."
    if st.im_schach():
        return "Rochade: Der König steht im Schach, und aus dem Schach heraus darf man nicht rochieren."
    bedroht = [B.name(c + 8 * reihe) for c in weg if st.angegriffen(c + 8 * reihe, gegner)]
    if bedroht:
        return f"{art.capitalize()} Rochade: Der König müsste über oder auf ein bedrohtes Feld ziehen ({', '.join(bedroht)})."
    return f"{art.capitalize()} Rochade ist in dieser Stellung nicht erlaubt."


def begruendung(st: B.Stellung, les: Lesung) -> str:
    """Ein Satz, warum der gelesene Zug in dieser Stellung nicht geht. Ist die Ursache nicht eindeutig, steht das da."""
    if les.art == "rochade":
        return _grund_rochade(st, les)
    if les.art != "zug":
        return "Die Zeichenfolge ist nicht als Zug zu erkennen."
    farbe = st.am_zug
    seite = B.SEITENNAMEN[farbe]
    fig = les.figur
    ziel = _feld_der(les)
    if fig == "?" or ziel is None:
        return "Kein legaler Zug passt zu den lesbaren Zeichen."
    figname = B.FIGURNAMEN[fig]
    ziel_name = B.name(ziel)
    # Gehört der Zug vielleicht der anderen Seite (Zug ausgelassen, Spalten vertauscht)?
    anders = B.Stellung(dict(st.figuren), B.ANDERE[farbe], st.rochade, None, st.halbzuege, st.zugnummer)
    if any(_passt(anders, z, les, False) for z in anders.legale_zuege()):
        return (f"Dieser Zug gehört {B.SEITENNAMEN[B.ANDERE[farbe]]}: Am Zug ist aber {seite}. Ein Zug ist ausgelassen oder die Spalten sind vertauscht.")
    eigene = [s for s, (c, a) in st.figuren.items() if c == farbe and a == fig]
    if les.von_datei not in ("", "?"):
        eigene = [s for s in eigene if B.name(s)[0] == les.von_datei]
    if les.von_reihe not in ("", "?"):
        eigene = [s for s in eigene if B.name(s)[1] == les.von_reihe]
    if not eigene:
        if les.von_datei not in ("", "?") or les.von_reihe not in ("", "?"):
            return f"Auf dem angegebenen Ausgangsfeld steht kein {figname} von {seite}."
        return f"{seite} hat {'keine' if fig == 'Q' else 'keinen'} {figname} mehr."
    if st.figuren.get(ziel, (None,))[0] == farbe:
        return f"Auf {ziel_name} steht schon eine eigene Figur."
    if fig == "P":
        return _grund_bauer(st, les, eigene, ziel, ziel_name, farbe)
    if les.umw not in ("", "?"):
        return "Eine Umwandlung gibt es nur beim Bauern auf der letzten Reihe."
    erreichbar, versperrt = [], []
    for s in eigene:
        if fig in "NK":
            if ziel in B.SPRUNG[fig][s]:
                erreichbar.append(s)
        else:
            for strahl in B.STRAHLEN[fig][s]:
                if ziel in strahl:
                    block = [t for t in strahl[:strahl.index(ziel)] if t in st.figuren]
                    (versperrt if block else erreichbar).append((s, block[0]) if block else s)
    if erreichbar:
        if fig == "K":
            return f"Das Feld {ziel_name} wird vom Gegner angegriffen: Ein König darf nicht ins Schach ziehen."
        if st.im_schach():
            return f"Der König von {seite} steht im Schach, und dieser Zug beendet das Schach nicht."
        return f"Der {figname} ist gefesselt: Der Zug ginge nach der Zugform, ließe aber den eigenen König im Schach stehen."
    if versperrt:
        s, b = versperrt[0]
        return f"Der Weg von {B.name(s)} nach {ziel_name} ist versperrt: Auf {B.name(b)} steht eine Figur."
    ort = " und ".join(B.name(s) for s in eigene[:3])
    return f"Ein {figname} von {ort} kann {ziel_name} nicht in einem Zug erreichen."


def _grund_bauer(st: B.Stellung, les: Lesung, eigene: list[int], ziel: int, ziel_name: str, farbe: str) -> str:
    dr = 1 if farbe == "w" else -1
    f = st.figuren
    schlag_gemeint = les.schlag or (les.von_datei not in ("", "?") and les.von_datei != ziel_name[0])
    if schlag_gemeint:
        if ziel not in f and ziel != st.ep:
            return f"Auf {ziel_name} steht keine gegnerische Figur, die ein Bauer schlagen könnte."
        if not any(abs(s % 8 - ziel % 8) == 1 and s // 8 + dr == ziel // 8 for s in eigene):
            return f"Kein eigener Bauer steht so, dass er {ziel_name} schräg vorwärts schlagen kann."
        return "Der Bauernschlag ginge, ließe aber den eigenen König im Schach stehen."
    if ziel in f:
        return f"Ein Bauer schlägt nicht geradeaus: Auf {ziel_name} steht schon eine Figur."
    auf_linie = [s for s in eigene if s % 8 == ziel % 8]
    if not auf_linie:
        return f"Auf der {ziel_name[0]}-Linie steht kein eigener Bauer, der nach {ziel_name} ziehen könnte (ein Schlag braucht das x und die Ausgangslinie)."
    s = auf_linie[0]
    abstand = (ziel // 8 - s // 8) * dr
    if abstand <= 0:
        return "Bauern ziehen nicht rückwärts oder seitwärts."
    if abstand > 2:
        return f"Ein Bauer zieht höchstens zwei Felder, und nur aus der Grundstellung: von {B.name(s)} nach {ziel_name} sind es {abstand}."
    if abstand == 2 and s // 8 != (1 if farbe == "w" else 6):
        return f"Der Doppelschritt ist nur aus der Grundstellung erlaubt, der Bauer steht auf {B.name(s)}."
    zwischen = s + 8 * dr
    if zwischen in f:
        return f"Der Weg ist versperrt: Auf {B.name(zwischen)} steht eine Figur."
    return "Der Zug ginge nach der Zugform, ließe aber den eigenen König im Schach stehen."


# --------------------------------------------------------------------------- Auflösung einer Zelle
def _meldungen_zu_zug(st: B.Stellung, z: B.Zug, les: Lesung, san: str, streng: bool) -> tuple[list[Meldung], bool]:
    """Hinweise zur Schreibweise; zweiter Wert: Die Zelle ist nicht genau in Standardnotation (Status hinweis statt ok)."""
    m = [Meldung("info", h) for h in les.hinweise if h != "Zug als unleserlich markiert"]
    abweichung = bool(les.hinweise)
    nxt = st.ausfuehren(z)
    schach = nxt.im_schach()
    matt = schach and not nxt.legale_zuege()
    echt = "#" if matt else "+" if schach else ""
    if les.schach != echt:
        if les.schach and not echt:
            m.append(Meldung("warnung", f"Auf dem Formular steht „{les.schach}“, aber {san} gibt kein Schach. Zug und Schachzeichen passen nicht zusammen."))
        elif les.schach == "+" and echt == "#":
            m.append(Meldung("info", "Auf dem Formular steht „+“, der Zug setzt aber matt (#)."))
        elif les.schach == "#" and echt == "+":
            m.append(Meldung("warnung", f"Auf dem Formular steht „#“ (Matt), aber {san} gibt nur Schach, die Partie geht weiter."))
        else:
            m.append(Meldung("info", f"Schach ({echt}) fehlt auf dem Formular und wurde ergänzt."))
        abweichung = True
    if les.art == "zug":
        art = st.figuren[z.von][1]
        if art == "K" and abs(z.nach - z.von) == 2:
            m.append(Meldung("info", "Als Rochade gelesen (auf dem Formular steht ein Königszug)."))
            abweichung = True
        schlag = st.ist_schlag(z)
        if not streng:
            if les.schlag and not schlag:
                m.append(Meldung("warnung", f"Auf dem Formular steht ein Schlagzeichen, aber {san} schlägt nichts."))
            elif schlag and not les.schlag:
                m.append(Meldung("info", "Das Schlagzeichen x fehlt auf dem Formular und wurde ergänzt."))
            abweichung = True
        elif art == "P" and schlag and not les.schlag:
            m.append(Meldung("info", "Das Schlagzeichen x fehlt auf dem Formular und wurde ergänzt."))
            abweichung = True
        zusatz = (les.von_datei + les.von_reihe).replace("?", "")
        if zusatz and art != "P" and zusatz not in san.split("x")[0][1:] and not les.ausfuehrlich:
            m.append(Meldung("info", f"Der Zusatz „{zusatz}“ ist nicht nötig, kein zweiter Zug dieser Art ist möglich."))
            abweichung = True
        if les.ausfuehrlich:
            abweichung = True
        if z.umw and not les.umw:
            abweichung = True
    return m, abweichung


def _prozent(p: float | None) -> str:
    return "?" if p is None else f"{100 * p:.0f} %"


def _nach_dem_bild(st: B.Stellung, kand: list[Kandidat], rest: list[Lesung], bp: dict | None) -> list[Kandidat]:
    """Ergänzt Kandidaten um die wahrscheinlichsten legalen Züge nach dem Bild (mindestens BILD_MINDEST, höchstens BILD_ANZAHL)."""
    if not bp:
        return kand
    vorhanden = {k.zug for k in kand}
    for z, p in sorted(bp.items(), key=lambda t: -t[1])[:BILD_ANZAHL]:
        if p >= BILD_MINDEST and z not in vorhanden:
            kand.append(_kandidat(st, z, rest, "nach dem Bild", bp))
    for k in kand:
        k.bild = bp.get(k.zug, 0.0)
    kand.sort(key=lambda k: (-k.fortsetzung, -(k.bild or 0.0), k.san))
    return kand


def _aufloesen(st: B.Stellung, les: Lesung, rest: list[Lesung], ply: int, luecke_ok: bool, bp: dict | None = None) -> ZugErgebnis:
    """Löst eine Zelle in der Stellung auf. `luecke_ok`: nach einer leeren Zelle folgen noch Züge (dann ist sie eine Lücke).
    `bp`: Bildwahrscheinlichkeit jedes legalen Zugs, wenn die Zelle von einem Erkenner gelesen wurde und noch unverändert ist."""
    erg = ZugErgebnis(ply, les.roh, les, vor=st, nag=les.nag)
    unleserlich = les.art in ("unleserlich", "unlesbar") or (les.art == "leer" and luecke_ok)
    if unleserlich:
        text = {"leer": "Der Zug fehlt im Formular (leere Zelle, danach geht es weiter).", "unleserlich": "Der Zug ist als unleserlich markiert.",
                "unlesbar": "Die Zeichenfolge ist nicht als Zug zu erkennen."}[les.art]
        kand = [_kandidat(st, z, rest, "", bp) for z in st.legale_zuege()]
        kand = _sortiert(kand, les)
        _unklar(erg, st, kand, [Meldung("warnung", text)], "Aus allen legalen Zügen ist der gewählt, nach dem die Partie am längsten regelkonform bleibt.")
        return erg
    treffer, streng = passende(st, les)
    if not treffer:
        erg.status = "illegal"
        grund = begruendung(st, les)
        erg.meldungen = [Meldung("fehler", f"Regelverstoß: {grund}")]
        erg.kandidaten = _nach_dem_bild(st, vorschlaege(st, les, rest), rest, bp)
        if bp and any((k.bild or 0.0) >= BILD_MINDEST for k in erg.kandidaten):
            # Aus einem Foto ist ein Lesefehler wahrscheinlicher als ein echter Regelverstoß: mit dem besten Zug nach dem Bild weiterprüfen, aber zur Bestätigung vorlegen.
            _unklar(erg, st, erg.kandidaten, [Meldung("warnung", f"Der gelesene Text „{les.roh.strip()}“ ist kein legaler Zug ({grund}) und wurde vermutlich falsch gelesen. "
                                                                  f"Das Bild passt am ehesten zu {erg.kandidaten[0].san} ({_prozent(erg.kandidaten[0].bild)}).")], "")
        return erg
    kand = _sortiert([_kandidat(st, z, rest, "", bp) for z in treffer], les) if len(treffer) > 1 else []
    if len(treffer) == 1 and bp and not les.unsicher and not (treffer[0].umw and les.umw in ("", "?")):
        z0 = treffer[0]
        p0 = bp.get(z0, 0.0)
        andere = max((p for z, p in bp.items() if z != z0), default=0.0)
        if p0 < ZWEIFEL_SICHER and andere >= ZWEIFEL_ANDERER:
            kand = _nach_dem_bild(st, [_kandidat(st, z0, rest, "passt zum Text", bp)], rest, bp)
            nahe = ", ".join(f"{k.san} {_prozent(k.bild)}" for k in kand if k.zug != z0)
            _unklar(erg, st, kand, [Meldung("warnung", f"Das Bild passt nicht sicher zum gelesenen Zug {st.san(z0)} ({_prozent(p0)}). Ähnlich wahrscheinlich: {nahe}.")], "")
            return erg
    if len(treffer) > 1 or les.unsicher or (treffer[0].umw and les.umw in ("", "?")):
        if not kand:
            kand = [_kandidat(st, treffer[0], rest)]
        ursache = []
        if les.unsicher:
            ursache.append(Meldung("warnung", "Unleserliches Zeichen („?“) ergänzt: " + ("nur ein legaler Zug passt." if len(treffer) == 1 else f"{len(treffer)} legale Züge passen.")))
        elif len(treffer) > 1 and any(z.umw for z in treffer) and len({z.nach for z in treffer}) == 1 and len({z.von for z in treffer}) == 1:
            ursache.append(Meldung("warnung", "Die Umwandlungsfigur fehlt auf dem Formular (Dame, Turm, Läufer oder Springer)."))
        elif len(treffer) > 1:
            ursache.append(Meldung("warnung", f"Mehrdeutig: {len(treffer)} legale Züge passen zu „{les.roh.strip()}“ (zum Beispiel zwei gleiche Figuren, die das Feld erreichen)."))
        else:
            ursache.append(Meldung("warnung", "Die Umwandlungsfigur fehlt auf dem Formular."))
        _unklar(erg, st, kand, ursache, "")
        return erg
    z = treffer[0]
    erg.zug, erg.san = z, st.san(z)
    erg.meldungen, abweichung = _meldungen_zu_zug(st, z, les, erg.san, streng)
    erg.status = "hinweis" if abweichung else "ok"
    erg.nach = st.ausfuehren(z)
    return erg


def _unklar(erg: ZugErgebnis, st: B.Stellung, kand: list[Kandidat], ursache: list[Meldung], zusatz: str) -> None:
    kand = kand[:MAX_KANDIDATEN] if len(kand) > MAX_KANDIDATEN else kand
    erg.status = "unklar"
    erg.kandidaten = kand
    erg.meldungen = list(ursache)
    if kand:
        erg.zug, erg.san = kand[0].zug, kand[0].san
        erg.nach = st.ausfuehren(kand[0].zug)
        gleich = [k for k in kand if (k.fortsetzung, k.ganz) == (kand[0].fortsetzung, kand[0].ganz)]
        if len(gleich) > 1 and len(kand) > 1 and kand[0].bild is not None:
            erg.meldungen.append(Meldung("warnung", f"{len(gleich)} Kandidaten lassen die übrige Partie gleich lang regelkonform: die Regeln allein entscheiden nicht. "
                                                    f"Nach dem Bild liegt {erg.san} vorn ({_prozent(kand[0].bild)}). Bitte am Formular prüfen."))
        elif len(gleich) > 1 and len(kand) > 1:
            erg.meldungen.append(Meldung("warnung", f"{len(gleich)} Kandidaten lassen die übrige Partie gleich lang regelkonform: die Regeln allein entscheiden nicht. "
                                                    f"Vorläufig gewählt: {erg.san}. Bitte am Formular prüfen."))
        elif len(kand) > 1:
            erg.meldungen.append(Meldung("info", f"Mit {erg.san} bleibt die übrige Partie am längsten regelkonform ({kand[0].fortsetzung} Folgezüge). "
                                                 "Vorläufig gewählt; bitte am Formular bestätigen."))
        else:
            erg.meldungen.append(Meldung("info", f"Vorläufig gewählt: {erg.san}. Bitte am Formular bestätigen."))
    if zusatz:
        erg.meldungen.append(Meldung("info", zusatz))


def vorschlaege(st: B.Stellung, les: Lesung, rest: list[Lesung], max_abweichung: int = 1) -> list[Kandidat]:
    """Ähnliche legale Züge für eine Zelle, die so nicht geht: höchstens `max_abweichung` Abweichungen in Figur, Ziellinie, Zielreihe oder angegebenem Ausgangsfeld."""
    punkte: list[tuple[int, B.Zug]] = []
    for z in st.legale_zuege():
        art, ziel, von = st.figuren[z.von][1], B.name(z.nach), B.name(z.von)
        fehl = 0
        fehl += les.figur not in ("?", art)
        fehl += les.ziel_datei not in ("?", ziel[0])
        fehl += les.ziel_reihe not in ("?", ziel[1])
        fehl += les.von_datei not in ("", "?", von[0])
        fehl += les.von_reihe not in ("", "?", von[1])
        if les.art == "rochade":
            fehl = 0 if art == "K" and abs(z.nach - z.von) == 2 else 9
        if fehl <= max_abweichung:
            punkte.append((fehl, z))
    kand = []
    for fehl, z in punkte:
        k = _kandidat(st, z, rest)
        k.grund = "anderes Zielfeld oder andere Linie/Reihe" if fehl else "passt"
        kand.append(k)
    kand.sort(key=lambda k: (-k.fortsetzung, k.san))
    return kand if max_abweichung > 1 else kand[:MAX_KANDIDATEN]


def fruehere_ursachen(ergebnisse: list[ZugErgebnis], lesungen: list[Lesung], i: int, zurueck: int = FRUEHER_FENSTER) -> list[tuple[int, Kandidat]]:
    """Ein Regelverstoß bei Halbzug i hat oft eine frühere Ursache: eine Zelle davor wurde falsch abgeschrieben, ist aber selbst legal.
    Gesucht: Züge für eine der letzten `zurueck` Zellen, die sich in höchstens zwei der Angaben Figur, Ziellinie, Zielreihe unterscheiden und mit denen die Partie
    über Halbzug i hinaus regelkonform bleibt."""
    gefunden: list[tuple[int, Kandidat]] = []
    for j in range(i - 1, max(-1, i - zurueck - 1), -1):
        e = ergebnisse[j]
        if e.status not in ("ok", "hinweis") or e.vor is None or e.zug is None:
            continue
        for k in vorschlaege(e.vor, lesungen[j], lesungen[j + 1:], max_abweichung=2):
            if k.zug != e.zug and k.fortsetzung >= i - j:
                gefunden.append((j, k))
    gefunden.sort(key=lambda t: (-(t[0] + t[1].fortsetzung), -t[0], t[1].san))
    return gefunden[:FRUEHER_ANZAHL]


# --------------------------------------------------------------------------- Partie prüfen
def zellen_zu_halbzuegen(zellen: list) -> list[str]:
    """Zeilen (Weiß, Schwarz) werden zu einer Folge von Halbzügen; leere Zellen am Ende fallen weg."""
    flach = []
    for zeile in zellen:
        w, s = (list(zeile) + ["", ""])[:2]
        flach += ["" if w is None else str(w), "" if s is None else str(s)]
    while flach and not flach[-1].strip():
        flach.pop()
    return flach


def pruefe(zellen: list, buchstaben: str = "auto", bild=None) -> Pruefung:
    """Prüft eine Partie. `zellen`: Liste von (Weiß, Schwarz). `buchstaben`: auto, de oder en (wie das Formular geschrieben ist).
    `bild`: optional ein `pf_lesen.Bewerter`, wenn die Zellen von einem Erkenner aus einem Foto gelesen wurden."""
    roh = zellen_zu_halbzuegen(zellen)
    lesungen = [lese(r) for r in roh]
    st = B.Stellung.start()
    zaehler = {st.schluessel(): 1}
    ergebnisse: list[ZugErgebnis] = []
    ende, ende_ply, ergebnis_zelle = None, None, ""
    gestoppt = False
    befunde: list[Meldung] = []
    for i, les in enumerate(lesungen):
        rest = lesungen[i + 1:]
        if les.art == "ergebnis":
            e = ZugErgebnis(i, les.roh, les, status="ergebnis", meldungen=[Meldung("info", f"Ergebnis „{les.ergebnis}“ im Formular, kein Zug.")])
            if any(r.art not in ("leer", "ergebnis") for r in rest):
                e.meldungen.append(Meldung("warnung", "Nach dem Ergebnis stehen noch Züge."))
            ergebnis_zelle = les.ergebnis
            ergebnisse.append(e)
            continue
        if gestoppt:
            ergebnisse.append(ZugErgebnis(i, les.roh, les, status="nicht_pruefbar" if les.art != "leer" else "leer"))
            continue
        if ende in ("matt", "patt", "material") and les.art != "leer":
            e = ZugErgebnis(i, les.roh, les, status="nach_ende", vor=st)
            e.meldungen = [Meldung("fehler", {"matt": "Die Partie war schon durch Matt beendet.", "patt": "Die Partie war schon durch Patt beendet (Remis).",
                                             "material": "Die Partie war schon beendet: Mit dem übrigen Material kann niemand mehr mattsetzen (Remis)."}[ende])]
            ergebnisse.append(e)
            gestoppt = True
            continue
        if les.art == "leer" and not any(r.art not in ("leer", "ergebnis") for r in rest):
            ergebnisse.append(ZugErgebnis(i, les.roh, les, status="leer"))
            continue
        zb = bild.fuer(i, roh[i]) if bild is not None else None
        e = _aufloesen(st, les, rest, i, les.art == "leer", zb.wahrscheinlichkeiten(st) if zb is not None else None)
        if e.status == "illegal":
            gestoppt = True
            ergebnisse.append(e)
            continue
        ergebnisse.append(e)
        if e.zug is None:
            gestoppt = True
            continue
        st = e.nach
        s = st.schluessel()
        zaehler[s] = zaehler.get(s, 0) + 1
        neu_ende = B.partieende(st, zaehler[s])
        if neu_ende and ende is None:
            ende, ende_ply = neu_ende, i
            if neu_ende in ("fuenffach", "75"):
                e.meldungen.append(Meldung("warnung", "Nach den FIDE-Regeln ist die Partie hier beendet: " + (
                    "dieselbe Stellung zum fünften Mal." if neu_ende == "fuenffach" else "75 Züge ohne Bauernzug und Schlag.")))
                ende = None
                ende_ply = None
    for e in ergebnisse:
        if e.status == "illegal":
            e.frueher = fruehere_ursachen(ergebnisse, lesungen, e.ply)
            break
    # Notationssystem
    de = sum(1 for e in ergebnisse if e.lesung.system in ("de", "gemischt"))
    en = sum(1 for e in ergebnisse if e.lesung.system in ("en", "gemischt"))
    system = "gemischt" if de and en else "de" if de else "en" if en else ""
    soll = system if buchstaben == "auto" else buchstaben
    if buchstaben == "auto" and system == "gemischt":
        befunde.append(Meldung("info", "Das Formular mischt deutsche (S, L, T, D) und englische (N, B, R, Q) Figurenbuchstaben. Beides wurde gelesen."))
    if buchstaben in ("de", "en"):
        falsch = [e for e in ergebnisse if e.lesung.system in (("en",) if soll == "de" else ("de",))]
        if falsch:
            namen = ", ".join(f"{e.zugnummer}. {'W' if e.ply % 2 == 0 else 'S'}" for e in falsch[:6])
            befunde.append(Meldung("warnung", f"{len(falsch)} Zelle(n) in {'englischen' if soll == 'de' else 'deutschen'} Buchstaben, obwohl das Formular als "
                                              f"{'deutsch' if soll == 'de' else 'englisch'} eingestellt ist ({namen}{', …' if len(falsch) > 6 else ''})."))
    return Pruefung(ergebnisse, st, ende, ende_ply, ergebnis_zelle, befunde, system, zaehler, st.schluessel())


def ergebnis_befunde(p: Pruefung, ergebnis_kopf: str) -> list[Meldung]:
    """Vergleicht das Ergebnis aus dem Kopf des Formulars (und aus einer Zelle) mit der Endstellung."""
    out: list[Meldung] = []
    erg = ergebnis_kopf
    if p.ergebnis_zelle and erg and p.ergebnis_zelle != erg:
        out.append(Meldung("fehler", f"Ergebnis im Kopf („{erg}“) und in der Zugliste („{p.ergebnis_zelle}“) widersprechen sich."))
    if not erg:
        erg = p.ergebnis_zelle
    if not p.zuege or p.zaehlen()["nicht_pruefbar"] or p.zaehlen()["illegal"]:
        return out
    st = p.endstellung
    if p.ende == "matt":
        sieger = "0-1" if st.am_zug == "w" else "1-0"
        if erg and erg != sieger:
            out.append(Meldung("fehler", f"Die Partie endet mit Matt, {B.SEITENNAMEN['b' if sieger == '0-1' else 'w']} hat gewonnen: erwartet „{sieger}“, auf dem Formular steht „{erg}“."))
        elif not erg:
            out.append(Meldung("info", f"Die Partie endet mit Matt: Ergebnis „{sieger}“."))
    elif p.ende in ("patt", "material"):
        grund = "Patt" if p.ende == "patt" else "Material reicht für kein Matt"
        if erg and erg != "1/2-1/2":
            out.append(Meldung("fehler", f"Die Partie endet remis ({grund}), auf dem Formular steht „{erg}“."))
    elif erg in ("1-0", "0-1", "1/2-1/2"):
        if erg == "1/2-1/2":
            n = p.zaehler.get(p.schluessel_ende, 1)
            if n >= 3:
                out.append(Meldung("info", f"Remis ist plausibel: dieselbe Stellung kam {n}-mal vor."))
            elif st.halbzuege >= 100:
                out.append(Meldung("info", "Remis ist plausibel: 50 Züge ohne Bauernzug und Schlag."))
            else:
                out.append(Meldung("info", "Remis ohne Matt oder Patt: nach dem Formular vereinbart (aus den Zügen nicht nachprüfbar)."))
        else:
            gewinner = "Weiß" if erg == "1-0" else "Schwarz"
            out.append(Meldung("info", f"Die Stellung ist nicht zu Ende gespielt, {gewinner} gewinnt laut Formular (Aufgabe oder Zeit): aus den Zügen nicht nachprüfbar."))
    return out
