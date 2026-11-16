"""
Partieformular → PGN: Züge vom Formular abschreiben, gegen die Schachregeln prüfen, Unklarheiten klären, PGN für die Datenbank erzeugen.
Sebastians Spielwiese - Demo C der Schach-Linie

Die App liest jede Zelle tolerant (deutsche und englische Buchstaben, ausführliche Schreibweise, fehlende Zeichen, unleserliche Stellen), spielt die Partie nach,
prüft jeden Zug gegen die Regeln und sagt bei Unklarheiten und Regelverstößen, was nicht stimmt und was in Frage kommt. Handschrift erkennt sie nicht.

Lauffähig mit: streamlit run app.py
"""
import io

import pandas as pd
import streamlit as st
from PIL import Image

import pf_ansicht as AN
import pf_brett as B
import pf_constants as C
import pf_erkenner as ER
import pf_lesen as LS
import modul_frisch
import pf_logik as L
import pf_notation as N
import pf_pgn as G
import pf_pruefung as P
import pf_raster as R

modul_frisch.aktualisieren(__file__)      # geänderte Hilfsmodule nach einem Update neu laden (die Cloud behält sie sonst bis zum Neustart)

st.set_page_config(page_title="Partieformular → PGN – Sebastians Spielwiese", layout="wide")

KOPF_FELDER = ["Event", "Site", "Date", "Round", "White", "Black", "Result", "WhiteElo", "BlackElo"]
MAX_PROBLEME = 5


# ------------------------------------------------------------------------------------------------- Zustand
def _kopf_setzen(kopf: dict) -> None:
    for k in KOPF_FELDER:
        st.session_state[f"kopf_{k}"] = kopf.get(k, "")


def _zeilen_setzen(zeilen: list) -> None:
    z = [list(r) for r in zeilen]
    while len(z) < C.ZEILEN_LEER:
        z.append(["", ""])
    st.session_state["pf_zeilen"] = z
    st.session_state["pf_basis"] = z
    st.session_state["pf_v"] = st.session_state.get("pf_v", 0) + 1


def _preset(name: str) -> None:
    p = C.PRESETS[name]
    _kopf_setzen(p["Kopf"])
    _zeilen_setzen(p["Zeilen"])
    st.session_state["pf_preset"] = name
    st.session_state.pop("pf_import_meldungen", None)
    st.session_state.pop("pf_bewerter", None)


def _setze_zelle(ply: int, text: str) -> None:
    _zeilen_setzen(L.zelle_setzen(st.session_state["pf_zeilen"], ply, text))


def _zelle_aus_feld(ply: int, key: str) -> None:
    _setze_zelle(ply, st.session_state.get(key, "") or "")


def _zelle_aus_liste(ply: int, key: str) -> None:
    wahl = st.session_state.get(key)
    if wahl:
        _setze_zelle(ply, wahl)


def _loesche_ab(ply: int) -> None:
    _zeilen_setzen(L.ab_ply_loeschen(st.session_state["pf_zeilen"], ply))


def _import() -> None:
    kopf, zeilen, meld = G.text_zu_zellen(st.session_state.get("pf_import_text", ""))
    if not zeilen and not kopf:
        st.session_state["pf_import_meldungen"] = [P.Meldung("warnung", "Im Text wurden keine Züge gefunden.")]
        return
    if kopf:
        neu = {k: st.session_state.get(f"kopf_{k}", "") for k in KOPF_FELDER}
        neu.update({k: v for k, v in kopf.items() if k in KOPF_FELDER})
        neu["Result"] = G.normiere_ergebnis(neu.get("Result", ""))
        _kopf_setzen(neu)
    _zeilen_setzen(zeilen)
    st.session_state["pf_preset"] = None
    st.session_state.pop("pf_bewerter", None)
    zellen = [c for r in zeilen for c in r if c.strip()]
    unlesbar = sum(1 for c in zellen if N.lese(c).art == "unlesbar")
    if zellen and 2 * unlesbar > len(zellen):
        meld = meld + [P.Meldung("warnung", f"{unlesbar} von {len(zellen)} Einträgen sehen nicht wie Züge aus. Ist das wirklich eine Zugliste?")]
    st.session_state["pf_import_meldungen"] = meld + [P.Meldung("info", f"{len(zeilen)} Zeile(n) übernommen" + (f", {len(kopf)} Kopfzeile(n) gelesen." if kopf else "."))]


if "pf_v" not in st.session_state:
    _preset(C.STANDARD_PRESET)

RASTER_STANDARD = {"pf_r_drehung": 0.0, "pf_r_links": 0, "pf_r_oben": 0, "pf_r_rechts": 100, "pf_r_unten": 100, "pf_r_zeilen": 30, "pf_r_bloecke": 2,
                   "pf_r_nr": 10, "pf_r_weiss": 45, "pf_r_schwarz": 45, "pf_r_einrasten": True, "pf_r_ecken": None}
for _k, _v in RASTER_STANDARD.items():
    st.session_state.setdefault(_k, _v)


