# SPDX-License-Identifier: Apache-2.0
"""Version 0.6.0 (ADR-040, étape 7) : logement rattaché et choix du logement, gestionnaire de
réseau facultatif, installation effacée depuis le compte. Keycloak et le service sont SIMULÉS.

Chaque comportement nouveau est derrière une détection : un service qui ne donne ni
``logement`` ni ``logements`` garde le parcours de 0.5 (vérifié ici aussi)."""
# Les fixtures « connecte » et « serveur » viennent de test_envoi : leurs paramètres les « redéfinissent ».
# ruff: noqa: F811
from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.sbg_energy_export import envoi
from custom_components.sbg_energy_export.const import DATA_JETON, DATA_SOURCE, DOMAIN

from .test_envoi import (  # noqa: F401 - connecte et serveur sont des fixtures
    OPTIONS,
    SOURCE,
    Serveur,
    _appels_api,
    _installer,
    _jours_passent,
    _options_jusqu_a_envoi,
    connecte,
    faux_5min,
    serveur,
)

COLLECTEUR = "custom_components.sbg_energy_export.collecteur.statistics_during_period"
MESSAGE_EFFACEE = ("Les données de cette installation ont été supprimées à votre demande depuis votre compte SBG : "
                   "elle n'envoie plus rien.")
LOGEMENTS = [{"id": 7, "nom": "Mon logement"}, {"id": 9, "nom": "Logement 2"}]


def _defauts(r: dict) -> dict:
    return {str(k): k.default() for k in r["data_schema"].schema}


async def _connecter(hass: HomeAssistant, entree, saisie: dict) -> dict:
    """Étape Envoi → connexion par code → fin de la progression."""
    r = await _options_jusqu_a_envoi(hass, entree)
    r = await hass.config_entries.options.async_configure(r["flow_id"], saisie)
    assert r["type"] is FlowResultType.SHOW_PROGRESS
    await hass.async_block_till_done()
    return await hass.config_entries.options.async_configure(r["flow_id"])


# ------------------------------------------------------------------ gestionnaire de réseau
async def test_gestionnaire_de_reseau_facultatif(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    with patch(COLLECTEUR, faux_5min):
        r = await _options_jusqu_a_envoi(hass, connecte)
        # « je ne sais pas » par défaut, même quand le code postal suffirait : c'est le service qui
        # déduit (une déduction faite ici passerait pour une déclaration du client)
        assert _defauts(r)["grd"] == "inconnu"
        options = r["data_schema"].schema
        champ = next(k for k in options if str(k) == "grd")
        assert options[champ].config["options"] == ["inconnu", "ores", "resa", "aieg", "aiesh", "rew", "sibelga",
                                                     "fluvius"]
        # enregistrer sans rien changer : aucun appel au service
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "grd": "inconnu"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert serveur.appels_reglages == []
        # choisi : envoyé avec les réglages, gardé dans les options
        r = await _options_jusqu_a_envoi(hass, connecte)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "grd": "resa"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert serveur.appels_reglages[-1] == {"source": SOURCE, "code_postal": "4000", "accord_amelioration": False,
                                               "grd": "resa"}
        assert connecte.options["grd"] == "resa"
        r = await _options_jusqu_a_envoi(hass, connecte)
        assert _defauts(r)["grd"] == "resa"
        # revenu à « je ne sais pas » : le champ n'est plus envoyé (le service garde ce qu'il a)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "grd": "inconnu",
                           "ameliorer_outils": True})
        await hass.async_block_till_done()
        assert "grd" not in serveur.appels_reglages[-1]
        assert connecte.options["grd"] == "inconnu"


async def test_gestionnaire_inconnu_refuse(hass: HomeAssistant, connecte) -> None:
    r = await _options_jusqu_a_envoi(hass, connecte)
    with pytest.raises(Exception):  # noqa: B017 - valeur hors de la liste
        await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "grd": "autre"})


