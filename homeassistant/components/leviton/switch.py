"""Switch entities for the Leviton integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_READ_ONLY, DEFAULT_READ_ONLY
from .coordinator import LevitonConfigEntry, LevitonCoordinator
from .entity import LevitonEntity, breaker_device_info

PARALLEL_UPDATES = 1

BREAKER_SWITCH_DESCRIPTION = EntityDescription(
    key="breaker",
    translation_key="breaker",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Leviton switch entities."""
    if entry.options.get(CONF_READ_ONLY, DEFAULT_READ_ONLY):
        return

    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    entities: list[SwitchEntity] = []

    for breaker_id, breaker in data.breakers.items():
        if breaker.can_remote_on:
            dev_info = breaker_device_info(breaker_id, data)
            entities.append(
                LevitonBreakerSwitch(
                    coordinator, BREAKER_SWITCH_DESCRIPTION, breaker_id, dev_info
                )
            )

    async_add_entities(entities)


class LevitonBreakerSwitch(LevitonEntity, SwitchEntity):
    """Switch entity for Gen 2 breaker on/off control."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: LevitonCoordinator,
        description: EntityDescription,
        breaker_id: str,
        device_info: "DeviceInfo",  # noqa: F821
    ) -> None:
        """Initialize the breaker switch."""
        super().__init__(coordinator, description, breaker_id, device_info)

    @property
    def is_on(self) -> bool | None:
        """Return True if the breaker is on."""
        breaker = self._data.breakers.get(self._device_id)
        if breaker is None:
            return None
        # remoteOn=True means on, currentState="ManualON" also means on
        if breaker.remote_on:
            return True
        return breaker.current_state == "ManualON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the breaker."""
        await self.coordinator.client.turn_on_breaker(self._device_id)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the breaker (trip)."""
        await self.coordinator.client.trip_breaker(self._device_id)
        await self.coordinator.async_request_refresh()
