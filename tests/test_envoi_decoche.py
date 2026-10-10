# SPDX-License-Identifier: Apache-2.0
"""Version 0.6.1 : l'étape Envoi ne coupe jamais l'envoi et ne retire jamais l'accord « Améliorer
les outils SBG » sans que l'utilisateur l'ait confirmé.

Constaté le 10/10/2026 sur une installation réelle, juste après la mise à jour 0.5.1 → 0.6.0
(compte connecté, envoi actif, accord donné) : l'utilisateur choisit seulement son gestionnaire de
réseau ; l'étape est validée avec les deux interrupteurs décochés, qu'il n'avait pas touchés ; 0.6.0
retire l'accord chez le service (qui efface les copies) et coupe l'envoi. Keycloak et le service
sont SIMULÉS."""
# Les fixtures « connecte » et « serveur » viennent de test_envoi : leurs paramètres les « redéfinissent ».
# ruff: noqa: F811
from __future__ import annotations

from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.sbg_energy_export.const import DATA_JETON, DATA_SOURCE, DOMAIN

from .test_envoi import (  # noqa: F401 - connecte et serveur sont des fixtures
    OPTIONS,
    RAFRAICHISSEMENT,
    SOURCE,
    Serveur,
    _installer,
    _options_jusqu_a_envoi,
    connecte,
    faux_5min,
    serveur,
)

COLLECTEUR = "custom_components.sbg_energy_export.collecteur.statistics_during_period"
# Entrée telle que 0.5.1 la laisse : envoi actif, accord donné, pas de gestionnaire de réseau.
A_LA_0_5_1 = {**OPTIONS, "conservation_ans": 3, "pas_5min": False, "envoi_actif": True, "pas_envoi": 15,
              "code_postal": "5000", "ameliorer_outils": True}
REGLAGE = {"source": SOURCE, "code_postal": "5000"}


def _defauts(r: dict) -> dict:
    return {str(k): k.default() for k in r["data_schema"].schema}


@pytest.fixture
async def mise_a_jour(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path, serveur: Serveur, hass_storage):
    """Installation connectée par 0.5.1 puis mise à jour : état de l'envoi SANS identifiant
    d'installation (``source``), réglages vus chez le service, un envoi déjà fait."""
    hass_storage[f"{DOMAIN}.envoi"] = {
        "version": 1, "minor_version": 1, "key": f"{DOMAIN}.envoi",
        "data": {"renouvele": 1767700000.0, "reglages": {"code_postal": "5000", "accord_amelioration": True},
                 "derniere": "2026-01-02T03:10:00+00:00", "prochaine": "2026-02-02", "jours": 31,
                 "mode": "complement"}}
    serveur.reglages = {"code_postal": "5000", "accord_amelioration": True}
    with patch(COLLECTEUR, faux_5min):
        yield await _installer(hass, freezer, tmp_path, dict(A_LA_0_5_1),
                               {DATA_JETON: RAFRAICHISSEMENT, DATA_SOURCE: SOURCE})


async def _flux_complet(hass: HomeAssistant, entree) -> dict:
    """Configurer → Appareils → Sélection → Catégories → étape Envoi, sans rien changer."""
    r = await hass.config_entries.options.async_init(entree.entry_id)
    assert r["step_id"] == "init"
    r = await hass.config_entries.options.async_configure(r["flow_id"], _defauts(r))
    assert r["step_id"] == "selection"
    r = await hass.config_entries.options.async_configure(r["flow_id"], _defauts(r))
    assert r["step_id"] == "categories"
    r = await hass.config_entries.options.async_configure(r["flow_id"], _defauts(r))
    assert (r["type"], r["step_id"]) == (FlowResultType.FORM, "envoi")
    return r


async def test_mise_a_jour_les_interrupteurs_restent_coches(hass: HomeAssistant, mise_a_jour,
                                                            serveur: Serveur) -> None:
    """Première ouverture après la mise à jour : tout est montré comme avant, et valider sans
    rien toucher n'envoie rien au service."""
    with patch(COLLECTEUR, faux_5min):
        assert mise_a_jour.runtime_data.etat.donnees["source"] == SOURCE    # l'état de 0.5.1 est repris
        r = await _flux_complet(hass, mise_a_jour)
        d = _defauts(r)
        assert (d["envoi_actif"], d["ameliorer_outils"], d["grd"], d["code_postal"]) == (True, True, "inconnu", "5000")
        assert r["description_placeholders"]["logement"] == "—"
        r = await hass.config_entries.options.async_configure(r["flow_id"], d)
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
    assert serveur.appels_reglages == []
    assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"]) == (True, True)