def _bild_laden(foto) -> Image.Image:
    """Dekodiert das Foto einmal je Upload und hält es nur in dieser Sitzung (session_state). Kein sitzungsübergreifender Cache: `st.cache_data` würde das Bild
    für andere Sitzungen im Arbeitsspeicher des Servers behalten."""
    s = st.session_state
    if s.get("pf_bild_id") != foto.file_id:
        s["pf_bild"] = R.verkleinern(R.vorbereiten(Image.open(io.BytesIO(foto.getvalue()))))
        s["pf_bild_id"] = foto.file_id
    return s["pf_bild"]


def _bild_vergessen() -> None:
    for k in ("pf_bild", "pf_bild_id", "pf_r_foto"):
        st.session_state.pop(k, None)


@st.cache_resource(show_spinner=False)
def _erkenner(tta: bool = False) -> ER.Erkenner:
    return ER.OnnxErkenner(tta=tta)


def _raster() -> R.Raster:
    s = st.session_state
    return R.Raster(s["pf_r_links"] / 100, s["pf_r_oben"] / 100, s["pf_r_rechts"] / 100, s["pf_r_unten"] / 100, s["pf_r_drehung"], int(s["pf_r_zeilen"]),
                    int(s["pf_r_bloecke"]), (s["pf_r_nr"], s["pf_r_weiss"], s["pf_r_schwarz"]), bool(s["pf_r_einrasten"]), s.get("pf_r_ecken"))


def _raster_automatisch(bild: Image.Image) -> None:
    """Als Callback oder vor den Reglern: Raster samt Perspektive aus den gedruckten Linien bestimmen und in die Regler eintragen."""
    s = st.session_state
    raster, hinweise = R.raster_finden(bild, int(s["pf_r_zeilen"]))
    s["pf_r_hinweise"] = hinweise
    s["pf_r_ecken"] = raster.ecken
    if raster.ecken is not None:
        s["pf_r_zeilen"], s["pf_r_bloecke"] = raster.zeilen, raster.bloecke
        s["pf_r_nr"], s["pf_r_weiss"], s["pf_r_schwarz"] = (max(1, round(100 * x)) for x in raster.spalten)


def _entzerrung_verwerfen() -> None:
    st.session_state["pf_r_ecken"] = None


def _gerade_richten(bild: Image.Image) -> None:
    st.session_state["pf_r_drehung"] = R.schaetze_drehung(bild)


def _raster_suchen(bild: Image.Image) -> None:
    """Als Callback: Die Regler dürfen nur vor ihrer Erzeugung gesetzt werden. Dauert etwa 10 Sekunden."""
    gefunden, _ = LS.suche_raster(bild, _raster(), _erkenner())
    st.session_state["pf_r_oben"], st.session_state["pf_r_unten"] = round(gefunden.oben * 100), round(gefunden.unten * 100)


def _raster_zuruecksetzen() -> None:
    for k, v in RASTER_STANDARD.items():
        st.session_state[k] = v


def pct(x: float, nd: int = 1) -> str:
    return f"{100 * x:.{nd}f} %".replace(".", ",")


# ------------------------------------------------------------------------------------------------- Kopf
st.title("📝 Partieformular → PGN")
st.markdown(
    """
Du hast ein **Partieformular** vom Turnier und willst die Partie in einer Datenbank haben (Lichess, Scid, ChessBase)? Schreib die Züge **so ab, wie sie auf dem Formular stehen**:
deutsch oder englisch, mit Tippfehlern und Lücken. Die App **liest jede Zelle tolerant**, spielt die Partie auf einem Brett nach und **prüft jeden Zug gegen die Schachregeln**.
Sie markiert **unklare Stellen** (zwei Springer können hin, ein Zeichen ist unleserlich, ein Zug fehlt), **begründet Regelverstöße** und macht daraus ein **PGN**.
Was nicht eindeutig ist, bleibt Deine Entscheidung: Du änderst die Zelle oder übernimmst einen Vorschlag. Ein Foto des Formulars kannst Du daneben legen, die App liest es aber nicht
selbst. Wie sie liest und was sie prüft, steht in den Aufklappfeldern am Ende.
"""
)

with st.sidebar:
    st.header("🎯 Schnellstart")
    st.caption("Ein Beispielformular laden:")
    aktiv = st.session_state.get("pf_preset")
    if aktiv and not (st.session_state["pf_zeilen"] == C.auffuellen(C.PRESETS[aktiv]["Zeilen"]) and all(
            st.session_state.get(f"kopf_{k}", "") == C.PRESETS[aktiv]["Kopf"].get(k, "") for k in KOPF_FELDER)):
        aktiv = None
    for name in C.PRESETS:
        st.button(name, key=f"preset_{name}", width="stretch", on_click=_preset, args=(name,), help=C.PRESET_HELP.get(name, ""),
                  type="primary" if name == aktiv else "secondary")
    st.header("⚙️ Einstellungen")
    st.radio("Figurenbuchstaben auf dem Formular", list(C.BUCHSTABEN), format_func=C.BUCHSTABEN.get, key="pf_buchstaben",
             help="Bei „automatisch“ werden beide Schreibweisen gelesen. Stellst Du eine ein, warnt die App bei Zellen in der anderen.")
    st.toggle("Nur Auffälliges in der Tabelle zeigen", key="pf_nur_auffaellig", help="Blendet Zellen aus, die in Ordnung sind.")

