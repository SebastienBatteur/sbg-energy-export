"""Configuration par l'interface : quels appareils exporter, et leur catégorie."""
from __future__ import annotations

import re
from typing import Any

from homeassistant.components.energy.data import async_get_manager
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .collecteur import a_des_sources
from .const import (
    CHOIX_AUCUN,
    CHOIX_SELECTION,
    CHOIX_TOUS,
    DOMAIN,
    OPT_APPAREILS,
    OPT_CATEGORIES,
    OPT_CHOIX,
)
from .sbg_format import CATEGORIES, appareils_du_tableau

# Devine une catégorie d'après le nom (FR, NL, EN, DE) ; l'utilisateur corrige.
INDICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("voiture", ("voiture", "borne", "wallbox", "charger", "chargeur", "laadpaal", "ev", "car", "tesla", "zoe")),
    ("pac", ("pac", "pompe a chaleur", "pompe à chaleur", "heat pump", "heatpump", "warmtepomp", "wärmepumpe", "airco", "clim")),
    ("ballon", ("ballon", "boiler", "chauffe-eau", "chauffe eau", "water heater", "ecs", "warmwater", "sanitaire")),
    ("cuisson", ("four", "oven", "cuisson", "cuisini", "induction", "kookplaat", "plaque", "cooking", "hob", "micro")),
)


def deviner_categorie(nom: str) -> str:
    """Catégorie proposée par défaut d'après le nom de l'appareil."""
    n = " " + " ".join(re.findall(r"\w+", nom.casefold())) + " "
    for categorie, mots in INDICES:
        if any(f" {m}" in n for m in mots):  # début de mot
            return categorie
    return "autre"


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

    async def _charger(self) -> dict[str, Any] | None:
        prefs = (await async_get_manager(self.hass)).data
        self._appareils = appareils_du_tableau(prefs) if prefs else []
        return prefs  # type: ignore[return-value]

    def _formulaire_choix(self, etape: str) -> ConfigFlowResult:
        defaut = self._options.get(OPT_CHOIX, CHOIX_TOUS if self._appareils else CHOIX_AUCUN)
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=etape,
            data_schema=vol.Schema({
                vol.Required(OPT_CHOIX, default=defaut): SelectSelector(SelectSelectorConfig(
                    options=[CHOIX_TOUS, CHOIX_AUCUN, CHOIX_SELECTION],
                    translation_key="choix", mode=SelectSelectorMode.LIST)),
            }),
            description_placeholders={"nombre": str(len(self._appareils))},
        )

    async def _apres_choix(self, saisie: dict[str, Any]) -> ConfigFlowResult:
        self._options[OPT_CHOIX] = saisie[OPT_CHOIX]
        if saisie[OPT_CHOIX] == CHOIX_SELECTION and self._appareils:
            return await self.async_step_selection()  # type: ignore[attr-defined]
        if saisie[OPT_CHOIX] == CHOIX_TOUS and self._appareils:
            self._options[OPT_APPAREILS] = [a["stat_consumption"] for a in self._appareils]
            return await self.async_step_categories()  # type: ignore[attr-defined]
        self._options[OPT_APPAREILS] = []
        self._options[OPT_CATEGORIES] = {}
        return self._terminer()  # type: ignore[attr-defined]

    def _formulaire_selection(self) -> ConfigFlowResult:
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="selection",
            data_schema=vol.Schema({
                vol.Required(OPT_APPAREILS, default=list(self._options.get(OPT_APPAREILS, []))): SelectSelector(
                    SelectSelectorConfig(
                        options=[SelectOptionDict(value=a["stat_consumption"], label=_nom(self.hass, a))
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
            defaut = anciennes.get(stat) or deviner_categorie(_nom(self.hass, a))
            schema[vol.Required(stat, default=defaut)] = SelectSelector(SelectSelectorConfig(
                options=list(CATEGORIES), translation_key="categorie", mode=SelectSelectorMode.DROPDOWN))
        return self.async_show_form(step_id="categories", data_schema=vol.Schema(schema))  # type: ignore[attr-defined]


class SbgConfigFlow(_Etapes, ConfigFlow, domain=DOMAIN):
    """Première configuration."""

    VERSION = 1

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._appareils: list[dict[str, Any]] = []

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
            return self._terminer()
        return await self.async_step_categories()

    async def async_step_categories(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Catégorie de chaque appareil retenu."""
        if user_input is None:
            return self._formulaire_categories()
        self._options[OPT_CATEGORIES] = {k: v for k, v in user_input.items() if v in CATEGORIES}
        return self._terminer()

    def _terminer(self) -> ConfigFlowResult:
        return self.async_create_entry(title="SBG Energy Export", data={}, options=self._options)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SbgOptionsFlow:
        """Options : mêmes étapes."""
        return SbgOptionsFlow()


class SbgOptionsFlow(_Etapes, OptionsFlow):
    """Modifier le choix des appareils ou leurs catégories."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._appareils: list[dict[str, Any]] = []

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
            return self._terminer()
        return await self.async_step_categories()

    async def async_step_categories(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Catégorie de chaque appareil retenu."""
        if user_input is None:
            return self._formulaire_categories()
        self._options[OPT_CATEGORIES] = {k: v for k, v in user_input.items() if v in CATEGORIES}
        return self._terminer()

    def _terminer(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self._options)
