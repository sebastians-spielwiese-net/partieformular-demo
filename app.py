"""
Partieformular → PGN: Züge vom Formular abschreiben, gegen die Schachregeln prüfen, Unklarheiten klären, PGN für die Datenbank erzeugen.
Sebastians Spielwiese - Demo C der Schach-Linie

Die App liest jede Zelle tolerant (deutsche und englische Buchstaben, ausführliche Schreibweise, fehlende Zeichen, unleserliche Stellen), spielt die Partie nach,
prüft jeden Zug gegen die Regeln und sagt bei Unklarheiten und Regelverstößen, was nicht stimmt und was in Frage kommt. Handschrift erkennt sie nicht.

Lauffähig mit: streamlit run app.py
"""
import io
import time

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
import pf_pgn as G
import pf_pruefung as P
import pf_raster as R
import pf_schwaerzen as SW

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


if "pf_v" not in st.session_state:
    _kopf_setzen({})
    _zeilen_setzen([])

RASTER_STANDARD = {"pf_r_drehung": 0.0, "pf_r_links": 0, "pf_r_oben": 0, "pf_r_rechts": 100, "pf_r_unten": 100, "pf_r_zeilen": 30, "pf_r_bloecke": 2,
                   "pf_r_nr": 10, "pf_r_weiss": 45, "pf_r_schwarz": 45, "pf_r_einrasten": True, "pf_r_ecken": None, "pf_r_vorlage": None}
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
    for k in ("pf_bild", "pf_bild_id", "pf_auto_id", "pf_bewerter", "pf_entschluesselt", "pf_dekodierer", "pf_fest", "pf_unsicher", "pf_auto_zeilen", "pf_folge_ab"):
        st.session_state.pop(k, None)


@st.cache_resource(show_spinner=False)
def _erkenner(tta: bool = False) -> ER.Erkenner:
    return ER.OnnxErkenner(tta=tta)


def _raster() -> R.Raster:
    s = st.session_state
    vorlage = s.get("pf_r_vorlage")                    # gedruckte Lage eines Linienformulars (pf_vorlage); gilt nur, solange Zeilen und Blöcke so eingestellt sind
    if vorlage is not None and vorlage["zeilen"] == int(s["pf_r_zeilen"]) and vorlage["bloecke"] == int(s["pf_r_bloecke"]) and s.get("pf_r_ecken") is None:
        return R.Raster(drehung=s["pf_r_drehung"], zeilen=vorlage["zeilen"], bloecke=vorlage["bloecke"], einrasten=False, spaltenlage=vorlage["spaltenlage"],
                        zeilenlinien=vorlage["zeilenlinien"], bereinigen=vorlage["bereinigen"])
    return R.Raster(s["pf_r_links"] / 100, s["pf_r_oben"] / 100, s["pf_r_rechts"] / 100, s["pf_r_unten"] / 100, s["pf_r_drehung"], int(s["pf_r_zeilen"]),
                    int(s["pf_r_bloecke"]), (s["pf_r_nr"], s["pf_r_weiss"], s["pf_r_schwarz"]), bool(s["pf_r_einrasten"]), s.get("pf_r_ecken"))


def _raster_automatisch(bild: Image.Image) -> None:
    """Als Callback oder vor den Reglern: Raster samt Perspektive aus den gedruckten Linien bestimmen und in die Regler eintragen."""
    s = st.session_state
    raster, hinweise = R.raster_finden(bild, int(s["pf_r_zeilen"]))
    s["pf_r_hinweise"] = hinweise
    s["pf_r_ecken"] = raster.ecken
    s["pf_r_vorlage"] = None
    if raster.spaltenlage is not None:                 # Linienformular: Lage und Drehung aus den gedruckten Zeilenlinien
        s["pf_r_vorlage"] = {"zeilen": raster.zeilen, "bloecke": raster.bloecke, "spaltenlage": raster.spaltenlage, "zeilenlinien": raster.zeilenlinien, "bereinigen": raster.bereinigen}
        s["pf_r_zeilen"], s["pf_r_bloecke"], s["pf_r_drehung"] = raster.zeilen, raster.bloecke, raster.drehung
    if raster.ecken is not None:
        s["pf_r_zeilen"], s["pf_r_bloecke"] = raster.zeilen, raster.bloecke
        s["pf_r_nr"], s["pf_r_weiss"], s["pf_r_schwarz"] = (max(1, round(100 * x)) for x in raster.spalten)


