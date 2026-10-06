# SPDX-License-Identifier: Apache-2.0
"""Configuration par l'interface."""
from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.components.energy.data import async_get_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sbg_energy_export.config_flow import deviner_categorie
from custom_components.sbg_energy_export.const import DOMAIN

PREFS = {
    "energy_sources": [
        {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.import", "stat_cost": None,
                                        "entity_energy_price": None, "number_energy_price": None}],
         "flow_to": [{"stat_energy_to": "sensor.export", "stat_compensation": None,
                      "entity_energy_price": None, "number_energy_price": None}],
         "cost_adjustment_day": 0},
    ],
    "device_consumption": [
        {"stat_consumption": "sensor.borne_voiture"},
        {"stat_consumption": "sensor.boiler"},
        {"stat_consumption": "sensor.frigo"},
    ],
}


@pytest.fixture(autouse=True)
def sans_demarrage() -> Iterator[None]:
    """Ces tests portent sur les écrans : l'entrée créée n'est pas démarrée (sinon le
    rattrapage en arrière-plan interroge le recorder pendant sa fermeture)."""
    with patch("custom_components.sbg_energy_export.async_setup_entry", return_value=True):
        yield


async def preparer(hass: HomeAssistant, prefs=PREFS) -> None:
    await async_setup_component(hass, "energy", {})
    manager = await async_get_manager(hass)
    manager.data = prefs  # préférences en mémoire, comme après energy/save_prefs


async def test_selection_et_categories(hass: HomeAssistant) -> None:
    await preparer(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"choix": "selection"})
    assert r["step_id"] == "selection"
    # classés par intérêt pour l'analyse ; les recommandés cochés, le frigo (fond) non
    champ = next(iter(r["data_schema"].schema))
    assert champ.default() == ["sensor.boiler", "sensor.borne_voiture"]
    options = r["data_schema"].schema[champ].config["options"]
    assert [o["value"] for o in options] == ["sensor.boiler", "sensor.borne_voiture", "sensor.frigo"]
    assert options[1]["label"].startswith("sensor.borne_voiture — Car / charger · recommended:")
    assert "optional" in options[2]["label"]
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"appareils": ["sensor.borne_voiture", "sensor.boiler"]})
    assert r["step_id"] == "categories"
    cles = [str(k) for k in r["data_schema"].schema]
    assert cles == ["sensor.boiler", "sensor.borne_voiture"]
    defauts = {str(k): k.default() for k in r["data_schema"].schema}
    assert defauts == {"sensor.borne_voiture": "voiture", "sensor.boiler": "ballon"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"sensor.borne_voiture": "voiture",
                                                                      "sensor.boiler": "ballon"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["options"] == {"choix": "selection", "appareils": ["sensor.borne_voiture", "sensor.boiler"],
                            "categories": {"sensor.borne_voiture": "voiture", "sensor.boiler": "ballon"},
                            "conservation_ans": 3, "pas_5min": False}


async def test_aucun(hass: HomeAssistant) -> None:
    await preparer(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(
        r["flow_id"], {"choix": "aucun", "conservation_ans": 5.0, "pas_5min": True})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["options"] == {"choix": "aucun", "appareils": [], "categories": {}, "conservation_ans": 5, "pas_5min": True}


async def test_tableau_energie_vide(hass: HomeAssistant) -> None:
    await preparer(hass, {"energy_sources": [], "device_consumption": []})
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "tableau_energie_vide"


async def test_options_tous(hass: HomeAssistant) -> None:
    await preparer(hass)
    entree = MockConfigEntry(domain=DOMAIN, options={"choix": "aucun", "appareils": [], "categories": {}})
    entree.add_to_hass(hass)
    r = await hass.config_entries.options.async_init(entree.entry_id)
    assert r["step_id"] == "init"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"choix": "tous"})
    assert r["step_id"] == "categories"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"sensor.borne_voiture": "voiture", "sensor.boiler": "ballon", "sensor.frigo": "autre"})
    # dernière étape : l'envoi direct, désactivé par défaut (rien ne part sans le cocher)
    assert (r["type"], r["step_id"]) == (FlowResultType.FORM, "envoi")
    schema = {str(k): k.default() for k in r["data_schema"].schema}
    assert schema["envoi_actif"] is False and "deconnecter" not in schema
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"envoi_actif": False, "pas_envoi": "15"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entree.options["envoi_actif"] is False
    assert entree.options["choix"] == "tous"
    assert entree.options["categories"]["sensor.frigo"] == "autre"
    assert entree.options["conservation_ans"] == 3 and entree.options["pas_5min"] is False


