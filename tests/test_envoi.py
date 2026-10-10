# SPDX-License-Identifier: Apache-2.0
"""Envoi direct vers analyse.sbg-energy.com : désactivé par défaut, connexion par code (flux
« Device Authorization Grant » simulé), synchronisation incrémentale, limite mensuelle du service,
réimport, et jetons jamais journalisés. Keycloak et le service sont SIMULÉS (aucun appel réel)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import logging
import re
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker, AiohttpClientMockResponse

from custom_components.sbg_energy_export import envoi
from custom_components.sbg_energy_export.const import (
    API_URL,
    AUTH_URL,
    DATA_JETON,
    DATA_SOURCE,
    DOMAIN,
    TEXTE_CONSENTEMENT,
    URL_CONDITIONS,
)

from .test_init import PAR_HEURE, PREFS, faux_5min

UTC = timezone.utc
MAINTENANT = datetime(2026, 1, 6, 12, 5, 30, tzinfo=UTC)
DEBUT = datetime(2026, 1, 1, 0, tzinfo=UTC)
SOURCE = "ab" * 16
RAFRAICHISSEMENT = "rafraichissement-SECRET-1"
ACCES = "acces-SECRET-xyz"
CODE_APPAREIL = "appareil-SECRET-42"
OPTIONS = {"choix": "selection", "appareils": ["sensor.borne_garage"], "categories": {"sensor.borne_garage": "voiture"}}


def importer(hass: HomeAssistant) -> None:
    heures = int((MAINTENANT.replace(minute=0, second=0) - DEBUT).total_seconds() // 3600)
    for stat, e in PAR_HEURE.items():
        meta = {"source": "recorder", "statistic_id": stat, "unit_of_measurement": "kWh", "has_sum": True,
                "mean_type": StatisticMeanType.NONE, "name": None, "unit_class": "energy"}
        lignes = [{"start": DEBUT + timedelta(hours=k), "sum": e * (k + 1), "state": e * (k + 1)} for k in range(heures)]
        async_import_statistics(hass, meta, lignes)


class Serveur:
    """Keycloak et le service, simulés : jours gardés, limite mensuelle, réimports."""

    def __init__(self) -> None:
        self.jours: set[str] = set()
        self.permise = True
        self.reimports = 3
        self.attente = 1                     # réponses « authorization_pending » avant l'accord
        self.refus_appareil: str | None = None
        self.rafraichissement_invalide = False
        self.n_rafraichi = 0
        self.envois: list[tuple[str, bytes]] = []
        self.ouvertures: list[dict] = []
        self.terminees = 0
        self.revocations = 0
        self.reglages: dict = {}                 # code postal et accord connus du service
        self.refus_reglages: tuple[str, str] | None = None
        self.statut_refus = 403
        self.refus_synchros: tuple[str, str] | None = None
        self.refus_jours: tuple[str, str] | None = None     # 403 de GET jours (installation déconnectée)
        self.refus_import: tuple[str, str] | None = None    # 409 de POST import
        self.refus_terminer: tuple[str, str] | None = None  # 409 de POST synchros/<id>/terminer
        self.textes: list[str | None] = []                   # champ « texte_consentement » de chaque réglage
        # 0.6.0 : champs facultatifs de la réponse ; None = service qui ne les connaît pas (0.5)
        self.logements: list[dict] | None = None
        self.logement: dict | None = None
        self.appels_reglages: list[dict] = []
        self.jour_min_5min = "2025-01-06"

    def r(self, method, url, status=200, **kw):
        return AiohttpClientMockResponse(method, url, status=status, json=kw)

    async def jeton(self, method, url, data):
        if data.get("grant_type") == envoi.GRANT_DEVICE:
            assert data["device_code"] == CODE_APPAREIL and data["client_id"] == "sbg-ha-export"
            if self.refus_appareil:
                return self.r(method, url, 400, error=self.refus_appareil)
            if self.attente:
                self.attente -= 1
                return self.r(method, url, 400, error="authorization_pending")
            return self.r(method, url, access_token=ACCES, refresh_token=RAFRAICHISSEMENT,
                          scope="offline_access ha-export", token_type="Bearer")
        assert data["grant_type"] == "refresh_token" and data["client_id"] == "sbg-ha-export"
        assert "client_secret" not in data
        if self.rafraichissement_invalide:
            return self.r(method, url, 400, error="invalid_grant")
        self.n_rafraichi += 1
        return self.r(method, url, access_token=ACCES, refresh_token=f"rafraichissement-SECRET-{self.n_rafraichi + 1}")

    async def appareil(self, method, url, data):
        assert data == {"client_id": "sbg-ha-export", "scope": "offline_access ha-export"}
        return self.r(method, url, device_code=CODE_APPAREIL, user_code="ABCD-EFGH", expires_in=600, interval=0,
                      verification_uri="https://auth.sbg-energy.com/realms/sbg/device",
                      verification_uri_complete="https://auth.sbg-energy.com/realms/sbg/device?user_code=ABCD-EFGH")

    async def revoquer(self, method, url, data):
        self.revocations += 1
        return self.r(method, url)

    async def api(self, method, url, data):
        chemin = url.path.split("/api/v1/ha/")[1]
        if chemin == "jours":
            if self.refus_jours:
                return self.r(method, url, 403, code=self.refus_jours[0], message=self.refus_jours[1])
            plages = [[j, j] for j in sorted(self.jours)]
            return self.r(method, url, couverture={"15": plages, "5": plages} if plages else {},
                          synchro={"permise": self.permise, "prochaine": "2026-02-02" if not self.permise else "2026-01-06",
                                   "reimports_restants": self.reimports},
                          jour_min="2023-01-06", jour_min_5min=self.jour_min_5min,
                          morceau={"octets_max": 1048576, "jours_max": 92},
                          reglages={"code_postal": self.reglages.get("code_postal", ""),
                                    "accord_amelioration": self.reglages.get("accord_amelioration", False)})
        if chemin == "reglages":
            d = dict(data if isinstance(data, dict) else json.loads(data))
            # 0.6.0 : chaque réglage nomme le texte affiché ; gardé à part pour que les comparaisons
            # des autres champs restent lisibles (test_texte_consentement_dans_chaque_reglage)
            self.textes.append(d.pop("texte_consentement", None))
            self.appels_reglages.append(d)
            if self.refus_reglages:
                return self.r(method, url, self.statut_refus, code=self.refus_reglages[0],
                              message=self.refus_reglages[1])
            self.reglages = {"code_postal": d["code_postal"], "accord_amelioration": d["accord_amelioration"]}
            extra: dict = {}
            if self.logements is not None:
                if "logement" in d:
                    self.logement = next(lg for lg in self.logements if str(lg["id"]) == d["logement"])
                extra = {"logement": self.logement, "logements": self.logements}
            elif self.logement is not None:
                extra = {"logement": self.logement}
            return self.r(method, url, reglages=self.reglages, copies_effacees=0, **extra)
        if chemin == "synchros":
            d = data if isinstance(data, dict) else json.loads(data)
            self.ouvertures.append(d)
            if self.refus_synchros:
                return self.r(method, url, 409, code=self.refus_synchros[0], message=self.refus_synchros[1])
            if d["mode"] == "remplacement":
                if self.reimports <= 0:
                    return self.r(method, url, 429, code="limite_reimports",
                                  message="Reimport : 3 par mois au plus. Prochain possible le 01/02/2026.")
                self.reimports -= 1
            elif not self.permise:
                return self.r(method, url, 429, code="limite_mensuelle", message="Deja envoye ce mois-ci.")
            return self.r(method, url, 201, id="session1", jour_min="2023-01-06")
        if chemin == "import":
            if self.refus_import:
                return self.r(method, url, 409, code=self.refus_import[0], message=self.refus_import[1])
            self.envois.append((data.decode().split("# pas_minutes: ")[1][:2].strip(), data))
            jours = sorted({l[:10] for l in data.decode().splitlines() if l[:2] == "20"})
            nouveaux = [j for j in jours if j not in self.jours]
            self.jours.update(jours)
            return self.r(method, url, ajoutes=nouveaux, remplaces=[j for j in jours if j not in nouveaux],
                          ignores=[], refuses=[], controles="valide")
        if chemin.endswith("/terminer"):
            if self.refus_terminer:
                return self.r(method, url, 409, code=self.refus_terminer[0], message=self.refus_terminer[1])
            self.terminees += 1
            self.permise = False
            return self.r(method, url, jours_recus=len(self.jours), rapport="reglages_manquants",
                          compte="https://analyse.sbg-energy.com/home-assistant/",
                          synchro={"permise": False, "prochaine": "2026-02-02"})
        raise AssertionError(chemin)

    def brancher(self, aioclient_mock: AiohttpClientMocker) -> None:
        aioclient_mock.post(f"{AUTH_URL}/protocol/openid-connect/token", side_effect=self.jeton)
        aioclient_mock.post(f"{AUTH_URL}/protocol/openid-connect/auth/device", side_effect=self.appareil)
        aioclient_mock.post(f"{AUTH_URL}/protocol/openid-connect/revoke", side_effect=self.revoquer)
        motif = re.compile(re.escape(API_URL) + "/")
        aioclient_mock.get(motif, side_effect=self.api)
        aioclient_mock.post(motif, side_effect=self.api)


@pytest.fixture
def serveur(aioclient_mock: AiohttpClientMocker):
    s = Serveur()
    s.brancher(aioclient_mock)
    yield s
    # 0.6.0 : chaque requête de réglages, dans chaque test, nomme le texte réellement affiché
    assert all(t == TEXTE_CONSENTEMENT for t in s.textes), s.textes


async def _installer(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path, options, data) -> MockConfigEntry:
    freezer.move_to(MAINTENANT)
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, "energy", {})
    (await async_get_manager(hass)).data = PREFS
    importer(hass)
    await async_wait_recording_done(hass)
    entree = MockConfigEntry(domain=DOMAIN, options=options, data=data)
    entree.add_to_hass(hass)
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        assert await hass.config_entries.async_setup(entree.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    return entree


@pytest.fixture
async def connecte(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path, serveur):
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        serveur.reglages = {"code_postal": "4000", "accord_amelioration": False}
        yield await _installer(hass, freezer, tmp_path, {**OPTIONS, "envoi_actif": True, "pas_envoi": 15,
                                                         "code_postal": "4000"},
                               {DATA_JETON: RAFRAICHISSEMENT, DATA_SOURCE: SOURCE})


def _heure_tache(jour: date, source: str | None) -> datetime:
    h, m = envoi.heure_quotidienne(source)
    return dt_util.as_utc(datetime(jour.year, jour.month, jour.day, h, m, 0, tzinfo=dt_util.get_default_time_zone()))


async def _jours_passent(hass: HomeAssistant, freezer: FrozenDateTimeFactory, n: int, source: str | None) -> None:
    """``n`` jours : l'heure de la tâche quotidienne de chaque jour (et le premier envoi programmé)."""
    for k in range(1, n + 1):
        t = _heure_tache(MAINTENANT.date() + timedelta(days=k), source)
        freezer.move_to(t)
        async_fire_time_changed(hass, t)
        await hass.async_block_till_done(wait_background_tasks=True)


