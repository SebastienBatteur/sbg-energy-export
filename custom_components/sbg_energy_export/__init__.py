# SPDX-License-Identifier: Apache-2.0
"""SBG Energy Export : vos données du tableau Énergie au format ouvert « SBG HA export ».

* Chaque quart d'heure (ou chaque période de 5 min, en option) est enregistré
  localement, ~10 jours avant l'installation puis au fil de l'eau (les
  statistiques de 5 minutes de Home Assistant sont purgées après
  ``purge_keep_days``, 10 jours par défaut). Mois terminés compressés,
  conservation réglable (3 ans par défaut).
* Un service et des boutons « Exporter » écrivent le fichier : le passé en
  horaire (statistiques à long terme), le pas fin là où il est enregistré.
* Export manuel : aucun appel réseau sortant ; le fichier se télécharge depuis
  Home Assistant et l'utilisateur le dépose lui-même où il veut.
* Envoi direct vers analyse.sbg-energy.com (``envoi.py``) : DÉSACTIVÉ par défaut ;
  seulement si l'utilisateur l'active et connecte son compte SBG Energy. C'est le
  seul appel réseau sortant de l'intégration.
"""
from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
from typing import Any

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from . import envoi
from .collecteur import Collecteur
from .const import (
    ATTR_DEBUT,
    ATTR_FIN,
    ATTR_PAS,
    DATA_JETON,
    DATA_SOURCE,
    DOMAIN,
    DOSSIER,
    SERVICE_ENVOYER,
    SERVICE_EXPORTER,
    SERVICE_REIMPORTER,
)
from .export import Resultat, VueFichier, async_exporter

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SCHEMA_EXPORTER = vol.Schema(
    {
        vol.Optional(ATTR_PAS, default=15): vol.All(vol.Coerce(int), vol.In([5, 15, 60])),
        vol.Optional(ATTR_DEBUT): cv.date,
        vol.Optional(ATTR_FIN): cv.date,
    }
)
SCHEMA_REIMPORTER = vol.Schema({vol.Required(ATTR_DEBUT): cv.date, vol.Required(ATTR_FIN): cv.date})
PREMIER_ENVOI_S = 120  # premier envoi après la connexion : laisser le collecteur rattraper


@dataclass
class Donnees:
    """Objets vivants de l'entrée."""

    collecteur: Collecteur
    dossier: Path
    etat: envoi.Etat
    options: dict[str, Any]  # options au chargement : un jeton renouvelé ne recharge pas l'entrée


