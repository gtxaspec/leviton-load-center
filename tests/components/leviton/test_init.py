"""Tests for the Leviton integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aioleviton import LevitonAuthError, LevitonConnectionError

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from homeassistant.components.leviton.const import DOMAIN

from .conftest import MOCK_AUTH_TOKEN, MOCK_EMAIL, MOCK_PASSWORD


async def test_setup_entry_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
    mock_config_entry: ConfigEntry,
) -> None:
    """Test successful setup of a config entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data is not None
    assert mock_config_entry.runtime_data.coordinator is not None
    assert mock_config_entry.runtime_data.client is not None


async def test_setup_entry_auth_error(
    hass: HomeAssistant,
    mock_config_entry: ConfigEntry,
) -> None:
    """Test setup fails with auth error triggers reauth."""
    with patch(
        "homeassistant.components.leviton.LevitonClient",
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonAuthError("Invalid credentials")
        )

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connection_error(
    hass: HomeAssistant,
    mock_config_entry: ConfigEntry,
) -> None:
    """Test setup fails with connection error raises ConfigEntryNotReady."""
    with patch(
        "homeassistant.components.leviton.LevitonClient",
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonConnectionError("Network error")
        )

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
    mock_config_entry: ConfigEntry,
) -> None:
    """Test unloading a config entry."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
    mock_config_entry: ConfigEntry,
) -> None:
    """Test removing a device from a config entry."""
    from homeassistant.components.leviton import (
        async_remove_config_entry_device,
    )

    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # async_remove_config_entry_device should always return True
    result = await async_remove_config_entry_device(
        hass, mock_config_entry, MagicMock()
    )
    assert result is True
