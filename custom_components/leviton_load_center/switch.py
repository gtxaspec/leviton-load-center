"""Switch entities for the Leviton integration."""

from __future__ import annotations

from typing import Any

from aioleviton import LevitonConnectionError

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_READ_ONLY, DEFAULT_READ_ONLY, DOMAIN
from .coordinator import LevitonConfigEntry
from .entity import LevitonEntity, breaker_device_info, should_include_breaker

PARALLEL_UPDATES = 1

BREAKER_SWITCH_DESCRIPTION = EntityDescription(
    key="breaker",
    translation_key="breaker",
)

IDENTIFY_SWITCH_DESCRIPTION = EntityDescription(
    key="identify",
    translation_key="identify",
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
    options = dict(entry.options)
    entities: list[SwitchEntity] = []

    for breaker_id, breaker in data.breakers.items():
        if not should_include_breaker(breaker, options):
            continue
        if not breaker.is_smart:
            continue
        dev_info = breaker_device_info(breaker_id, data)
        if breaker.can_remote_on:
            entities.append(
                LevitonBreakerSwitch(
                    coordinator, BREAKER_SWITCH_DESCRIPTION, breaker_id, dev_info
                )
            )
        # LED identify switch: all smart breakers
        entities.append(
            LevitonBreakerIdentifySwitch(
                coordinator, IDENTIFY_SWITCH_DESCRIPTION, breaker_id, dev_info
            )
        )

    async_add_entities(entities)


class LevitonBreakerSwitch(LevitonEntity, SwitchEntity):
    """Switch entity for Gen 2 breaker on/off control."""

    _attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        """Return True if the breaker is on."""
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker is None:
            return None
        # WS never delivers currentState for remote commands, so
        # remoteState is the source of truth for remotely-controlled breakers.
        if breaker.remote_state == "RemoteON":
            return True
        if breaker.remote_state == "RemoteOFF":
            return False
        # No remote command active — use physical state
        return breaker.current_state == "ManualON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the breaker."""
        try:
            await self.coordinator.client.turn_on_breaker(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="breaker_control_failed",
                translation_placeholders={
                    "name": self.name or self._device_id,
                    "error": str(err),
                },
            ) from err
        # Optimistic: Gen 2 remote on/off only changes remoteState,
        # not currentState (physical handle position doesn't change).
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker:
            breaker.remote_state = "RemoteON"
            self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the breaker."""
        try:
            await self.coordinator.client.turn_off_breaker(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="breaker_control_failed",
                translation_placeholders={
                    "name": self.name or self._device_id,
                    "error": str(err),
                },
            ) from err
        # Optimistic: Gen 2 remote on/off only changes remoteState,
        # not currentState (physical handle position doesn't change).
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker:
            breaker.remote_state = "RemoteOFF"
            self.coordinator.async_set_updated_data(self.coordinator.data)


class LevitonBreakerIdentifySwitch(LevitonEntity, SwitchEntity):
    """Switch entity to toggle breaker LED identification."""

    @property
    def is_on(self) -> bool | None:
        """Return True if the breaker LED is blinking."""
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker is None:
            return None
        return breaker.blink_led

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start blinking the breaker LED."""
        try:
            await self.coordinator.client.blink_led(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="identify_failed",
                translation_placeholders={
                    "name": self.name or self._device_id,
                    "error": str(err),
                },
            ) from err
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker:
            breaker.blink_led = True
            self.coordinator.async_set_updated_data(self.coordinator.data)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop blinking the breaker LED."""
        try:
            await self.coordinator.client.stop_blink_led(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="identify_failed",
                translation_placeholders={
                    "name": self.name or self._device_id,
                    "error": str(err),
                },
            ) from err
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker:
            breaker.blink_led = False
            self.coordinator.async_set_updated_data(self.coordinator.data)