def _appels_api(aioclient_mock: AiohttpClientMocker, fin: str = "") -> list:
    return [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(API_URL) and str(c[1].path).endswith(fin)]


@pytest.mark.parametrize("options,data", [
    (OPTIONS, {DATA_JETON: RAFRAICHISSEMENT, DATA_SOURCE: SOURCE}),          # compte connecté, envoi désactivé
    ({**OPTIONS, "envoi_actif": True}, {}),                                   # envoi coché, compte non connecté
    (OPTIONS, {}),                                                            # défaut
])
async def test_rien_ne_part_si_desactive(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path,
                                         aioclient_mock: AiohttpClientMocker, serveur, options, data) -> None:
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        entree = await _installer(hass, freezer, tmp_path, options, data)
        await _jours_passent(hass, freezer, 40, data.get(DATA_SOURCE))       # tâche quotidienne, premier envoi
        with pytest.raises(HomeAssistantError, match="désactivé"):
            await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(DOMAIN, "reimporter", {"debut": "2026-01-02", "fin": "2026-01-04"},
                                           blocking=True, return_response=True)
    assert aioclient_mock.call_count == 0
    assert hass.states.get("button.sbg_energy_export_send_now") is None or options.get("envoi_actif")
    assert entree.data == data


async def test_synchro_incrementale_puis_limite_mensuelle(hass: HomeAssistant, connecte, serveur: Serveur,
                                                          aioclient_mock: AiohttpClientMocker, caplog,
                                                          freezer: FrozenDateTimeFactory) -> None:
    caplog.set_level(logging.DEBUG)
    serveur.jours = {"2026-01-03"}                                             # déjà reçu par le service
    runtime = connecte.runtime_data
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        await hass.services.async_call("button", "press", {"entity_id": "button.sbg_energy_export_send_now"},
                                       blocking=True)
        await hass.async_block_till_done()
    # seulement les jours UTC complets manquants : le 2, puis le 4 et le 5 (le 6 n'est pas fini)
    envoyes = [sorted({l[:10] for l in corps.decode().splitlines() if l[:2] == "20"}) for _, corps in serveur.envois]
    assert envoyes == [["2026-01-02"], ["2026-01-04", "2026-01-05"]]
    for _, corps in serveur.envois:
        texte = corps.decode()
        assert texte.startswith("# SBG HA export\n") and "# pas_minutes: 15" in texte
        assert texte.splitlines()[-1][:20] != "2026-01-06T00:00:00Z"
        for interdit in ("sensor", "borne", "garage", "frigo", "cave"):
            assert interdit not in texte
        assert "voiture_1" in texte
    imports = _appels_api(aioclient_mock, "/import")
    assert {c[3]["X-SBG-Mode"] for c in imports} == {"complement"}
    assert all(c[3]["Authorization"] == f"Bearer {ACCES}" for c in _appels_api(aioclient_mock))
    assert serveur.ouvertures == [{"source": SOURCE, "pas": 15, "mode": "complement"}]
    assert serveur.terminees == 1
    # jeton renouvelé : gardé, SANS recharger l'entrée
    assert connecte.data[DATA_JETON] == "rafraichissement-SECRET-2"
    assert connecte.runtime_data is runtime
    etat = hass.states.get("sensor.sbg_energy_export_last_send")
    assert etat is not None and etat.attributes["prochain_envoi"] == "2026-02-02"
    assert etat.attributes["jours_envoyes"] == 3
    # deuxième envoi du mois : refusé par le service, rien n'est envoyé
    n = len(serveur.envois)
    with pytest.raises(HomeAssistantError, match="02/02/2026"):
        await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
    assert len(serveur.envois) == n
    # tâche quotidienne avant le 2 février : AUCUN appel réseau
    avant, api_avant = aioclient_mock.call_count, len(_appels_api(aioclient_mock))
    await _jours_passent(hass, freezer, 19, SOURCE)
    assert len(_appels_api(aioclient_mock)) == api_avant
    assert 1 <= aioclient_mock.call_count - avant <= 3                          # renouvellement hebdomadaire du jeton
    assert all(str(c[1]).startswith(AUTH_URL) for c in aioclient_mock.mock_calls[avant:])
    for secret in (RAFRAICHISSEMENT, "rafraichissement-SECRET-2", ACCES):
        assert secret not in caplog.text


