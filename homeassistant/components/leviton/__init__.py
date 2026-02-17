"""The Leviton integration."""

from __future__ import annotations

from aioleviton import (
    LevitonAuthError,
    LevitonClient,
    LevitonConnectionError,
    LevitonTwoFactorRequired,
)

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry

from aioleviton import enable_debug_logging as _enable_aioleviton_debug

from .const import CONF_TOKEN, CONF_USER_ID, LOGGER
from .coordinator import LevitonConfigEntry, LevitonCoordinator, LevitonRuntimeData

_enable_aioleviton_debug()

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

    authenticated = False

    # Try stored token first (avoids 2FA prompt on every restart)
    if CONF_TOKEN in entry.data and CONF_USER_ID in entry.data:
        client.restore_session(entry.data[CONF_TOKEN], entry.data[CONF_USER_ID])
        try:
            await client.get_permissions()
            authenticated = True
        except LevitonAuthError:
            LOGGER.debug("Stored token expired, falling back to login")
            client.restore_session("", "")
        except LevitonConnectionError as err:
            raise ConfigEntryNotReady(err) from err

    # Fall back to email/password login
    if not authenticated:
        try:
            await client.login(
                entry.data[CONF_EMAIL],
                entry.data[CONF_PASSWORD],
            )
        except (LevitonAuthError, LevitonTwoFactorRequired) as err:
            raise ConfigEntryAuthFailed(err) from err
        except LevitonConnectionError as err:
            raise ConfigEntryNotReady(err) from err

        # Update stored token for next restart
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_TOKEN: client.token,
                CONF_USER_ID: client.user_id,
            },
        )

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
