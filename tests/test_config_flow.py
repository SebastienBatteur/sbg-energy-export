"""Configuration par l'interface."""
from __future__ import annotations

from homeassistant import config_entries
from homeassistant.components.energy.data import async_get_manager
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component
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
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"appareils": ["sensor.borne_voiture", "sensor.boiler"]})
    assert r["step_id"] == "categories"
    cles = [str(k) for k in r["data_schema"].schema]
    assert cles == ["sensor.borne_voiture", "sensor.boiler"]
    defauts = {str(k): k.default() for k in r["data_schema"].schema}
    assert defauts == {"sensor.borne_voiture": "voiture", "sensor.boiler": "ballon"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"sensor.borne_voiture": "voiture",
                                                                      "sensor.boiler": "ballon"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["options"] == {"choix": "selection", "appareils": ["sensor.borne_voiture", "sensor.boiler"],
                            "categories": {"sensor.borne_voiture": "voiture", "sensor.boiler": "ballon"}}


async def test_aucun(hass: HomeAssistant) -> None:
    await preparer(hass)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"choix": "aucun"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert r["options"] == {"choix": "aucun", "appareils": [], "categories": {}}


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
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert entree.options["choix"] == "tous"
    assert entree.options["categories"]["sensor.frigo"] == "autre"


def test_deviner_categorie() -> None:
    assert deviner_categorie("Borne de recharge") == "voiture"
    assert deviner_categorie("sensor.ev_charger_energy") == "voiture"
    assert deviner_categorie("Warmtepomp") == "pac"
    assert deviner_categorie("Chauffe-eau") == "ballon"
    assert deviner_categorie("Four") == "cuisson"
    assert deviner_categorie("Autoconsommation") == "autre"
    assert deviner_categorie("Niveau eau") == "autre"
