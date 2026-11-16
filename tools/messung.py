"""Messung: Wie gut löst die Prüfung Unklarheiten auf? Zufallspartien, jeweils eine Störung, Vergleich mit dem wahren Zug (python-chess nur hier).

Fünf Störungen, je Partie höchstens eine Messung, immer mit festen Zufalls-Seeds (Partie `s`, Störung mit `random.Random(s)`):
  zusatz      Zusatz bei zwei gleichen Figuren weggelassen („Nbd7“ -> „Nd7“): erste Zelle der Partie mit Zusatz
  zeichen     ein Zeichen der Zelle durch „?“ ersetzt (Figur, Linie oder Reihe des Zielfelds), zufällige Zelle ab Halbzug 6
  luecke      Zelle leer gelassen, zufällige Zelle ab Halbzug 6, mindestens 10 Halbzüge danach
  erfunden    Zug durch eine erfundene Figur-Feld-Angabe ersetzt, die nicht geht (Regelverstoß)
  zielfeld    Linie des Zielfelds eines wahren Zugs um eins verschoben, wenn das nicht geht: Regelverstoß; stehen die wahren Züge unter den Vorschlägen?
  frueher     ein früherer Zug durch einen anderen legalen Zug derselben Figurenart ersetzt; später zeigt sich ein Regelverstoß: nennt die App die frühere Zelle?
Aufruf: python tools/messung.py [--partien N] [--ausgabe data/messung.json]
"""
import argparse
import json
import random
import sys
from pathlib import Path

import chess

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
sys.path.insert(0, str(WURZEL / "tools"))

import pf_pruefung as P  # noqa: E402
from zufall import zeilen, zufallsspiel  # noqa: E402

PARTIEN = 300
MINDEST_LAENGE = 24


def partien(n: int):
    for seed in range(n):
        sans, _ = zufallsspiel(seed, 90)
        if len(sans) >= MINDEST_LAENGE:
            yield seed, sans


def spitze(kand) -> tuple[bool, int]:
    """(Gleichstand an der Spitze?, Anzahl der Kandidaten mit gleicher Spitzenlänge)"""
    top = (kand[0].fortsetzung, kand[0].ganz)
    gleich = [k for k in kand if (k.fortsetzung, k.ganz) == top]
    return len(gleich) > 1, len(gleich)


def zaehle(d: dict, kand: list, wahr: str) -> None:
    """Zählt für eine unklare Zelle: steht der wahre Zug unter den Kandidaten, gibt es an der Spitze einen Gleichstand, und wenn nicht: ist der erste der wahre?"""
    namen = [k.san.rstrip("+#") for k in kand]
    d["wahrer_unter_kandidaten"] += wahr in namen
    gleich, anzahl = spitze(kand)
    if gleich:
        d["gleichstand"] += 1
        d["gleichstand_wahrer_dabei"] += wahr in namen[:anzahl]
        d["gleichstand_kandidaten_summe"] += anzahl
    else:
        d["ohne_gleichstand"] += 1
        d["ohne_gleichstand_richtig"] += namen[0] == wahr


