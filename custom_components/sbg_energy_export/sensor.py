"""Capteur : dernier quart d'heure enregistré localement."""
from __future__ import annotations

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import SbgConfigEntry
from .entite import appareil_service


async def async_setup_entry(
    hass: HomeAssistant, entree: SbgConfigEntry, ajouter: AddConfigEntryEntitiesCallback
) -> None:
    """Un capteur de diagnostic."""
    ajouter([CapteurDernierQuart(entree)])


class CapteurDernierQuart(SensorEntity):
    """Fin du dernier quart d'heure traité ; attribut : début des enregistrements."""

    _attr_has_entity_name = True
    _attr_translation_key = "dernier_quart"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entree: SbgConfigEntry) -> None:
        self._collecteur = entree.runtime_data.collecteur
        self._attr_unique_id = f"{entree.entry_id}_dernier_quart"
        self._attr_device_info = appareil_service(entree)

    async def async_added_to_hass(self) -> None:
        """Mise à jour à chaque passage du collecteur."""
        self.async_on_remove(self._collecteur.async_ecouter(self.async_write_ha_state))

    @property
    def native_value(self) -> datetime | None:
        """Fin du dernier quart traité."""
        p = self._collecteur.prochain
        return datetime.fromtimestamp(p, timezone.utc) if p else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """Premier quart d'heure enregistré."""
        p = self._collecteur.premier
        return {"premier_quart": datetime.fromtimestamp(p, timezone.utc).isoformat() if p else None}
