# SPDX-License-Identifier: Apache-2.0
"""Version 0.6.0, décisions du 09/10/2026 : installation « arrêtée » depuis le compte (403
``installation_deconnectee``) dite une seule fois, et texte accepté nommé dans les réglages.
Keycloak et le service sont SIMULÉS."""
# Les fixtures « connecte » et « serveur » viennent de test_envoi : leurs paramètres les « redéfinissent ».
# ruff: noqa: F811
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.sbg_energy_export import envoi
from custom_components.sbg_energy_export.const import DOMAIN, TEXTE_CONSENTEMENT

from .test_envoi import (  # noqa: F401 - connecte et serveur sont des fixtures
    MAINTENANT,
    SOURCE,
    Serveur,
    _appels_api,
    _heure_tache,
    _options_jusqu_a_envoi,
    connecte,
    faux_5min,
    serveur,
)

COLLECTEUR = "custom_components.sbg_energy_export.collecteur.statistics_during_period"
DECONNECTEE = ("installation_deconnectee", "Cette installation a été déconnectée depuis votre compte SBG : elle ne "
               "peut plus rien envoyer. Pour la reprendre : https://analyse.sbg-energy.com/home-assistant/")
NOTE = f"{DOMAIN}_installation_deconnectee"
GENERIQUE = f"{DOMAIN}_envoi"


def _notes(hass: HomeAssistant) -> dict:
    return persistent_notification._async_get_or_create_notifications(hass)


async def _jours(hass: HomeAssistant, freezer: FrozenDateTimeFactory, de: int, a: int) -> None:
    """Heure de la tâche quotidienne des jours ``de`` à ``a`` après MAINTENANT (inclus)."""
    for k in range(de, a + 1):
        t = _heure_tache(MAINTENANT.date() + timedelta(days=k), SOURCE)
        freezer.move_to(t)
        async_fire_time_changed(hass, t)
        await hass.async_block_till_done(wait_background_tasks=True)


async def test_deconnectee_dite_une_seule_fois(hass: HomeAssistant, connecte, serveur: Serveur,
                                               aioclient_mock: AiohttpClientMocker,
                                               freezer: FrozenDateTimeFactory) -> None:
    serveur.refus_jours = DECONNECTEE
    with patch(COLLECTEUR, faux_5min):
        await _jours(hass, freezer, 1, 1)
        assert NOTE in _notes(hass)
        assert "ne vous le redira pas" in _notes(hass)[NOTE]["message"]
        assert GENERIQUE not in _notes(hass)                # pas de « Rien n'a été envoyé »
        assert connecte.options["envoi_actif"] is True       # rien n'est coupé : il peut la reprendre
        # l'utilisateur ferme la notification ; les jours suivants, on réessaie sans la refaire
        persistent_notification.async_dismiss(hass, NOTE)
        n = len(_appels_api(aioclient_mock, "jours"))
        await _jours(hass, freezer, 2, 6)
        assert len(_appels_api(aioclient_mock, "jours")) - n >= 4        # un essai par jour
        assert NOTE not in _notes(hass) and GENERIQUE not in _notes(hass)
        assert serveur.envois == []
        # « Envoyer maintenant » : l'erreur est rendue au bouton, sans nouvelle notification
        with pytest.raises(HomeAssistantError, match="déconnectée"):
            await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
        assert NOTE not in _notes(hass) and GENERIQUE not in _notes(hass)
        # reprise depuis le compte : l'envoi suivant passe, l'état est oublié
        serveur.refus_jours = None
        await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
        assert serveur.envois
        assert not connecte.runtime_data.etat.deconnectee
        # déconnectée de nouveau plus tard : c'est un nouvel événement, dit une fois de plus
        serveur.refus_jours = DECONNECTEE
        serveur.permise = True
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
        assert NOTE in _notes(hass)


async def test_deconnectee_notification_retiree_quand_le_service_accepte(hass: HomeAssistant, connecte,
                                                                         serveur: Serveur,
                                                                         freezer: FrozenDateTimeFactory) -> None:
    serveur.refus_jours = DECONNECTEE
    with patch(COLLECTEUR, faux_5min):
        await _jours(hass, freezer, 1, 1)
        assert NOTE in _notes(hass) and connecte.runtime_data.etat.deconnectee
        serveur.refus_jours = None
        await _jours(hass, freezer, 2, 2)
    assert serveur.envois                                # l'envoi a repris seul
    assert NOTE not in _notes(hass)
    assert not connecte.runtime_data.etat.deconnectee


async def test_deconnectee_notification_retiree_si_envoi_desactive(hass: HomeAssistant, connecte,
                                                                   serveur: Serveur,
                                                                   aioclient_mock: AiohttpClientMocker,
                                                                   freezer: FrozenDateTimeFactory) -> None:
    serveur.refus_jours = DECONNECTEE
    with patch(COLLECTEUR, faux_5min):
        await _jours(hass, freezer, 1, 1)
        assert NOTE in _notes(hass)
        r = await _options_jusqu_a_envoi(hass, connecte)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": False, "pas_envoi": "15", "code_postal": "4000"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert NOTE not in _notes(hass)
        assert not connecte.runtime_data.etat.deconnectee
        # envoi décoché : plus aucun essai
        n = len(_appels_api(aioclient_mock))
        await _jours(hass, freezer, 2, 4)
        assert len(_appels_api(aioclient_mock)) == n


async def test_texte_consentement_dans_chaque_reglage(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    """Le service garde comme preuve le texte nommé ici : celui réellement affiché par 0.6.0, la
    version « votre logement » avec la phrase de conservation de 0.5.1 (pas ENVOI_HA_LOGEMENT,
    qui contient CONSERVATION_LOGEMENT, pas encore publiée)."""
    assert TEXTE_CONSENTEMENT == "ENVOI_HA_LOGEMENT_AVANT_ETAPE_5"
    await envoi.async_reglages(hass, connecte, "4000", False)
    await envoi.async_reglages(hass, connecte, "4000", True, "resa")
    assert serveur.textes == [TEXTE_CONSENTEMENT, TEXTE_CONSENTEMENT]


async def test_texte_affiche_sans_conservation_logement(hass: HomeAssistant) -> None:
    """Décision du 09/10 : CONSERVATION_LOGEMENT n'est pas affichée avant l'étape 5 du service ; la
    phrase de 0.5.1 reste, dans chaque langue."""
    import json
    from pathlib import Path

    racine = Path(__file__).parents[1] / "custom_components" / DOMAIN
    attendu = {
        "strings.json": "everything deleted after 3 rolling years",
        "translations/en.json": "everything deleted after 3 rolling years",
        "translations/fr.json": "tout supprimé après 3 ans glissants",
        "translations/nl.json": "alles verwijderd na 3 glijdende jaren",
        "translations/de.json": "alles nach 3 gleitenden Jahren gelöscht",
    }
    for f, phrase in attendu.items():
        texte = json.loads((racine / f).read_text(encoding="utf-8"))["options"]["step"]["envoi"]["description"]
        assert phrase in texte, f
        assert "90" not in texte, f            # « fichiers bruts 90 jours » : phrase de l'étape 5