# ------------------------------------------------------------------------------------------------- 1 Formular
st.header("1 · Formular erfassen")
c1, c2, c3 = st.columns(3)
c1.text_input("Weiß", key="kopf_White", help="Name auf dem Formular. Datenbanken führen Namen als „Nachname, Vorname“.")
c2.text_input("Schwarz", key="kopf_Black")
c3.selectbox("Ergebnis", ["", "1-0", "0-1", "1/2-1/2", "*"], key="kopf_Result", format_func=lambda x: {"": "nicht angegeben", "*": "* (offen)"}.get(x, x))
c4, c5, c6, c7 = st.columns(4)
c4.text_input("Turnier / Anlass", key="kopf_Event")
c5.text_input("Ort", key="kopf_Site")
c6.text_input("Datum", key="kopf_Date", help="Zum Beispiel 15.11.2026, 2026-11-15 oder nur 2026. Fehlende Teile werden „??“.")  # lint-ok: doppelte-satzzeichen
c7.text_input("Runde", key="kopf_Round", help="Zum Beispiel 3 oder 3.2.")
c8, c9, _ = st.columns([1, 1, 2])
c8.text_input("Elo Weiß (optional)", key="kopf_WhiteElo")
c9.text_input("Elo Schwarz (optional)", key="kopf_BlackElo")
kopf_roh = {k: st.session_state.get(f"kopf_{k}", "") for k in KOPF_FELDER}

zustimmung = st.checkbox("Ich bestätige: Die Spieler auf dem Formular sind mit dem Hochladen einverstanden, oder ich habe die Namen vorher abgeschnitten.", key="pf_foto_ok",
                         help="Ohne diese Bestätigung gibt es kein Upload-Feld. Ohne Foto lässt sich alles andere nutzen: abtippen, Text einfügen, prüfen, PGN erzeugen.")
foto = None
if zustimmung:
    foto = st.file_uploader("Foto oder Scan des Formulars (optional)", type=["png", "jpg", "jpeg", "webp"], key="pf_foto",
                            help="Das Bild wird zum Server dieser App übertragen und liegt dort nur für diese Sitzung im Arbeitsspeicher. Es liegt neben der Tabelle zum Abtippen; im Tab „Foto lesen“ kann die App es lesen.")
if foto is None:
    _bild_vergessen()
st.caption("**Datenschutz:** Ein hochgeladenes Foto geht an den Server, auf dem diese App läuft (bei der öffentlichen Fassung Streamlit Community Cloud). Die App speichert es nicht, "
           "hält es nur für diese Sitzung im Arbeitsspeicher und gibt es nicht weiter. Auf Formularen stehen Namen von Spielern: Das Upload-Feld erscheint erst nach Deiner Bestätigung. "
           "Schneide die Kopfzeile mit den Namen am besten vorher ab. Für den Betrieb der Plattform gilt deren eigene Datenschutzerklärung.")
tab_tabelle, tab_text, tab_foto = st.tabs(["Zug für Zug", "Text einfügen", "Foto lesen"])
with tab_tabelle:
    links, rechts = st.columns([3, 2]) if foto is not None else (st.container(), None)
    with links:
        st.markdown("**Zug für Zug:** Jede Zeile ist ein Zug mit Weiß und Schwarz, wie auf dem Formular. Leere Zellen am Ende zählen nicht. Mit dem Plus unten kommen Zeilen dazu.")
        basis = pd.DataFrame(st.session_state["pf_basis"], columns=["Weiß", "Schwarz"], index=range(1, len(st.session_state["pf_basis"]) + 1))
        bearbeitet = st.data_editor(basis, key=f"pf_editor_{st.session_state['pf_v']}", num_rows="dynamic", width="stretch", height=420,
                                    column_config={"Weiß": st.column_config.TextColumn("Weiß", help="Zug von Weiß, wie abgeschrieben"),
                                                   "Schwarz": st.column_config.TextColumn("Schwarz", help="Zug von Schwarz, wie abgeschrieben")})
        st.session_state["pf_zeilen"] = [["" if pd.isna(w) else str(w), "" if pd.isna(s) else str(s)] for w, s in bearbeitet.itertuples(index=False)]
    if rechts is not None:
        with rechts:
            st.image(foto, caption="Dein Formular (nur zur Ansicht; zum Vergrößern auf das Bild klicken)", width="stretch")
with tab_text:
    st.text_area("Züge als Text (auch ein ganzes PGN mit Kopfzeilen)", key="pf_import_text", height=130,
                 placeholder='Zum Beispiel: 1. e4 e5 2. Sf3 Sc6 3. Lb5 a6  oder  [White "Muster, Max"] … 1. e4 e5 …')
    st.button("In das Formular übernehmen", on_click=_import, help="Ersetzt die Zeilen der Tabelle. Zugnummern bestimmen die Zeile; fehlt eine Antwort, bleibt die Zelle leer.")
    for m in st.session_state.get("pf_import_meldungen", []):
        st.markdown(f"{C.STUFE_ICON[m.stufe]} {m.text}")

