"""Sensor entities for the Leviton integration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .const import CONF_SHOW_ENERGY_IMPORT, DEFAULT_SHOW_ENERGY_IMPORT, LOGGER
from .coordinator import LevitonConfigEntry, LevitonCoordinator
from .entity import (
    LevitonEntity,
    breaker_device_info,
    ct_device_info,
    panel_device_info,
    should_include_breaker,
    whem_device_info,
)
from .sensor_descriptions import (
    BREAKER_SENSORS,
    CT_SENSORS,
    PANEL_SENSORS,
    WHEM_SENSORS,
    LevitonBreakerSensorDescription,
    LevitonCtSensorDescription,
    LevitonPanelSensorDescription,
    LevitonWhemSensorDescription,
)

PARALLEL_UPDATES = 0


# --- Platform setup ---


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Leviton sensor entities."""
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    entities: list[SensorEntity] = []
    show_import = entry.options.get(CONF_SHOW_ENERGY_IMPORT, DEFAULT_SHOW_ENERGY_IMPORT)

    def _skip_import(key: str) -> bool:
        return key in ("lifetime_energy_import", "energy_import") and not show_import

    # Breaker sensors
    for breaker_id, breaker in data.breakers.items():
        if not should_include_breaker(breaker, entry.options):
            continue
        dev_info = breaker_device_info(breaker_id, data)
        entities.extend(
            LevitonBreakerSensor(
                coordinator, desc, breaker_id, dev_info, entry.options
            )
            for desc in BREAKER_SENSORS
            if desc.exists_fn(breaker) and not _skip_import(desc.key)
        )

    # CT sensors (skip unused channels)
    for ct_id, ct in data.cts.items():
        if ct.usage_type == "NOT_USED":
            continue
        dev_info = ct_device_info(ct_id, data)
        entities.extend(
            LevitonCtSensor(coordinator, desc, ct_id, dev_info)
            for desc in CT_SENSORS
            if desc.exists_fn(ct) and not _skip_import(desc.key)
        )

    # WHEM sensors
    for whem_id in data.whems:
        dev_info = whem_device_info(whem_id, data)
        entities.extend(
            LevitonWhemSensor(coordinator, desc, whem_id, dev_info)
            for desc in WHEM_SENSORS
        )

    # Panel sensors
    for panel_id in data.panels:
        dev_info = panel_device_info(panel_id, data)
        entities.extend(
            LevitonPanelSensor(coordinator, desc, panel_id, dev_info)
            for desc in PANEL_SENSORS
        )

    LOGGER.debug("Sensor platform: created %d entities", len(entities))
    async_add_entities(entities)

    # Remove stale import entities from the registry when the toggle is off
    if not show_import:
        registry = er.async_get(hass)
        import_suffixes = ("_energy_import", "_lifetime_energy_import")
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg_entry.unique_id.endswith(import_suffixes):
                LOGGER.debug("Removing stale import entity: %s", reg_entry.entity_id)
                registry.async_remove(reg_entry.entity_id)


# --- Entity classes ---


def _today_midnight() -> datetime:
    """Return midnight of the current day in the local timezone."""
    return dt_util.start_of_local_day()


class LevitonBreakerSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton breaker."""

    entity_description: LevitonBreakerSensorDescription

    def __init__(
        self,
        coordinator: LevitonCoordinator,
        description: LevitonBreakerSensorDescription,
        breaker_id: str,
        device_info: DeviceInfo,
        options: Mapping[str, Any],
    ) -> None:
        """Initialize the breaker sensor."""
        super().__init__(coordinator, description, breaker_id, device_info)
        self._options = options

    @property
    def last_reset(self) -> datetime | None:
        """Return the time of the last reset for daily energy sensors."""
        if self.entity_description.key in ("energy", "energy_import"):
            return _today_midnight()
        return None

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker is None:
            return None
        value = self.entity_description.value_fn(
            breaker, self.coordinator.data, self._options
        )
        if (
            value is not None
            and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING
        ):
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value


class LevitonCtSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton CT clamp."""

    entity_description: LevitonCtSensorDescription
    _collection = "cts"

    @property
    def last_reset(self) -> datetime | None:
        """Return the time of the last reset for daily energy sensors."""
        if self.entity_description.key in ("energy", "energy_import"):
            return _today_midnight()
        return None

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        ct = self.coordinator.data.cts.get(self._device_id)
        if ct is None:
            return None
        value = self.entity_description.value_fn(ct, self.coordinator.data)
        if (
            value is not None
            and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING
        ):
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value


class LevitonWhemSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton WHEM hub."""

    entity_description: LevitonWhemSensorDescription
    _collection = "whems"

    @property
    def last_reset(self) -> datetime | None:
        """Return the time of the last reset for daily energy sensors."""
        if self.entity_description.key in ("energy", "energy_import"):
            return _today_midnight()
        return None

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        whem = self.coordinator.data.whems.get(self._device_id)
        if whem is None:
            return None
        value = self.entity_description.value_fn(whem, self.coordinator.data)
        if (
            value is not None
            and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING
        ):
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value


class LevitonPanelSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton DAU panel."""

    entity_description: LevitonPanelSensorDescription
    _collection = "panels"

    @property
    def last_reset(self) -> datetime | None:
        """Return the time of the last reset for daily energy sensors."""
        if self.entity_description.key in ("energy", "energy_import"):
            return _today_midnight()
        return None

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        panel = self.coordinator.data.panels.get(self._device_id)
        if panel is None:
            return None
        value = self.entity_description.value_fn(panel, self.coordinator.data)
        if (
            value is not None
            and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING
        ):
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value
