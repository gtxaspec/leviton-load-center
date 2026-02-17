"""Tests for the Leviton config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from aioleviton import (
    LevitonAuthError,
    LevitonConnectionError,
    LevitonInvalidCode,
    LevitonTwoFactorRequired,
)

from homeassistant import config_entries
from homeassistant.components.leviton.const import (
    CONF_CALCULATED_CURRENT,
    CONF_HIDE_DUMMY,
    CONF_READ_ONLY,
    CONF_VOLTAGE_208,
    DOMAIN,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MOCK_AUTH_TOKEN, MOCK_EMAIL, MOCK_PASSWORD


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user config flow."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == MOCK_EMAIL
        assert result["data"][CONF_EMAIL] == MOCK_EMAIL
        assert result["data"][CONF_PASSWORD] == MOCK_PASSWORD


async def test_user_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Test user flow with invalid credentials."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonAuthError("Invalid")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    """Test user flow with connection error."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonConnectionError("Network error")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_unknown_error(hass: HomeAssistant) -> None:
    """Test user flow with unknown error."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


async def test_user_flow_2fa_required(hass: HomeAssistant) -> None:
    """Test user flow triggers 2FA step."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.login = AsyncMock(
            side_effect=LevitonTwoFactorRequired("2FA required")
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "2fa"


async def test_2fa_flow_success(hass: HomeAssistant) -> None:
    """Test successful 2FA flow."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        # First call triggers 2FA, second call succeeds
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                MOCK_AUTH_TOKEN,
            ]
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["step_id"] == "2fa"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "123456"},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_2fa_flow_invalid_code(hass: HomeAssistant) -> None:
    """Test 2FA flow with invalid code."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                LevitonInvalidCode("Bad code"),
            ]
        )

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "badcode"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_code"}


async def test_duplicate_entry(hass: HomeAssistant) -> None:
    """Test duplicate config entry is rejected."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)

        # Create first entry
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY

        # Try duplicate
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"


async def test_reauth_flow(hass: HomeAssistant) -> None:
    """Test reauthentication flow."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)

        # Create initial entry
        entry = config_entries.ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
            source=config_entries.SOURCE_USER,
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "newpassword"},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test options flow."""
    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title=MOCK_EMAIL,
        data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        source=config_entries.SOURCE_USER,
        unique_id=MOCK_EMAIL.lower(),
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_VOLTAGE_208: True,
            CONF_READ_ONLY: False,
            CONF_CALCULATED_CURRENT: True,
            CONF_HIDE_DUMMY: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_VOLTAGE_208] is True
    assert entry.options[CONF_CALCULATED_CURRENT] is True
    assert entry.options[CONF_HIDE_DUMMY] is True


async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test reconfigure flow."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)

        entry = config_entries.ConfigEntry(
            version=1,
            minor_version=1,
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
            source=config_entries.SOURCE_USER,
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "newpass"},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"
