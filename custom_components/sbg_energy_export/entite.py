"""Appareil de service commun aux entités."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN, VERSION


def appareil_service(entree: ConfigEntry) -> DeviceInfo:
    """Un « appareil » de type service, sans matériel."""
    return DeviceInfo(
        identifiers={(DOMAIN, entree.entry_id)},
        name="SBG Energy Export",
        entry_type=DeviceEntryType.SERVICE,
        sw_version=VERSION,
    )
