"""CTC-Rechnung gegen eine Brute-Force-Summe über alle Ausrichtungen (unabhängiges Orakel) und gegen den Zeichensatz des Modells."""
import itertools
import json
from pathlib import Path

import numpy as np
import pytest

import pf_ctc as C

DATEN = Path(__file__).resolve().parent.parent.parent / "_daten_spielwiese" / "hcs" / "dl" / "config.sjon"


def zufalls_logp(T: int, K: int, seed: int) -> np.ndarray:
    return C.log_softmax(np.random.default_rng(seed).normal(size=(T, K)) * 2)


def zusammenfassen(pfad) -> tuple:
    out, vor = [], 0
    for c in pfad:
        if c != vor and c != 0:
            out.append(c)
        vor = c
    return tuple(out)


def brute_force(logp: np.ndarray, ziel: tuple) -> float:
    T, K = logp.shape
    p = np.exp(logp)
    summe = 0.0
    for pfad in itertools.product(range(K), repeat=T):
        if zusammenfassen(pfad) == ziel:
            summe += float(np.prod([p[t, c] for t, c in enumerate(pfad)]))
    return float(np.log(summe)) if summe > 0 else C.NEG


@pytest.mark.parametrize("ziel", [(), (1,), (2,), (1, 2), (1, 1), (2, 1, 2), (1, 1, 1), (3, 3), (1, 2, 3)])
def test_vorwaertsverfahren_gleich_brute_force(ziel):
    for seed in range(4):
        logp = zufalls_logp(7, 4, seed)
        assert C.logwahrscheinlichkeit(logp, list(ziel)) == pytest.approx(brute_force(logp, ziel), abs=1e-9), (ziel, seed)


def test_zu_kurz_fuer_die_folge():
    logp = zufalls_logp(2, 4, 0)
    assert C.logwahrscheinlichkeit(logp, [1, 2, 3]) <= C.NEG / 2
    assert C.logwahrscheinlichkeit(logp, [1, 1]) <= C.NEG / 2 or C.logwahrscheinlichkeit(logp, [1, 1]) < -1       # zwei gleiche Zeichen brauchen drei Spalten


def test_summe_ueber_alle_folgen_ist_eins():
    logp = zufalls_logp(5, 3, 1)
    alle = [()] + [f for n in range(1, 6) for f in itertools.product((1, 2), repeat=n)]
    assert sum(np.exp(C.logwahrscheinlichkeit(logp, list(f))) for f in alle) == pytest.approx(1.0, abs=1e-9)


def test_gierig_und_joker():
    z = C.ZEICHEN
    ix = {c: i for i, c in enumerate(z)}
    # Spalten: e, e (zusammengefasst), Leerschritt, 4 (unsicher), Leerschritt
    p = np.full((5, len(z)), 1e-6)
    for t, (c, w) in enumerate([("e", 0.97), ("e", 0.9), ("", 0.99), ("4", 0.45), ("", 0.99)]):
        p[t, ix[c] if c else 0] = w
    p[3, ix["4"]], p[3, 0], p[3, ix["1"]] = 0.5, 0.3, 0.2         # in der unsicheren Spalte ist die 4 vorn, aber nicht sicher
    logp = np.log(p / p.sum(axis=1, keepdims=True))
    text, sicher = C.gierig(logp)
    assert text == "e4" and sicher[0] > 0.9 and sicher[1] < 0.6
    assert C.mit_joker(logp, 0.6) == "e?" and C.mit_joker(logp, 0.3) == "e4"


def test_kodieren():
    assert C.kodiere("Nf3") == [5, 11, 16] and C.kodiere("O-O") == [26, 27, 26] and C.kodiere("Sf3") == [28, 11, 16] and C.kodiere("Zf3") is None and C.kodiere("") == []


def test_als_logp_formen():
    logp = zufalls_logp(6, 28, 0)
    assert np.allclose(C.als_logp(logp), logp)
    assert np.allclose(C.als_logp(logp[:, None, :]), logp) and np.allclose(C.als_logp(logp[None]), logp)
    assert np.allclose(np.exp(C.als_logp(logp * 3 + 5)).sum(axis=1), 1.0)            # Rohwerte werden normiert


@pytest.mark.skipif(not DATEN.exists(), reason="Datensatz und Modell liegen nur lokal unter _daten_spielwiese")
def test_zeichensatz_gleich_modellkonfiguration():
    assert json.loads(DATEN.read_text(encoding="utf-8"))["charset"] == C.ZEICHEN_ORIGINAL == C.ZEICHEN[:28] and C.ZEICHEN[28:] == ["S", "L", "T", "D"]
