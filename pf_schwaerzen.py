"""Foto im Browser wählen und Namen schwärzen, bevor etwas an den Server geht (Streamlit-Komponente aus HTML und JavaScript, kein Build, nur Standardbibliothek).

Die Datei wird in der Komponente nur im Browser gelesen. Der Nutzer zieht schwarze Rechtecke über Namen und andere Angaben; erst nach „Übernehmen“ schickt die Komponente ein
neu gezeichnetes JPEG (ohne Dateiname und EXIF, längste Seite höchstens 2200 Pixel) als Data-URL an die App. Der Server sieht also nie das Original, nur das geschwärzte Bild.
Technisch geprüft wird hier nur, dass ein JPEG in angemessener Größe ankommt; ob wirklich alle Namen geschwärzt sind, entscheidet der Mensch vor dem Bildschirm.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from pathlib import Path

import streamlit.components.v1 as components

FRONTEND = Path(__file__).resolve().parent / "pf_schwaerzen_frontend"
PRAEFIX = "data:image/jpeg;base64,"
MAX_BYTES = 12 * 1024 * 1024
_komponente = components.declare_component("pf_schwaerzen", path=str(FRONTEND))


@dataclass(frozen=True)
class Foto:
    """Das übernommene Bild; `file_id` wechselt mit jedem Übernehmen (die App sucht dann das Raster neu)."""
    file_id: str
    daten: bytes
    flaechen: int = 0

    def getvalue(self) -> bytes:
        return self.daten


def dekodieren(wert: dict | None) -> Foto | None:
    """Wert der Komponente -> Foto, oder None bei leerem, fremdem oder zu großem Inhalt."""
    if not isinstance(wert, dict):
        return None
    url = wert.get("dataUrl")
    if not isinstance(url, str) or not url.startswith(PRAEFIX):
        return None
    try:
        daten = base64.b64decode(url[len(PRAEFIX):], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not (0 < len(daten) <= MAX_BYTES) or daten[:3] != b"\xff\xd8\xff":
        return None
    return Foto(file_id=str(wert.get("n", "")), daten=daten, flaechen=int(wert.get("flaechen", 0) or 0))


def foto_schwaerzen(key: str) -> Foto | None:
    """Zeigt die Komponente; liefert das zuletzt übernommene Bild oder None."""
    return dekodieren(_komponente(key=key, default=None))
