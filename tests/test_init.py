# SPDX-License-Identifier: Apache-2.0
"""Intégration complète avec un vrai recorder (SQLite en mémoire)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import html
import io
import logging
from pathlib import Path
import re
import sqlite3
from unittest.mock import patch
import zipfile

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period as vrai_statistics_during_period,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done
from sqlalchemy.exc import OperationalError

from custom_components.sbg_energy_export.collecteur import recorder_pret
from custom_components.sbg_energy_export.const import DOMAIN
from tests import lire_zip

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
    texte = lire_zip(tmp_path / "sbg_energy_export" / "exports" / r["fichier"])
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
    texte = lire_zip(tmp_path / "sbg_energy_export" / "exports" / r["fichier"])
    corps = [l for l in texte.splitlines() if not l.startswith("#")]
    assert "# debut_mesure_15min: 2026-01-06T10:00:00Z" in texte
    lignes = {l.split(",")[0]: l for l in corps[1:]}
    assert lignes["2026-01-06T10:15:00Z"] == "2026-01-06T10:15:00Z,mesure_15min,0.25,0.05,0.1,,,0.3,0.15"
    # version 2 : une heure sans mesure au quart d'heure reste en UNE ligne horaire
    assert "# version: 2" in texte and r["fichier"].endswith("_15min.zip")
    assert lignes["2026-01-06T09:00:00Z"] == "2026-01-06T09:00:00Z,mesure_60min,1,0.2,0.4,,,1.2,0.6"
    assert "2026-01-06T09:15:00Z" not in lignes
    assert len(corps) - 1 == 34 + 4  # 34 heures du passé, puis l'heure mesurée en 4 quarts


async def test_bouton_et_telechargement(installe, hass: HomeAssistant, hass_client, hass_client_no_auth) -> None:
    with (patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min),
          patch("custom_components.sbg_energy_export.persistent_notification.async_create") as notifier):
        await hass.services.async_call("button", "press",
                                       {"entity_id": "button.sbg_energy_export_export_hourly"}, blocking=True)
    # Le lien de la notification porte target="_blank" : sans lui, le frontend intercepte le clic
    # (lien sur la même origine) comme une page interne et retombe sur le tableau de bord.
    message = notifier.call_args.args[1]
    lien = re.search(r'<a href="([^"]+)" target="_blank">Télécharger</a>', message)
    assert lien is not None and "authSig=" in lien.group(1) and "[Télécharger](" not in message
    assert (await (await hass_client_no_auth()).get(html.unescape(lien.group(1)))).status == 200
    r = await hass.services.async_call(DOMAIN, "exporter", {"pas": 60}, blocking=True, return_response=True)
    anonyme = await hass_client_no_auth()
    assert (await anonyme.get(f"/api/sbg_energy_export/fichier/{r['fichier']}")).status == 401
    reponse = await anonyme.get(r["lien"])
    assert reponse.status == 200
    assert reponse.headers["Content-Type"] == "application/zip"
    assert f'filename="{r["fichier"]}"' in reponse.headers["Content-Disposition"]
    with zipfile.ZipFile(io.BytesIO(await reponse.read())) as z:
        # au pas horaire, les deux versions du format sont identiques : il reste en version 1
        assert z.read(z.namelist()[0]).decode().startswith("# SBG HA export\n# version: 1\n")
    connecte = await hass_client()
    assert (await connecte.get("/api/sbg_energy_export/fichier/..%2Fsecrets.yaml")).status in (400, 404)
    assert (await connecte.get("/api/sbg_energy_export/fichier/sbg_ha_export_20990101-000000_60min.csv")).status == 404


@pytest.mark.parametrize(("langue_ha", "debut"), [
    ("fr", "Pour ne plus déposer ce fichier à la main chaque mois"),
    ("en", "To stop uploading this file by hand every month"),
    ("nl", "Wilt u dit bestand niet meer elke maand"),
    ("de", "Damit Sie diese Datei nicht mehr jeden Monat"),
    ("es", "To stop uploading this file by hand every month"),     # autre langue : anglais
])
async def test_export_rappelle_l_envoi_automatique(installe, hass: HomeAssistant, langue_ha: str,
                                                   debut: str) -> None:
    """ADR-040 § 5.4 : sous l'export manuel, une phrase rappelle que l'envoi automatique évite le
    dépôt mensuel, dans la langue de Home Assistant ; seulement tant que l'envoi n'est pas actif."""
    from custom_components.sbg_energy_export import RAPPEL_ENVOI

    hass.config.language = langue_ha
    with (patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min),
          patch("custom_components.sbg_energy_export.persistent_notification.async_create") as notifier):
        await hass.services.async_call("button", "press",
                                       {"entity_id": "button.sbg_energy_export_export_hourly"}, blocking=True)
        assert debut in notifier.call_args.args[1]
        # envoi actif (coché et compte connecté) : plus de rappel
        with patch("custom_components.sbg_energy_export.envoi.actif", return_value=True):
            await hass.services.async_call(DOMAIN, "exporter", {"pas": 60}, blocking=True, return_response=True)
        assert not any(t in notifier.call_args.args[1] for t in RAPPEL_ENVOI.values())


async def test_dechargement(installe, hass: HomeAssistant) -> None:
    collecteur = installe.runtime_data.collecteur
    assert collecteur._arret is not None
    assert await hass.config_entries.async_unload(installe.entry_id)
    assert collecteur._arret is None


async def test_passage_periodique_suivi_et_annule_au_dechargement(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Le passage lancé par le minuteur est une tâche de fond suivie : le déchargement l'annule
    (avant : tâche orpheline, qui interrogeait encore le recorder après l'arrêt)."""
    collecteur = installe.runtime_data.collecteur
    parti, jamais = asyncio.Event(), asyncio.Event()

    async def lent() -> int:
        parti.set()
        await jamais.wait()
        return 0

    with patch.object(collecteur, "async_rattraper", lent):
        t = MAINTENANT.replace(minute=17, second=30)
        freezer.move_to(t)
        async_fire_time_changed(hass, t)
        await asyncio.wait_for(parti.wait(), 5)
        tache = collecteur._passage
        assert tache is not None and not tache.done()
        assert tache in hass._background_tasks
        # un passage encore en cours : le minuteur suivant n'en lance pas un second
        t = MAINTENANT.replace(minute=32, second=30)
        freezer.move_to(t)
        async_fire_time_changed(hass, t)
        assert collecteur._passage is tache
        assert await hass.config_entries.async_unload(installe.entry_id)
        await hass.async_block_till_done()
    assert tache.cancelled()
    assert collecteur._passage is None and collecteur._arret is None and collecteur._arret_ha is None


