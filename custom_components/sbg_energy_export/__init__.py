"""SBG Energy Export : vos données du tableau Énergie au format ouvert « SBG HA export ».

* Chaque quart d'heure (ou chaque période de 5 min, en option) est enregistré
  localement, ~10 jours avant l'installation puis au fil de l'eau (les
  statistiques de 5 minutes de Home Assistant sont purgées après
  ``purge_keep_days``, 10 jours par défaut). Mois terminés compressés,
  conservation réglable (3 ans par défaut).
* Un service et des boutons « Exporter » écrivent le fichier : le passé en
  horaire (statistiques à long terme), le pas fin là où il est enregistré.
* Aucun appel réseau sortant : le fichier se télécharge depuis Home Assistant
  et l'utilisateur le dépose lui-même où il veut.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homeassistant.components import persistent_notification
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .collecteur import Collecteur
from .const import ATTR_DEBUT, ATTR_FIN, ATTR_PAS, DOMAIN, DOSSIER, SERVICE_EXPORTER
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


@dataclass
class Donnees:
    """Objets vivants de l'entrée."""

    collecteur: Collecteur
    dossier: Path


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
    return True


async def async_exporter_et_notifier(
    hass: HomeAssistant, entree: SbgConfigEntry, pas: int, debut=None, fin=None
) -> Resultat:
    """Export, puis notification persistante avec le lien de téléchargement."""
    d = entree.runtime_data
    r = await async_exporter(hass, dict(entree.options), d.collecteur, d.dossier, pas, debut, fin)
    persistent_notification.async_create(
        hass,
        (f"Fichier prêt : **{r.chemin.name}** ({r.lignes} lignes au pas de {pas} min).\n\n"
         f"[Télécharger]({r.lien}) (lien valable une heure).\n\n"
         "Le fichier reste aussi dans le dossier `sbg_energy_export/exports` de la configuration. "
         "Rien n'a été envoyé : déposez-le vous-même sur analyse.sbg-energy.com."),
        title="SBG Energy Export",
        notification_id=f"{DOMAIN}_export",
    )
    return r


async def async_setup_entry(hass: HomeAssistant, entree: SbgConfigEntry) -> bool:
    """Démarre l'enregistrement des mesures fines."""
    dossier = Path(hass.config.path(DOSSIER))
    collecteur = Collecteur(hass, dossier, entree.options)
    await collecteur.async_demarrer()
    entree.runtime_data = Donnees(collecteur, dossier)
    entree.async_on_unload(collecteur.async_arreter)
    entree.async_on_unload(entree.add_update_listener(_async_options_modifiees))
    entree.async_create_background_task(hass, collecteur.async_rattraper(), f"{DOMAIN}_rattrapage")
    await hass.config_entries.async_forward_entry_setups(entree, PLATFORMS)
    return True


async def _async_options_modifiees(hass: HomeAssistant, entree: SbgConfigEntry) -> None:
    await hass.config_entries.async_reload(entree.entry_id)


async def async_unload_entry(hass: HomeAssistant, entree: SbgConfigEntry) -> bool:
    """Arrête l'enregistrement (les fichiers restent)."""
    return await hass.config_entries.async_unload_platforms(entree, PLATFORMS)