with tab_foto:
    if foto is None:
        st.info("Bestätige oben das Einverständnis der Spieler und lade ein Foto oder einen Scan Deines Partieformulars hoch. Hier stellst Du dann das Raster ein, und die App liest die Zellen.")
    else:
        bild = _bild_laden(foto)
        if st.session_state.get("pf_r_foto") != foto.file_id:              # neues Foto: Raster gleich selbst suchen
            st.session_state["pf_r_foto"] = foto.file_id
            _raster_automatisch(bild)
        st.caption("Die App sucht das Zeilenraster aus den gedruckten Linien und entzerrt dabei schiefe Aufnahmen. Prüfe in der Vorschau, dass die farbigen Felder auf den Zellen liegen "
                   "(Blau ist Weiß, Rot ist Schwarz) und dass die erste Zeile Zug 1 ist.")
        entzerrt = st.session_state.get("pf_r_ecken") is not None
        for hinweis in st.session_state.get("pf_r_hinweise", []):
            st.caption(f"ℹ️ {hinweis}")
        regler, vorschau = st.columns([2, 3])
        with regler:
            st.button("Raster automatisch finden", on_click=_raster_automatisch, args=(bild,), type="primary" if not entzerrt else "secondary",
                      help="Sucht die gedruckten Zeilenlinien (30 Zeilen je Block), entzerrt die Perspektive und bestimmt Blöcke und Spaltenbreiten.")
            if entzerrt:
                st.success("Raster gefunden und entzerrt.")
                st.button("Entzerrung verwerfen, von Hand einstellen", on_click=_entzerrung_verwerfen)
            else:
                st.warning("Kein Raster gefunden oder verworfen: Stelle Ausschnitt und Drehung von Hand ein.")
            st.slider("Drehung (Grad)", -10.0, 10.0, step=0.25, key="pf_r_drehung", disabled=entzerrt, help="Dreht eine schiefe Aufnahme gerade (nur ohne Entzerrung).")
            st.button("Automatisch geraderichten", on_click=_gerade_richten, args=(bild,), disabled=entzerrt, help="Sucht den Winkel, bei dem die gedruckten Zeilenlinien waagerecht liegen.")
            a, b = st.columns(2)
            a.slider("Links (%)", 0, 90, key="pf_r_links", disabled=entzerrt)
            b.slider("Rechts (%)", 10, 100, key="pf_r_rechts", disabled=entzerrt)
            a.slider("Oben (%)", 0, 90, key="pf_r_oben", disabled=entzerrt)
            b.slider("Unten (%)", 10, 100, key="pf_r_unten", disabled=entzerrt)
            a.number_input("Zeilen je Block", 1, 60, key="pf_r_zeilen")
            b.selectbox("Blöcke nebeneinander", [1, 2, 3], key="pf_r_bloecke", help="Viele Formulare haben zwei Blöcke: Zug 1 bis 30 und 31 bis 60.")
            st.markdown("**Spaltenbreite im Block** (Nummer, Weiß, Schwarz)")
            a, b, c = st.columns(3)
            a.number_input("Nr.", 1, 90, key="pf_r_nr")
            b.number_input("Weiß", 1, 90, key="pf_r_weiss")
            c.number_input("Schwarz", 1, 90, key="pf_r_schwarz")
            st.checkbox("Zeilen auf die gedruckten Linien einrasten", key="pf_r_einrasten", help="Verschiebt die Zeilengrenzen auf die Linien, die im Bild zu finden sind.")
            st.button("Raster zurücksetzen", on_click=_raster_zuruecksetzen)
        raster = _raster()
        try:
            raster.pruefe()
            with vorschau:
                st.image(R.vorschau(bild, raster), caption="Raster auf dem Formular", width="stretch")
        except ValueError:
            raster = None
            vorschau.warning("Der Ausschnitt ist ungültig: Links muss kleiner sein als Rechts, Oben kleiner als Unten.")
        st.markdown("**Lesen**")
        if not ER.onnxruntime_vorhanden():
            st.warning("Der Erkenner ist hier nicht installiert (Paket `onnxruntime`). Die Tabelle zum Abtippen funktioniert weiter.")
        elif not ER.modell_vorhanden():
            st.info(f"Für das Lesen braucht die App ein Modell (nach „chess-ocr-bilstm“, MIT-Lizenz, nachtrainiert für englische und deutsche Figurenbuchstaben, {ER.MODELL_BYTES // 1_000_000} MB). "
                    "Es wird einmal von GitHub auf den Server dieser App geladen; Dein Foto wird dabei nicht mitgeschickt.")
            if st.button("Modell laden"):
                with st.spinner("Lade das Modell …"):
                    try:
                        ER.modell_holen()
                    except Exception as fehler:      # Netz, Prüfsumme, Schreibrecht: der Nutzer soll den Grund sehen
                        st.error(f"Das Modell konnte nicht geladen werden: {fehler}")
                    else:
                        st.rerun()
        elif raster is not None:
            if not entzerrt:
                st.button("Raster mit dem Erkenner suchen", on_click=_raster_suchen, args=(bild,), help="Für Formulare ohne erkennbare Linien: Probiert Oberkante und Unterkante durch und nimmt die Lage, bei der der Erkenner "
                                                         "die meisten lesbaren Züge findet (etwa 10 Sekunden). Prüfe danach in der Vorschau, dass die erste Zeile Zug 1 ist.")
            lesen = st.button("Zellen lesen", type="primary", help="Liest jede beschriebene Zelle und trägt den Text in die Tabelle ein.")
            if lesen:
                fortschritt = st.progress(0.0, text="Lese die Zellen …")
                lesung = LS.lese_formular(bild, raster, _erkenner(tta=True), fortschritt=lambda i, n: fortschritt.progress(i / n, text=f"Zelle {i} von {n}"))
                fortschritt.empty()
                if not lesung.zellen:
                    st.warning("Im Raster wurde keine Schrift gefunden. Prüfe Ausschnitt und Zeilen in der Vorschau.")
                else:
                    _zeilen_setzen(lesung.zeilen())
                    st.session_state["pf_bewerter"] = LS.Bewerter(lesung)
                    st.session_state["pf_preset"] = None
                    st.session_state["pf_lese_info"] = f"{lesung.beschrieben()} beschriebene Zellen gelesen."
                    st.rerun()
        if st.session_state.get("pf_bewerter") is not None:
            st.success(st.session_state.get("pf_lese_info", "Zellen gelesen.") + " Der gelesene Text steht in der Tabelle; unsichere Zeichen sind „?“. Unten prüft die App ihn gegen die Regeln und das Bild.")
    if st.session_state.get("pf_bewerter") is None:
        st.caption("Das Modell kennt englische und deutsche Figurenbuchstaben (S, L, T, D), aber nur wenige Handschriften: Auf Blättern, die es nie sah, liest es etwa 6 von 10 Zellen ganz richtig. Prüfe die Hinweise unten.")