async def test_choisir_le_gestionnaire_ne_touche_ni_l_envoi_ni_l_accord(hass: HomeAssistant, mise_a_jour,
                                                                        serveur: Serveur) -> None:
    with patch(COLLECTEUR, faux_5min):
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {**_defauts(r), "grd": "ores"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
    assert serveur.appels_reglages == [{**REGLAGE, "accord_amelioration": True, "grd": "ores"}]
    assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"]) == (True, True)


async def test_interrupteurs_recus_decoches_rien_ne_part_sans_confirmation(hass: HomeAssistant, mise_a_jour,
                                                                           serveur: Serveur) -> None:
    """Le défaut constaté : l'étape arrive avec les deux interrupteurs décochés (ils étaient
    montrés cochés) et le gestionnaire choisi. 0.6.0 retirait l'accord et coupait l'envoi."""
    with patch(COLLECTEUR, faux_5min):
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {**_defauts(r), "grd": "ores", "envoi_actif": False, "ameliorer_outils": False})
        # rien n'est parti ni enregistré : une confirmation, cases décochées par défaut
        assert (r["type"], r["step_id"]) == (FlowResultType.FORM, "confirmer")
        assert _defauts(r) == {"confirmer_arret": False, "confirmer_retrait": False}
        assert serveur.appels_reglages == []
        assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"]) == (True, True)
        # validée sans rien cocher : l'envoi et l'accord restent ; le gestionnaire est enregistré
        r = await hass.config_entries.options.async_configure(r["flow_id"], _defauts(r))
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
        assert serveur.appels_reglages == [{**REGLAGE, "accord_amelioration": True, "grd": "ores"}]
        assert serveur.reglages["accord_amelioration"] is True
        assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"],
                mise_a_jour.options["grd"]) == (True, True, "ores")
        # réouverture : toujours cochés
        d = _defauts(await _flux_complet(hass, mise_a_jour))
        assert (d["envoi_actif"], d["ameliorer_outils"]) == (True, True)


async def test_retrait_et_arret_confirmes(hass: HomeAssistant, mise_a_jour, serveur: Serveur) -> None:
    """L'utilisateur le veut vraiment : il le confirme, le retrait part et l'envoi est coupé."""
    with patch(COLLECTEUR, faux_5min):
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {**_defauts(r), "envoi_actif": False, "ameliorer_outils": False})
        assert r["step_id"] == "confirmer"
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"confirmer_arret": True, "confirmer_retrait": True})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
    assert serveur.appels_reglages == [{**REGLAGE, "accord_amelioration": False}]
    assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"]) == (False, False)


async def test_confirmation_seulement_de_ce_qui_a_ete_decoche(hass: HomeAssistant, mise_a_jour,
                                                              serveur: Serveur) -> None:
    """Une case par effet : l'accord seul décoché ne demande pas de confirmer l'arrêt de l'envoi ;
    et ce qui est confirmé n'emporte pas le reste."""
    with patch(COLLECTEUR, faux_5min):
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {**_defauts(r), "ameliorer_outils": False})
        assert r["step_id"] == "confirmer"
        assert _defauts(r) == {"confirmer_retrait": False}
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"confirmer_retrait": True})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
        assert serveur.appels_reglages == [{**REGLAGE, "accord_amelioration": False}]
        assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"]) == (True, False)
        # les deux décochés, un seul confirmé (l'arrêt) : l'accord, redonné entre-temps, reste
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {**_defauts(r), "ameliorer_outils": True})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {**_defauts(r), "envoi_actif": False, "ameliorer_outils": False})
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"confirmer_arret": True, "confirmer_retrait": False})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
    assert serveur.reglages["accord_amelioration"] is True
    assert [a["accord_amelioration"] for a in serveur.appels_reglages] == [False, True]   # aucun retrait de plus
    assert (mise_a_jour.options["envoi_actif"], mise_a_jour.options["ameliorer_outils"]) == (False, True)


async def test_accord_donne_depuis_le_compte_pendant_que_le_formulaire_est_ouvert(hass: HomeAssistant, connecte,
                                                                                 serveur: Serveur) -> None:
    """La comparaison se fait avec ce que CE formulaire montrait à son ouverture. Montré décoché,
    laissé décoché, alors que l'accord a été donné entre-temps depuis le compte (vu par un envoi) :
    0.6.0 comparait à l'état relu au moment de valider et envoyait un retrait."""
    with patch(COLLECTEUR, faux_5min):
        r = await _options_jusqu_a_envoi(hass, connecte)
        d = _defauts(r)
        assert d["ameliorer_outils"] is False
        serveur.reglages = {"code_postal": "4000", "accord_amelioration": True}
        await connecte.runtime_data.etat.async_noter(reglages=dict(serveur.reglages))
        r = await hass.config_entries.options.async_configure(r["flow_id"], {**d, "grd": "resa"})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
    assert serveur.appels_reglages == [{"source": SOURCE, "code_postal": "4000", "accord_amelioration": True,
                                        "grd": "resa"}]
    assert serveur.reglages["accord_amelioration"] is True
    assert connecte.options["ameliorer_outils"] is True


async def test_deconnecter_ne_demande_pas_de_confirmation(hass: HomeAssistant, mise_a_jour, serveur: Serveur) -> None:
    """« Déconnecter mon compte » est déjà un geste explicite : rien de plus n'est demandé, et
    aucun réglage (donc aucun retrait d'accord) ne part au service."""
    with patch(COLLECTEUR, faux_5min):
        r = await _flux_complet(hass, mise_a_jour)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {**_defauts(r), "envoi_actif": False, "ameliorer_outils": False, "deconnecter": True})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done(wait_background_tasks=True)
    assert serveur.appels_reglages == []
    assert serveur.revocations == 1
    assert DATA_JETON not in mise_a_jour.data
    assert mise_a_jour.options["envoi_actif"] is False