async def test_reimport_remplace_une_periode(hass: HomeAssistant, connecte, serveur: Serveur,
                                             aioclient_mock: AiohttpClientMocker) -> None:
    serveur.jours = {"2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"}
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        r = await hass.services.async_call(DOMAIN, "reimporter", {"debut": "2026-01-03", "fin": "2026-01-05"},
                                           blocking=True, return_response=True)
    assert r["jours"] == 2
    assert serveur.ouvertures[-1] == {"source": SOURCE, "pas": 15, "mode": "remplacement", "debut": "2026-01-03",
                                      "fin": "2026-01-05"}
    assert [sorted({l[:10] for l in c.decode().splitlines() if l[:2] == "20"}) for _, c in serveur.envois] \
        == [["2026-01-03", "2026-01-04"]]
    assert {c[3]["X-SBG-Mode"] for c in _appels_api(aioclient_mock, "/import")} == {"remplacement"}
    serveur.reimports = 0
    with pytest.raises(HomeAssistantError, match="3 par mois"):
        await hass.services.async_call(DOMAIN, "reimporter", {"debut": "2026-01-03", "fin": "2026-01-05"},
                                       blocking=True, return_response=True)


async def test_jeton_retire_il_faut_se_reconnecter(hass: HomeAssistant, connecte, serveur: Serveur,
                                                   aioclient_mock: AiohttpClientMocker, caplog) -> None:
    serveur.rafraichissement_invalide = True
    with pytest.raises(HomeAssistantError, match="reconnectez"):
        await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
    assert DATA_JETON not in connecte.data and connecte.data[DATA_SOURCE] == SOURCE
    assert _appels_api(aioclient_mock) == []
    assert RAFRAICHISSEMENT not in caplog.text