zeilen = st.session_state["pf_zeilen"]
buchstaben = st.session_state.get("pf_buchstaben", "auto")
bewerter = st.session_state.get("pf_bewerter")
p = L.pruefe_gemerkt(L.zellen_tupel(zeilen), buchstaben, bewerter)
schreibweise = L.schreibweise_des_formulars(p, buchstaben)


def formular_san(san: str) -> str:
    """Zug so, wie er ins Formular geschrieben wird (deutsche Buchstaben auf einem deutschen Formular)."""
    return L.in_schreibweise(san, schreibweise)


ergebnis_pgn, ergebnis_quelle = L.wirksames_ergebnis(kopf_roh.get("Result", ""), p)
kopf_norm, kopf_meldungen = G.normiere_kopf(kopf_roh)

# ------------------------------------------------------------------------------------------------- 2 Prüfung
st.header("2 · Prüfung gegen die Schachregeln")
z = p.zaehlen()
if not p.zuege:
    st.info("Noch keine Züge im Formular. Tippe Züge in die Tabelle, füge sie als Text ein oder lade ein Beispiel in der Seitenleiste.")
else:
    regelverstoesse = z["illegal"] + z["nach_ende"]
    m = st.columns(5)
    m[0].metric("Halbzüge gelesen", p.halbzuege)
    m[1].metric("in Ordnung", z["ok"] + z["hinweis"], help="Genau ein legaler Zug passt. Davon sind so viele bereinigt: " + str(z["hinweis"]))
    m[2].metric("unklar", z["unklar"], help="Mehrere legale Züge passen, ein Zeichen ist unleserlich oder ein Zug fehlt.")
    m[3].metric("Regelverstöße", regelverstoesse, help="Kein legaler Zug passt, oder ein Zug steht nach dem Ende der Partie.")
    m[4].metric("nicht prüfbar", z["nicht_pruefbar"], help="Steht hinter einem Regelverstoß: die Stellung ist ab dort unbekannt.")
    befunde = P.ergebnis_befunde(p, G.normiere_ergebnis(kopf_roh.get("Result", ""))) + p.befunde
    if p.datenbanktauglich():
        st.success(f"Datenbanktauglich: alle {p.halbzuege} Halbzüge sind regelkonform und eindeutig" + (f", die Partie endet mit {'Matt' if p.ende == 'matt' else 'Patt' if p.ende == 'patt' else 'Remis'}." if p.ende else "."))
    elif regelverstoesse or z["nicht_pruefbar"]:
        st.error("Mindestens ein Zug verstößt gegen die Regeln. Die Prüfung stoppt dort; alles dahinter ist erst nach dem Beheben prüfbar.")
    elif z["unklar"]:
        st.warning(f"{z['unklar']} Stelle(n) sind unklar. Die App hat vorläufig den wahrscheinlichsten Zug gewählt. Bestätige ihn oder wähle einen anderen.")
    for b in befunde + kopf_meldungen:
        if b.stufe == "fehler" or b.stufe == "warnung":
            st.markdown(f"{C.STUFE_ICON[b.stufe]} {b.text}")
    infos = [b for b in befunde if b.stufe == "info"]
    for b in infos:
        st.caption(f"{C.STUFE_ICON['info']} {b.text}")

    zeilen_tab = []
    for e in p.zuege:
        if st.session_state.get("pf_nur_auffaellig") and e.status in ("ok", "ergebnis", "leer"):
            continue
        icon, wort = C.STATUS[e.status]
        hinweis = " · ".join(x.text for x in e.meldungen if x.stufe != "info" or e.status in ("hinweis", "unklar"))
        zeilen_tab.append({"Zug": e.beschriftung, "Formular": e.roh.strip() or "(leer)", "Geprüft (SAN)": e.san, "Status": f"{icon} {wort}", "Hinweis": hinweis, "_s": e.status})
    if zeilen_tab:
        df = pd.DataFrame(zeilen_tab)
        stile = df["_s"].map(C.FARBEN)
        sichtbar = df.drop(columns="_s")
        st.dataframe(sichtbar.style.apply(lambda r: [f"background-color: {stile[r.name]}"] * len(r), axis=1), hide_index=True, width="stretch",
                     height=min(38 * (len(sichtbar) + 1) + 2, 460))
        st.caption("Grün: in Ordnung · Blau: genau ein Zug passt, die Schreibweise wurde bereinigt · Gelb: unklar, vorläufig gewählt · Rot: Regelverstoß · Grau: nicht prüfbar. "
                   "SAN ist die internationale Notation des PGN (S heißt dort N, L = B, T = R, D = Q).")
    else:
        st.caption("Alle Zellen sind in Ordnung.")

    # --------------------------------------------------------------------------------------------- Nacharbeit
    probleme = p.probleme()
    st.subheader("Nacharbeit")
    if not probleme:
        st.success("Nichts nachzuarbeiten.")
    else:
        st.caption("Die Stellen stehen in der Reihenfolge der Partie. Ein Vorschlag wird übernommen, indem sein Zug in die Zelle geschrieben wird; die Zelle kannst Du auch selbst ändern.")
    for e in probleme[:MAX_PROBLEME]:
        icon = C.STATUS[e.status][0]
        v = st.session_state["pf_v"]
        with st.container(border=True):
            st.markdown(f"**{icon} {e.beschriftung}: „{e.roh.strip() or '(leer)'}“**")
            brett, steuer = st.columns([2, 3])
            kand = e.kandidaten[:5]
            pfeile = [(k.zug.von, k.zug.nach) for k in kand]
            with brett:
                st.markdown(AN.brett_svg(e.vor.figuren, pfeile, [k.zug.nach for k in kand], None,
                                         label=f"Stellung vor {e.beschriftung}", flip=e.vor.am_zug == "b"), unsafe_allow_html=True)
                st.caption(f"Stellung vor dem Zug, {B.SEITENNAMEN[e.vor.am_zug]} ist am Zug." + (" Pfeile: die Kandidaten." if kand else ""))
            with steuer:
                if bewerter is not None and bewerter.png(e.ply):
                    st.image(bewerter.png(e.ply), caption=f"So sieht die Zelle im Foto aus (gelesen: „{e.roh.strip() or '?'}“)")
                for x in e.meldungen:
                    st.markdown(f"{C.STUFE_ICON[x.stufe]} {x.text}")
                if e.status == "nach_ende":
                    st.button("Diese Zelle und alle folgenden leeren", key=f"pf_del_{v}_{e.ply}", on_click=_loesche_ab, args=(e.ply,))
                for i, k in enumerate(e.kandidaten):
                    c_a, c_b = st.columns([1, 4])
                    c_a.button(f"✔ {formular_san(k.san)}", key=f"pf_k_{v}_{e.ply}_{i}", on_click=_setze_zelle, args=(e.ply, formular_san(k.san)), width="stretch",
                               help="Schreibt diesen Zug in die Zelle.")
                    c_b.caption(("danach bleibt die ganze übrige Partie regelkonform" if k.ganz else
                                 f"danach bleibt {k.fortsetzung} Folgezug regelkonform" if k.fortsetzung == 1 else
                                 f"danach bleiben {k.fortsetzung} Folgezüge regelkonform" if k.fortsetzung else "danach geht es nicht weiter")
                                + (f" · {k.grund}" if k.grund and k.grund != "passt" else "")
                                + (f" · Bild: {100 * k.bild:.0f} %" if k.bild is not None else ""))
                for j, k in e.frueher:
                    ej = p.zuege[j]
                    c_a, c_b = st.columns([1, 4])
                    c_a.button(f"↩ {formular_san(k.san)}", key=f"pf_f_{v}_{e.ply}_{j}_{k.san}", on_click=_setze_zelle, args=(j, formular_san(k.san)), width="stretch",
                               help="Ändert die frühere Zelle.")
                    c_b.caption(f"Mögliche frühere Ursache: {ej.beschriftung} „{ej.roh.strip()}“ statt {k.san}"
                                + (": danach hält die Partie bis zum Ende." if k.ganz else f": danach hält die Partie {k.fortsetzung + 1} Halbzüge weiter."))
                if e.status != "nach_ende":
                    with st.form(f"pf_form_{v}_{e.ply}", border=False):
                        st.text_input("Zelle selbst ändern", value=e.roh.strip(), key=f"pf_txt_{v}_{e.ply}")
                        st.form_submit_button("Zelle ändern", on_click=_zelle_aus_feld, args=(e.ply, f"pf_txt_{v}_{e.ply}"))
                    legal = sorted({formular_san(e.vor.san(zg)) for zg in e.vor.legale_zuege()}, key=lambda s: (s[0].isupper() is False, s))
                    st.selectbox("Oder einen legalen Zug wählen", legal, index=None, placeholder=f"{len(legal)} legale Züge", key=f"pf_sel_{v}_{e.ply}",
                                 on_change=_zelle_aus_liste, args=(e.ply, f"pf_sel_{v}_{e.ply}"))
    if len(probleme) > MAX_PROBLEME:
        st.caption(f"Es folgen noch {len(probleme) - MAX_PROBLEME} weitere Stelle(n).")

    # --------------------------------------------------------------------------------------------- Nachspielen
    st.header("3 · Partie nachspielen")
    aufgeloest = []
    for e in p.zuege:
        if e.status == "ergebnis" or e.status == "leer":
            continue
        if e.nach is None:
            break
        aufgeloest.append(e)
    n = len(aufgeloest)
    if n:
        ply = st.slider("Halbzug", 0, n, n, key=f"pf_ply_{st.session_state['pf_v']}_{n}",
                        help="0 ist die Grundstellung, die letzte Stellung ist die bis zum ersten Regelverstoß.")
        stand = aufgeloest[ply - 1].nach if ply else B.Stellung.start()
        letzter = (aufgeloest[ply - 1].zug.von, aufgeloest[ply - 1].zug.nach) if ply else None
        nachspiel_l, nachspiel_r = st.columns([2, 3])
        with nachspiel_l:
            st.markdown(AN.brett_svg(stand.figuren, [], [], letzter, label=f"Stellung nach Halbzug {ply}", flip=False), unsafe_allow_html=True)
        with nachspiel_r:
            if ply:
                e = aufgeloest[ply - 1]
                st.markdown(f"**Nach {e.beschriftung}: {e.san}**" + ("  ⚠️ vorläufig gewählt" if e.status == "unklar" else ""))
            else:
                st.markdown("**Grundstellung**")
            st.markdown(f"{B.SEITENNAMEN[stand.am_zug]} ist am Zug." + (" Schach!" if stand.im_schach() else ""))
            st.code(stand.fen(), language=None)
            st.caption("Vergleiche das Brett mit dem Formular: Stimmt eine Stellung nicht, liegt der Fehler meist in einem der letzten Züge davor.")
    else:
        st.caption("Es gibt noch keinen prüfbaren Zug.")

