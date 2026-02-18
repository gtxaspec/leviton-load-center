"""Binary sensor entities for the Leviton integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import LevitonConfigEntry, LevitonCoordinator
from .entity import LevitonEntity, panel_device_info, whem_device_info

PARALLEL_UPDATES = 0

CONNECTIVITY_DESCRIPTION = EntityDescription(
    key="connectivity",
    translation_key="connectivity",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Leviton binary sensor entities."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    entities: list[BinarySensorEntity] = []

    # WHEM connectivity
    for whem_id in data.whems:
        dev_info = whem_device_info(whem_id, data)
        entities.append(
            LevitonWhemConnectivity(
                coordinator, CONNECTIVITY_DESCRIPTION, whem_id, dev_info
            )
        )

    # Panel connectivity
    for panel_id in data.panels:
        dev_info = panel_device_info(panel_id, data)
        entities.append(
            LevitonPanelConnectivity(
                coordinator, CONNECTIVITY_DESCRIPTION, panel_id, dev_info
            )
        )

    async_add_entities(entities)


class LevitonWhemConnectivity(LevitonEntity, BinarySensorEntity):
    """Binary sensor for LWHEM hub connectivity."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        """Return True if the hub is connected."""
        whem = self._data.whems.get(self._device_id)
        if whem is None:
            return None
        return whem.connected


class LevitonPanelConnectivity(LevitonEntity, BinarySensorEntity):
    """Binary sensor for DAU panel connectivity."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self) -> bool | None:
        """Return True if the panel is online."""
        panel = self._data.panels.get(self._device_id)
        if panel is None:
            return None
        return panel.is_online