type SbgConfigEntry = ConfigEntry[Donnees]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Service « exporter » et vue de téléchargement (une seule fois)."""
    dossier = Path(hass.config.path(DOSSIER))
    hass.http.register_view(VueFichier(dossier))

    async def exporter_service(appel: ServiceCall) -> ServiceResponse:
        entrees: list[SbgConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entrees:
            raise HomeAssistantError("SBG Energy Export n'est pas configuré.")
        r = await async_exporter_et_notifier(
            hass, entrees[0], appel.data[ATTR_PAS], appel.data.get(ATTR_DEBUT), appel.data.get(ATTR_FIN)
        )
        return {"fichier": r.chemin.name, "lien": r.lien, "lignes": r.lignes}

    hass.services.async_register(
        DOMAIN, SERVICE_EXPORTER, exporter_service,
        schema=SCHEMA_EXPORTER,  # type: ignore[arg-type]  # voluptuous = alias de probatio depuis 2026.9
        supports_response=SupportsResponse.OPTIONAL,
    )

    async def envoyer_service(appel: ServiceCall) -> ServiceResponse:
        r = await envoi.async_synchroniser(hass, _entree(hass), manuel=True)
        return {"jours": r.jours if r else 0, "prochaine": r.prochaine if r else None}

    async def reimporter_service(appel: ServiceCall) -> ServiceResponse:
        r = await envoi.async_reimporter(hass, _entree(hass), appel.data[ATTR_DEBUT], appel.data[ATTR_FIN])
        return {"jours": r.jours, "prochaine": r.prochaine}

    hass.services.async_register(DOMAIN, SERVICE_ENVOYER, envoyer_service,
                                 supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_REIMPORTER, reimporter_service,
                                 schema=SCHEMA_REIMPORTER,  # type: ignore[arg-type]
                                 supports_response=SupportsResponse.OPTIONAL)
    return True


def _entree(hass: HomeAssistant) -> SbgConfigEntry:
    entrees: list[SbgConfigEntry] = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entrees:
        raise HomeAssistantError("SBG Energy Export n'est pas configuré.")
    return entrees[0]


def lien_telechargement(lien: str) -> str:
    """Lien « Télécharger » pour le Markdown d'une notification (0.5.0).

    Un lien Markdown ``[Télécharger](/api/…)`` ne marche pas : il est sur la même
    origine que l'interface, et le frontend (écouteur de clics global de
    ``home-assistant.ts`` → ``isNavigationClick``) l'intercepte comme une navigation
    interne vers une page inconnue, qui retombe sur le tableau de bord ; la requête
    n'atteint jamais ``VueFichier``. ``isNavigationClick`` laisse passer un lien qui
    porte un attribut ``target``, et le filtre HTML du Markdown (bibliothèque ``xss``,
    liste blanche par défaut : ``a`` → ``target``, ``href``, ``title``) le garde ;
    ``download`` et ``rel`` sont retirés. ``target="_blank"`` fait donc faire au
    navigateur la vraie requête, et la réponse ``Content-Disposition: attachment``
    déclenche le téléchargement. Le lien reste signé et valable une heure.
    """
    return f'<a href="{html.escape(lien, quote=True)}" target="_blank">Télécharger</a>'


async def async_exporter_et_notifier(
    hass: HomeAssistant, entree: SbgConfigEntry, pas: int, debut=None, fin=None
) -> Resultat:
    """Export, puis notification persistante avec le lien de téléchargement."""
    d = entree.runtime_data
    r = await async_exporter(hass, dict(entree.options), d.collecteur, d.dossier, pas, debut, fin)
    persistent_notification.async_create(
        hass,
        (f"Fichier prêt : **{r.chemin.name}** ({r.lignes} lignes"
         + (f" ; pas de {pas} min là où il est mesuré, heure par heure avant" if pas != 60 else " horaires")
         + ").\n\n"
         f"{lien_telechargement(r.lien)} (lien valable une heure ; si rien ne se télécharge : "
         "clic droit sur le lien → « Ouvrir dans un nouvel onglet »).\n\n"
         "C'est une archive ZIP : déposez-la telle quelle sur analyse.sbg-energy.com. "
         "Elle reste aussi dans le dossier `sbg_energy_export/exports` de la configuration. "
         "Rien n'a été envoyé."),
        title="SBG Energy Export",
        notification_id=f"{DOMAIN}_export",
    )
    return r


async def async_setup_entry(hass: HomeAssistant, entree: SbgConfigEntry) -> bool:
    """Démarre l'enregistrement des mesures fines."""
    dossier = Path(hass.config.path(DOSSIER))
    collecteur = Collecteur(hass, dossier, entree.options)
    await collecteur.async_demarrer()
    etat = envoi.Etat(hass)
    await etat.async_charger()
    entree.runtime_data = Donnees(collecteur, dossier, etat, dict(entree.options))
    if not envoi.actif(entree):
        # envoi décoché ou compte déconnecté (les options rechargent l'entrée) : plus d'essai, donc
        # plus de raison d'afficher « installation déconnectée »
        await envoi.async_oublier_deconnectee(hass, entree)
    entree.async_on_unload(collecteur.async_arreter)
    entree.async_on_unload(entree.add_update_listener(_async_options_modifiees))
    entree.async_create_background_task(hass, collecteur.async_rattraper(), f"{DOMAIN}_rattrapage")
    await hass.config_entries.async_forward_entry_setups(entree, PLATFORMS)
    _programmer_envoi(hass, entree)
    return True


def _programmer_envoi(hass: HomeAssistant, entree: SbgConfigEntry) -> None:
    """Tâche quotidienne (elle ne fait rien tant que l'envoi est désactivé), et premier envoi
    peu après la connexion du compte."""
    heure, minute = envoi.heure_quotidienne(entree.data.get(DATA_SOURCE))

    @callback
    def lancer(_maintenant: Any = None) -> None:
        entree.async_create_background_task(hass, envoi.async_tache_quotidienne(hass, entree), f"{DOMAIN}_envoi")

    entree.async_on_unload(async_track_time_change(hass, lancer, hour=heure, minute=minute, second=0))
    if envoi.actif(entree) and not entree.runtime_data.etat.donnees.get("derniere"):
        entree.async_on_unload(async_call_later(hass, PREMIER_ENVOI_S, lancer))


async def _async_options_modifiees(hass: HomeAssistant, entree: SbgConfigEntry) -> None:
    # Le jeton de rafraîchissement renouvelé est écrit dans entree.data : pas de rechargement pour ça.
    if dict(entree.options) == entree.runtime_data.options:
        return
    await hass.config_entries.async_reload(entree.entry_id)


async def async_unload_entry(hass: HomeAssistant, entree: SbgConfigEntry) -> bool:
    """Arrête l'enregistrement (les fichiers restent)."""
    return await hass.config_entries.async_unload_platforms(entree, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entree: SbgConfigEntry) -> None:
    """Suppression de l'intégration : le jeton est retiré chez SBG Energy (au mieux).

    Home Assistant efface l'entrée (et donc le jeton) de toute façon ; la révocation évite
    qu'une autorisation reste valable dans le compte SBG Energy. Les fichiers locaux
    (``<config>/sbg_energy_export/``) restent : ce sont les données de l'utilisateur, le
    README dit comment les supprimer.
    """
    if jeton := entree.data.get(DATA_JETON):
        await envoi.async_revoquer(hass, jeton)
