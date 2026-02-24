"""Button entities for the Leviton integration."""

from __future__ import annotations

import asyncio

from aioleviton import LevitonConnectionError

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_READ_ONLY,
    CONF_STAGGER_DELAY,
    DEFAULT_READ_ONLY,
    DEFAULT_STAGGER_DELAY,
    DOMAIN,
    LOGGER,
    STATE_REMOTE_OFF,
    STATE_REMOTE_ON,
    STATE_SOFTWARE_TRIP,
)
from .coordinator import LevitonConfigEntry
from .entity import (
    LevitonBreakerControlEntity,
    LevitonEntity,
    breaker_device_info,
    panel_device_info,
    should_include_breaker,
    whem_device_info,
)

PARALLEL_UPDATES = 1

TRIP_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="trip",
    translation_key="trip",
)

IDENTIFY_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="identify",
    translation_key="identify",
)

ALL_OFF_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="all_off",
    translation_key="all_off",
)

ALL_ON_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="all_on",
    translation_key="all_on",
)

TRIP_ALL_BUTTON_DESCRIPTION = ButtonEntityDescription(
    key="trip_all",
    translation_key="trip_all",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Leviton button entities."""
    if entry.options.get(CONF_READ_ONLY, DEFAULT_READ_ONLY):
        LOGGER.debug("Button platform: read-only mode, skipping")
        return

    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    entities: list[ButtonEntity] = []

    for breaker_id, breaker in data.breakers.items():
        if not should_include_breaker(breaker, entry.options):
            continue
        # Trip button: Gen 1 only (Gen 2 uses switch turn_off instead)
        if breaker.is_smart and not breaker.can_remote_on:
            dev_info = breaker_device_info(breaker_id, data)
            entities.append(
                LevitonTripButton(
                    coordinator, TRIP_BUTTON_DESCRIPTION, breaker_id, dev_info
                )
            )

    # WHEM buttons: identify, all off, all on
    for whem_id in data.whems:
        dev_info = whem_device_info(whem_id, data)
        entities.append(
            LevitonWhemIdentifyButton(
                coordinator, IDENTIFY_BUTTON_DESCRIPTION, whem_id, dev_info
            )
        )
        entities.append(
            LevitonWhemAllOffButton(
                coordinator, ALL_OFF_BUTTON_DESCRIPTION, whem_id, dev_info
            )
        )
        entities.append(
            LevitonWhemAllOnButton(
                coordinator, ALL_ON_BUTTON_DESCRIPTION, whem_id, dev_info
            )
        )

    # Panel buttons: trip all
    for panel_id in data.panels:
        dev_info = panel_device_info(panel_id, data)
        entities.append(
            LevitonPanelTripAllButton(
                coordinator, TRIP_ALL_BUTTON_DESCRIPTION, panel_id, dev_info
            )
        )

    LOGGER.debug("Button platform: created %d entities", len(entities))
    async_add_entities(entities)


class LevitonTripButton(LevitonBreakerControlEntity, ButtonEntity):
    """Button entity to trip a Gen 1 breaker."""

    _attr_device_class = None

    async def async_press(self) -> None:
        """Trip the breaker."""
        LOGGER.debug("Tripping breaker %s", self._device_id)
        try:
            await self.coordinator.client.trip_breaker(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="breaker_control_failed",
                translation_placeholders={
                    "name": self._device_id,
                    "error": str(err),
                },
            ) from err
        # Optimistic update: WS never delivers currentState for remote
        # commands, so set expected state immediately and notify all entities.
        breaker = self.coordinator.data.breakers.get(self._device_id)
        if breaker:
            breaker.current_state = STATE_SOFTWARE_TRIP
            self.coordinator.async_set_updated_data(self.coordinator.data)


class LevitonWhemIdentifyButton(LevitonEntity, ButtonEntity):
    """Button entity to blink the WHEM hub LED."""

    _attr_device_class = ButtonDeviceClass.IDENTIFY
    _collection = "whems"

    @property
    def available(self) -> bool:
        """Return False when the WHEM is offline."""
        if not super().available:
            return False
        whem = self.coordinator.data.whems.get(self._device_id)
        if whem is None:
            return False
        return whem.connected

    async def async_press(self) -> None:
        """Blink the WHEM LED."""
        LOGGER.debug("Identifying WHEM %s", self._device_id)
        try:
            await self.coordinator.client.identify_whem(self._device_id)
        except LevitonConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="identify_failed",
                translation_placeholders={
                    "name": self._device_id,
                    "error": str(err),
                },
            ) from err


class LevitonWhemAllOffButton(LevitonEntity, ButtonEntity):
    """Button to turn off all breakers on a WHEM hub."""

    _collection = "whems"

    async def async_press(self) -> None:
        """Turn off all child breakers sequentially."""
        delay = self.coordinator.config_entry.options.get(
            CONF_STAGGER_DELAY, DEFAULT_STAGGER_DELAY
        )
        children = [
            (bid, b)
            for bid, b in self.coordinator.data.breakers.items()
            if b.iot_whem_id == self._device_id and b.is_smart
        ]
        LOGGER.debug("All Off for WHEM %s: %d breakers", self._device_id, len(children))
        for i, (breaker_id, breaker) in enumerate(children):
            if i > 0:
                await asyncio.sleep(delay)
            try:
                if breaker.can_remote_on:
                    await self.coordinator.client.turn_off_breaker(breaker_id)
                    breaker.remote_state = STATE_REMOTE_OFF
                else:
                    await self.coordinator.client.trip_breaker(breaker_id)
                    breaker.current_state = STATE_SOFTWARE_TRIP
            except LevitonConnectionError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="bulk_control_failed",
                    translation_placeholders={
                        "name": breaker_id,
                        "error": str(err),
                    },
                ) from err
        self.coordinator.async_set_updated_data(self.coordinator.data)


class LevitonWhemAllOnButton(LevitonEntity, ButtonEntity):
    """Button to turn on all Gen 2 breakers on a WHEM hub."""

    _collection = "whems"

    async def async_press(self) -> None:
        """Turn on all Gen 2 child breakers sequentially."""
        delay = self.coordinator.config_entry.options.get(
            CONF_STAGGER_DELAY, DEFAULT_STAGGER_DELAY
        )
        children = [
            (bid, b)
            for bid, b in self.coordinator.data.breakers.items()
            if b.iot_whem_id == self._device_id
            and b.is_smart
            and b.can_remote_on
        ]
        LOGGER.debug("All On for WHEM %s: %d breakers", self._device_id, len(children))
        for i, (breaker_id, breaker) in enumerate(children):
            if i > 0:
                await asyncio.sleep(delay)
            try:
                await self.coordinator.client.turn_on_breaker(breaker_id)
                breaker.remote_state = STATE_REMOTE_ON
            except LevitonConnectionError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="bulk_control_failed",
                    translation_placeholders={
                        "name": breaker_id,
                        "error": str(err),
                    },
                ) from err
        self.coordinator.async_set_updated_data(self.coordinator.data)


class LevitonPanelTripAllButton(LevitonEntity, ButtonEntity):
    """Button to trip all breakers on an LDATA panel."""

    _collection = "panels"

    async def async_press(self) -> None:
        """Trip all child breakers sequentially."""
        delay = self.coordinator.config_entry.options.get(
            CONF_STAGGER_DELAY, DEFAULT_STAGGER_DELAY
        )
        children = [
            (bid, b)
            for bid, b in self.coordinator.data.breakers.items()
            if b.residential_breaker_panel_id == self._device_id and b.is_smart
        ]
        LOGGER.debug(
            "Trip All for panel %s: %d breakers", self._device_id, len(children)
        )
        for i, (breaker_id, breaker) in enumerate(children):
            if i > 0:
                await asyncio.sleep(delay)
            try:
                await self.coordinator.client.trip_breaker(breaker_id)
                breaker.current_state = STATE_SOFTWARE_TRIP
            except LevitonConnectionError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="bulk_control_failed",
                    translation_placeholders={
                        "name": breaker_id,
                        "error": str(err),
                    },
                ) from err
        self.coordinator.async_set_updated_data(self.coordinator.data)
