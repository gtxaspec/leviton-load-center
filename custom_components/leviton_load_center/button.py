"""Button entities for the Leviton integration."""

from __future__ import annotations

from aioleviton import LevitonConnectionError

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_READ_ONLY, DEFAULT_READ_ONLY, DOMAIN
from .coordinator import LevitonConfigEntry, LevitonCoordinator
from .entity import (
    LevitonEntity,
    breaker_device_info,
    should_include_breaker,
    whem_device_info,
)

PARALLEL_UPDATES = 1

TRIP_BUTTON_DESCRIPTION = EntityDescription(
    key="trip",
    translation_key="trip",
)

IDENTIFY_BUTTON_DESCRIPTION = EntityDescription(
    key="identify",
    translation_key="identify",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Leviton button entities."""
    if entry.options.get(CONF_READ_ONLY, DEFAULT_READ_ONLY):
        return

    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    options = dict(entry.options)
    entities: list[ButtonEntity] = []

    for breaker_id, breaker in data.breakers.items():
        if not should_include_breaker(breaker, options):
            continue
        # Trip button: Gen 1 only (Gen 2 uses switch turn_off instead)
        if breaker.is_smart and not breaker.can_remote_on:
            dev_info = breaker_device_info(breaker_id, data)
            entities.append(
                LevitonTripButton(
                    coordinator, TRIP_BUTTON_DESCRIPTION, breaker_id, dev_info
                )
            )

    # WHEM identify button
    for whem_id in data.whems:
        dev_info = whem_device_info(whem_id, data)
        entities.append(
            LevitonWhemIdentifyButton(
                coordinator, IDENTIFY_BUTTON_DESCRIPTION, whem_id, dev_info
            )
        )

    async_add_entities(entities)


class LevitonTripButton(LevitonEntity, ButtonEntity):
    """Button entity to trip a Gen 1 breaker."""

    _attr_device_class = ButtonDeviceClass.RESTART

    async def async_press(self) -> None:
        """Trip the breaker."""
        try:
            await self.coordinator.client.trip_breaker(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="breaker_control_failed",
                translation_placeholders={
                    "name": self.name or self._device_id,
                    "error": str(err),
                },
            ) from err
        # Optimistic update: WS never delivers currentState for remote
        # commands, so set expected state immediately and notify all entities.
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker:
            breaker.current_state = "SoftwareTrip"
            self.coordinator.async_set_updated_data(self.coordinator.data)


class LevitonWhemIdentifyButton(LevitonEntity, ButtonEntity):
    """Button entity to blink the WHEM hub LED."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _collection = "whems"

    async def async_press(self) -> None:
        """Blink the WHEM LED."""
        try:
            await self.coordinator.client.identify_whem(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="identify_failed",
                translation_placeholders={
                    "name": self.name or self._device_id,
                    "error": str(err),
                },
            ) from err
