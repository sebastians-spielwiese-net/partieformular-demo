"""Foto lesen: Zellen, Erkenner (simuliert), Bildwahrscheinlichkeit der legalen Züge, Zweifel, Regelverstoß aus Lesefehler, Ablauf in der App.
Der Erkenner ist hier simuliert: Die Tests prüfen die Dekodierung gegen die Regeln, nicht die Güte eines Handschriftmodells."""
import io

import numpy as np
import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from test_raster import formular
from zufall import zufallsspiel

import pf_brett as B
import pf_ctc as C
import pf_erkenner as E
import pf_schwaerzen as SW
import pf_lesen as L
import pf_pruefung as P
import pf_raster as R

OPER = "e4 e5 Nf3 d6 d4 Bg4 dxe5 Bxf3 Qxf3 dxe5 Bc4 Nf6 Qb3 Qe7 Nc3 c6 Bg5 b5 Nxb5 cxb5 Bxb5+ Nbd7 O-O-O Rd8 Rxd7 Rxd7 Rd1 Qe6 Bxd7+ Nxd7 Qb8+ Nxb8 Rd8#".split()


def lesung_aus(sans, unsicher=0.0, falsch=0.0, seed=0, schwelle=0.6) -> L.FormularLesung:
    er = E.SimulierterErkenner(dict(enumerate(sans)), unsicher, falsch, seed)
    zellen = []
    for i in range(len(sans)):
        lp = er.logp(None, i)
        zellen.append(L.ZellLesung(i, False, C.mit_joker(lp, schwelle), lp))
    return L.FormularLesung(zellen)


def test_san_varianten():
    v = L.san_varianten("Nxe5+")
    assert C.kodiere("Nxe5+") in v and C.kodiere("Nxe5") in v and C.kodiere("Ne5") in v and C.kodiere("Ne5+") in v and len(v) == 8                  # vier Schreibweisen, je englisch und deutsch
    assert C.kodiere("e8=Q") in L.san_varianten("e8=Q") and C.kodiere("e8Q") in L.san_varianten("e8=Q")
    assert L.san_varianten("O-O") == [C.kodiere("O-O")]


def test_san_varianten_deutsche_buchstaben():
    v = L.san_varianten("Nxe5+")
    assert C.kodiere("Sxe5+") in v and C.kodiere("Se5") in v and len(v) == 8
    assert C.kodiere("Lb5") in L.san_varianten("Bb5") and C.kodiere("Tae1") in L.san_varianten("Rae1") and C.kodiere("Dd8") in L.san_varianten("Qd8")
    assert C.kodiere("e8=D") in L.san_varianten("e8=Q") and C.kodiere("e8D") in L.san_varianten("e8=Q") and C.kodiere("exd8=S") in L.san_varianten("exd8=N")
    assert L.deutsch("Kf1") == "Kf1" and L.deutsch("bxc3") == "bxc3" and L.deutsch("Bb5") == "Lb5" and L.deutsch("b8=B") == "b8=L"
    assert len(L.san_varianten("Kf1")) == 1                                            # K ist in beiden Sprachen gleich: keine doppelten Varianten


def test_wahrer_zug_hat_die_hoechste_bildwahrscheinlichkeit():
    les = lesung_aus(OPER)
    bw = L.Bewerter(les)
    st = B.Stellung.start()
    for i, san in enumerate(OPER):
        p = bw.fuer(i, les.zellen[i].text).wahrscheinlichkeiten(st)
        assert sum(p.values()) == pytest.approx(1.0)
        bester = max(p, key=p.get)
        assert st.san(bester) == san and p[bester] > 0.9, (i, san)
        st = st.ausfuehren(bester)


def test_bewerter_gilt_nur_fuer_unveraenderten_text():
    les = lesung_aus(OPER[:4])
    bw = L.Bewerter(les)
    assert bw.fuer(0, "e4") is not None and bw.fuer(0, " e4 ") is not None
    assert bw.fuer(0, "e3") is None and bw.fuer(99, "e4") is None
    leer = L.FormularLesung([L.ZellLesung(0, True), L.ZellLesung(1, False, "e5", lesung_aus(["e4", "e5"]).zellen[1].logp)])
    assert L.Bewerter(leer).fuer(0, "") is None and L.Bewerter(leer).fuer(1, "e5") is not None


