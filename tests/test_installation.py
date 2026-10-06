# SPDX-License-Identifier: Apache-2.0
"""Installation sur un Home Assistant qui a 1 an de statistiques horaires et 10 jours
de statistiques de 5 minutes (vrai recorder SQLite en mémoire ; les statistiques de
5 minutes sont simulées, le recorder de test n'en compile pas).

Vérifie : dès l'installation, l'export contient tout le passé en horaire et les
~10 derniers jours au pas fin, puis le pas fin en continu ; le stockage ne garde que
les appareils choisis ; un appareil ajouté est rattrapé ; mois terminés compressés ;
mois trop anciens supprimés ; option 5 minutes.
"""
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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.sbg_energy_export import stockage
from custom_components.sbg_energy_export.const import DOMAIN
from tests import lire_zip

UTC = timezone.utc
MAINTENANT = datetime(2026, 1, 6, 12, 5, 30, tzinfo=UTC)
DEBUT = datetime(2025, 1, 6, 0, tzinfo=UTC)            # 1 an de statistiques horaires
PURGE = MAINTENANT - timedelta(days=10)                # statistiques de 5 min encore présentes
PREMIER_FIN = datetime(2025, 12, 27, 13, tzinfo=UTC)   # première heure entière après la purge
PATCH = "custom_components.sbg_energy_export.collecteur.statistics_during_period"

PREFS = {
    "energy_sources": [
        {"type": "grid", "stat_energy_from": "sensor.import", "stat_energy_to": "sensor.export",
         "stat_cost": None, "entity_energy_price": None, "number_energy_price": None, "stat_compensation": None,
         "entity_energy_price_export": None, "number_energy_price_export": None, "cost_adjustment_day": 0},
        {"type": "solar", "stat_energy_from": "sensor.pv", "config_entry_solar_forecast": None},
    ],
    "device_consumption": [{"stat_consumption": "sensor.borne_garage"}, {"stat_consumption": "sensor.frigo_cave"}],
}
PAR_HEURE = {"sensor.import": 1.0, "sensor.export": 0.2, "sensor.pv": 0.4, "sensor.borne_garage": 0.6,
             "sensor.frigo_cave": 0.06}


