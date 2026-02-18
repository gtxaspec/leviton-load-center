"""Tests for the Leviton integration setup."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aioleviton import (
    LevitonAuthError,
    LevitonConnectionError,
    LevitonTwoFactorRequired,
)

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.leviton.const import CONF_TOKEN, CONF_USER_ID, DOMAIN

from .conftest import (
    MOCK_AUTH_TOKEN,
    MOCK_EMAIL,
    MOCK_PASSWORD,
    MOCK_TOKEN,
    MOCK_USER_ID,
)


async def test_setup_entry_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
    mock_config_entry: MockConfigEntry,
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
    mock_config_entry: MockConfigEntry,
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


async def test_setup_entry_token_and_login_both_fail(
    hass: HomeAssistant,
) -> None:
    """Test both token restore and login fail with auth error → SETUP_ERROR."""
    with patch(
        "homeassistant.components.leviton.LevitonClient",
    ) as mock_cls:
        client = mock_cls.return_value
        client.restore_session = MagicMock()
        # Token restore fails (get_permissions raises auth error)
        client.get_permissions = AsyncMock(
            side_effect=LevitonAuthError("Token expired")
        )
        # Fallback login also fails
        client.login = AsyncMock(
            side_effect=LevitonAuthError("Bad password")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={
                CONF_EMAIL: MOCK_EMAIL,
                CONF_PASSWORD: MOCK_PASSWORD,
                CONF_TOKEN: MOCK_TOKEN,
                CONF_USER_ID: MOCK_USER_ID,
            },
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        # Token expired → fell back to login → login also failed → auth error
        assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_setup_entry_connection_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
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
    mock_config_entry: MockConfigEntry,
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
    mock_config_entry: MockConfigEntry,
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


# --- Token restore path tests ---


async def test_setup_entry_token_restore_success(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
) -> None:
    """Test stored token works and login is NOT called."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_EMAIL,
        data={
            CONF_EMAIL: MOCK_EMAIL,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_TOKEN: MOCK_TOKEN,
            CONF_USER_ID: MOCK_USER_ID,
        },
        unique_id=MOCK_EMAIL.lower(),
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    # restore_session should have been called, login should NOT
    mock_client.restore_session.assert_called_once_with(MOCK_TOKEN, MOCK_USER_ID)
    mock_client.login.assert_not_called()


async def test_setup_entry_token_restore_auth_failure_falls_back(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
) -> None:
    """Test token fails, falls back to login."""
    call_count = 0
    original_return = mock_client.get_permissions.return_value

    async def _get_permissions_side_effect():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LevitonAuthError("Token expired")
        return original_return

    mock_client.get_permissions = AsyncMock(
        side_effect=_get_permissions_side_effect
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_EMAIL,
        data={
            CONF_EMAIL: MOCK_EMAIL,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_TOKEN: "expired_token",
            CONF_USER_ID: MOCK_USER_ID,
        },
        unique_id=MOCK_EMAIL.lower(),
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    mock_client.login.assert_called_once()


async def test_setup_entry_token_restore_connection_error(
    hass: HomeAssistant,
) -> None:
    """Test token path raises ConfigEntryNotReady on connection error."""
    with patch(
        "homeassistant.components.leviton.LevitonClient",
    ) as mock_cls:
        client = mock_cls.return_value
        client.restore_session = MagicMock()
        client.get_permissions = AsyncMock(
            side_effect=LevitonConnectionError("Network error")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={
                CONF_EMAIL: MOCK_EMAIL,
                CONF_PASSWORD: MOCK_PASSWORD,
                CONF_TOKEN: MOCK_TOKEN,
                CONF_USER_ID: MOCK_USER_ID,
            },
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_persists_token_after_login(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_websocket: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that async_update_entry is called with new token after login."""
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    # Entry data should now contain token and user_id
    assert CONF_TOKEN in mock_config_entry.data
    assert CONF_USER_ID in mock_config_entry.data
    assert mock_config_entry.data[CONF_TOKEN] == MOCK_TOKEN
    assert mock_config_entry.data[CONF_USER_ID] == MOCK_USER_ID


async def test_setup_entry_2fa_required(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test LevitonTwoFactorRequired raises ConfigEntryAuthFailed."""
    with patch(
        "homeassistant.components.leviton.LevitonClient",
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonTwoFactorRequired("2FA required")
        )

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

        assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