async def _options_jusqu_a_envoi(hass: HomeAssistant, entree: MockConfigEntry) -> dict:
    r = await hass.config_entries.options.async_init(entree.entry_id)
    assert r["step_id"] == "init"
    r = await hass.config_entries.options.async_configure(
        r["flow_id"], {"choix": "aucun", "conservation_ans": 3, "pas_5min": False})
    assert (r["type"], r["step_id"]) == (FlowResultType.FORM, "envoi")
    return r


async def test_connexion_par_code_sans_mot_de_passe(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path,
                                                     serveur: Serveur, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _options_jusqu_a_envoi(hass, entree)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"envoi_actif": True, "pas_envoi": "15"})
        assert r["errors"] == {"code_postal": "code_postal"}              # obligatoire pour envoyer
        assert aioclient_mock_vide(serveur)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "5000", "ameliorer_outils": True})
        assert (r["type"], r["step_id"]) == (FlowResultType.SHOW_PROGRESS, "connexion")
        assert r["description_placeholders"]["code"] == "ABCD-EFGH"
        assert r["description_placeholders"]["url"].startswith("https://auth.sbg-energy.com/")
        await hass.async_block_till_done()                    # accord donné : « progression terminée »
        r = await hass.config_entries.options.async_configure(r["flow_id"])
        assert r["type"] is FlowResultType.CREATE_ENTRY, r
        await hass.async_block_till_done()
    assert hass.config_entries.options.async_progress() == []
    # jeton gardé (renouvelé une fois par l'envoi des réglages, juste après la connexion)
    assert entree.data[DATA_JETON] == "rafraichissement-SECRET-2"
    assert re.fullmatch(r"[0-9a-f]{32}", entree.data[DATA_SOURCE])
    assert entree.options["envoi_actif"] is True and entree.options["pas_envoi"] == 15
    # réglages donnés au service juste après la connexion
    assert serveur.appels_reglages == [{"source": entree.data[DATA_SOURCE], "code_postal": "5000",
                                        "accord_amelioration": True}]
    for secret in (RAFRAICHISSEMENT, "rafraichissement-SECRET-2", ACCES, CODE_APPAREIL):
        assert secret not in caplog.text
    assert "password" not in json.dumps(dict(entree.data)) and "secret" not in json.dumps(list(entree.data))


