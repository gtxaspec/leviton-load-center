"""Sensor entities for the Leviton integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import LOGGER
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
    options = dict(entry.options)
    entities: list[SensorEntity] = []

    # Breaker sensors
    for breaker_id, breaker in data.breakers.items():
        if not should_include_breaker(breaker, options):
            continue
        dev_info = breaker_device_info(breaker_id, data)
        for desc in BREAKER_SENSORS:
            if desc.exists_fn(breaker):
                entities.append(
                    LevitonBreakerSensor(
                        coordinator, desc, breaker_id, dev_info, options
                    )
                )

    # CT sensors (skip unused channels)
    for ct_id, ct in data.cts.items():
        if ct.usage_type == "NOT_USED":
            continue
        dev_info = ct_device_info(ct_id, data)
        for desc in CT_SENSORS:
            entities.append(
                LevitonCtSensor(coordinator, desc, ct_id, dev_info)
            )

    # WHEM sensors
    for whem_id in data.whems:
        dev_info = whem_device_info(whem_id, data)
        for desc in WHEM_SENSORS:
            entities.append(
                LevitonWhemSensor(coordinator, desc, whem_id, dev_info)
            )

    # Panel sensors
    for panel_id in data.panels:
        dev_info = panel_device_info(panel_id, data)
        for desc in PANEL_SENSORS:
            entities.append(
                LevitonPanelSensor(coordinator, desc, panel_id, dev_info)
            )

    LOGGER.debug("Sensor platform: created %d entities", len(entities))
    async_add_entities(entities)


# --- Entity classes ---


class LevitonBreakerSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton breaker."""

    entity_description: LevitonBreakerSensorDescription

    def __init__(
        self,
        coordinator: LevitonCoordinator,
        description: LevitonBreakerSensorDescription,
        breaker_id: str,
        device_info: DeviceInfo,
        options: dict[str, Any],
    ) -> None:
        """Initialize the breaker sensor."""
        super().__init__(coordinator, description, breaker_id, device_info)
        self._options = options

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker is None:
            return None
        value = self.entity_description.value_fn(
            breaker, self.coordinator.data, self._options
        )
        if value is not None and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING:
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value


class LevitonCtSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton CT clamp."""

    entity_description: LevitonCtSensorDescription
    _collection = "cts"

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        ct = self.coordinator.data.cts.get(self._device_id)
        if ct is None:
            return None
        value = self.entity_description.value_fn(ct, self.coordinator.data)
        if value is not None and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING:
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value


class LevitonWhemSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton WHEM hub."""

    entity_description: LevitonWhemSensorDescription
    _collection = "whems"

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        whem = self.coordinator.data.whems.get(self._device_id)
        if whem is None:
            return None
        value = self.entity_description.value_fn(whem, self.coordinator.data)
        if value is not None and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING:
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value


class LevitonPanelSensor(LevitonEntity, SensorEntity):
    """Sensor entity for a Leviton DAU panel."""

    entity_description: LevitonPanelSensorDescription
    _collection = "panels"

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        panel = self.coordinator.data.panels.get(self._device_id)
        if panel is None:
            return None
        value = self.entity_description.value_fn(panel, self.coordinator.data)
        if value is not None and self.entity_description.state_class == SensorStateClass.TOTAL_INCREASING:
            value = self.coordinator.clamp_increasing(self._attr_unique_id, value)
        return value