def cumul(stat: str, fin: datetime) -> float:
    """Compteur à la fin de ``fin``. La borne alterne 1,5 et 0,5 fois sa puissance
    moyenne d'une période de 5 min à l'autre (un cycle), les autres sont constants."""
    n = int((fin - DEBUT).total_seconds() // 300)
    e5 = PAR_HEURE[stat] / 12
    if stat == "sensor.borne_garage":
        return e5 * (2 * (n // 2) + 1.5 * (n % 2))
    return e5 * n


def importer_horaires(hass: HomeAssistant) -> None:
    heures = int((MAINTENANT.replace(minute=0, second=0) - DEBUT).total_seconds() // 3600)
    for stat in PAR_HEURE:
        meta = {"source": "recorder", "statistic_id": stat, "unit_of_measurement": "kWh", "has_sum": True,
                "mean_type": StatisticMeanType.NONE, "name": None, "unit_class": "energy"}
        lignes = []
        for k in range(heures):
            debut = DEBUT + timedelta(hours=k)
            s = cumul(stat, debut + timedelta(hours=1))
            lignes.append({"start": debut, "sum": s, "state": s})
        async_import_statistics(hass, meta, lignes)


def faux_5min(hass, debut, fin, ids, periode, unites, types):
    """Statistiques de 5 min : de la purge (10 jours) à la dernière période compilée."""
    if periode != "5minute":
        return vrai_statistics_during_period(hass, debut, fin, ids, periode, unites, types)
    maintenant = datetime.now(UTC)
    t = max(debut, PURGE)
    t = t + timedelta(seconds=-t.timestamp() % 300)
    sortie: dict = {}
    while t < fin and t + timedelta(minutes=5) <= maintenant:
        for stat in ids:
            sortie.setdefault(stat, []).append(
                {"start": t.timestamp(), "end": t.timestamp() + 300, "sum": cumul(stat, t + timedelta(minutes=5))})
        t += timedelta(minutes=5)
    return sortie


async def installer(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path: Path, options: dict) -> MockConfigEntry:
    freezer.move_to(MAINTENANT)
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, "energy", {})
    (await async_get_manager(hass)).data = PREFS
    importer_horaires(hass)
    await async_wait_recording_done(hass)
    entree = MockConfigEntry(domain=DOMAIN, options=options)
    entree.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entree.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entree


def corps(tmp_path: Path, r: dict) -> tuple[str, list[str]]:
    texte = lire_zip(tmp_path / "sbg_energy_export" / "exports" / r["fichier"])
    return texte, [l for l in texte.splitlines() if not l.startswith("#")]


BORNE = {"choix": "selection", "appareils": ["sensor.borne_garage"], "categories": {"sensor.borne_garage": "voiture"}}


async def test_installation_un_an_horaire_et_dix_jours_au_quart(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path: Path
) -> None:
    mesures = tmp_path / "sbg_energy_export" / "mesures"
    mesures.mkdir(parents=True)
    (mesures / "mesures_15min_2022-12.csv.gz").write_bytes(b"")  # au-delà de 3 ans : supprimé
    with patch(PATCH, faux_5min):
        entree = await installer(hass, freezer, tmp_path, BORNE)
        # stockage : seulement les sources et l'appareil choisi ; décembre terminé, donc compressé
        assert sorted(f.name for f in mesures.iterdir()) == ["mesures_15min_2025-12.csv.gz", "mesures_15min_2026-01.csv"]
        colonnes, lignes = stockage.lire_fichier(mesures / "mesures_15min_2025-12.csv.gz")
        assert colonnes == ["sensor.borne_garage", "sensor.export", "sensor.import", "sensor.pv"]
        assert min(lignes) == int(PREMIER_FIN.timestamp())

        r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 15}, blocking=True, return_response=True)
        texte, c = corps(tmp_path, r)
        assert "# debut_mesure_15min: 2025-12-27T13:00:00Z" in texte
        assert "# version: 2" in texte
        assert c[1] == "2025-01-06T01:00:00Z,mesure_60min,1,0.2,0.4,,,1.2,0.6"   # tout le passé, en horaire
        lignes_par_t = {l.split(",")[0]: l for l in c[1:]}
        assert lignes_par_t["2025-12-27T12:00:00Z"].split(",")[1] == "mesure_60min"
        assert "2025-12-27T12:45:00Z" not in lignes_par_t
        assert lignes_par_t["2025-12-27T13:00:00Z"] == "2025-12-27T13:00:00Z,mesure_15min,0.25,0.05,0.1,,,0.3,0.175"
        assert lignes_par_t["2025-12-27T13:15:00Z"] == "2025-12-27T13:15:00Z,mesure_15min,0.25,0.05,0.1,,,0.3,0.125"
        assert c[-1].startswith("2026-01-06T11:45:00Z,mesure_15min,")
        heures = int((datetime(2026, 1, 6, 12, tzinfo=UTC) - DEBUT).total_seconds() // 3600) - 1
        mesurees = 10 * 24 - 1  # ~10 jours au quart d'heure
        assert len(c) - 1 == (heures - mesurees) + 4 * mesurees
        provenances = [l.split(",")[1] for l in c[1:]]
        assert provenances.count("mesure_15min") == 4 * mesurees
        assert set(provenances) == {"mesure_60min", "mesure_15min"}

        # puis en continu
        freezer.move_to(MAINTENANT + timedelta(hours=1))
        assert await entree.runtime_data.collecteur.async_rattraper() == 4
        r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 15}, blocking=True, return_response=True)
        _, c = corps(tmp_path, r)
        assert c[-1].startswith("2026-01-06T12:45:00Z,mesure_15min,0.25,0.05,0.1,,,0.3,")

        with pytest.raises(HomeAssistantError, match="5 minutes"):
            await hass.services.async_call(DOMAIN, "exporter", {"pas": 5}, blocking=True, return_response=True)
    assert hass.states.get("button.sbg_energy_export_export_5_min") is None


