"""Base entity for the Leviton integration."""

from __future__ import annotations

from typing import Any

from aioleviton import Breaker

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HIDE_DUMMY, DEFAULT_HIDE_DUMMY, DOMAIN
from .coordinator import LevitonCoordinator, LevitonData


_BREAKER_OFFLINE_STATES = frozenset({
    "NotCommunicating", "CommunicationFailure", "UNDEFINED",
})


class LevitonEntity(CoordinatorEntity[LevitonCoordinator]):
    """Base class for Leviton entities."""

    _attr_has_entity_name = True
    _collection: str = "breakers"

    def __init__(
        self,
        coordinator: LevitonCoordinator,
        description: EntityDescription,
        device_id: str,
        device_info: DeviceInfo,
    ) -> None:
        """Initialize a Leviton entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._device_id = device_id
        entry_uid = coordinator.config_entry.unique_id or ""
        self._attr_unique_id = f"{entry_uid}_{device_id}_{description.key}"
        self._attr_device_info = device_info

    @property
    def available(self) -> bool:
        """Return True if the entity's device is present in coordinator data."""
        if not super().available:
            return False
        data = self.coordinator.data
        if self._device_id not in getattr(data, self._collection):
            return False
        # Breaker entities: unavailable if parent hub is offline
        if self._collection == "breakers":
            breaker = data.breakers.get(self._device_id)
            if breaker is not None:
                if breaker.iot_whem_id:
                    whem = data.whems.get(breaker.iot_whem_id)
                    if whem is not None and not whem.connected:
                        return False
                elif breaker.residential_breaker_panel_id:
                    panel = data.panels.get(
                        breaker.residential_breaker_panel_id
                    )
                    if panel is not None and not panel.is_online:
                        return False
        return True


def whem_device_info(whem_id: str, data: LevitonData) -> DeviceInfo:
    """Build DeviceInfo for a LWHEM hub."""
    whem = data.whems[whem_id]
    return DeviceInfo(
        identifiers={(DOMAIN, whem_id)},
        name=whem.name or f"LWHEM {whem_id}",
        manufacturer=whem.manufacturer,
        model=whem.model,
        sw_version=whem.version,
        serial_number=whem.serial,
    )


def panel_device_info(panel_id: str, data: LevitonData) -> DeviceInfo:
    """Build DeviceInfo for a DAU panel."""
    panel = data.panels[panel_id]
    return DeviceInfo(
        identifiers={(DOMAIN, panel_id)},
        name=panel.name or f"Panel {panel_id}",
        manufacturer="Leviton",
        model="LDATA",
        sw_version=panel.package_ver,
        serial_number=panel.id,
    )


def breaker_device_info(breaker_id: str, data: LevitonData) -> DeviceInfo:
    """Build DeviceInfo for a breaker."""
    breaker = data.breakers[breaker_id]
    name = breaker.name or f"Breaker {breaker.position}"

    # Determine parent hub
    via_device: tuple[str, str] | None = None
    if breaker.iot_whem_id and breaker.iot_whem_id in data.whems:
        via_device = (DOMAIN, breaker.iot_whem_id)
    elif (
        breaker.residential_breaker_panel_id
        and breaker.residential_breaker_panel_id in data.panels
    ):
        via_device = (DOMAIN, breaker.residential_breaker_panel_id)

    return DeviceInfo(
        identifiers={(DOMAIN, breaker_id)},
        name=name,
        manufacturer="Leviton",
        model="Basic Breaker" if breaker.model in ("NONE", "NONE-1", "NONE-2") else breaker.model,
        sw_version=breaker.firmware_version_ble,
        hw_version=breaker.hw_version,
        serial_number=breaker.serial_number,
        via_device=via_device,
    )


def ct_device_info(ct_id: str, data: LevitonData) -> DeviceInfo:
    """Build DeviceInfo for a CT clamp."""
    ct = data.cts[ct_id]
    name = ct.name or f"CT Channel {ct.channel}"

    via_device: tuple[str, str] | None = None
    if ct.iot_whem_id and ct.iot_whem_id in data.whems:
        via_device = (DOMAIN, ct.iot_whem_id)

    return DeviceInfo(
        identifiers={(DOMAIN, str(ct_id))},
        name=name,
        manufacturer="Leviton",
        model="LWHEM CT",
        via_device=via_device,
    )


def should_include_breaker(breaker: Breaker, options: dict[str, Any]) -> bool:
    """Determine if a breaker should have entities created."""
    if breaker.is_lsbma:
        return False
    hide_dummy = options.get(CONF_HIDE_DUMMY, DEFAULT_HIDE_DUMMY)
    if hide_dummy and breaker.is_placeholder and not breaker.has_lsbma:
        return False
    return True