# ------------------------------------------------------------------------------------------------- 4 PGN
st.header("4 · PGN für die Datenbank")
modi = L.export_modi(p) if p.zuege else []
if not p.zuege:
    st.caption("Sobald Züge im Formular stehen, erscheint hier das PGN.")
elif not modi:
    st.error("Es gibt noch keinen gesicherten Zug, aus dem ein PGN entstehen könnte. Klär zuerst die Stelle oben.")
else:
    if L.EXPORT_SAUBER in modi:
        modus = L.EXPORT_SAUBER
    else:
        namen = {L.EXPORT_TEIL: "Teil-PGN: nur die gesicherten Züge bis vor die erste offene Stelle",
                 L.EXPORT_VORLAEUFIG: "Vorläufiges PGN: auch die gewählten Vorschläge, unklare Stellen als Kommentar"}
        modus = st.radio("Was exportieren?", modi, format_func=namen.get, key="pf_export",
                         help="Ein Teil-PGN ist regelkonform, aber kurz. Ein vorläufiges PGN enthält Vermutungen und gehört nicht ungeprüft in eine Datenbank.")
    text, _ = L.pgn_text(kopf_roh, p, modus)
    st.markdown(f"Ergebnis im PGN: `{ergebnis_pgn if modus != L.EXPORT_TEIL else '*'}` ({ergebnis_quelle if modus != L.EXPORT_TEIL else 'Teil-PGN: Ergebnis offen'}).")
    st.code(text, language=None)
    st.download_button("⬇ PGN herunterladen", text.encode("utf-8"), file_name=L.dateiname(kopf_roh, modus), mime="application/x-chess-pgn", type="primary",
                       help="Datei in UTF-8. Lässt sich in Lichess (Import), Scid und ChessBase öffnen.")
    st.caption("Das PGN hat die sieben Pflichtzeilen in der Reihenfolge des Standards, Zugnummern und Zeilen von höchstens 80 Zeichen. Bewertungszeichen aus dem Formular stehen als NAG.")

