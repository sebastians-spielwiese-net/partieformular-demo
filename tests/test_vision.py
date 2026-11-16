"""Vision-Modell: Anfrage, Antwort, Fehler, Datenschutz (nur die Zugtabelle), Ablauf in der App. Der Client ist ein Ersatz: Es wird nie die echte API aufgerufen."""
import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest
from test_entzerren import SCHIEF, foto, vorlage

import pf_raster as R
import pf_vision as V


class Ersatzclient:
    """Sieht aus wie anthropic.Anthropic für die eine Methode, die gebraucht wird, und merkt sich die Anfrage."""

    def __init__(self, antwort=None, fehler=None, stop="end_turn"):
        self.anfragen = []
        self._antwort, self._fehler, self._stop = antwort, fehler, stop
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.anfragen.append(kw)
        if self._fehler:
            raise self._fehler
        text = self._antwort if isinstance(self._antwort, str) else json.dumps(self._antwort)
        return SimpleNamespace(stop_reason=self._stop, content=[SimpleNamespace(type="text", text=text)])


ANTWORT = {"zeilen": [{"nr": 1, "weiss": "e4", "schwarz": "e5"}, {"nr": 2, "weiss": "Sf3", "schwarz": "Sc6"}, {"nr": 3, "weiss": "Lb5", "schwarz": "a?"}], "hinweise": []}


def raster_und_foto():
    bild = foto(vorlage(texte={(1, 0): "e4", (1, 1): "e5"}), SCHIEF)
    raster, _ = R.raster_finden(bild)
    assert raster.ecken is not None
    return bild, raster


def test_anfrage_mit_raster_sendet_nur_die_tabelle():
    bild, raster = raster_und_foto()
    c = Ersatzclient(ANTWORT)
    zeilen, hinweise = V.lies_zeilen(bild, raster, "geheim", client=c)
    assert zeilen == [["e4", "e5"], ["Sf3", "Sc6"], ["Lb5", "a?"]] and hinweise == []
    kw = c.anfragen[0]
    assert kw["model"] == "claude-opus-5-5" and kw["betas"] == [V.BETA_FALLBACK] and kw["fallbacks"] == "default" and kw["max_tokens"] == V.MAX_TOKENS
    inhalt = kw["messages"][0]["content"]
    bilder = [b for b in inhalt if b["type"] == "image"]
    assert len(bilder) == raster.bloecke == 2 and inhalt[-1]["type"] == "text" and inhalt[0]["type"] == "image"
    for b in bilder:
        assert b["source"]["type"] == "base64" and b["source"]["media_type"] == "image/jpeg"
        jpeg = base64.b64decode(b["source"]["data"])
        assert jpeg[:2] == b"\xff\xd8" and max(Image.open(io.BytesIO(jpeg)).size) <= V.MAX_SEITE
    assert "names and header are not included" in inhalt[-1]["text"] and "Do NOT correct" in inhalt[-1]["text"] and "German letters" in inhalt[-1]["text"]
    assert "geheim" not in json.dumps(kw, default=str)                           # der Schlüssel gehört in den Client, nie in die Anfrage


def test_anfrage_ohne_raster_sendet_das_ganze_foto():
    bild = Image.new("RGB", (3000, 2000), (240, 240, 240))
    c = Ersatzclient(ANTWORT)
    V.lies_zeilen(bild, None, "k", client=c)
    inhalt = c.anfragen[0]["messages"][0]["content"]
    assert len([b for b in inhalt if b["type"] == "image"]) == 1 and "whole sheet" in inhalt[-1]["text"]
    assert max(Image.open(io.BytesIO(base64.b64decode(inhalt[0]["source"]["data"]))).size) == V.MAX_SEITE


def test_schema_ist_streng():
    s = V.SCHEMA
    assert s["additionalProperties"] is False and set(s["required"]) == {"zeilen", "hinweise"}
    zeile = s["properties"]["zeilen"]["items"]
    assert zeile["additionalProperties"] is False and set(zeile["required"]) == {"nr", "weiss", "schwarz"}
    c = Ersatzclient(ANTWORT)
    V.lies_zeilen(Image.new("RGB", (400, 300), "white"), None, "k", client=c)
    assert c.anfragen[0]["output_config"] == {"format": {"type": "json_schema", "schema": s}}


def test_zeilen_nach_nummer_geordnet_mit_luecken_und_doppelten():
    zeilen, hinweise = V.zeilen_aus_antwort({"zeilen": [{"nr": 3, "weiss": " c4 ", "schwarz": "c5"}, {"nr": 1, "weiss": "e4", "schwarz": "e5"}, {"nr": 3, "weiss": "x", "schwarz": "y"},
                                                          {"nr": 0, "weiss": "q", "schwarz": "q"}, {"nr": 500, "weiss": "q", "schwarz": "q"}], "hinweise": ["Zug 1 überschrieben"]})
    assert zeilen == [["e4", "e5"], ["", ""], ["c4", "c5"]]
    text = " ".join(hinweise)
    assert "Zug 1 überschrieben" in text and "doppelt" in text and "unplausibler" in text and "Zug 2" in text
    assert V.zeilen_aus_antwort({"zeilen": [], "hinweise": []}) == ([], [])
    with pytest.raises(KeyError):
        V.zeilen_aus_antwort({"hinweise": []})


