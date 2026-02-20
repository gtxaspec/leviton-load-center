"""The Leviton Load Center integration."""

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
from homeassistant.helpers import device_registry as dr

from .const import CONF_TOKEN, CONF_USER_ID, DOMAIN, LOGGER
from .coordinator import LevitonConfigEntry, LevitonCoordinator, LevitonData, LevitonRuntimeData
from .entity import should_include_breaker

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

    _cleanup_hidden_devices(hass, entry, coordinator.data)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    LOGGER.debug("Setup complete for %s", entry.data.get(CONF_EMAIL))
    return True


def _cleanup_hidden_devices(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    data: LevitonData,
) -> None:
    """Remove devices for breakers filtered out by options."""
    options = dict(entry.options)
    device_reg = dr.async_get(hass)

    for breaker_id, breaker in data.breakers.items():
        if should_include_breaker(breaker, options):
            continue
        device = device_reg.async_get_device(identifiers={(DOMAIN, breaker_id)})
        if device is not None:
            LOGGER.debug("Removing hidden breaker device: %s", breaker_id)
            device_reg.async_remove_device(device.id)


async def _async_update_options(
    hass: HomeAssistant, entry: LevitonConfigEntry
) -> None:
    """Reload the integration when options change."""
    LOGGER.debug("Options changed, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: LevitonConfigEntry
) -> bool:
    """Unload a Leviton config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    entry: LevitonConfigEntry,
    device_entry: DeviceEntry,
) -> bool:
    """Allow manual removal of stale devices."""
    return True