# ------------------------------------------------------------------------------------------------- Erklärungen
with st.expander("📖 So liest die App eine Zelle"):
    st.markdown("Jede Zelle wird für sich gelesen und danach gegen die Stellung geprüft. Das akzeptiert die App:")
    st.markdown(C.LESEREGELN)

with st.expander("📐 Was geprüft wird"):
    st.markdown(
        """
* **Zugform:** Jede Figur zieht nur so, wie sie darf; Läufer, Türme und Damen springen nicht über Figuren; Bauern ziehen einen Schritt, aus der Grundstellung zwei, und schlagen schräg.
* **König:** Kein Zug darf den eigenen König im Schach lassen (Fesselung, Schach nicht beendet, König auf bedrohtes Feld).
* **Rochade:** König und Turm nicht bewegt, Felder dazwischen frei, König nicht im Schach, nicht über ein bedrohtes Feld und nicht auf ein bedrohtes Feld.
* **Besondere Züge:** Schlag en passant (nur direkt nach dem Doppelschritt), Umwandlung auf der letzten Reihe.
* **Ende der Partie:** nach Matt, Patt oder wenn kein Matt mehr möglich ist, darf kein Zug mehr folgen. Fünfmal dieselbe Stellung und 75 Züge ohne Bauernzug und Schlag beenden die Partie nach FIDE-Regeln von selbst; die App warnt dann.
* **Ergebnis:** Matt, Patt und das Ergebnis im Kopf müssen zusammenpassen. Gewonnen durch Aufgabe oder Zeit ist aus den Zügen nicht prüfbar und wird nur vermerkt.
* **Formular:** Schreibweise (deutsch oder englisch, gemischt?), Schachzeichen, Schlagzeichen, Datum, Namen, Elo.
"""
    )