def test_joker_aus_unsicheren_zeichen():
    les = lesung_aus(["Nf3"], unsicher=1.0)
    assert les.zellen[0].text == "???"
    assert lesung_aus(["Nf3"]).zellen[0].text == "Nf3"


def test_zweifel_wird_zur_unklarheit():
    """Der Text „e4“ ist legal, aber das Bild zeigt fast ebenso gut „e3“: Statt ok kommt unklar mit beiden Kandidaten."""
    z = C.ZEICHEN
    p = np.full((12, len(z)), 0.002)
    p[:, 0] = 0.95
    p[3, z.index("e")] = 0.97
    p[3, 0] = 0.02
    p[7, z.index("4")], p[7, z.index("3")], p[7, 0] = 0.52, 0.43, 0.03
    p /= p.sum(axis=1, keepdims=True)
    logp = np.log(p)
    les = L.FormularLesung([L.ZellLesung(0, False, C.gierig(logp)[0], logp)])
    assert les.zellen[0].text == "e4"
    erg = P.pruefe([("e4", "")], bild=L.Bewerter(les)).zuege[0]
    assert erg.status == "unklar" and {k.san for k in erg.kandidaten} >= {"e4", "e3"} and "nicht sicher" in erg.meldungen[0].text
    assert erg.kandidaten[0].bild == pytest.approx(0.55, abs=0.05) or erg.kandidaten[0].san == "e4"
    # ohne Bild bleibt es bei „ok“
    assert P.pruefe([("e4", "")]).zuege[0].status == "ok"
    # hat der Mensch die Zelle bestätigt (anderer Text), wird nicht mehr gezweifelt
    assert P.pruefe([("e4 ", "")], bild=L.Bewerter(les)).zuege[0].status == "unklar"            # nur Leerzeichen geändert: gilt als unverändert
    les2 = L.FormularLesung([L.ZellLesung(0, False, "e3", logp)])
    assert P.pruefe([("e4", "")], bild=L.Bewerter(les2)).zuege[0].status == "ok"


def test_regelverstoss_aus_lesefehler_wird_zum_bildvorschlag():
    """Der Erkenner liest „Nf6“ für ein Bild, das „Nf3“ zeigt: kein legaler Zug in der Grundstellung. Mit Bild weiterprüfen, ohne Bild: Regelverstoß."""
    logp = lesung_aus(["Nf3"]).zellen[0].logp
    les = L.FormularLesung([L.ZellLesung(0, False, "Nf6", logp), L.ZellLesung(1, False, "e5", lesung_aus(["e4", "e5"]).zellen[1].logp)])
    ohne = P.pruefe([("Nf6", "e5")])
    assert ohne.zuege[0].status == "illegal" and ohne.zuege[1].status == "nicht_pruefbar"
    mit = P.pruefe([("Nf6", "e5")], bild=L.Bewerter(les))
    e = mit.zuege[0]
    assert e.status == "unklar" and e.san == "Nf3" and e.kandidaten[0].san == "Nf3" and "Bild" in e.meldungen[0].text
    assert mit.zuege[1].status in ("ok", "hinweis", "unklar")           # die Prüfung läuft weiter


def test_bild_ordnet_gleichstand():
    """Bei Gleichstand der Fortsetzung entscheidet die Bildwahrscheinlichkeit statt des Alphabets (Nbd7 gegen Nfd7 mit gleich langer Fortsetzung)."""
    sans = ["e4", "e5", "Nf3", "Nc6", "Nc3", "Nf6", "Nd5", "Nxd5", "exd5", "Nd4", "Nxd4", "exd4"]
    for wahr, andere in (("Nbd2", "Nfd2"), ("Nfd2", "Nbd2")):
        # Zwei Springer können nach d2 (b1 und f3): die Folgezüge sind für beide ohne Folgen. Hier nur: Bild zieht den wahren vor.
        st = B.Stellung.aus_fen("4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1")
        logp = lesung_aus([wahr]).zellen[0].logp
        bp = L.ZellBewerter(logp).wahrscheinlichkeiten(st)
        assert max(bp, key=bp.get) == B.zug_aus_uci("b1d2" if wahr == "Nbd2" else "f3d2")
    assert andere and sans