async def test_connexion_refusee(hass: HomeAssistant, freezer: FrozenDateTimeFactory, tmp_path,
                                 serveur: Serveur) -> None:
    serveur.refus_appareil = "access_denied"
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _options_jusqu_a_envoi(hass, entree)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"envoi_actif": True, "pas_envoi": "15",
                                                                             "code_postal": "4000"})
        assert r["type"] is FlowResultType.SHOW_PROGRESS
        await hass.async_block_till_done()
        r = await hass.config_entries.options.async_configure(r["flow_id"])
    assert (r["type"], r["reason"]) == (FlowResultType.ABORT, "connexion_echouee")
    assert "refusée" in r["description_placeholders"]["message"]
    assert DATA_JETON not in entree.data
    assert not entree.options.get("envoi_actif")


async def test_deconnexion_depuis_les_options(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        r = await _options_jusqu_a_envoi(hass, connecte)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "deconnecter": True})
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert serveur.revocations == 1
    assert DATA_JETON not in connecte.data
    assert connecte.options["envoi_actif"] is False


async def test_suppression_de_l_integration_retire_le_jeton(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        assert await hass.config_entries.async_remove(connecte.entry_id)
        await hass.async_block_till_done()
    assert serveur.revocations == 1


async def test_ecran_envoi_donne_le_lien_des_conditions(hass: HomeAssistant, connecte) -> None:
    """Le lien des conditions vient d'un paramètre (hassfest refuse les URL dans les traductions)."""
    r = await _options_jusqu_a_envoi(hass, connecte)
    assert r["description_placeholders"]["conditions"] == URL_CONDITIONS
    assert URL_CONDITIONS == "https://analyse.sbg-energy.com/conditions/#home-assistant"


async def test_pas_de_5_minutes_sans_option(hass: HomeAssistant, connecte) -> None:
    r = await _options_jusqu_a_envoi(hass, connecte)
    with pytest.raises(Exception):  # noqa: B017 - « 5 » n'est même pas proposé sans l'option
        await hass.config_entries.options.async_configure(r["flow_id"], {"envoi_actif": True, "pas_envoi": "5"})


def test_morceaux_et_fin_envoyable() -> None:
    d = date(2026, 1, 1)
    jours = [d, d + timedelta(days=1), d + timedelta(days=2), d + timedelta(days=5)]
    assert envoi.morceaux(jours, 2) == [(d, d + timedelta(days=2)), (d + timedelta(days=2), d + timedelta(days=3)),
                                        (d + timedelta(days=5), d + timedelta(days=6))]
    assert envoi.fin_envoyable(datetime(2026, 1, 6, 0, 30, tzinfo=UTC)) == date(2026, 1, 5)
    assert envoi.fin_envoyable(datetime(2026, 1, 6, 1, 0, tzinfo=UTC)) == date(2026, 1, 6)
    assert envoi.heure_quotidienne(SOURCE)[0] in (3, 4, 5)


def aioclient_mock_vide(serveur: Serveur) -> bool:
    return serveur.appels_reglages == [] and serveur.ouvertures == []


async def test_quatrieme_installation_refusee_a_la_connexion(hass: HomeAssistant, freezer: FrozenDateTimeFactory,
                                                             tmp_path, serveur: Serveur) -> None:
    serveur.refus_reglages = ("trop_d_installations", "Votre compte SBG a déjà 3 installations Home Assistant "
                              "connectées, le maximum. Déconnectez-en une depuis votre compte.")
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        entree = await _installer(hass, freezer, tmp_path, OPTIONS, {})
        r = await _options_jusqu_a_envoi(hass, entree)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"envoi_actif": True, "pas_envoi": "15",
                                                                             "code_postal": "4000"})
        await hass.async_block_till_done()
        r = await hass.config_entries.options.async_configure(r["flow_id"])
    assert (r["type"], r["reason"]) == (FlowResultType.ABORT, "reglages_refuses")
    assert "3 installations" in r["description_placeholders"]["message"]
    assert DATA_JETON not in entree.data                              # oublié...
    assert serveur.revocations == 1                                   # ... et retiré chez Keycloak
    assert not entree.options.get("envoi_actif")