with st.expander("🔬 Wie die App Unklarheiten entscheidet"):
    st.markdown(
        """
Zu jeder Zelle sucht die App alle **legalen Züge**, die zu den lesbaren Zeichen passen. Ist es genau einer, ist die Zelle in Ordnung. Sind es mehrere (zwei Springer können nach d2) oder fehlt ein Zeichen,
spielt sie **für jeden Kandidaten den Rest der Partie nach** und zählt, wie viele Folgezellen danach noch **eindeutig und legal** sind. Auch ein abgeschriebenes Schach- oder Mattzeichen muss stimmen.
Der Kandidat, nach dem die Partie am längsten hält, steht vorn und wird vorläufig gewählt. Gleichstand zeigt die App als Gleichstand: Dann entscheiden die Regeln allein nichts, und nur das Formular kann es klären.

Ein **Regelverstoß** unterbricht die Prüfung. Die App nennt den Grund, schlägt ähnliche legale Züge vor (höchstens eine Abweichung in Figur, Ziel oder angegebenem Ausgangsfeld) und sucht in den **zehn Halbzügen davor**
nach einer Zelle, die selbst legal ist, deren Änderung die Partie aber über den Verstoß hinaus hält (der Klassiker: „0-0“ statt „0-0-0“).
"""
    )

with st.expander("🚧 Was die Demo nicht kann"):
    st.markdown(
        """
* **Verlässlich Handschrift lesen:** Das Lesen von Fotos ist ein Gerüst mit einem kleinen Modell, das auf einem englischen Datensatz und gerenderten Zellen trainiert ist. Auf Blättern fremder Schreiber liest es etwa 6 von 10 Zellen ganz richtig; echte deutsche Ligabögen hat es nie gesehen, deutsche Buchstaben kennt es nur aus eingesetzten Handschrift-Buchstaben und Schriften. Das Raster findet und entzerrt die App nur bei gedruckten Zeilenlinien.
* **Mehr als die Hauptlinie:** Varianten, Kommentare, Uhrzeiten und Zeitangaben vom Formular werden nicht übernommen (Text mit Klammern wird gelesen, die Klammern gehen verloren).
* **Andere Ausgangsstellungen:** nur die normale Grundstellung, kein Schach960, keine Partie ab FEN.
* **Frühere Fehlerursache:** gesucht wird nur in den zehn Halbzügen vor dem Regelverstoß und nur unter Zügen, die sich in höchstens zwei der Angaben Figur, Ziellinie und Zielreihe unterscheiden. Liegt der Fehler weiter zurück oder ist die Abschrift an mehreren Stellen falsch, zeigt die App nur den ersten Verstoß.
* **Remis auf Antrag:** dreifache Wiederholung und 50-Züge-Regel werden nur beim Abgleich mit dem Ergebnis erwähnt, nicht erzwungen.
* **Datenbanken:** Das PGN ist UTF-8; Namen mit Umlauten sind in Lichess, Scid und neuen ChessBase-Versionen kein Problem, in sehr alten Programmen können sie als Sonderzeichen erscheinen.
"""
    )

st.markdown("---")
st.caption("Teil von [Sebastians Spielwiese](https://sebastians-spielwiese.net/) · Schachregeln und Prüfung im Repo, gegen python-chess getestet · Figuren: „cburnett“ von Colin M. L. Burnett (BSD).")