async def test_gestionnaire_donne_a_la_connexion(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path,
                                                serveur: Serveur) -> None:
    with patch(COLLECTEUR, faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _connecter(hass, entree, {"envoi_actif": True, "pas_envoi": "15", "code_postal": "1000",
                                            "grd": "sibelga"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    assert serveur.appels_reglages == [{"source": entree.data[DATA_SOURCE], "code_postal": "1000",
                                        "accord_amelioration": False, "grd": "sibelga"}]


# ------------------------------------------------------------------ logement
async def test_service_sans_logement_parcours_de_0_5(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path,
                                                    serveur: Serveur) -> None:
    """Réponse sans ``logement`` : la connexion se termine directement, aucun champ « logement »."""
    with patch(COLLECTEUR, faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _connecter(hass, entree, {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        r = await _options_jusqu_a_envoi(hass, entree)
    assert "logement" not in _defauts(r)
    assert r["description_placeholders"]["logement"] == "—"
    assert len(serveur.appels_reglages) == 1 and "logement" not in serveur.appels_reglages[0]


async def test_un_seul_logement_affiche_apres_la_connexion(hass: HomeAssistant, freezer: FrozenDateTimeFactory,
                                                          tmp_path, serveur: Serveur) -> None:
    serveur.logement = {"id": 7, "nom": "Mon logement"}
    with patch(COLLECTEUR, faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _connecter(hass, entree, {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000"})
        assert (r["type"], r["step_id"]) == (FlowResultType.FORM, "logement")
        assert r["description_placeholders"]["logement"] == "Mon logement"
        assert _defauts(r) == {}                                     # rien à choisir
        r = await hass.config_entries.options.async_configure(r["flow_id"], {})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert len(serveur.appels_reglages) == 1
        assert entree.options["envoi_actif"] is True
        # et dans l'étape Envoi, ensuite
        r = await _options_jusqu_a_envoi(hass, entree)
    assert r["description_placeholders"]["logement"] == "Mon logement"
    assert "logement" not in _defauts(r)


async def test_choix_du_logement_si_le_compte_en_a_plusieurs(hass: HomeAssistant, freezer: FrozenDateTimeFactory,
                                                             tmp_path, serveur: Serveur) -> None:
    serveur.logements, serveur.logement = LOGEMENTS, LOGEMENTS[0]
    with patch(COLLECTEUR, faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _connecter(hass, entree, {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000"})
        assert (r["type"], r["step_id"]) == (FlowResultType.FORM, "logement")
        assert _defauts(r) == {"logement": "7"}
        champ = next(iter(r["data_schema"].schema))
        assert r["data_schema"].schema[champ].config["options"] == [{"value": "7", "label": "Mon logement"},
                                                                     {"value": "9", "label": "Logement 2"}]
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"logement": "9"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        source = entree.data[DATA_SOURCE]
        assert serveur.appels_reglages[-1] == {"source": source, "code_postal": "4000", "accord_amelioration": False,
                                               "logement": "9"}
        # l'étape Envoi montre le logement choisi et la liste ; ne rien changer n'appelle pas le service
        r = await _options_jusqu_a_envoi(hass, entree)
        assert r["description_placeholders"]["logement"] == "Logement 2"
        assert _defauts(r)["logement"] == "9"
        n = len(serveur.appels_reglages)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "logement": "9"})
        await hass.async_block_till_done()
        assert len(serveur.appels_reglages) == n
        # changer de logement plus tard : un appel, avec le logement
        r = await _options_jusqu_a_envoi(hass, entree)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "logement": "7"})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert serveur.appels_reglages[-1]["logement"] == "7"
    assert entree.runtime_data.etat.logement == {"id": "7", "nom": "Mon logement"}
    assert "logement" not in entree.options                         # état du service, pas une option


def test_logements_de_reponses_inattendues() -> None:
    assert envoi.logements_de({}) == {}
    assert envoi.logements_de({"logement": None}) == {"logement": None}
    assert envoi.logements_de({"logement": {"nom": "sans id"}, "logements": "pas une liste"}) == {"logement": None}
    assert envoi.logements_de({"logements": [{"id": 3}, {"id": True}, "x", {"id": 4, "nom": "B"}]}) == \
        {"logements": [{"id": "3", "nom": "3"}, {"id": "4", "nom": "B"}]}


# ------------------------------------------------------------------ installation effacée
@pytest.mark.parametrize("ou", ["reglages", "synchros"])
async def test_installation_effacee_coupe_l_envoi(hass: HomeAssistant, connecte, serveur: Serveur,
                                                  aioclient_mock: AiohttpClientMocker,
                                                  freezer: FrozenDateTimeFactory, ou: str) -> None:
    if ou == "reglages":
        # GET jours d'une installation effacée : le service ne la connaît plus (code postal vide) ;
        # l'intégration redonne ses réglages, et c'est là que le refus arrive
        serveur.reglages = {}
        serveur.refus_reglages, serveur.statut_refus = ("installation_effacee", MESSAGE_EFFACEE), 409
    else:
        serveur.refus_synchros = ("installation_effacee", MESSAGE_EFFACEE)
    runtime = connecte.runtime_data
    with patch(COLLECTEUR, faux_5min):
        with pytest.raises(HomeAssistantError, match="supprimées"):
            await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
        await hass.async_block_till_done()
        # coupé, sans recharger l'entrée ; le compte reste connecté (rien à révoquer de plus)
        assert connecte.options["envoi_actif"] is False
        assert connecte.runtime_data is runtime
        assert connecte.data[DATA_JETON]
        notes = persistent_notification._async_get_or_create_notifications(hass)
        assert f"{DOMAIN}_installation_effacee" in notes
        assert "coupé" in notes[f"{DOMAIN}_installation_effacee"]["message"]
        assert f"{DOMAIN}_envoi" not in notes                     # pas deux notifications pour la même chose
        assert serveur.envois == []
        # plus aucun nouvel essai : 40 jours sans un seul appel au service
        n = len(_appels_api(aioclient_mock))
        await _jours_passent(hass, freezer, 40, SOURCE)
        assert len(_appels_api(aioclient_mock)) == n
        # le flux d'options le dit, et l'envoi y est décoché
        r = await _options_jusqu_a_envoi(hass, connecte)
        assert r["errors"] == {"base": "installation_effacee"}
        assert _defauts(r)["envoi_actif"] is False
        # recoché alors que le compte ne l'a pas autorisée à nouveau : toujours refusé, rien d'activé
        serveur.refus_reglages, serveur.statut_refus = ("installation_effacee", MESSAGE_EFFACEE), 409
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000"})
        assert r["errors"] == {"base": "installation_effacee"}
        assert connecte.options["envoi_actif"] is False
        # autorisée à nouveau depuis le compte, puis recochée : l'envoi reprend
        serveur.refus_reglages = serveur.refus_synchros = None
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
    assert connecte.options["envoi_actif"] is True
    assert not connecte.runtime_data.etat.effacee
    assert f"{DOMAIN}_installation_effacee" not in persistent_notification._async_get_or_create_notifications(hass)


async def test_autre_refus_ne_coupe_pas_l_envoi(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    """Seul ``installation_effacee`` coupe : un refus passager laisse l'envoi actif (réessai demain)."""
    serveur.refus_synchros = ("trop_de_sessions", "Trop d'envois commences ce mois-ci.")
    with patch(COLLECTEUR, faux_5min), pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
    assert connecte.options["envoi_actif"] is True
    assert not connecte.runtime_data.etat.effacee
