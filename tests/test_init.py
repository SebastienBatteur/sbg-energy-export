# SPDX-License-Identifier: Apache-2.0
"""Intégration complète avec un vrai recorder (SQLite en mémoire)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period as vrai_statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.sbg_energy_export.const import DOMAIN

UTC = timezone.utc
MAINTENANT = datetime(2026, 1, 6, 12, 5, 30, tzinfo=UTC)
DEBUT = datetime(2026, 1, 5, 0, tzinfo=UTC)
QUARTS_MESURES = datetime(2026, 1, 6, 10, tzinfo=UTC)  # 10:00 → 11:00 en statistiques de 5 min

PREFS = {
    "energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.import", "stat_energy_to": "sensor.export",
         "stat_cost": None, "entity_energy_price": None, "number_energy_price": None, "stat_compensation": None,
         "entity_energy_price_export": None, "number_energy_price_export": None, "cost_adjustment_day": 0},
        {"type": "solar", "stat_energy_from": "sensor.pv", "config_entry_solar_forecast": None},
    ],
    "device_consumption": [{"stat_consumption": "sensor.borne_garage"}, {"stat_consumption": "sensor.frigo_cave"}],
}
# Énergie par heure (kWh) : prélèvement, injection, solaire, borne, frigo.
PAR_HEURE = {"sensor.import": 1.0, "sensor.export": 0.2, "sensor.pv": 0.4, "sensor.borne_garage": 0.6,
             "sensor.frigo_cave": 0.05}


def importer(hass: HomeAssistant) -> None:
    heures = int((MAINTENANT.replace(minute=0, second=0) - DEBUT).total_seconds() // 3600)
    for stat, e in PAR_HEURE.items():
        meta = {"source": "recorder", "statistic_id": stat, "unit_of_measurement": "kWh", "has_sum": True,
                "mean_type": StatisticMeanType.NONE, "name": None, "unit_class": "energy"}
        lignes = [{"start": DEBUT + timedelta(hours=k), "sum": e * (k + 1), "state": e * (k + 1)} for k in range(heures)]
        async_import_statistics(hass, meta, lignes)


def faux_5min(hass, debut, fin, ids, periode, unites, types):
    """Statistiques de 5 min synthétiques (le recorder de test n'en compile pas) ;
    les autres périodes viennent du vrai recorder."""
    if periode != "5minute":
        return vrai_statistics_during_period(hass, debut, fin, ids, periode, unites, types)
    sortie = {}
    for stat in ids:
        e5 = PAR_HEURE[stat] / 12
        lignes = []
        t = QUARTS_MESURES - timedelta(minutes=5)
        while t < QUARTS_MESURES + timedelta(hours=1):
            if debut <= t < fin:
                k = int((t - QUARTS_MESURES).total_seconds() // 300) + 1
                lignes.append({"start": t.timestamp(), "end": t.timestamp() + 300, "sum": 1000 + e5 * k})
            t += timedelta(minutes=5)
        if lignes:
            sortie[stat] = lignes
    return sortie


@pytest.fixture
async def installe(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path):
    freezer.move_to(MAINTENANT)
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, "energy", {})
    (await async_get_manager(hass)).data = PREFS
    importer(hass)
    await async_wait_recording_done(hass)
    entree = MockConfigEntry(domain=DOMAIN, options={
        "choix": "selection", "appareils": ["sensor.borne_garage"], "categories": {"sensor.borne_garage": "voiture"}})
    entree.add_to_hass(hass)
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        assert await hass.config_entries.async_setup(entree.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        yield entree


async def test_export_horaire(installe, hass: HomeAssistant, tmp_path: Path) -> None:
    r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 60}, blocking=True, return_response=True)
    texte = (tmp_path / "sbg_energy_export" / "exports" / r["fichier"]).read_text(encoding="utf-8")
    corps = [l for l in texte.splitlines() if not l.startswith("#")]
    assert corps[0].split(",")[-2:] == ["consommation_maison", "voiture_1"]
    # la première ligne de statistiques sert de référence : l'export commence à 01:00
    assert corps[1] == "2026-01-05T01:00:00Z,mesure_60min,1,0.2,0.4,,,1.2,0.6"
    assert len(corps) - 1 == 35
    assert corps[-1].startswith("2026-01-06T11:00:00Z,mesure_60min")
    assert "# non_configure: charge_batterie,decharge_batterie" in texte
    for interdit in ("sensor", "garage", "frigo", "cave"):
        assert interdit not in texte
    assert r["lien"].startswith("/api/sbg_energy_export/fichier/") and "authSig=" in r["lien"]


async def test_quarts_enregistres_puis_export_15(installe, hass: HomeAssistant, tmp_path: Path) -> None:
    fichiers = sorted((tmp_path / "sbg_energy_export" / "mesures").iterdir())
    assert [f.name for f in fichiers] == ["mesures_15min_2026-01.csv"]
    contenu = fichiers[0].read_text(encoding="utf-8").splitlines()
    # seulement les sources et l'appareil choisi : pas le frigo
    assert contenu[0] == "debut_utc,sensor.borne_garage,sensor.export,sensor.import,sensor.pv"
    assert contenu[1:] == [f"2026-01-06T10:{m:02d}:00Z,0.15,0.05,0.25,0.1" for m in (0, 15, 30, 45)]
    etat = hass.states.get("sensor.sbg_energy_export_last_recorded_quarter_hour")
    assert etat is not None and etat.state.startswith("2026-01-06T11:00:00")
    assert etat.attributes["premier_quart"].startswith("2026-01-06T10:00:00")

    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 15}, blocking=True, return_response=True)
    texte = (tmp_path / "sbg_energy_export" / "exports" / r["fichier"]).read_text(encoding="utf-8")
    corps = [l for l in texte.splitlines() if not l.startswith("#")]
    assert "# debut_mesure_15min: 2026-01-06T10:00:00Z" in texte
    lignes = {l.split(",")[0]: l for l in corps[1:]}
    assert lignes["2026-01-06T10:15:00Z"] == "2026-01-06T10:15:00Z,mesure_15min,0.25,0.05,0.1,,,0.3,0.15"
    assert lignes["2026-01-06T09:15:00Z"] == "2026-01-06T09:15:00Z,heure_repartie,0.25,0.05,0.1,,,0.3,0.15"
    assert len(corps) - 1 == 4 * 35


async def test_bouton_et_telechargement(installe, hass: HomeAssistant, hass_client, hass_client_no_auth) -> None:
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        await hass.services.async_call("button", "press",
                                       {"entity_id": "button.sbg_energy_export_export_hourly"}, blocking=True)
    r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 60}, blocking=True, return_response=True)
    anonyme = await hass_client_no_auth()
    assert (await anonyme.get(f"/api/sbg_energy_export/fichier/{r['fichier']}")).status == 401
    reponse = await anonyme.get(r["lien"])
    assert reponse.status == 200
    assert (await reponse.text()).startswith("# SBG HA export\n")
    connecte = await hass_client()
    assert (await connecte.get("/api/sbg_energy_export/fichier/..%2Fsecrets.yaml")).status in (400, 404)
    assert (await connecte.get("/api/sbg_energy_export/fichier/sbg_ha_export_20990101-000000_60min.csv")).status == 404


async def test_dechargement(installe, hass: HomeAssistant) -> None:
    collecteur = installe.runtime_data.collecteur
    assert collecteur._arret is not None
    assert await hass.config_entries.async_unload(installe.entry_id)
    assert collecteur._arret is None
