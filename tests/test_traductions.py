# SPDX-License-Identifier: Apache-2.0
"""Traductions complètes : fr, en, nl, de (mêmes clés que strings.json) et phrases du sélecteur."""
from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from custom_components.sbg_energy_export import categories

DOSSIER = Path(__file__).resolve().parent.parent / "custom_components" / "sbg_energy_export"
LANGUES = ("en", "fr", "nl", "de")


def _cles(d: dict, prefixe: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in d.items():
        out |= _cles(v, f"{prefixe}{k}.") if isinstance(v, dict) else {prefixe + k}
    return out


def _lire(chemin: Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))


@pytest.mark.parametrize("langue", LANGUES)
def test_memes_cles_que_strings(langue: str) -> None:
    attendu = _cles(_lire(DOSSIER / "strings.json"))
    assert _cles(_lire(DOSSIER / "translations" / f"{langue}.json")) == attendu


@pytest.mark.parametrize("langue", LANGUES)
def test_memes_variables_que_strings(langue: str) -> None:
    """Chaque {variable} de strings.json est reprise telle quelle dans la traduction."""

    def variables(d: dict, prefixe: str = "") -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out |= variables(v, f"{prefixe}{k}.")
            else:
                out[prefixe + k] = set(re.findall(r"\{(\w+)\}", v))
        return out

    attendu = variables(_lire(DOSSIER / "strings.json"))
    assert variables(_lire(DOSSIER / "translations" / f"{langue}.json")) == attendu


def test_phrases_du_selecteur_dans_les_quatre_langues() -> None:
    for lg in LANGUES:
        assert set(categories.RAISONS[lg]) == set(categories.PRIORITE), lg
        assert set(categories.LIBELLES[lg]) == set(categories.PRIORITE), lg
    assert categories.langue("nl-BE") == "nl"
    assert categories.langue("de") == "de"
    assert categories.langue("fr") == "fr"
    assert categories.langue("it") == "en"
    assert categories.langue(None) == "en"
    assert "laadpaal" in categories.libelle("Borne", "voiture", "nl")