def messe(n: int) -> dict:
    erg = {k: {"versuche": 0} for k in ("zusatz", "zeichen", "luecke", "erfunden", "zielfeld", "frueher")}
    z = erg["zusatz"]
    ZAEHLER = dict(wahrer_unter_kandidaten=0, gleichstand=0, gleichstand_wahrer_dabei=0, gleichstand_kandidaten_summe=0, ohne_gleichstand=0, ohne_gleichstand_richtig=0)
    z.update(unklar=0, **ZAEHLER)
    c = erg["zeichen"]
    c.update(eindeutig=0, mehrere=0, regelverstoss=0, unklar=0, **ZAEHLER)
    lk = erg["luecke"]
    lk.update(unklar=0, **ZAEHLER)
    e = erg["erfunden"]
    e.update(als_regelverstoss=0, vorschlaege_legal=0, vorschlaege_geprueft=0)
    zf = erg["zielfeld"]
    zf.update(regelverstoss=0, wahrer_unter_vorschlaegen=0)
    fr = erg["frueher"]
    fr.update(spaeter_regelverstoss=0, davon_im_fenster=0, frueher_genannt=0, frueher_genannt_ganz=0)
    for seed, sans in partien(n):
        rng = random.Random(seed)
        # --- zusatz
        for i, s in enumerate(sans):
            kern = s.rstrip("+#")
            if kern[:1] in "NBRQ" and "=" not in kern and len(kern.replace("x", "")) >= 4:
                ohne = list(sans)
                ohne[i] = kern[0] + ("x" if "x" in kern else "") + kern[-2:]
                p = P.pruefe(zeilen(ohne))
                z["versuche"] += 1
                ez = p.zuege[i]
                if ez.status == "unklar":
                    z["unklar"] += 1
                    zaehle(z, ez.kandidaten, kern)
                break
        # --- zeichen
        i = rng.randrange(6, len(sans))
        kern = sans[i].rstrip("+#")
        if not kern.startswith("O-O"):
            ziel_start = len(kern) - 2 - (2 if "=" in kern else 0)
            felder = [ziel_start, ziel_start + 1] + ([0] if kern[0] in "NBRQK" else [])
            pos = rng.choice(felder)
            gestoert = list(sans)
            gestoert[i] = kern[:pos] + "?" + kern[pos + 1:]
            p = P.pruefe(zeilen(gestoert))
            ec = p.zuege[i]
            c["versuche"] += 1
            if ec.status == "unklar":
                c["unklar"] += 1
                c["eindeutig" if len(ec.kandidaten) == 1 else "mehrere"] += 1
                zaehle(c, ec.kandidaten, kern)
            elif ec.status == "illegal":
                c["regelverstoss"] += 1
        # --- luecke
        if len(sans) >= 16:
            i = rng.randrange(6, len(sans) - 10)
            gestoert = list(sans)
            gestoert[i] = ""
            p = P.pruefe(zeilen(gestoert))
            el = p.zuege[i]
            lk["versuche"] += 1
            if el.status == "unklar":
                lk["unklar"] += 1
                zaehle(lk, el.kandidaten, sans[i].rstrip("+#"))       # gezeigt werden höchstens acht Kandidaten
        # --- erfunden
        i = rng.randrange(6, len(sans))
        ref = chess.Board()
        for s in sans[:i]:
            ref.push_san(s)
        legal = {(ref.piece_type_at(m.from_square), m.to_square) for m in ref.legal_moves}
        versuche = [(f, sq) for f in range(2, 7) for sq in range(64) if (f, sq) not in legal]
        f, sq = rng.choice(versuche)
        erfunden = list(sans[:i]) + ["?NBRQK"[f - 1] + chess.square_name(sq)] + list(sans[i + 1:])
        p = P.pruefe(zeilen(erfunden[:i + 1]))
        ee = p.zuege[i]
        e["versuche"] += 1
        if ee.status == "illegal":
            e["als_regelverstoss"] += 1
            for k in ee.kandidaten:
                e["vorschlaege_geprueft"] += 1
                e["vorschlaege_legal"] += ref.parse_san(k.san) in ref.legal_moves
        # --- zielfeld: Linie des Ziels verschoben
        i = rng.randrange(6, len(sans))
        kern = sans[i].rstrip("+#")
        if kern[:1] in "NBRQK" and "=" not in kern:
            ref = chess.Board()
            for s in sans[:i]:
                ref.push_san(s)
            datei = "abcdefgh".index(kern[-2])
            neu = "abcdefgh"[(datei + 1) % 8] if datei < 7 else "g"
            falsch = kern[:-2].replace("x", "") + neu + kern[-1]
            p = P.pruefe(zeilen(sans[:i] + [falsch]))
            ez = p.zuege[i]
            zf["versuche"] += 1
            if ez.status == "illegal":
                zf["regelverstoss"] += 1
                zf["wahrer_unter_vorschlaegen"] += kern in [k.san.rstrip("+#") for k in ez.kandidaten]
        # --- frueher: anderer legaler Zug derselben Figurenart
        i = rng.randrange(4, len(sans) - 6)
        ref = chess.Board()
        for s in sans[:i]:
            ref.push_san(s)
        wahr = ref.parse_san(sans[i])
        art = ref.piece_type_at(wahr.from_square)
        andere = [m for m in ref.legal_moves if m != wahr and ref.piece_type_at(m.from_square) == art and not m.promotion and not ref.is_castling(m)]
        if andere and not ref.is_castling(wahr):
            m = rng.choice(sorted(andere, key=lambda x: x.uci()))
            neu_san = ref.san(m)
            gestoert = list(sans)
            gestoert[i] = neu_san
            p = P.pruefe(zeilen(gestoert))
            fr["versuche"] += 1
            ill = next((x for x in p.zuege if x.status == "illegal"), None)
            if ill is not None:
                fr["spaeter_regelverstoss"] += 1
                fr["davon_im_fenster"] += ill.ply - i <= P.FRUEHER_FENSTER
                treffer = [(j, k) for j, k in ill.frueher if j == i and k.san.rstrip("+#") == sans[i].rstrip("+#")]
                fr["frueher_genannt"] += bool(treffer)
                fr["frueher_genannt_ganz"] += any(k.ganz for _, k in treffer)
    erg["partien"] = n
    erg["mindestlaenge"] = MINDEST_LAENGE
    return erg


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--partien", type=int, default=PARTIEN)
    ap.add_argument("--ausgabe", default=str(WURZEL / "data" / "messung.json"))
    a = ap.parse_args()
    erg = messe(a.partien)
    Path(a.ausgabe).parent.mkdir(exist_ok=True)
    Path(a.ausgabe).write_text(json.dumps(erg, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(erg, ensure_ascii=False, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
