# SPDX-License-Identifier: Apache-2.0
"""Boutons « Exporter » (5 min si l'option est choisie, quart d'heure, heure)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SbgConfigEntry, async_exporter_et_notifier
from .const import OPT_CINQ_MINUTES
from .entite import appareil_service


async def async_setup_entry(
    hass: HomeAssistant, entree: SbgConfigEntry, ajouter: AddConfigEntryEntitiesCallback
) -> None:
    """Export au quart d'heure, export horaire, et export à 5 min avec l'option."""
    pas = [5, 15, 60] if entree.options.get(OPT_CINQ_MINUTES) else [15, 60]
    ajouter([BoutonExporter(entree, p) for p in pas])


class BoutonExporter(ButtonEntity):
    """Écrit le fichier « SBG HA export » et notifie le lien de téléchargement."""

    _attr_has_entity_name = True

    def __init__(self, entree: SbgConfigEntry, pas: int) -> None:
        self._entree = entree
        self._pas = pas
        self._attr_translation_key = f"exporter_{pas}"
        self._attr_unique_id = f"{entree.entry_id}_exporter_{pas}"
        self._attr_device_info = appareil_service(entree)

    async def async_press(self) -> None:
        """Export à la demande."""
        await async_exporter_et_notifier(self.hass, self._entree, self._pas)
