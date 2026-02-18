"""Tests for the Leviton config flow."""

from __future__ import annotations

from collections.abc import Generator
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
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    MOCK_AUTH_TOKEN,
    MOCK_EMAIL,
    MOCK_PASSWORD,
    MOCK_TOKEN,
    MOCK_USER_ID,
)


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[None]:
    """Prevent actual integration setup during config flow tests."""
    with (
        patch(
            "homeassistant.components.leviton.async_setup_entry",
            return_value=True,
        ),
        patch(
            "homeassistant.components.leviton.async_unload_entry",
            return_value=True,
        ),
    ):
        yield


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test successful user config flow."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)
        mock_cls.return_value.token = MOCK_TOKEN
        mock_cls.return_value.user_id = MOCK_USER_ID

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
        assert result["title"] == f"Leviton Load Center ({MOCK_EMAIL})"
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
        mock_client.token = MOCK_TOKEN
        mock_client.user_id = MOCK_USER_ID
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
        mock_cls.return_value.token = MOCK_TOKEN
        mock_cls.return_value.user_id = MOCK_USER_ID

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
        mock_cls.return_value.token = MOCK_TOKEN
        mock_cls.return_value.user_id = MOCK_USER_ID

        # Create initial entry
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
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
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_EMAIL,
        data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
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


async def test_reauth_flow_invalid_auth(hass: HomeAssistant) -> None:
    """Test reauth flow shows error on invalid credentials."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonAuthError("Wrong password")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "wrongpassword"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_connection_error(hass: HomeAssistant) -> None:
    """Test reauth flow shows error on connection failure."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonConnectionError("Network down")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "newpassword"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow(hass: HomeAssistant) -> None:
    """Test reconfigure flow."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)
        mock_cls.return_value.token = MOCK_TOKEN
        mock_cls.return_value.user_id = MOCK_USER_ID

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
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


async def test_reconfigure_flow_auth_error(hass: HomeAssistant) -> None:
    """Test reconfigure flow shows error on invalid credentials."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonAuthError("Bad creds")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "new@example.com", CONF_PASSWORD: "badpass"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_flow_connection_error(hass: HomeAssistant) -> None:
    """Test reconfigure flow shows error on connection failure."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=LevitonConnectionError("Timeout")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "newpass"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow_unknown_error(hass: HomeAssistant) -> None:
    """Test reconfigure flow shows error on unexpected exception."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "newpass"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


async def test_reauth_flow_unknown_error(hass: HomeAssistant) -> None:
    """Test reauth flow shows error on unexpected exception."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_cls.return_value.login = AsyncMock(
            side_effect=RuntimeError("Unexpected")
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "newpassword"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


# --- 2FA error path tests ---


async def test_2fa_flow_connection_error(hass: HomeAssistant) -> None:
    """Test 2FA step with connection error during code verification."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                LevitonConnectionError("Network down"),
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
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}


async def test_2fa_flow_auth_error(hass: HomeAssistant) -> None:
    """Test 2FA step with auth error during code verification."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                LevitonAuthError("Auth failed"),
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
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_auth"}


async def test_2fa_flow_unknown_error(hass: HomeAssistant) -> None:
    """Test 2FA step with unexpected error during code verification."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                RuntimeError("Unexpected"),
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
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "unknown"}


async def test_2fa_flow_2fa_required_again(hass: HomeAssistant) -> None:
    """Test 2FA step when server returns 2FA required again (treated as invalid code)."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                LevitonTwoFactorRequired("2FA required again"),
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
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_code"}


# --- 2FA reauth tests ---


async def test_reauth_flow_2fa_success(hass: HomeAssistant) -> None:
    """Test reauth triggers 2FA and completes successfully."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.token = MOCK_TOKEN
        mock_client.user_id = MOCK_USER_ID
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                MOCK_AUTH_TOKEN,
            ]
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "newpassword"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "2fa_reauth"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "123456"},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"


async def test_reauth_flow_2fa_invalid_code(hass: HomeAssistant) -> None:
    """Test reauth 2FA step with invalid code."""
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

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "oldpassword"},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "newpassword"},
        )
        assert result["step_id"] == "2fa_reauth"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "badcode"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_code"}


# --- 2FA reconfigure tests ---


async def test_reconfigure_flow_2fa_success(hass: HomeAssistant) -> None:
    """Test reconfigure triggers 2FA and completes successfully."""
    with patch(
        "homeassistant.components.leviton.config_flow.LevitonClient"
    ) as mock_cls:
        mock_client = mock_cls.return_value
        mock_client.token = MOCK_TOKEN
        mock_client.user_id = MOCK_USER_ID
        mock_client.login = AsyncMock(
            side_effect=[
                LevitonTwoFactorRequired("2FA required"),
                MOCK_AUTH_TOKEN,
            ]
        )

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        assert result["step_id"] == "reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "newpass"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "2fa_reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "123456"},
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reconfigure_successful"


async def test_reconfigure_flow_2fa_invalid_code(hass: HomeAssistant) -> None:
    """Test reconfigure 2FA step with invalid code."""
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

        entry = MockConfigEntry(
            domain=DOMAIN,
            title=MOCK_EMAIL,
            data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
            unique_id=MOCK_EMAIL.lower(),
        )
        entry.add_to_hass(hass)

        result = await entry.start_reconfigure_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: "newpass"},
        )
        assert result["step_id"] == "2fa_reconfigure"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"code": "badcode"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "invalid_code"}
