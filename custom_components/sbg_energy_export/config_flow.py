# SPDX-License-Identifier: Apache-2.0
"""Configuration par l'interface : quels appareils, leur catégorie, et le stockage local
(durée de conservation, pas de 5 minutes).

Les options ont une dernière étape, « Envoi à analyse.sbg-energy.com » (désactivé
par défaut) : l'activer lance la connexion au compte SBG Energy par un code à
saisir sur auth.sbg-energy.com (flux « Device Authorization Grant », aucun mot de
passe dans Home Assistant). Depuis la version 0.4.0 (décisions du 06/10/2026), la
même étape demande le code postal (obligatoire pour envoyer) et porte la case
facultative « Améliorer les outils SBG », décochée par défaut, retirable à tout
moment ; ces deux réglages partent au service quand on les enregistre (compte
connecté), et c'est là que le service refuse une 4e installation par compte.

Version 0.6.0 (ADR-040, étape 7) : la même étape porte le gestionnaire de réseau,
FACULTATIF (« je ne sais pas » par défaut : le service le déduit du code postal quand il
est certain) ; après la connexion, une étape « Logement » dit où les données arrivent et,
si le service donne la liste des logements du compte, laisse en choisir un autre. Un
service qui ne donne pas ces champs garde le comportement de 0.5 (rangement par code
postal, aucune étape de plus).

L'écran de sélection classe les appareils par intérêt pour l'analyse (gros
consommateurs et pilotables, puis cuisson et lavage, puis consommation de fond),
dit pourquoi en une phrase, et coche par défaut les recommandés ; la catégorie
est proposée par des règles déterministes (``categories.py``).

Version 0.6.1 : désactiver l'envoi ou retirer l'accord « Améliorer les outils SBG » depuis
l'étape Envoi demande une confirmation (étape « confirmer », cases décochées par défaut).
Constaté le 10/10/2026 sur une installation réelle : après le choix du gestionnaire de réseau,
l'étape a été validée avec les deux interrupteurs décochés sans que l'utilisateur l'ait voulu,
et 0.6.0 a retiré l'accord et coupé l'envoi sur cette seule foi.
"""
from __future__ import annotations

import asyncio
import logging
import re
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
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from . import envoi
from .categories import PRIORITE, deviner_categorie, libelle, recommande
from .collecteur import a_des_sources, async_statistiques
from .const import (
    CHOIX_AUCUN,
    CHOIX_SELECTION,
    CHOIX_TOUS,
    CONF_ARRET,
    CONF_RETRAIT,
    CONSERVATION_DEFAUT,
    CONSERVATION_MAX,
    DATA_JETON,
    DATA_SOURCE,
    DOMAIN,
    GRD_INCONNU,
    GRDS,
    OPT_AMELIORER,
    OPT_APPAREILS,
    OPT_CATEGORIES,
    OPT_CHOIX,
    OPT_CINQ_MINUTES,
    OPT_CODE_POSTAL,
    OPT_CONSERVATION,
    OPT_DECONNECTER,
    OPT_ENVOI,
    OPT_GRD,
    OPT_LOGEMENT,
    OPT_PAS_ENVOI,
    PAS_ENVOI_DEFAUT,
    URL_CONDITIONS,
)
from .sbg_format import CATEGORIES, appareils_du_tableau, variations