async def test_accord_change_dans_les_options(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        r = await _options_jusqu_a_envoi(hass, connecte)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "ameliorer_outils": True})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert serveur.appels_reglages[-1] == {"source": SOURCE, "code_postal": "4000", "accord_amelioration": True}
        # retrait : un appel aussi (le service efface les copies), après confirmation (0.6.1)
        r = await _options_jusqu_a_envoi(hass, connecte)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "4000", "ameliorer_outils": False})
        assert r["step_id"] == "confirmer"
        assert serveur.appels_reglages[-1]["accord_amelioration"] is True
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"confirmer_retrait": True})
        assert r["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        assert serveur.appels_reglages[-1]["accord_amelioration"] is False
        # refus du service : l'erreur s'affiche, rien n'est enregistré
        serveur.refus_reglages = ("code_postal", "Code postal belge à 4 chiffres attendu.")
        r = await _options_jusqu_a_envoi(hass, connecte)
        r = await hass.config_entries.options.async_configure(
            r["flow_id"], {"envoi_actif": True, "pas_envoi": "15", "code_postal": "9999", "ameliorer_outils": False})
        assert r["errors"] == {"base": "reglages_refuses"}
        assert "4 chiffres" in r["description_placeholders"]["message"]
    assert connecte.options["code_postal"] == "4000"


async def test_vieux_jours_au_quart_d_heure_dans_une_session_a_5_min(hass: HomeAssistant, freezer, tmp_path,
                                                                     serveur: Serveur) -> None:
    serveur.reglages = {"code_postal": "4000", "accord_amelioration": False}
    serveur.jour_min_5min = "2026-01-04"                             # 12 mois : ici, avant le 4 janvier
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        await _installer(hass, freezer, tmp_path, {**OPTIONS, "envoi_actif": True, "pas_envoi": 5, "pas_5min": True,
                                                   "code_postal": "4000"},
                         {DATA_JETON: RAFRAICHISSEMENT, DATA_SOURCE: SOURCE})
        await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
    assert serveur.ouvertures[-1]["pas"] == 5
    pas = [(p, sorted({l[:10] for l in c.decode().splitlines() if l[:2] == "20"})) for p, c in serveur.envois]
    assert pas == [("15", ["2026-01-02", "2026-01-03"]), ("5", ["2026-01-04", "2026-01-05"])]


async def test_reglages_redonnes_si_le_service_ne_les_a_pas(hass: HomeAssistant, connecte, serveur: Serveur) -> None:
    serveur.reglages = {}
    with patch("custom_components.sbg_energy_export.collecteur.statistics_during_period", faux_5min):
        await hass.services.async_call(DOMAIN, "envoyer", {}, blocking=True, return_response=True)
    assert serveur.appels_reglages == [{"source": SOURCE, "code_postal": "4000", "accord_amelioration": False}]