async def test_plus_de_passage_a_l_arret_de_home_assistant(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Arrêt de Home Assistant (l'entrée n'est pas déchargée) : le minuteur est retiré et rien
    n'est plus demandé au recorder, qui se ferme."""
    collecteur = installe.runtime_data.collecteur
    appels: list[int] = []

    async def compte() -> int:
        appels.append(1)
        return 0

    with patch.object(collecteur, "async_rattraper", compte):
        hass.set_state(CoreState.stopping)
        collecteur._async_tic(MAINTENANT)          # minuteur déjà en route au moment de l'arrêt
        assert collecteur._passage is None
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
        await hass.async_block_till_done()
        assert collecteur._arret is None and collecteur._arret_ha is None
        t = MAINTENANT.replace(minute=17, second=30)
        freezer.move_to(t)
        async_fire_time_changed(hass, t)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert appels == []


PATCH_STATS = "custom_components.sbg_energy_export.collecteur.statistics_during_period"
JOURNAL = "custom_components.sbg_energy_export.collecteur"
ONZE_HEURES = int(datetime(2026, 1, 6, 11, tzinfo=UTC).timestamp())


def base_fermee(hass, debut, fin, ids, periode, unites, types):
    """Ce que rend le recorder interrogé pendant sa fermeture (journal de la CI du 10/10/2026)."""
    raise OperationalError("SELECT … FROM statistics_meta", {}, sqlite3.OperationalError("no such table: statistics_meta"))


def faux_5min_suite(hass, debut, fin, ids, periode, unites, types):
    """Comme ``faux_5min``, avec l'heure suivante compilée (11:00 → 12:00)."""
    if periode != "5minute":
        return vrai_statistics_during_period(hass, debut, fin, ids, periode, unites, types)
    sortie = {}
    for stat in ids:
        e5 = PAR_HEURE[stat] / 12
        lignes = []
        t = QUARTS_MESURES - timedelta(minutes=5)
        while t < QUARTS_MESURES + timedelta(hours=2):
            if debut <= t < fin:
                k = int((t - QUARTS_MESURES).total_seconds() // 300) + 1
                lignes.append({"start": t.timestamp(), "end": t.timestamp() + 300, "sum": 1000 + e5 * k})
            t += timedelta(minutes=5)
        if lignes:
            sortie[stat] = lignes
    return sortie


async def tic(hass: HomeAssistant, freezer: FrozenDateTimeFactory, minute: int) -> asyncio.Task[int]:
    """Fait sonner le minuteur du collecteur et attend la fin du passage qu'il lance."""
    t = MAINTENANT.replace(minute=minute, second=30)
    freezer.move_to(t)
    async_fire_time_changed(hass, t)
    await hass.async_block_till_done(wait_background_tasks=True)
    tache = hass.config_entries.async_loaded_entries(DOMAIN)[0].runtime_data.collecteur._passage
    assert tache is not None and tache.done()
    return tache


async def test_erreur_de_base_au_passage_consignee_puis_rattrapee(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Le recorder échoue pendant un passage (ici comme dans la CI : « no such table ») : une
    ligne d'avertissement, pas d'exception perdue dans la tâche de fond, rien de marqué comme
    enregistré, et le passage suivant rattrape (avant : « Task exception was never retrieved »)."""
    collecteur = installe.runtime_data.collecteur
    assert collecteur.prochain == ONZE_HEURES
    etat = await collecteur._store.async_load()
    assert etat is not None and etat["prochain"] == ONZE_HEURES
    with patch(PATCH_STATS, base_fermee), caplog.at_level(logging.WARNING, logger=JOURNAL):
        tache = await tic(hass, freezer, 17)
    assert tache.exception() is None and tache.result() == 0
    lignes = [r for r in caplog.records if r.name == JOURNAL]
    assert [r.levelno for r in lignes] == [logging.WARNING]
    assert "no such table: statistics_meta" in lignes[0].getMessage()
    assert "nouvel essai" in lignes[0].getMessage() and lignes[0].exc_info is None
    assert collecteur.prochain == ONZE_HEURES and await collecteur._store.async_load() == etat
    lu = await collecteur.async_lire(["sensor.import"], ONZE_HEURES, ONZE_HEURES + 3600)
    assert lu["sensor.import"] == {}
    # le recorder répond de nouveau : l'heure manquée est enregistrée au passage suivant
    with patch(PATCH_STATS, faux_5min_suite):
        tache = await tic(hass, freezer, 32)
    assert tache.result() == 4 and collecteur.prochain == ONZE_HEURES + 3600
    lu = await collecteur.async_lire(["sensor.import"], ONZE_HEURES, ONZE_HEURES + 3600)
    assert lu["sensor.import"] == {ONZE_HEURES + k * 900: pytest.approx(0.25) for k in range(4)}


async def test_erreur_inattendue_au_passage_consignee_avec_sa_trace(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Une erreur qui n'est pas celle d'un recorder indisponible est consignée en erreur, avec
    sa trace : elle n'est ni perdue ni maquillée en « statistiques indisponibles »."""
    collecteur = installe.runtime_data.collecteur

    def casse(*_args):
        raise ValueError("inattendu")

    with patch(PATCH_STATS, casse), caplog.at_level(logging.WARNING, logger=JOURNAL):
        tache = await tic(hass, freezer, 17)
    assert tache.exception() is None and tache.result() == 0
    lignes = [r for r in caplog.records if r.name == JOURNAL]
    assert [r.levelno for r in lignes] == [logging.ERROR]
    assert lignes[0].exc_info is not None and lignes[0].exc_info[0] is ValueError
    assert collecteur.prochain == ONZE_HEURES


@pytest.mark.parametrize("cas", ["base_pas_prete", "demarrage_echoue", "recorder_arrete"])
async def test_pas_de_passage_sans_recorder(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory, cas: str
) -> None:
    """Recorder pas encore prêt, jamais démarré ou arrêté : le passage ne lui demande rien et ne
    marque rien comme enregistré (avant, recorder arrêté : « RuntimeError: cannot schedule new
    futures after shutdown » ; base pas prête : requête envoyée quand même)."""
    collecteur = installe.runtime_data.collecteur
    instance = get_instance(hass)
    assert recorder_pret(hass)
    appels: list[str] = []

    def compte(hass, debut, fin, ids, periode, unites, types):
        appels.append(periode)
        return {}

    pret: asyncio.Future[bool] = hass.loop.create_future()
    if cas == "demarrage_echoue":
        pret.set_result(False)
    if cas == "recorder_arrete":
        await instance._async_shutdown(None)  # ce que fait Home Assistant à son arrêt
        pret = instance.async_db_ready
    with patch(PATCH_STATS, compte), patch.object(instance, "async_db_ready", pret):
        assert not recorder_pret(hass)
        tache = await tic(hass, freezer, 17)
        assert tache.exception() is None and tache.result() == 0
        assert await collecteur.async_rattraper() == 0  # export, envoi : même garde
    pret.cancel()
    assert appels == []
    assert collecteur.prochain == ONZE_HEURES


async def test_erreur_de_base_au_demarrage_consignee(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Le rattrapage lancé au chargement de l'entrée est protégé comme le passage périodique."""
    freezer.move_to(MAINTENANT.replace(minute=40))
    with patch(PATCH_STATS, base_fermee), caplog.at_level(logging.WARNING, logger=JOURNAL):
        assert await hass.config_entries.async_reload(installe.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    lignes = [r for r in caplog.records if r.name == JOURNAL]
    assert [r.levelno for r in lignes] == [logging.WARNING]
    assert "no such table: statistics_meta" in lignes[0].getMessage()
    assert installe.runtime_data.collecteur.prochain == ONZE_HEURES


async def test_recorder_arrete_entre_deux_tranches_statistique_nouvelle_pas_marquee(
    installe, hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Un rattrapage fait une requête par jour. Si le recorder s'arrête entre deux, la suivante
    ne part pas, et un appareil ajouté dont le rattrapage n'est pas fini n'est pas noté comme
    suivi : il est rattrapé en entier au passage suivant."""
    instance = get_instance(hass)
    appels: list[datetime] = []

    def s_arrete_a_la_deuxieme(hass, debut, fin, ids, periode, unites, types):
        appels.append(debut)
        if len(appels) == 2:  # première tranche du rattrapage du frigo (10 jours, 10 requêtes)
            instance.is_running = False
        return faux_5min(hass, debut, fin, ids, periode, unites, types)

    try:
        with patch(PATCH_STATS, s_arrete_a_la_deuxieme):
            hass.config_entries.async_update_entry(installe, options={
                "choix": "selection", "appareils": ["sensor.frigo_cave"], "categories": {"sensor.frigo_cave": "autre"}})
            await hass.async_block_till_done(wait_background_tasks=True)
        collecteur = installe.runtime_data.collecteur
        assert len(appels) == 2
        assert "sensor.frigo_cave" not in collecteur.suivies
        assert "sensor.frigo_cave" not in (await collecteur._store.async_load())["suivies"]
    finally:
        instance.is_running = True
    # le recorder est de retour : le frigo est rattrapé (ses 5 min existent de 10:00 à 11:00)
    appels.clear()
    with patch(PATCH_STATS, s_arrete_a_la_deuxieme):
        tache = await tic(hass, freezer, 17)
    instance.is_running = True
    assert tache.exception() is None
    assert len(appels) == 2  # arrêté de nouveau à la deuxième requête : toujours pas noté
    assert "sensor.frigo_cave" not in collecteur.suivies
    with patch(PATCH_STATS, faux_5min):
        await tic(hass, freezer, 32)
    assert "sensor.frigo_cave" in collecteur.suivies
    lu = await collecteur.async_lire(["sensor.frigo_cave"], ONZE_HEURES - 3600, ONZE_HEURES)
    assert lu["sensor.frigo_cave"] == {ONZE_HEURES - 3600 + k * 900: pytest.approx(0.0125) for k in range(4)}
