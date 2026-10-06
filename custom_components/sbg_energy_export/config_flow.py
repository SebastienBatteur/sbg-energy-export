# SPDX-License-Identifier: Apache-2.0
"""Configuration par l'interface : quels appareils, leur catégorie, et le stockage local
(durée de conservation, pas de 5 minutes).

Les options ont une dernière étape, « Envoi à analyse.sbg-energy.com » (désactivé
par défaut) : l'activer lance la connexion au compte SBG Energy par un code à
saisir sur auth.sbg-energy.com (flux « Device Authorization Grant », aucun mot de
passe dans Home Assistant).

L'écran de sélection classe les appareils par intérêt pour l'analyse (gros
consommateurs et pilotables, puis cuisson et lavage, puis consommation de fond),
dit pourquoi en une phrase, et coche par défaut les recommandés ; la catégorie
est proposée par des règles déterministes (``categories.py``).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from homeassistant.components.energy.data import async_get_manager
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from . import envoi
from .categories import PRIORITE, deviner_categorie, libelle, recommande
from .collecteur import a_des_sources, async_statistiques
from .const import (
    CHOIX_AUCUN,
    CHOIX_SELECTION,
    CHOIX_TOUS,
    CONSERVATION_DEFAUT,
    CONSERVATION_MAX,
    DATA_JETON,
    DATA_SOURCE,
    DOMAIN,
    OPT_APPAREILS,
    OPT_CATEGORIES,
    OPT_CHOIX,
    OPT_CINQ_MINUTES,
    OPT_CONSERVATION,
    OPT_DECONNECTER,
    OPT_ENVOI,
    OPT_PAS_ENVOI,
    PAS_ENVOI_DEFAUT,
)
from .sbg_format import CATEGORIES, appareils_du_tableau, variations

_LOGGER = logging.getLogger(__name__)
JOURS_PUISSANCE = 30  # période regardée pour la puissance typique


def _nom(hass: HomeAssistant, appareil: dict[str, Any]) -> str:
    stat = appareil["stat_consumption"]
    if appareil.get("name"):
        return str(appareil["name"])
    etat = hass.states.get(stat)
    return etat.name if etat and etat.name else stat


class _Etapes:
    """Étapes communes à la configuration et aux options."""

    hass: HomeAssistant
    _options: dict[str, Any]
    _appareils: list[dict[str, Any]]
    _proposees: dict[str, str]

    async def _charger(self) -> dict[str, Any] | None:
        prefs = (await async_get_manager(self.hass)).data
        appareils = appareils_du_tableau(prefs) if prefs else []
        self._proposees = await self._categories_proposees(appareils)
        # du plus utile pour l'analyse au moins utile, puis par nom
        self._appareils = sorted(appareils, key=lambda a: (
            PRIORITE.get(self._categorie(a["stat_consumption"]), 4), _nom(self.hass, a).casefold()))
        return prefs  # type: ignore[return-value]

    async def _categories_proposees(self, appareils: list[dict[str, Any]]) -> dict[str, str]:
        """Nom, appareil Home Assistant (nom, modèle, fabricant), puis puissance typique."""
        ids = {a["stat_consumption"] for a in appareils}
        maxi: dict[str, float] = {}
        if ids:
            fin = int(time.time()) // 3600 * 3600
            try:
                lignes = await async_statistiques(self.hass, ids, fin - JOURS_PUISSANCE * 86400, fin, "hour")
                for s, l in lignes.items():
                    v = variations(l, 3600)
                    if v:
                        maxi[s] = max(v.values())
            except Exception:  # noqa: BLE001 - une proposition ne doit jamais bloquer l'écran
                _LOGGER.debug("Puissance typique indisponible", exc_info=True)
        entites, appareils_ha = er.async_get(self.hass), dr.async_get(self.hass)
        sortie: dict[str, str] = {}
        for a in appareils:
            stat = a["stat_consumption"]
            textes: list[str | None] = []
            entite = entites.async_get(stat)
            appareil = appareils_ha.async_get(entite.device_id) if entite and entite.device_id else None
            if appareil:
                textes = [getattr(appareil, c, None) for c in ("name_by_user", "name", "model", "manufacturer")]
            sortie[stat] = deviner_categorie(_nom(self.hass, a), *textes, kwh_h_max=maxi.get(stat))
        return sortie

    def _categorie(self, stat: str) -> str:
        """Catégorie déjà choisie, sinon proposée."""
        return self._options.get(OPT_CATEGORIES, {}).get(stat) or self._proposees.get(stat, "autre")

    def _formulaire_choix(self, etape: str) -> ConfigFlowResult:
        defaut = self._options.get(OPT_CHOIX, CHOIX_TOUS if self._appareils else CHOIX_AUCUN)
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=etape,
            data_schema=vol.Schema({
                vol.Required(OPT_CHOIX, default=defaut): SelectSelector(SelectSelectorConfig(
                    options=[CHOIX_TOUS, CHOIX_AUCUN, CHOIX_SELECTION],
                    translation_key="choix", mode=SelectSelectorMode.LIST)),
                vol.Required(OPT_CONSERVATION, default=self._options.get(OPT_CONSERVATION, CONSERVATION_DEFAUT)):
                    NumberSelector(NumberSelectorConfig(min=1, max=CONSERVATION_MAX, step=1,
                                                        mode=NumberSelectorMode.BOX)),
                vol.Required(OPT_CINQ_MINUTES, default=self._options.get(OPT_CINQ_MINUTES, False)):
                    BooleanSelector(),
            }),
            description_placeholders={"nombre": str(len(self._appareils))},
        )

    async def _apres_choix(self, saisie: dict[str, Any]) -> ConfigFlowResult:
        self._options[OPT_CHOIX] = saisie[OPT_CHOIX]
        self._options[OPT_CONSERVATION] = int(saisie.get(OPT_CONSERVATION, CONSERVATION_DEFAUT))
        self._options[OPT_CINQ_MINUTES] = bool(saisie.get(OPT_CINQ_MINUTES, False))
        if saisie[OPT_CHOIX] == CHOIX_SELECTION and self._appareils:
            return await self.async_step_selection()  # type: ignore[attr-defined]
        if saisie[OPT_CHOIX] == CHOIX_TOUS and self._appareils:
            self._options[OPT_APPAREILS] = [a["stat_consumption"] for a in self._appareils]
            return await self.async_step_categories()  # type: ignore[attr-defined]
        self._options[OPT_APPAREILS] = []
        self._options[OPT_CATEGORIES] = {}
        return await self._async_terminer()  # type: ignore[attr-defined]

    def _formulaire_selection(self) -> ConfigFlowResult:
        defaut = list(self._options.get(OPT_APPAREILS, [])) or [
            a["stat_consumption"] for a in self._appareils if recommande(self._categorie(a["stat_consumption"]))]
        langue = self.hass.config.language
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="selection",
            data_schema=vol.Schema({
                vol.Required(OPT_APPAREILS, default=defaut): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(
                            value=a["stat_consumption"],
                            label=libelle(_nom(self.hass, a), self._categorie(a["stat_consumption"]), langue))
                            for a in self._appareils],
                        multiple=True, mode=SelectSelectorMode.LIST)),
            }),
        )

    def _formulaire_categories(self) -> ConfigFlowResult:
        anciennes = self._options.get(OPT_CATEGORIES, {})
        schema: dict[Any, Any] = {}
        for a in self._appareils:
            stat = a["stat_consumption"]
            if stat not in self._options.get(OPT_APPAREILS, []):
                continue
            defaut = anciennes.get(stat) or self._proposees.get(stat, "autre")
            schema[vol.Required(stat, default=defaut)] = SelectSelector(SelectSelectorConfig(
                options=list(CATEGORIES), translation_key="categorie", mode=SelectSelectorMode.DROPDOWN))
        return self.async_show_form(step_id="categories", data_schema=vol.Schema(schema))  # type: ignore[attr-defined]


class SbgConfigFlow(_Etapes, ConfigFlow, domain=DOMAIN):
    """Première configuration."""

    VERSION = 1

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._appareils: list[dict[str, Any]] = []
        self._proposees: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix : tous les appareils, aucun, ou une sélection."""
        prefs = await self._charger()
        if not a_des_sources(prefs):
            return self.async_abort(reason="tableau_energie_vide")
        if user_input is None:
            return self._formulaire_choix("user")
        return await self._apres_choix(user_input)

    async def async_step_selection(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sélection des appareils."""
        if user_input is None:
            return self._formulaire_selection()
        self._options[OPT_APPAREILS] = list(user_input[OPT_APPAREILS])
        if not self._options[OPT_APPAREILS]:
            self._options[OPT_CHOIX] = CHOIX_AUCUN
            self._options[OPT_CATEGORIES] = {}
            return await self._async_terminer()
        return await self.async_step_categories()

    async def async_step_categories(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Catégorie de chaque appareil retenu."""
        if user_input is None:
            return self._formulaire_categories()
        self._options[OPT_CATEGORIES] = {k: v for k, v in user_input.items() if v in CATEGORIES}
        return await self._async_terminer()

    async def _async_terminer(self) -> ConfigFlowResult:
        # L'envoi direct reste désactivé : il s'active ensuite dans « Configurer ».
        return self.async_create_entry(title="SBG Energy Export", data={}, options=self._options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SbgOptionsFlow:
        """Options : mêmes étapes."""
        return SbgOptionsFlow()


class SbgOptionsFlow(_Etapes, OptionsFlow):
    """Modifier le choix des appareils, leurs catégories, et l'envoi direct."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._appareils: list[dict[str, Any]] = []
        self._proposees: dict[str, str] = {}
        self._connexion: envoi.Connexion | None = None
        self._tache: asyncio.Task[str] | None = None

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choix : tous, aucun, ou une sélection."""
        if not self._options:
            self._options = dict(self.config_entry.options)
        await self._charger()
        if user_input is None:
            return self._formulaire_choix("init")
        return await self._apres_choix(user_input)

    async def async_step_selection(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Sélection des appareils."""
        if user_input is None:
            return self._formulaire_selection()
        self._options[OPT_APPAREILS] = list(user_input[OPT_APPAREILS])
        if not self._options[OPT_APPAREILS]:
            self._options[OPT_CHOIX] = CHOIX_AUCUN
            self._options[OPT_CATEGORIES] = {}
            return await self._async_terminer()
        return await self.async_step_categories()

    async def async_step_categories(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Catégorie de chaque appareil retenu."""
        if user_input is None:
            return self._formulaire_categories()
        self._options[OPT_CATEGORIES] = {k: v for k, v in user_input.items() if v in CATEGORIES}
        return await self._async_terminer()

    async def _async_terminer(self) -> ConfigFlowResult:
        return await self.async_step_envoi()

    async def async_step_envoi(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Envoi direct vers analyse.sbg-energy.com : désactivé par défaut."""
        connecte = bool(self.config_entry.data.get(DATA_JETON))
        erreurs: dict[str, str] = {}
        if user_input is not None:
            pas = int(user_input.get(OPT_PAS_ENVOI, PAS_ENVOI_DEFAUT))
            if pas == 5 and not self._options.get(OPT_CINQ_MINUTES):
                erreurs[OPT_PAS_ENVOI] = "pas_5_sans_option"
            else:
                self._options[OPT_ENVOI] = bool(user_input.get(OPT_ENVOI))
                self._options[OPT_PAS_ENVOI] = pas
                if connecte and user_input.get(OPT_DECONNECTER):
                    await envoi.async_revoquer(self.hass, self.config_entry.data[DATA_JETON])
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data={k: v for k, v in self.config_entry.data.items() if k != DATA_JETON})
                    self._options[OPT_ENVOI] = False
                    return self.async_create_entry(data=self._options)
                if self._options[OPT_ENVOI] and not connecte:
                    return await self.async_step_connexion()
                return self.async_create_entry(data=self._options)
        pas_permis = ["5", "15", "60"] if self._options.get(OPT_CINQ_MINUTES) else ["15", "60"]
        schema: dict[Any, Any] = {
            vol.Required(OPT_ENVOI, default=bool(self._options.get(OPT_ENVOI, False))): BooleanSelector(),
            vol.Required(OPT_PAS_ENVOI, default=str(self._options.get(OPT_PAS_ENVOI, PAS_ENVOI_DEFAUT))):
                SelectSelector(SelectSelectorConfig(options=pas_permis, translation_key="pas_envoi",
                                                    mode=SelectSelectorMode.LIST)),
        }
        if connecte:
            schema[vol.Required(OPT_DECONNECTER, default=False)] = BooleanSelector()
        return self.async_show_form(step_id="envoi", data_schema=vol.Schema(schema), errors=erreurs,
                                    description_placeholders={"compte": "connecté" if connecte else "non connecté"})

    async def async_step_connexion(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Code à saisir sur auth.sbg-energy.com ; attend la validation (10 minutes au plus)."""
        if self._connexion is None:
            try:
                self._connexion = await envoi.async_demarrer_connexion(self.hass)
            except envoi.EnvoiErreur:
                return self.async_abort(reason="auth_injoignable")
        if self._tache is None:
            self._tache = self.hass.async_create_task(envoi.async_attendre_connexion(self.hass, self._connexion))
        if self._tache.done():
            if self._tache.exception() is not None:
                return self.async_show_progress_done(next_step_id="echec")
            return self.async_show_progress_done(next_step_id="connecte")
        return self.async_show_progress(
            step_id="connexion", progress_action="connexion", progress_task=self._tache,
            description_placeholders={"url": self._connexion.url_complete, "code": self._connexion.code})

    async def async_step_connecte(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Jeton gardé dans l'entrée (jamais journalisé) ; identifiant aléatoire de l'installation."""
        assert self._tache is not None
        jeton = self._tache.result()
        donnees = {**self.config_entry.data, DATA_JETON: jeton}
        donnees.setdefault(DATA_SOURCE, envoi.nouvelle_source())
        self.hass.config_entries.async_update_entry(self.config_entry, data=donnees)
        return self.async_create_entry(data=self._options)

    async def async_step_echec(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Connexion refusée ou expirée : rien n'est activé."""
        e = self._tache.exception() if self._tache else None
        message = e.message if isinstance(e, envoi.EnvoiErreur) else "La connexion a échoué."
        return self.async_abort(reason="connexion_echouee", description_placeholders={"message": message})
