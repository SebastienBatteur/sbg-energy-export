# SPDX-License-Identifier: Apache-2.0
"""Information des occupants à l'étape « Envoi » (décision du 07/10/2026, AIPD risque R4).

La courbe envoyée décrit tout le foyer, pas seulement le titulaire du compte SBG Energy.
La phrase française est la même, mot pour mot, que sur le formulaire de dépôt du site
(/donnees-compteur/) et la page « Home Assistant » du service d'analyse ; les autres
langues la traduisent. Pas d'URL (règle de hassfest, vérifiée par test_traductions).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DOSSIER = Path(__file__).resolve().parent.parent / "custom_components" / "sbg_energy_export"

PHRASES = {
    "fr": ("Les données de consommation peuvent refléter l'activité des personnes vivant dans le logement. "
           "Si vous partagez ce logement, pensez à les informer de l'utilisation de ce service."),
    "en": ("Consumption data may reflect the activity of the people living in the home. "
           "If you share this home, consider informing them that you use this service."),
    "nl": ("Verbruiksgegevens kunnen de activiteit weerspiegelen van de mensen die in de woning wonen. "
           "Deelt u deze woning, informeer hen dan over het gebruik van deze dienst."),
    "de": ("Verbrauchsdaten können die Aktivität der Personen widerspiegeln, die in der Wohnung leben. "
           "Wenn Sie diese Wohnung mit anderen teilen, informieren Sie sie bitte über die Nutzung dieses Dienstes."),
}


def _envoi(fichier: str) -> str:
    d = json.loads((DOSSIER / fichier).read_text(encoding="utf-8"))
    return d["options"]["step"]["envoi"]["description"]


@pytest.mark.parametrize("langue", sorted(PHRASES))
def test_phrase_occupants_a_l_etape_envoi(langue: str) -> None:
    texte = _envoi(f"translations/{langue}.json")
    assert PHRASES[langue] in texte
    # un paragraphe à part, avant la ligne du compte
    assert "\n\n" + PHRASES[langue] + "\n\n" in texte


def test_strings_json_identique_a_l_anglais() -> None:
    assert _envoi("strings.json") == _envoi("translations/en.json")