@pytest.mark.parametrize("fehler,teil", [
    (type("AuthenticationError", (Exception,), {})("x"), "nicht akzeptiert"),
    (type("RateLimitError", (Exception,), {})("x"), "Limit"),
    (type("APIConnectionError", (Exception,), {})("x"), "Keine Verbindung"),
    (type("PermissionDeniedError", (Exception,), {})("x"), "Berechtigung"),
    (RuntimeError("kaputt"), "RuntimeError"),
])
def test_fehler_werden_lesbar(fehler, teil):
    with pytest.raises(V.VisionFehler, match=teil):
        V.lies_zeilen(Image.new("RGB", (400, 300), "white"), None, "k", client=Ersatzclient(fehler=fehler))


def test_ablehnung_abbruch_und_kaputte_antwort():
    bild = Image.new("RGB", (400, 300), "white")
    with pytest.raises(V.VisionFehler, match="abgelehnt"):
        V.lies_zeilen(bild, None, "k", client=Ersatzclient(ANTWORT, stop="refusal"))
    with pytest.raises(V.VisionFehler, match="abgeschnitten"):
        V.lies_zeilen(bild, None, "k", client=Ersatzclient(ANTWORT, stop="max_tokens"))
    for text in ("kein json", '{"zeilen": [{"nr": "x"}], "hinweise": []}', '{"hinweise": []}', "[]"):
        with pytest.raises(V.VisionFehler, match="nicht lesbar"):
            V.lies_zeilen(bild, None, "k", client=Ersatzclient(text))


def test_ohne_schluessel_oder_paket(monkeypatch):
    bild = Image.new("RGB", (400, 300), "white")
    with pytest.raises(V.VisionFehler, match="Schlüssel"):
        V.lies_zeilen(bild, None, "")
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)          # Import schlägt fehl
    assert not V.sdk_vorhanden()
    with pytest.raises(V.VisionFehler, match="nicht installiert"):
        V.lies_zeilen(bild, None, "k")


def test_schluessel_aus_der_umgebung(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aus-der-umgebung")
    assert V.schluessel_aus_umgebung() == "aus-der-umgebung"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert V.schluessel_aus_umgebung() == ""


def test_gelesene_zeilen_laufen_durch_die_regelpruefung():
    """Das Vision-Ergebnis ist Text wie jeder andere: „a?“ wird aus den Regeln ergänzt oder als unklar gemeldet, deutsche Buchstaben werden gelesen."""
    import pf_pruefung as P
    zeilen, _ = V.zeilen_aus_antwort(ANTWORT)
    p = P.pruefe(zeilen)
    assert [e.san for e in p.zuege[:5]] == ["e4", "e5", "Nf3", "Nc6", "Bb5"]
    assert p.zuege[-1].status == "unklar" and "a6" in [k.san for k in p.zuege[-1].kandidaten]


# --------------------------------------------------------------------------- Ablauf in der App
PFAD = str(__import__("pathlib").Path(__file__).resolve().parent.parent / "app.py")


def png_bytes(bild) -> bytes:
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    return puffer.getvalue()


def app_mit_foto(monkeypatch, sdk=True):
    monkeypatch.setattr(V, "sdk_vorhanden", lambda: sdk)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    aufrufe = []

    def ersatz(bild, raster, schluessel, client=None):
        aufrufe.append((raster is not None and raster.ecken is not None, schluessel))
        return V.zeilen_aus_antwort(ANTWORT)

    monkeypatch.setattr(V, "lies_zeilen", ersatz)
    at = AppTest.from_file(PFAD, default_timeout=120)
    at.run()
    at.file_uploader(key="pf_foto").set_value(("formular.png", png_bytes(foto(vorlage(), SCHIEF)), "image/png"))
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at, aufrufe


def knopf(at):
    return next(b for b in at.button if b.label == "Mit Vision-Modell lesen")


def test_app_knopf_braucht_schluessel_und_einverstaendnis(monkeypatch):
    at, aufrufe = app_mit_foto(monkeypatch)
    assert knopf(at).disabled
    at.text_input(key="pf_api_key").set_value("k").run()
    assert knopf(at).disabled                                   # Einverständnis fehlt noch
    at.checkbox(key="pf_vision_ok").set_value(True).run()
    assert not knopf(at).disabled and not aufrufe


def test_app_liest_mit_dem_vision_modell(monkeypatch):
    at, aufrufe = app_mit_foto(monkeypatch)
    at.text_input(key="pf_api_key").set_value("mein-schluessel").run()
    at.checkbox(key="pf_vision_ok").set_value(True).run()
    knopf(at).click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert aufrufe == [(True, "mein-schluessel")]                # mit gefundenem Raster: nur die Tabelle
    assert at.session_state["pf_zeilen"][2][:2] == ["Lb5", "a?"] and "pf_bewerter" not in at.session_state
    assert any("vom Vision-Modell gelesen" in s.value for s in at.success)
    assert [m.label for m in at.metric][:1] == ["Halbzüge gelesen"]


def test_app_zeigt_fehler_des_modells(monkeypatch):
    at, _ = app_mit_foto(monkeypatch)

    def fehler(*a, **k):
        raise V.VisionFehler("Der API-Schlüssel wurde nicht akzeptiert.")
    monkeypatch.setattr(V, "lies_zeilen", fehler)
    at.text_input(key="pf_api_key").set_value("falsch").run()
    at.checkbox(key="pf_vision_ok").set_value(True).run()
    knopf(at).click().run()
    assert not at.exception and any("nicht akzeptiert" in e.value for e in at.error)


def test_app_ohne_sdk_zeigt_hinweis_und_sperrt(monkeypatch):
    at, _ = app_mit_foto(monkeypatch, sdk=False)
    assert any("`anthropic` ist hier nicht installiert" in w.value for w in at.warning) and knopf(at).disabled
