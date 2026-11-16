"""Schwärzen im Browser: Wert der Komponente prüfen, Rahmen der Frontend-Datei (die Pixel prüft die Browser-Verifikation)."""
import base64
import io
import re

import pytest
from PIL import Image

import pf_schwaerzen as SW

HTML = (SW.FRONTEND / "index.html").read_text(encoding="utf-8")


def jpeg_bytes() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 0, 0)).save(puffer, "JPEG")
    return puffer.getvalue()


def wert(daten: bytes, n: str = "1-1", flaechen: int = 2) -> dict:
    return {"n": n, "dataUrl": SW.PRAEFIX + base64.b64encode(daten).decode(), "flaechen": flaechen}


def test_gueltiges_jpeg_wird_zum_foto():
    foto = SW.dekodieren(wert(jpeg_bytes(), "7-99", 3))
    assert foto is not None and foto.file_id == "7-99" and foto.flaechen == 3
    assert foto.getvalue()[:3] == b"\xff\xd8\xff" and Image.open(io.BytesIO(foto.getvalue())).size == (40, 30)


@pytest.mark.parametrize("schlecht", [
    None, "text", {}, {"n": "1", "dataUrl": None}, {"n": "1", "dataUrl": "data:image/png;base64,AAAA"},
    {"n": "1", "dataUrl": SW.PRAEFIX + "!!!kein base64!!!"}, {"n": "1", "dataUrl": SW.PRAEFIX},
])
def test_ungueltige_werte_ergeben_kein_foto(schlecht):
    assert SW.dekodieren(schlecht) is None


def test_kein_jpeg_inhalt_oder_zu_gross_wird_abgelehnt():
    assert SW.dekodieren(wert(b"GIF89a....")) is None                       # Endung stimmt, Inhalt nicht
    assert SW.dekodieren(wert(b"\xff\xd8\xff" + b"0" * (SW.MAX_BYTES + 1))) is None


def test_frontend_liest_die_datei_nur_im_browser_und_sendet_ein_neu_gezeichnetes_bild():
    for teil in ("streamlit:componentReady", "streamlit:setComponentValue", "streamlit:setFrameHeight", "createObjectURL", 'toDataURL("image/jpeg"', "fillRect"):
        assert teil in HTML, teil
    assert "FileReader" not in HTML                                             # kein Lesen der Rohdaten, nur Bild und Canvas
    sendet = HTML[HTML.index('document.getElementById("ok")'):]
    assert "dataUrl" in sendet and ".name" not in sendet and "lastModified" not in sendet, "kein Dateiname und keine Aufnahmedaten an die App"
    assert re.search(r"fillRect\(0, 0, W, H \* z / 100\)", HTML), "obere Zone wird im gesendeten Bild geschwärzt"
    assert "boxen.forEach(function (b) { x.fillRect" in HTML, "Markierungen werden im gesendeten Bild geschwärzt"
    assert "http://" not in HTML and "https://" not in HTML, "lädt nichts von außen"
    assert "fetch(" not in HTML and "XMLHttpRequest" not in HTML and "sendBeacon" not in HTML, "kein eigener Netzzugriff"