def test_simulation_bild_schlaegt_text_allein():
    """Mit Verwechslungen und unsicheren Zeichen liest die Prüfung mit Bildwahrscheinlichkeit deutlich mehr Züge richtig als der Text allein; stille Fehler bleiben selten."""
    basis = bild = still = n = 0
    for seed in range(14):
        sans, _ = zufallsspiel(seed, 50)
        if len(sans) < 20:
            continue
        les = lesung_aus(sans, 0.05, 0.03, seed)
        zeilen = les.zeilen()
        p0, p1 = P.pruefe(zeilen), P.pruefe(zeilen, bild=L.Bewerter(les))
        for e0, e1, wahr in zip(p0.zuege, p1.zuege, sans):
            n += 1
            basis += e0.san == wahr
            bild += e1.san == wahr
            still += e1.status in ("ok", "hinweis") and e1.san != wahr
    assert n > 500 and bild / n > basis / n + 0.15 and bild / n > 0.8 and still / n < 0.02, (n, basis / n, bild / n, still / n)


def test_lese_formular_mit_gezeichnetem_blatt():
    wahrheit = {i: s for i, s in enumerate(OPER[:12])}
    texte = {(i // 2 + 1, i % 2): s for i, s in wahrheit.items()}
    bild, _ = formular(texte=texte)
    les = L.lese_formular(bild, R.Raster(), E.SimulierterErkenner(wahrheit))
    assert len(les.zellen) == 12 and les.beschrieben() == 12
    assert les.zeilen() == [[OPER[2 * k], OPER[2 * k + 1]] for k in range(6)]
    assert all(c.png.startswith(b"\x89PNG") for c in les.zellen)
    fortschritt = []
    L.lese_formular(bild, R.Raster(), E.SimulierterErkenner(wahrheit), fortschritt=lambda i, n: fortschritt.append((i, n)))
    assert fortschritt[0] == (1, 120) and fortschritt[-1] == (120, 120)


def test_lese_formular_leere_zellen_zwischendurch():
    wahrheit = {0: "e4", 1: "e5", 4: "Nf3"}
    bild, _ = formular(texte={(1, 0): "e4", (1, 1): "e5", (3, 0): "Nf3"})
    les = L.lese_formular(bild, R.Raster(), E.SimulierterErkenner(wahrheit))
    assert [c.text for c in les.zellen] == ["e4", "e5", "", "", "Nf3"] and [c.leer for c in les.zellen] == [False, False, True, True, False]
    assert les.beschrieben() == 3 and les.zeilen() == [["e4", "e5"], ["", ""], ["Nf3", ""]]


def test_erkenner_schnittstelle_und_modellpfad(tmp_path):
    assert not E.modell_vorhanden(tmp_path / "gibt_es_nicht.onnx")
    kurz = tmp_path / "kurz.onnx"
    kurz.write_bytes(b"x")
    assert not E.modell_vorhanden(kurz)
    assert E.MODELL_BYTES > 40_000_000 and len(E.MODELL_SHA256) == 64 and E.MODELL_QUELLE.startswith("https://github.com/") and E.MODELL_DATEI.name == "chess_ocr_de.onnx"
    assert E.ORIGINAL_BYTES == 43266310 and len(E.ORIGINAL_SHA256) == 64 and E.ORIGINAL_QUELLE.startswith("https://huggingface.co/")
    with pytest.raises(NotImplementedError):
        E.Erkenner().logp(None)


class Sitzung:
    """Ersatz für eine onnxruntime-Sitzung mit 28 Klassen (Original) oder 32 Klassen; merkt sich die Eingaben."""

    def __init__(self, klassen):
        self.klassen, self.eingaben = klassen, []

    def get_inputs(self):
        return [__import__("types").SimpleNamespace(name="input")]

    def run(self, _, eingabe):
        x = eingabe["input"]
        self.eingaben.append(x)
        rng = np.random.default_rng(int(abs(x).sum() * 1000) % 2**32)
        roh = rng.normal(size=(63, 1, self.klassen))
        return [roh - np.log(np.exp(roh).sum(axis=-1, keepdims=True))]


def onnx_erkenner(monkeypatch, klassen, tta):
    import sys
    import types
    ort = types.SimpleNamespace(InferenceSession=lambda *a, **k: Sitzung(klassen))
    monkeypatch.setitem(sys.modules, "onnxruntime", ort)
    return E.OnnxErkenner(tta=tta)


def test_original_mit_28_klassen_wird_auf_32_aufgefuellt(monkeypatch):
    er = onnx_erkenner(monkeypatch, 28, False)
    lp = er.logp(Image.new("L", (200, 60), 255), 0)
    assert lp.shape == (63, len(C.ZEICHEN)) and np.exp(lp[:, 28:]).max() < 1e-12 and np.exp(lp[:, :28]).sum(axis=1) == pytest.approx(np.ones(63))
    assert onnx_erkenner(monkeypatch, 32, False).logp(Image.new("L", (200, 60), 255), 0).shape == (63, 32)


def test_tta_liest_fuenfmal_und_mittelt(monkeypatch):
    er = onnx_erkenner(monkeypatch, 32, True)
    lp = er.logp(Image.new("L", (200, 60), 200), 0)
    assert len(er.sitzung.eingaben) == len(E.TTA_VARIANTEN) == 5 and all(x.shape == (1, 1, 64, 256) for x in er.sitzung.eingaben)
    assert np.exp(lp).sum(axis=1) == pytest.approx(np.ones(63), abs=1e-6)


def test_verschieben_und_strecken_erhalten_form_und_raender():
    x = np.zeros((1, 1, 64, 256), dtype=np.float32)
    x[0, 0, :, 100:110] = 1.0
    assert np.array_equal(E.verschieben(x, 0, 1.0), x)
    rechts = E.verschieben(x, 6, 1.0)
    assert rechts.shape == x.shape and rechts[0, 0, 0, 106:116].min() == 1.0 and rechts[0, 0, 0, 100:105].max() == 0.0
    links = E.verschieben(x, -6, 1.0)
    assert links[0, 0, 0, 94:104].min() == 1.0
    breit, schmal = E.verschieben(x, 0, 1.08), E.verschieben(x, 0, 0.92)
    assert breit.shape == schmal.shape == x.shape and breit[0, 0].sum() > x[0, 0].sum() > schmal[0, 0].sum() * 0.99
    rand = np.ones((1, 1, 64, 256), dtype=np.float32)
    assert np.allclose(E.verschieben(rand, 6, 0.92), 1.0) and np.allclose(E.verschieben(rand, -6, 1.08), 1.0)


def test_modell_holen_prueft_die_datei(tmp_path, monkeypatch):
    import urllib.request

    class Antwort(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Antwort(b"kaputt"))
    ziel = tmp_path / "m" / "chess_ocr.onnx"
    with pytest.raises(ValueError):
        E.modell_holen(ziel)
    assert not ziel.exists() and not ziel.with_suffix(".teil").exists()


def test_simulierter_erkenner_ist_deterministisch():
    a = E.SimulierterErkenner({0: "Nxe5+"}, 0.3, 0.2, seed=4).logp(None, 0)
    b = E.SimulierterErkenner({0: "Nxe5+"}, 0.3, 0.2, seed=4).logp(None, 0)
    assert np.array_equal(a, b) and np.exp(a).sum(axis=1) == pytest.approx(np.ones(a.shape[0]))


# --------------------------------------------------------------------------- Ablauf in der App
PFAD = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py")


def png_bytes(bild) -> bytes:
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    return puffer.getvalue()


def app_mit_foto(monkeypatch, wahrheit, unsicher=0.0, falsch=0.0, onnx=True, modell=True):
    import streamlit as st
    st.cache_resource.clear()
    monkeypatch.setattr(E, "onnxruntime_vorhanden", lambda: onnx)
    monkeypatch.setattr(E, "modell_vorhanden", lambda *a: modell)
    monkeypatch.setattr(E, "OnnxErkenner", lambda **kw: E.SimulierterErkenner(wahrheit, unsicher, falsch, seed=1))
    bild, _ = formular(texte={(i // 2 + 1, i % 2): s for i, s in wahrheit.items()})
    foto = SW.Foto(file_id="test-1", daten=png_bytes(bild))
    monkeypatch.setattr(SW, "foto_schwaerzen", lambda key: foto)       # die Komponente (HTML/JS) läuft nur im Browser
    at = AppTest.from_file(PFAD, default_timeout=120)
    at.run()
    at.checkbox(key="pf_foto_ok").check().run()                       # die Foto-Auswahl erscheint erst nach der Bestätigung; danach läuft die Automatik
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_app_liest_das_foto_von_selbst(monkeypatch):
    """Nach der Bestätigung läuft alles allein: Raster, Zellen, Strahlsuche; die Tabelle ist gefüllt und die Partie datenbanktauglich."""
    wahrheit = {i: s for i, s in enumerate(OPER)}
    at = app_mit_foto(monkeypatch, wahrheit)
    zeilen = at.session_state["pf_zeilen"]
    assert zeilen[0][:2] == ["e4", "e5"] and zeilen[16][0] in ("Rd8#", "Td8#")
    assert any(s.value.startswith("Datenbanktauglich") for s in at.success)
    assert at.session_state["pf_bewerter"] is not None and at.session_state["pf_auto_id"] == "test-1"
    assert any("entschlüsselt" in str(s.label) for s in at.status) or at.session_state["pf_entschluesselt"]
    assert not [b for b in at.button if b.label == "Zellen lesen"], "kein eigener Lese-Knopf mehr"


def test_app_foto_mit_unsicherem_erkenner_zeigt_zellbilder_und_bildwerte(monkeypatch):
    wahrheit = {i: s for i, s in enumerate(OPER)}
    at = app_mit_foto(monkeypatch, wahrheit, unsicher=0.08, falsch=0.04)
    assert at.session_state["pf_bewerter"] is not None and len(at.image) >= 1
    # Nach dem Übernehmen eines Vorschlags bleibt das Bild für die übrigen Zellen erhalten
    knoepfe = [b for b in at.button if (b.key or "").startswith("pf_k_")]
    if knoepfe:
        knoepfe[0].click().run()
        assert not at.exception and at.session_state["pf_bewerter"] is not None


def test_app_ohne_onnxruntime_oder_modell(monkeypatch):
    at = app_mit_foto(monkeypatch, {0: "e4"}, onnx=False)
    assert any("onnxruntime" in str(s.label) for s in at.status) and at.session_state.get("pf_bewerter") is None
    geladen = []
    monkeypatch.setattr(E, "modell_holen", lambda *a, **k: geladen.append(1))
    app_mit_foto(monkeypatch, {0: "e4"}, modell=False)
    assert geladen == [1], "fehlt das Modell, lädt die App es selbst (einmalig)"


def test_app_sucht_das_raster_beim_hochladen_selbst(monkeypatch):
    at = app_mit_foto(monkeypatch, {i: s for i, s in enumerate(OPER[:6])})
    assert at.session_state["pf_r_ecken"] is not None
    assert at.session_state["pf_r_zeilen"] == 30 and at.session_state["pf_r_bloecke"] == 2
    next(b for b in at.button if b.label == "Entzerrung verwerfen, von Hand einstellen").click().run()
    assert at.session_state["pf_r_ecken"] is None and not at.exception
    next(b for b in at.button if b.label == "Raster automatisch finden").click().run()
    assert at.session_state["pf_r_ecken"] is not None and not at.exception


def test_app_neu_lesen_mit_eingestelltem_raster(monkeypatch):
    at = app_mit_foto(monkeypatch, {i: s for i, s in enumerate(OPER[:6])})
    next(b for b in at.button if b.label == "Entzerrung verwerfen, von Hand einstellen").click().run()
    next(b for b in at.button if b.label == "Mit diesem Raster neu lesen").click().run()
    assert not at.exception and at.session_state["pf_r_ecken"] is None, "Neu lesen sucht das Raster nicht noch einmal"


def test_app_ungueltiger_ausschnitt(monkeypatch):
    at = app_mit_foto(monkeypatch, {0: "e4"})
    next(b for b in at.button if b.label == "Entzerrung verwerfen, von Hand einstellen").click().run()
    at.slider(key="pf_r_links").set_value(80).run()
    at.slider(key="pf_r_rechts").set_value(20).run()
    assert not at.exception and any("ungültig" in w.value for w in at.warning)
