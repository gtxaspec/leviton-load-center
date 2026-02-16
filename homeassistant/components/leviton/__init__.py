"""The Leviton integration."""

from __future__ import annotations

from aiolevtion import LevitonAuthError, LevitonClient, LevitonConnectionError

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from .coordinator import LevitonConfigEntry, LevitonCoordinator, LevitonRuntimeData

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant, entry: LevitonConfigEntry
) -> bool:
    """Set up Leviton from a config entry."""
    session = async_get_clientsession(hass)
    client = LevitonClient(session)

    try:
        await client.login(
            entry.data[CONF_EMAIL],
            entry.data[CONF_PASSWORD],
        )
    except LevitonAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except LevitonConnectionError as err:
        raise ConfigEntryNotReady(err) from err

    coordinator = LevitonCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = LevitonRuntimeData(
        client=client, coordinator=coordinator
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: LevitonConfigEntry
) -> bool:
    """Unload a Leviton config entry."""
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow manual removal of stale devices."""
    return True