async def test_appareil_ajoute_rattrape_appareil_retire_garde(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path: Path
) -> None:
    mesures = tmp_path / "sbg_energy_export" / "mesures"
    debut, fin = int(PREMIER_FIN.timestamp()), int(MAINTENANT.timestamp()) + 7200
    with patch(PATCH, faux_5min):
        entree = await installer(hass, freezer, tmp_path, BORNE)
        lu = stockage.lire(mesures, 15, ["sensor.frigo_cave"], debut, fin)
        assert lu["sensor.frigo_cave"] == {}  # pas choisi : pas enregistré
        # le frigo remplace la borne
        hass.config_entries.async_update_entry(entree, options={
            "choix": "selection", "appareils": ["sensor.frigo_cave"], "categories": {"sensor.frigo_cave": "autre"}})
        await hass.async_block_till_done(wait_background_tasks=True)
        freezer.move_to(MAINTENANT + timedelta(hours=1))
        await entree.runtime_data.collecteur.async_rattraper()
    lu = stockage.lire(mesures, 15, ["sensor.frigo_cave", "sensor.borne_garage"], debut, fin)
    frigo, borne = lu["sensor.frigo_cave"], lu["sensor.borne_garage"]
    # frigo : rattrapé depuis la purge des statistiques de 5 min, puis en continu
    assert min(frigo) == debut and max(frigo) == int(datetime(2026, 1, 6, 12, 45, tzinfo=UTC).timestamp())
    assert len(frigo) == 4 * (10 * 24)
    assert all(v == pytest.approx(0.015) for v in frigo.values())
    # borne : ce qui est déjà enregistré reste, rien de nouveau
    assert max(borne) == int(datetime(2026, 1, 6, 11, 45, tzinfo=UTC).timestamp())


async def test_option_cinq_minutes(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path: Path) -> None:
    mesures = tmp_path / "sbg_energy_export" / "mesures"
    with patch(PATCH, faux_5min):
        await installer(hass, freezer, tmp_path, {**BORNE, "pas_5min": True})
        assert sorted(f.name for f in mesures.iterdir()) == ["mesures_5min_2025-12.csv.gz", "mesures_5min_2026-01.csv"]
        r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 5}, blocking=True, return_response=True)
        texte, c = corps(tmp_path, r)
        assert r["fichier"].endswith("_5min.zip")
        assert "# pas_minutes: 5" in texte and "# debut_mesure_5min: 2025-12-27T13:00:00Z" in texte
        assert c[1] == "2025-01-06T01:00:00Z,mesure_60min,1,0.2,0.4,,,1.2,0.6"  # le passé reste horaire (v2)
        lignes_par_t = {l.split(",")[0]: l for l in c[1:]}
        assert lignes_par_t["2025-12-27T13:00:00Z"] == "2025-12-27T13:00:00Z,mesure_5min,0.0833,0.0167,0.0333,,,0.1,0.075"
        assert lignes_par_t["2025-12-27T13:05:00Z"] == "2025-12-27T13:05:00Z,mesure_5min,0.0833,0.0167,0.0333,,,0.1,0.025"
        assert c[-1].startswith("2026-01-06T11:55:00Z,mesure_5min,")
        # le pas de 15 min reste disponible, reconstitué depuis les périodes de 5 min
        r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 15}, blocking=True, return_response=True)
        texte, c = corps(tmp_path, r)
        assert "# debut_mesure_15min: 2025-12-27T13:00:00Z" in texte
        assert c[-1].startswith("2026-01-06T11:45:00Z,mesure_15min,0.25,0.05,0.1,,,0.3,")
        await hass.services.async_call("button", "press", {"entity_id": "button.sbg_energy_export_export_5_min"},
                                       blocking=True)