def test_deviner_categorie_nouvelles_categories_et_puissance() -> None:
    assert deviner_categorie("Lave-vaisselle") == "lavage"
    assert deviner_categorie("Sèche-linge") == "lavage"
    assert deviner_categorie("Frigo cuisine") == "froid"
    assert deviner_categorie("Box internet") == "informatique"
    assert deviner_categorie("Lampes salon") == "eclairage"
    assert deviner_categorie("Prise 3", "Prise connectée", "Zaptec Go") == "voiture"  # appareil Home Assistant
    assert deviner_categorie("Prise 3", kwh_h_max=7.2) == "voiture"                  # puissance typique
    assert deviner_categorie("Prise 3", kwh_h_max=2.0) == "autre"


def test_deviner_categorie() -> None:
    assert deviner_categorie("Borne de recharge") == "voiture"
    assert deviner_categorie("sensor.ev_charger_energy") == "voiture"
    assert deviner_categorie("Warmtepomp") == "pac"
    assert deviner_categorie("Chauffe-eau") == "ballon"
    assert deviner_categorie("Four") == "cuisson"
    assert deviner_categorie("Autoconsommation") == "autre"
    assert deviner_categorie("Niveau eau") == "autre"


def test_categories_regles_de_proposition_retour_installation_reelle() -> None:
    """Noms neutres équivalents à ceux d'une vraie installation (07/10/2026)."""
    # port PoE d'un switch : toujours informatique, jamais la catégorie du mot qui suit
    assert deviner_categorie("switch_16_ports_port_pac_poe") == "informatique"
    assert deviner_categorie("Switch 16 ports - port camera PoE") == "informatique"
    assert deviner_categorie("switch_16_ports_port_ap2_poe") == "informatique"
    assert deviner_categorie("Poêle à pellets") != "informatique"  # « poe » est un mot entier
    # eau chaude sanitaire avant la PAC
    assert deviner_categorie("pac_appoint_ecs") == "ballon"
    assert deviner_categorie("Boiler sanitaire") == "ballon"
    assert deviner_categorie("Dégivrage PAC") == "pac"
    assert deviner_categorie("Pompe à chaleur air-eau") == "pac"
    # traitement de l'eau, pas éclairage ; pompes
    assert deviner_categorie("Lampe UV eau de pluie") == "pompe"
    assert deviner_categorie("Pompe citerne") == "pompe"
    assert deviner_categorie("Pompe piscine") == "pompe"
    assert deviner_categorie("Adoucisseur") == "pompe"
    assert deviner_categorie("Lampe salon") == "eclairage"
    # ventilation
    assert deviner_categorie("ComfoAir Q350") == "ventilation"
    assert deviner_categorie("VMC double flux") == "ventilation"
    assert deviner_categorie("Ventilation cave") == "ventilation"
    # réseau
    for nom in ("Starlink", "Modem fibre", "Routeur", "Point d'accès AP1", "ap2", "NAS", "Home Assistant"):
        assert deviner_categorie(nom) == "informatique", nom
    assert deviner_categorie("Appoint salle de bain") != "informatique"  # « ap » : mot entier
    # un support d'alimentation ne décide pas : on lit le reste du nom
    assert deviner_categorie("Prise lave-linge") == "lavage"
    assert deviner_categorie("Multiprise bureau ordinateur") == "informatique"
    assert deviner_categorie("Porte de garage") == "autre"