def _entschluesseln(neu: bool = True) -> None:
    """Strahlsuche über die gelesenen Zellen (`pf_lesen.Dekodierer`); die Tabelle zeigt danach den besten legalen Verlauf in der Schreibweise des Formulars.
    `neu=False`: mit dem Gedächtnis der letzten Suche und den bestätigten Zellen (`pf_fest`) nur ab der ersten geänderten Zelle neu suchen."""
    s = st.session_state
    bewerter = s.get("pf_bewerter")
    if bewerter is None:
        return
    if neu or s.get("pf_dekodierer") is None:
        s["pf_dekodierer"], s["pf_fest"] = LS.Dekodierer(bewerter.lesung), {}
    d, fest = s["pf_dekodierer"], s["pf_fest"]
    start = time.time()
    entscheidungen = d.lauf(fest)
    if d.gescheitert is not None:
        s["pf_entschluesselt"] = (f"Die bestätigte Zelle im Zug {d.gescheitert // 2 + 1} passt zu keiner regelkonformen Partie mit den Zellen davor. "
                                  "Prüfe sie, oder korrigiere eine frühere Zelle und suche noch einmal.")
        return
    if not entscheidungen:
        s["pf_entschluesselt"] = "Es gab keine lesbaren Zellen zum Entschlüsseln."
        return
    zellen = ["" if i >= len(entscheidungen) else L.in_schreibweise(entscheidungen[i].san, "de") for i in range(2 * ((len(entscheidungen) + 1) // 2))]
    zeilen = [[zellen[i], zellen[i + 1]] for i in range(0, len(zellen), 2)]
    _zeilen_setzen(zeilen)
    s["pf_auto_zeilen"] = [list(r) for r in s["pf_zeilen"]]
    s["pf_unsicher"] = {e.ply: e for e in entscheidungen if e.unsicher() and e.ply not in fest}
    s["pf_folge_ab"] = LS.folgefehler_ab([e.ply in s["pf_unsicher"] for e in entscheidungen])
    s["pf_entschluesselt"] = (f"Strahlsuche: {len(entscheidungen)} Halbzüge eingetragen, {len(s['pf_unsicher'])} davon sind nach dem Bild unsicher (Spalte „Bild“ in der Prüfung)"
                              + (f"; {len(fest)} Zelle(n) bestätigt" if fest else "") + f" ({time.time() - start:.0f} s). Das sind Vorschläge: Korrigiere falsche Zellen in der Tabelle und suche weiter.")


def _korrekturen() -> dict[int, str]:
    """Zellen, die Du in der Tabelle gegenüber dem letzten Suchergebnis geändert hast (Halbzug -> Text); leere Zellen zählen nicht."""
    s = st.session_state
    alt = s.get("pf_auto_zeilen") or []
    out = {}
    for i, zeile in enumerate(s["pf_zeilen"]):
        for j, text in enumerate(zeile):
            vorher = alt[i][j] if i < len(alt) else ""
            if text.strip() and text.strip() != vorher.strip():
                out[2 * i + j] = text.strip()
    return out


def _nachsuchen() -> None:
    """Die geänderten Zellen gelten ab jetzt als bestätigt; gesucht wird nur ab der ersten von ihnen neu."""
    s = st.session_state
    s["pf_fest"] = {**s.get("pf_fest", {}), **_korrekturen()}
    _entschluesseln(neu=False)


def _entzerrung_verwerfen() -> None:
    st.session_state["pf_r_ecken"] = None


def _gerade_richten(bild: Image.Image) -> None:
    st.session_state["pf_r_drehung"] = R.schaetze_drehung(bild)


def _raster_zuruecksetzen() -> None:
    for k, v in RASTER_STANDARD.items():
        st.session_state[k] = v


def _automatisch(foto, raster_suchen: bool = True) -> None:
    """Alles in einem Zug, sobald ein neues Foto da ist: Modell laden, Raster suchen, Zellen lesen, wahrscheinlichste legale Partie suchen und in die Tabelle schreiben."""
    s = st.session_state
    bild = _bild_laden(foto)
    with st.status("Lese das Formular …", expanded=True) as status:
        if not ER.onnxruntime_vorhanden():
            status.update(label="Das Erkennungsmodell lässt sich hier nicht ausführen (onnxruntime fehlt).", state="error")
            return
        if not ER.modell_vorhanden():
            status.write("Lade das Erkennungsmodell (einmalig, etwa 43 MB; Dein Foto wird dabei nicht mitgeschickt) …")
            try:
                ER.modell_holen()
            except Exception as fehler:      # Netz, Prüfsumme, Schreibrecht: der Nutzer soll den Grund sehen
                status.update(label=f"Das Modell konnte nicht geladen werden: {fehler}", state="error")
                return
        if raster_suchen:
            status.write("Suche das Raster …")
            _raster_automatisch(bild)
        raster = _raster()
        try:
            raster.pruefe()
        except ValueError:
            status.update(label="Der Ausschnitt ist ungültig: Links muss kleiner sein als Rechts, Oben kleiner als Unten.", state="error")
            return
        status.write("Lese die Zellen …")
        balken = st.progress(0.0)
        lesung = LS.lese_formular(bild, raster, _erkenner(tta=True), fortschritt=lambda i, n: balken.progress(i / n, text=f"Zelle {i} von {n}"))
        balken.empty()
        if not lesung.zellen:
            status.update(label="Im Raster wurde keine Schrift gefunden. Prüfe das Raster unter „Erweitert“.", state="error")
            s["pf_auto_id"] = foto.file_id
            return
        _zeilen_setzen(lesung.zeilen())
        s["pf_bewerter"] = LS.Bewerter(lesung)
        s["pf_lese_info"] = f"{lesung.beschrieben()} beschriebene Zellen gelesen."
        status.write("Suche die wahrscheinlichste regelkonforme Partie …")
        _entschluesseln()
        status.update(label=f"Fertig: {lesung.beschrieben()} Zellen gelesen und die Partie entschlüsselt.", state="complete", expanded=False)
    s["pf_auto_id"] = foto.file_id


def _neu_lesen() -> None:
    st.session_state["pf_neu_lesen"] = True


def pct(x: float, nd: int = 1) -> str:
    return f"{100 * x:.{nd}f} %".replace(".", ",")


# ------------------------------------------------------------------------------------------------- Kopf
st.title("📷 Partieformular → PGN")
st.markdown(
    """
Foto oder Scan Deines **Turnier-Partieformulars** hochladen, mehr nicht: Die App **findet das Raster selbst**, **liest die Zellen** mit einem kleinen Handschrift-Modell und sucht dazu die
**wahrscheinlichste Partie, in der jeder Zug nach den Schachregeln erlaubt ist**. Dann **prüft** sie jeden Zug, **zeigt unklare Stellen** und macht ein **PGN** für die Datenbank (Lichess, Scid, ChessBase).
Handschrift ist schwer: Auf Blättern, die das Modell nie sah, liest es oft weniger als jeden zweiten Zug richtig. Was die App nicht sicher weiß, bleibt Deine Entscheidung (Abschnitt „Nacharbeit“).
"""
)

# ------------------------------------------------------------------------------------------------- 1 Foto
st.header("1 · Foto")
zustimmung = st.checkbox("Ich bestätige: Ich schwärze die Namen auf dem Foto, oder die Spieler sind mit dem Hochladen einverstanden.", key="pf_foto_ok",
                         help="Ohne diese Bestätigung gibt es keine Foto-Auswahl.")
foto = None
if zustimmung:
    st.markdown("**Foto oder Scan des Formulars.** Das Foto wird nur in Deinem Browser gelesen. Du schwärzt dort die Namen; erst nach „Übernehmen“ geht das Bild mit den schwarzen Flächen an den Server dieser App.")
    foto = SW.foto_schwaerzen(key="pf_foto")
if foto is None:
    _bild_vergessen()
st.caption("**Datenschutz:** Das Original verlässt Deinen Browser nicht: Die Datei wird dort gelesen, Namen schwärzt Du dort, und nur das neu gezeichnete Bild (ohne Dateiname und Aufnahmedaten) geht an den Server, "
           "auf dem diese App läuft (bei der öffentlichen Fassung Streamlit Community Cloud). Die App speichert es nicht, hält es nur für diese Sitzung im Arbeitsspeicher und gibt es nicht weiter. "
           "Ob alle Namen geschwärzt sind, prüfst Du selbst: Die App kann es nicht erkennen. Für den Betrieb der Plattform gilt deren eigene Datenschutzerklärung.")
if foto is not None and (st.session_state.get("pf_auto_id") != foto.file_id or st.session_state.pop("pf_neu_lesen", False)):
    _automatisch(foto, raster_suchen=st.session_state.get("pf_auto_id") != foto.file_id)
elif foto is None:
    st.info("Bestätige oben, wähle ein Foto oder einen Scan Deines Partieformulars und schwärze die Namen. Danach läuft alles von selbst.")

with st.expander("Kopfdaten für das PGN (optional)"):
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
st.session_state.setdefault("pf_buchstaben", "auto")
st.session_state.setdefault("pf_nur_auffaellig", False)

# ------------------------------------------------------------------------------------------------- Tabelle zum Korrigieren
with st.expander("Gelesene Züge als Tabelle (zum Korrigieren)", expanded=foto is not None):
    links, rechts = st.columns([3, 2]) if foto is not None else (st.container(), None)
    with links:
        st.markdown("Jede Zeile ist ein Zug mit Weiß und Schwarz. Hier kannst Du Zellen ändern, die Prüfung unten läuft sofort neu.")
        basis = pd.DataFrame(st.session_state["pf_basis"], columns=["Weiß", "Schwarz"], index=range(1, len(st.session_state["pf_basis"]) + 1))
        bearbeitet = st.data_editor(basis, key=f"pf_editor_{st.session_state['pf_v']}", num_rows="dynamic", width="stretch", height=420,
                                    column_config={"Weiß": st.column_config.TextColumn("Weiß"), "Schwarz": st.column_config.TextColumn("Schwarz")})
        st.session_state["pf_zeilen"] = [["" if pd.isna(w) else str(w), "" if pd.isna(s) else str(s)] for w, s in bearbeitet.itertuples(index=False)]
        if st.session_state.get("pf_dekodierer") is not None:
            geaendert = _korrekturen()
            if st.button(f"Korrekturen übernehmen und weiter suchen ({len(geaendert)} geändert)", type="primary" if geaendert else "secondary", key="pf_nachsuchen",
                         help="Die geänderten Zellen gelten als bestätigt. Die Suche setzt bei der ersten von ihnen neu an (die Zellen davor bleiben, die Suche ist daher schneller als die erste) "
                              "und passt die Folgezüge an: Ein richtiger Zug macht oft die Zellen dahinter eindeutig."):
                if geaendert:
                    with st.spinner("Suche weiter …"):
                        _nachsuchen()
                    st.rerun()
                else:
                    st.caption("Keine Zelle geändert: Ändere in der Tabelle eine falsch gelesene Zelle, dann suche weiter.")
    if rechts is not None:
        with rechts:
            st.image(foto.getvalue(), caption="Dein Formular, wie es bei der App angekommen ist (zum Vergrößern auf das Bild klicken)", width="stretch")
if st.session_state.get("pf_entschluesselt") and foto is not None:
    st.info(st.session_state["pf_entschluesselt"])

with st.expander("Erweitert: Raster von Hand einstellen und neu lesen"):
    if foto is None:
        st.caption("Erst ein Foto übernehmen.")
    else:
        bild = _bild_laden(foto)
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
        st.button("Mit diesem Raster neu lesen", on_click=_neu_lesen, type="primary", help="Liest alle Zellen mit dem eingestellten Raster noch einmal und sucht die Partie neu. "
                  "Eigene Änderungen in der Tabelle gehen dabei verloren.", disabled=raster is None)

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
    st.info("Noch keine Züge. Übernimm oben ein Foto, dann läuft alles von selbst.")
else:
    regelverstoesse = z["illegal"] + z["nach_ende"]
    unsicher_bild = {ply: e for ply, e in (st.session_state.get("pf_unsicher") or {}).items()
                     if ply < len(p.zuege) and st.session_state["pf_zeilen"][ply // 2][ply % 2] == st.session_state["pf_auto_zeilen"][ply // 2][ply % 2]}
    m = st.columns(6 if st.session_state.get("pf_unsicher") is not None else 5)
    m[0].metric("Halbzüge gelesen", p.halbzuege)
    m[1].metric("in Ordnung", z["ok"] + z["hinweis"], help="Genau ein legaler Zug passt. Davon sind so viele bereinigt: " + str(z["hinweis"]))
    m[2].metric("unklar", z["unklar"], help="Mehrere legale Züge passen, ein Zeichen ist unleserlich oder ein Zug fehlt.")
    m[3].metric("Regelverstöße", regelverstoesse, help="Kein legaler Zug passt, oder ein Zug steht nach dem Ende der Partie.")
    m[4].metric("nicht prüfbar", z["nicht_pruefbar"], help="Steht hinter einem Regelverstoß: die Stellung ist ab dort unbekannt.")
    if len(m) == 6:
        m[5].metric("unsicher (Bild)", len(unsicher_bild), help="Das Bild der Zelle sieht den gewählten Zug nicht klar vor den anderen legalen Zügen (Anteil unter 95 %). Die Zuversicht der Suche allein ist zu hoch, deshalb zählt das Bild.")
    befunde = P.ergebnis_befunde(p, G.normiere_ergebnis(kopf_roh.get("Result", ""))) + p.befunde
    if unsicher_bild:
        erste = min((e for e in unsicher_bild.values() if e.passt_schlecht()), key=lambda e: e.ply, default=min(unsicher_bild.values(), key=lambda e: e.ply))
        folge = st.session_state.get("pf_folge_ab")
        st.info(f"**Von oben nach unten prüfen:** Fehler ziehen spätere Züge mit. Beginne bei {erste.ply // 2 + 1}. {'Weiß' if erste.ply % 2 == 0 else 'Schwarz'} "
                f"(Bild: {formular_san(erste.san)} {pct(erste.zellanteil, 0)}" + "".join(f", {formular_san(s)} {pct(a, 0)}" for s, a in erste.bild_alternativen[:2] if a >= 0.02) + "). "
                + (f"Ab dem {folge // 2 + 1}. Zug häufen sich unsichere Zellen: Dort ist vermutlich ein früherer Fehler die Ursache, und die Züge danach sind oft alle falsch. " if folge is not None else "")
                + "Korrigiere die Zelle in der Tabelle, dann „Korrekturen übernehmen und weiter suchen“.")
    if p.datenbanktauglich() and unsicher_bild:
        st.warning(f"Regelkonform, aber {len(unsicher_bild)} Zelle(n) sind nach dem Bild unsicher (Spalte „Bild“). Die Regeln lassen in diesen Stellungen auch andere Züge zu: Prüfe sie gegen das Foto, bevor Du das PGN benutzt.")
    elif p.datenbanktauglich():
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

    st.toggle("Nur Auffälliges zeigen", key="pf_nur_auffaellig", help="Blendet Zellen aus, die in Ordnung und nach dem Bild sicher sind.")
    zeilen_tab = []
    for e in p.zuege:
        if st.session_state.get("pf_nur_auffaellig") and e.status in ("ok", "ergebnis", "leer") and e.ply not in unsicher_bild:
            continue
        icon, wort = C.STATUS[e.status]
        hinweis = " · ".join(x.text for x in e.meldungen if x.stufe != "info" or e.status in ("hinweis", "unklar"))
        eintrag = {"Zug": e.beschriftung, "Formular": e.roh.strip() or "(leer)", "Status": f"{icon} {wort}"}
        if st.session_state.get("pf_unsicher") is not None:
            u = unsicher_bild.get(e.ply)
            eintrag["Bild"] = ("✗ passt schlecht" if u.passt_schlecht() else "⚠ unsicher") if u else ""
            if u:
                sonst = ", ".join(f"{formular_san(s)} {pct(a, 0)}" for s, a in u.bild_alternativen if a >= 0.02)
                hinweis = (hinweis + " · " if hinweis else "") + f"Bild: {formular_san(u.san)} nur {pct(u.zellanteil, 0)}" + (f", sonst {sonst}" if sonst else "")
        eintrag.update({"Hinweis": hinweis, "_s": e.status})
        zeilen_tab.append(eintrag)
    if zeilen_tab:
        df = pd.DataFrame(zeilen_tab)
        stile = df["_s"].map(C.FARBEN)
        sichtbar = df.drop(columns="_s")
        st.dataframe(sichtbar.style.apply(lambda r: [f"background-color: {stile[r.name]}"] * len(r), axis=1), hide_index=True, width="stretch",
                     height=min(38 * (len(sichtbar) + 1) + 2, 460))
        st.caption("Grün: in Ordnung · Blau: genau ein Zug passt, die Schreibweise wurde bereinigt · Gelb: unklar, vorläufig gewählt · Rot: Regelverstoß · Grau: nicht prüfbar.")
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

# ------------------------------------------------------------------------------------------------- 4 PGN
st.header("3 · PGN für die Datenbank")
modi = L.export_modi(p) if p.zuege else []
if not p.zuege:
    st.caption("Sobald Züge gelesen sind, erscheint hier das PGN.")
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
with st.expander("📖 So arbeitet die App und wo sie an Grenzen kommt"):
    st.markdown(
        """
* **Raster:** Die App sucht die gedruckten Zeilenlinien (auch bei Formularen ohne senkrechte Linien, etwa drei Blöcke zu 20 Zügen) und schneidet jede Zelle aus.
* **Lesen:** Ein kleines Modell (CNN mit BiLSTM, auf Handschrift-Zellen und gerenderten Zügen trainiert) liest jede Zelle, englische und deutsche Figurenbuchstaben (S, L, T, D).
* **Entschlüsseln:** Eine Strahlsuche über die ganze Partie nimmt den wahrscheinlichsten Verlauf, in dem jeder Zug legal ist. Ein falsch gelesener Zug, der die Folgezellen unmöglich macht, verliert gegen den richtigen.
  Ein früher Fehler zieht aber spätere Züge mit; korrigiere die erste falsche Zelle in der Tabelle, dann prüft die App neu.
* **Prüfen:** Jeder Zug wird gegen die Schachregeln geprüft (eigener Zuggenerator, gegen python-chess getestet). Mehrere mögliche Züge, ein unleserliches Zeichen oder ein Regelverstoß erscheinen unter „Nacharbeit“ mit Vorschlägen.
* **Grenzen:** Handschrift verlässlich lesen kann die App nicht. Bleistift, Schreibschrift und fremde Schreiber sind schwer; echte deutsche Ligabögen hat das Modell kaum gesehen. Varianten, Kommentare und Zeitangaben werden nicht übernommen,
  nur die normale Grundstellung, kein Schach960. Das PGN ist UTF-8 und lässt sich in Lichess, Scid und ChessBase öffnen (in ChessBase und Scid nicht geprüft).
"""
    )

st.markdown("---")
st.caption("Teil von [Sebastians Spielwiese](https://sebastians-spielwiese.net/) · Schachregeln und Prüfung im Repo, gegen python-chess getestet · Figuren: „cburnett“ von Colin M. L. Burnett (BSD).")