_LOGGER = logging.getLogger(__name__)
JOURS_PUISSANCE = 30  # période regardée pour la puissance typique
CODE_POSTAL = re.compile(r"^[1-9]\d{3}$")  # Belgique : 1000 à 9999 (le service vérifie la région)


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
        # Étape Envoi (0.6.1) : ce qu'elle montrait à son ouverture, ce qui attend une confirmation
        # (saisie reçue, effets à confirmer) et la réponse à cette confirmation.
        self._reference: dict[str, Any] | None = None
        self._en_attente: dict[str, Any] = {}
        self._a_confirmer: dict[str, bool] = {}
        self._confirme: dict[str, bool] | None = None

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

    def _etat(self) -> envoi.Etat | None:
        return getattr(getattr(self.config_entry, "runtime_data", None), "etat", None)

    def _reglages_connus(self) -> dict[str, Any]:
        """Derniers réglages vus chez le service (ils ont pu changer depuis le compte), sinon les options."""
        etat = self._etat()
        serveur = (etat.donnees.get("reglages") if etat else None) or {}
        grd = serveur.get("grd") or self._options.get(OPT_GRD) or GRD_INCONNU
        logement = etat.logement if etat else None
        return {OPT_CODE_POSTAL: serveur.get("code_postal") or self._options.get(OPT_CODE_POSTAL, ""),
                OPT_AMELIORER: bool(serveur.get("accord_amelioration", self._options.get(OPT_AMELIORER, False))),
                OPT_GRD: grd if grd in GRDS else GRD_INCONNU,
                OPT_LOGEMENT: logement["id"] if logement else ""}

    def _logements_au_choix(self) -> list[dict[str, str]]:
        """Logements proposés par le service, seulement s'il y en a plusieurs ET que le logement
        actuel en fait partie (sinon, valider le formulaire déplacerait la source sans le vouloir)."""
        etat = self._etat()
        if etat is None or etat.logement is None:
            return []
        logements = etat.logements
        if len(logements) < 2 or etat.logement["id"] not in {lg["id"] for lg in logements}:
            return []
        return logements

    @staticmethod
    def _champ_logement(logements: list[dict[str, str]]) -> SelectSelector:
        return SelectSelector(SelectSelectorConfig(
            options=[SelectOptionDict(value=lg["id"], label=lg["nom"]) for lg in logements],
            mode=SelectSelectorMode.DROPDOWN))

    def _affiche_envoi(self, connus: dict[str, Any], effacee: bool) -> dict[str, Any]:
        """Ce que l'étape Envoi montre à son ouverture (aucune saisie encore)."""
        return {OPT_ENVOI: bool(self._options.get(OPT_ENVOI, False)) and not effacee,
                OPT_AMELIORER: bool(connus[OPT_AMELIORER])}

    async def async_step_envoi(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Envoi direct vers analyse.sbg-energy.com : désactivé par défaut.

        0.6.1 : désactiver l'envoi et retirer l'accord « Améliorer les outils SBG » (le service
        efface alors les copies) ne se font JAMAIS sur la seule foi des interrupteurs reçus. Les
        deux se comparent à ce que CE formulaire montrait à son ouverture (``self._reference``),
        pas à un état relu au moment de valider ; et un interrupteur reçu décoché alors qu'il était
        montré coché passe par l'étape « confirmer », dont les cases sont décochées par défaut :
        sans confirmation, l'interrupteur reste comme il était et le reste du formulaire est
        enregistré."""
        connecte = bool(self.config_entry.data.get(DATA_JETON))
        etat = self._etat()
        effacee = bool(etat and etat.effacee)
        erreurs: dict[str, str] = {}
        message = ""
        connus = self._reglages_connus()
        logements = self._logements_au_choix() if connecte else []
        if user_input is None:
            self._reference = self._affiche_envoi(connus, effacee)
            self._confirme = None
            if effacee:
                erreurs["base"] = "installation_effacee"  # dit dans les options, pas seulement en notification
        reference = self._reference or self._affiche_envoi(connus, effacee)
        if user_input is not None:
            pas = int(user_input.get(OPT_PAS_ENVOI, PAS_ENVOI_DEFAUT))
            cp = str(user_input.get(OPT_CODE_POSTAL) or "").strip()
            # un interrupteur absent de la saisie n'a pas été touché : il vaut ce qui était montré
            accord = bool(user_input.get(OPT_AMELIORER, reference[OPT_AMELIORER]))
            actif = bool(user_input.get(OPT_ENVOI, reference[OPT_ENVOI]))
            grd = str(user_input.get(OPT_GRD) or GRD_INCONNU)
            grd = grd if grd in GRDS else GRD_INCONNU
            voulu = str(user_input.get(OPT_LOGEMENT) or "") if logements else ""
            logement = voulu if voulu and voulu != connus[OPT_LOGEMENT] else None
            deconnecter = connecte and bool(user_input.get(OPT_DECONNECTER))
            if pas == 5 and not self._options.get(OPT_CINQ_MINUTES):
                erreurs[OPT_PAS_ENVOI] = "pas_5_sans_option"
            elif (actif or cp) and not CODE_POSTAL.match(cp):
                erreurs[OPT_CODE_POSTAL] = "code_postal"
            elif connecte and not deconnecter:
                # Décoché ici alors que c'était montré coché : seulement si confirmé.
                arret = reference[OPT_ENVOI] and not actif
                retrait = reference[OPT_AMELIORER] and not accord
                if (arret or retrait) and self._confirme is None:
                    self._a_confirmer = {CONF_ARRET: arret, CONF_RETRAIT: retrait}
                    self._en_attente = dict(user_input)
                    return await self.async_step_confirmer()
                confirme, self._confirme = self._confirme or {}, None
                if arret and not confirme.get(CONF_ARRET):
                    actif = True
                if retrait and not confirme.get(CONF_RETRAIT):
                    accord = True
                # L'accord ne part « donné » que si l'interrupteur est passé ICI de décoché (tel
                # que montré) à coché. Laissé comme montré, c'est l'état du service qui vaut :
                if accord and reference[OPT_AMELIORER] and not connus[OPT_AMELIORER]:
                    # montré coché, mais retiré entre-temps depuis le compte : il reste retiré.
                    # Rien n'est enregistré ; le formulaire revient, case décochée, et le dit
                    # (la recocher alors est un choix fait ici).
                    accord = False
                    self._reference = reference = {**reference, OPT_AMELIORER: False}
                    erreurs["base"] = "accord_retire"
                elif not accord and not reference[OPT_AMELIORER] and connus[OPT_AMELIORER]:
                    # montré décoché et laissé décoché, mais donné entre-temps depuis le
                    # compte : ce formulaire ne le retire pas
                    accord = True
                if (actif or cp) and not CODE_POSTAL.match(cp):
                    # sur la valeur FINALE : un arrêt non confirmé laisse l'envoi actif, qui ne
                    # s'enregistre pas sans code postal
                    erreurs[OPT_CODE_POSTAL] = "code_postal"
            if not erreurs:
                self._options[OPT_ENVOI] = actif
                self._options[OPT_PAS_ENVOI] = pas
                self._options[OPT_CODE_POSTAL] = cp
                self._options[OPT_AMELIORER] = accord
                self._options[OPT_GRD] = grd
                if deconnecter:
                    await envoi.async_revoquer(self.hass, self.config_entry.data[DATA_JETON])
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data={k: v for k, v in self.config_entry.data.items() if k != DATA_JETON})
                    self._options[OPT_ENVOI] = False
                    if (etat := self._etat()) is not None:
                        # logement, « effacée », prochain envoi… : c'était ce compte-là
                        await envoi.async_oublier_compte(self.hass, etat)
                    return self.async_create_entry(data=self._options)
                if actif and not connecte:
                    return await self.async_step_connexion()
                change = (cp, accord, grd) != (connus[OPT_CODE_POSTAL], connus[OPT_AMELIORER], connus[OPT_GRD])
                # installation effacée puis recochée : on redemande au service (autorisée à nouveau ?)
                if connecte and cp and (change or logement or (actif and effacee)):
                    # un appel, au moment où l'utilisateur enregistre (retirer l'accord efface les copies)
                    try:
                        await envoi.async_reglages(self.hass, self.config_entry, cp, accord, grd, logement)
                    except envoi.EnvoiErreur as e:
                        erreurs["base"] = "installation_effacee" if e.code == envoi.EFFACEE else "reglages_refuses"
                        message = e.message
                        if e.code == envoi.EFFACEE:
                            self._options[OPT_ENVOI] = False
                if not erreurs:
                    return self.async_create_entry(data=self._options)
            if erreurs:
                # le formulaire revient avec ce qui a été retenu (et, après un refus, demandé au service)
                user_input = {**user_input, OPT_ENVOI: actif, OPT_AMELIORER: accord}
        pas_permis = ["5", "15", "60"] if self._options.get(OPT_CINQ_MINUTES) else ["15", "60"]
        saisie = user_input or {}
        envoi_coche = bool(saisie.get(OPT_ENVOI, reference[OPT_ENVOI]))
        if erreurs.get("base") == "installation_effacee":
            envoi_coche = False
        schema: dict[Any, Any] = {
            vol.Required(OPT_ENVOI, default=envoi_coche): BooleanSelector(),
            vol.Optional(OPT_CODE_POSTAL, default=str(saisie.get(OPT_CODE_POSTAL, connus[OPT_CODE_POSTAL]) or "")):
                TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
            vol.Optional(OPT_GRD, default=str(saisie.get(OPT_GRD, connus[OPT_GRD]))):
                SelectSelector(SelectSelectorConfig(options=[GRD_INCONNU, *GRDS], translation_key="grd",
                                                    mode=SelectSelectorMode.DROPDOWN)),
            vol.Required(OPT_AMELIORER, default=bool(saisie.get(OPT_AMELIORER, reference[OPT_AMELIORER]))):
                BooleanSelector(),
        }
        if logements:
            schema[vol.Required(OPT_LOGEMENT, default=str(saisie.get(OPT_LOGEMENT, connus[OPT_LOGEMENT])))] = \
                self._champ_logement(logements)
        schema[vol.Required(OPT_PAS_ENVOI, default=str(self._options.get(OPT_PAS_ENVOI, PAS_ENVOI_DEFAUT)))] = \
            SelectSelector(SelectSelectorConfig(options=pas_permis, translation_key="pas_envoi",
                                                mode=SelectSelectorMode.LIST))
        if connecte:
            schema[vol.Required(OPT_DECONNECTER, default=False)] = BooleanSelector()
        logement_actuel = etat.logement if etat and connecte else None
        return self.async_show_form(step_id="envoi", data_schema=vol.Schema(schema), errors=erreurs,
                                    description_placeholders={"compte": "connecté" if connecte else "non connecté",
                                                              "logement": logement_actuel["nom"] if logement_actuel
                                                              else "—",
                                                              "message": message,
                                                              "conditions": URL_CONDITIONS})

    async def async_step_confirmer(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirmation de ce que l'étape Envoi a reçu décoché alors qu'elle le montrait coché.

        Une case par effet (désactiver l'envoi ; retirer l'accord, ce qui efface les copies),
        décochée par défaut. Ce qui n'est pas confirmé reste comme avant ; le reste de l'étape
        Envoi (code postal, gestionnaire de réseau, logement, pas) est enregistré."""
        if user_input is None:
            return self.async_show_form(step_id="confirmer", data_schema=vol.Schema({
                vol.Required(cle, default=False): BooleanSelector()
                for cle in (CONF_ARRET, CONF_RETRAIT) if self._a_confirmer.get(cle)}))
        self._confirme = {cle: user_input.get(cle) is True for cle in (CONF_ARRET, CONF_RETRAIT)
                          if self._a_confirmer.get(cle)}
        return await self.async_step_envoi(self._en_attente)

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
        """Jeton gardé dans l'entrée (jamais journalisé) ; identifiant aléatoire de l'installation ;
        puis code postal et accord au service, qui refuse ici une 4e installation par compte."""
        assert self._tache is not None
        jeton = self._tache.result()
        donnees = {**self.config_entry.data, DATA_JETON: jeton}
        donnees.setdefault(DATA_SOURCE, envoi.nouvelle_source())
        self.hass.config_entries.async_update_entry(self.config_entry, data=donnees)
        if (etat := self._etat()) is not None:
            # Nouveau jeton, peut-être un autre compte (ou l'ancien jeton avait expiré, sans passer
            # par « déconnecter ») : rien de l'état précédent ne doit se montrer à l'étape suivante.
            await envoi.async_oublier_compte(self.hass, etat)
        try:
            await envoi.async_reglages(self.hass, self.config_entry, self._options.get(OPT_CODE_POSTAL, ""),
                                       bool(self._options.get(OPT_AMELIORER)), str(self._options.get(OPT_GRD) or ""))
        except envoi.EnvoiErreur as e:
            if e.code in ("reseau", "auth"):
                # service injoignable : la connexion est gardée, les réglages repartiront au premier envoi
                _LOGGER.info("Réglages de l'envoi non transmis (%s) : ils le seront au premier envoi", e.code)
                return self.async_create_entry(data=self._options)
            # refus du service (4e installation, code postal…) : rien n'est activé, jeton oublié et révoqué
            await envoi.async_revoquer(self.hass, jeton)
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={k: v for k, v in self.config_entry.data.items() if k != DATA_JETON})
            return self.async_abort(reason="reglages_refuses", description_placeholders={"message": e.message})
        return await self.async_step_logement()

    async def async_step_logement(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Après la connexion (0.6.0) : le logement du compte où arrivent les données, et le choix
        d'un autre si le service donne la liste. Service sans ces champs : rien à montrer (0.5)."""
        etat = self._etat()
        actuel = etat.logement if etat else None
        if actuel is None:
            return self.async_create_entry(data=self._options)
        logements = self._logements_au_choix()
        erreurs: dict[str, str] = {}
        message = ""
        if user_input is not None:
            voulu = str(user_input.get(OPT_LOGEMENT) or "") if logements else ""
            if not voulu or voulu == actuel["id"]:
                return self.async_create_entry(data=self._options)
            try:
                await envoi.async_reglages(self.hass, self.config_entry, self._options.get(OPT_CODE_POSTAL, ""),
                                           bool(self._options.get(OPT_AMELIORER)),
                                           str(self._options.get(OPT_GRD) or ""), voulu)
            except envoi.EnvoiErreur as e:
                erreurs["base"] = "reglages_refuses"
                message = e.message
            else:
                return self.async_create_entry(data=self._options)
        schema: dict[Any, Any] = {}
        if logements:
            schema[vol.Required(OPT_LOGEMENT, default=actuel["id"])] = self._champ_logement(logements)
        return self.async_show_form(step_id="logement", data_schema=vol.Schema(schema), errors=erreurs,
                                    description_placeholders={"logement": actuel["nom"], "message": message})

    async def async_step_echec(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Connexion refusée ou expirée : rien n'est activé."""
        e = self._tache.exception() if self._tache else None
        message = e.message if isinstance(e, envoi.EnvoiErreur) else "La connexion a échoué."
        return self.async_abort(reason="connexion_echouee", description_placeholders={"message": message})
