"""Tests for the Leviton coordinator."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aioleviton import LevitonAuthError, LevitonConnectionError

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from homeassistant.components.leviton.coordinator import (
    LevitonCoordinator,
    LevitonData,
)

from .conftest import (
    MOCK_AUTH_TOKEN,
    MOCK_BREAKER_GEN1,
    MOCK_BREAKER_GEN2,
    MOCK_CT,
    MOCK_PANEL,
    MOCK_PERMISSION,
    MOCK_RESIDENCE,
    MOCK_TOKEN,
    MOCK_USER_ID,
    MOCK_WHEM,
)


def _make_coordinator(hass, entry, mock_client) -> LevitonCoordinator:
    """Create a coordinator with a mocked client."""
    return LevitonCoordinator(hass, entry, mock_client)


async def test_discover_devices(hass, mock_client) -> None:
    """Test device discovery finds all device types."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)

    await coordinator._discover_devices()

    assert MOCK_WHEM.id in coordinator.data.whems
    assert MOCK_PANEL.id in coordinator.data.panels
    assert MOCK_BREAKER_GEN1.id in coordinator.data.breakers
    assert MOCK_BREAKER_GEN2.id in coordinator.data.breakers
    assert MOCK_CT.id in coordinator.data.cts
    assert MOCK_RESIDENCE.id in coordinator.data.residences


async def test_discover_devices_auth_error(hass, mock_client) -> None:
    """Test device discovery raises ConfigEntryAuthFailed on auth error."""
    mock_client.get_permissions = AsyncMock(
        side_effect=LevitonAuthError("Token expired")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._discover_devices()


async def test_discover_devices_connection_error(hass, mock_client) -> None:
    """Test device discovery raises UpdateFailed on connection error."""
    mock_client.get_permissions = AsyncMock(
        side_effect=LevitonConnectionError("Network error")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)

    with pytest.raises(UpdateFailed):
        await coordinator._discover_devices()


async def test_discover_residence_whem_failure(hass, mock_client) -> None:
    """Test graceful handling of WHEM fetch failure in a residence."""
    mock_client.get_whems = AsyncMock(
        side_effect=LevitonConnectionError("WHEM error")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)

    await coordinator._discover_devices()

    # WHEMs and their children should be missing, but panels still found
    assert len(coordinator.data.whems) == 0
    assert MOCK_PANEL.id in coordinator.data.panels


async def test_discover_residence_panel_failure(hass, mock_client) -> None:
    """Test graceful handling of panel fetch failure in a residence."""
    mock_client.get_panels = AsyncMock(
        side_effect=LevitonConnectionError("Panel error")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)

    await coordinator._discover_devices()

    # Panels should be missing, but WHEMs still found
    assert len(coordinator.data.panels) == 0
    assert MOCK_WHEM.id in coordinator.data.whems


async def test_ws_notification_whem_breaker_update(hass, mock_client) -> None:
    """Test WebSocket notification updates breaker data via WHEM parent."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
        breakers={MOCK_BREAKER_GEN1.id: deepcopy(MOCK_BREAKER_GEN1)},
        cts={MOCK_CT.id: deepcopy(MOCK_CT)},
    )

    notification = {
        "modelName": "IotWhem",
        "modelId": MOCK_WHEM.id,
        "data": {
            "ResidentialBreaker": [
                {"id": MOCK_BREAKER_GEN1.id, "power": 500}
            ],
        },
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.breakers[MOCK_BREAKER_GEN1.id].power == 500


async def test_ws_notification_whem_ct_update(hass, mock_client) -> None:
    """Test WebSocket notification updates CT data via WHEM parent."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
        cts={MOCK_CT.id: deepcopy(MOCK_CT)},
    )

    notification = {
        "modelName": "IotWhem",
        "modelId": MOCK_WHEM.id,
        "data": {
            "IotCt": [
                {"id": MOCK_CT.id, "activePower": 999}
            ],
        },
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.cts[MOCK_CT.id].active_power == 999


async def test_ws_notification_whem_own_update(hass, mock_client) -> None:
    """Test WebSocket notification updates WHEM own properties."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
    )

    notification = {
        "modelName": "IotWhem",
        "modelId": MOCK_WHEM.id,
        "data": {"rmsVoltageA": 121, "connected": False},
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.whems[MOCK_WHEM.id].rms_voltage_a == 121
    assert coordinator.data.whems[MOCK_WHEM.id].connected is False


async def test_ws_notification_panel_breaker_update(hass, mock_client) -> None:
    """Test WebSocket notification updates breaker data via panel parent."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        panels={MOCK_PANEL.id: deepcopy(MOCK_PANEL)},
        breakers={MOCK_BREAKER_GEN2.id: deepcopy(MOCK_BREAKER_GEN2)},
    )

    notification = {
        "modelName": "ResidentialBreakerPanel",
        "modelId": MOCK_PANEL.id,
        "data": {
            "ResidentialBreaker": [
                {"id": MOCK_BREAKER_GEN2.id, "power": 300}
            ],
        },
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.breakers[MOCK_BREAKER_GEN2.id].power == 300


async def test_ws_notification_panel_own_update(hass, mock_client) -> None:
    """Test WebSocket notification updates panel own properties."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        panels={MOCK_PANEL.id: deepcopy(MOCK_PANEL)},
    )

    notification = {
        "modelName": "ResidentialBreakerPanel",
        "modelId": MOCK_PANEL.id,
        "data": {"rmsVoltage": 118},
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.panels[MOCK_PANEL.id].rms_voltage == 118


async def test_ws_notification_direct_breaker_update(hass, mock_client) -> None:
    """Test WebSocket notification for a direct breaker update."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        breakers={MOCK_BREAKER_GEN1.id: deepcopy(MOCK_BREAKER_GEN1)},
    )

    notification = {
        "modelName": "ResidentialBreaker",
        "modelId": MOCK_BREAKER_GEN1.id,
        "data": {"currentState": "Tripped"},
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.breakers[MOCK_BREAKER_GEN1.id].current_state == "Tripped"


async def test_ws_notification_direct_ct_update(hass, mock_client) -> None:
    """Test WebSocket notification for a direct CT update."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        cts={MOCK_CT.id: deepcopy(MOCK_CT)},
    )

    notification = {
        "modelName": "IotCt",
        "modelId": MOCK_CT.id,
        "data": {"activePower": 250},
    }

    coordinator._handle_ws_notification(notification)

    assert coordinator.data.cts[MOCK_CT.id].active_power == 250


async def test_ws_notification_unknown_model_ignored(hass, mock_client) -> None:
    """Test that unknown model names don't cause errors."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()

    notification = {
        "modelName": "UnknownModel",
        "modelId": "abc123",
        "data": {"foo": "bar"},
    }

    # Should not raise
    coordinator._handle_ws_notification(notification)


async def test_ws_notification_empty_data_ignored(hass, mock_client) -> None:
    """Test that notifications with empty data are ignored."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()

    notification = {
        "modelName": "IotWhem",
        "modelId": MOCK_WHEM.id,
        "data": {},
    }

    coordinator._handle_ws_notification(notification)


async def test_ws_disconnect_handler(hass, mock_client) -> None:
    """Test WebSocket disconnect handler clears ws reference."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.ws = MagicMock()

    coordinator._handle_ws_disconnect()

    assert coordinator.ws is None


async def test_async_update_data_auth_error(hass, mock_client) -> None:
    """Test REST fallback raises ConfigEntryAuthFailed on auth error."""
    mock_client.get_whem = AsyncMock(
        side_effect=LevitonAuthError("Token expired")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
    )
    coordinator._residence_ids = [MOCK_RESIDENCE.id]

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_async_update_data_connection_error(hass, mock_client) -> None:
    """Test REST fallback raises UpdateFailed on connection error."""
    mock_client.get_whem = AsyncMock(
        side_effect=LevitonConnectionError("Network error")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
    )
    coordinator._residence_ids = [MOCK_RESIDENCE.id]

    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()


async def test_async_shutdown_disconnects_ws(hass, mock_client) -> None:
    """Test shutdown disconnects WebSocket and disables bandwidth."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        panels={MOCK_PANEL.id: deepcopy(MOCK_PANEL)},
    )

    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws = mock_ws

    mock_remove_notif = MagicMock()
    mock_remove_disc = MagicMock()
    coordinator._ws_remove_notification = mock_remove_notif
    coordinator._ws_remove_disconnect = mock_remove_disc

    await coordinator.async_shutdown()

    mock_remove_notif.assert_called_once()
    mock_remove_disc.assert_called_once()
    mock_client.set_panel_bandwidth.assert_called_once_with(
        MOCK_PANEL.id, enabled=False
    )
    mock_ws.disconnect.assert_called_once()
    assert coordinator.ws is None


async def test_async_shutdown_no_ws(hass, mock_client) -> None:
    """Test shutdown handles case when no WebSocket exists."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()

    # Should not raise
    await coordinator.async_shutdown()


# --- Firmware update check tests ---


async def test_check_firmware_updates_whem_update_available(
    hass, mock_client
) -> None:
    """Test firmware check creates repair issue when WHEM update available."""
    from copy import deepcopy

    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    whem = deepcopy(MOCK_WHEM)
    whem.version = "1.7.6"
    whem.raw = {"downloaded": "2.0.13"}
    coordinator.data = LevitonData(whems={whem.id: whem})

    with patch(
        "homeassistant.components.leviton.coordinator.ir"
    ) as mock_ir:
        coordinator._check_firmware_updates()
        mock_ir.async_create_issue.assert_called_once()
        call_kwargs = mock_ir.async_create_issue.call_args
        assert call_kwargs[1]["translation_key"] == "firmware_update_available"


async def test_check_firmware_updates_whem_up_to_date(
    hass, mock_client
) -> None:
    """Test firmware check deletes repair issue when WHEM is up to date."""
    from copy import deepcopy

    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    whem = deepcopy(MOCK_WHEM)
    whem.version = "2.0.13"
    whem.raw = {"downloaded": "2.0.13"}
    coordinator.data = LevitonData(whems={whem.id: whem})

    with patch(
        "homeassistant.components.leviton.coordinator.ir"
    ) as mock_ir:
        coordinator._check_firmware_updates()
        mock_ir.async_delete_issue.assert_called_once()


async def test_check_firmware_updates_panel_update_available(
    hass, mock_client
) -> None:
    """Test firmware check creates repair issue when panel update available."""
    from copy import deepcopy

    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    panel = deepcopy(MOCK_PANEL)
    panel.raw = {"updateAvailability": "AVAILABLE", "updateVersion": "0.2.0"}
    coordinator.data = LevitonData(panels={panel.id: panel})

    with patch(
        "homeassistant.components.leviton.coordinator.ir"
    ) as mock_ir:
        coordinator._check_firmware_updates()
        mock_ir.async_create_issue.assert_called_once()
        call_kwargs = mock_ir.async_create_issue.call_args
        assert call_kwargs[1]["translation_key"] == "firmware_update_available"


async def test_check_firmware_updates_panel_up_to_date(
    hass, mock_client
) -> None:
    """Test firmware check deletes repair issue when panel is up to date."""
    from copy import deepcopy

    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    panel = deepcopy(MOCK_PANEL)
    panel.raw = {"updateAvailability": "UP_TO_DATE"}
    coordinator.data = LevitonData(panels={panel.id: panel})

    with patch(
        "homeassistant.components.leviton.coordinator.ir"
    ) as mock_ir:
        coordinator._check_firmware_updates()
        mock_ir.async_delete_issue.assert_called_once()


# --- Needs individual breaker subs tests ---


def test_needs_individual_breaker_subs_fw_2x() -> None:
    """Test FW 2.0.13 needs individual breaker subscriptions."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = "2.0.13"
    assert LevitonCoordinator._needs_individual_breaker_subs(whem) is True


def test_needs_individual_breaker_subs_fw_1x() -> None:
    """Test FW 1.7.6 does not need individual breaker subscriptions."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = "1.7.6"
    assert LevitonCoordinator._needs_individual_breaker_subs(whem) is False


def test_needs_individual_breaker_subs_fw_none() -> None:
    """Test None FW assumes newest (needs individual subs)."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = None
    assert LevitonCoordinator._needs_individual_breaker_subs(whem) is True


def test_needs_individual_breaker_subs_fw_unparseable() -> None:
    """Test unparseable FW assumes newest (needs individual subs)."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = "invalid"
    assert LevitonCoordinator._needs_individual_breaker_subs(whem) is True


# --- REST poll skip test ---


async def test_async_update_data_ws_connected_skips_poll(
    hass, mock_client
) -> None:
    """Test REST fallback returns cached data when WS is connected."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
    )
    coordinator.ws = MagicMock()  # WS is connected

    result = await coordinator._async_update_data()

    assert result is coordinator.data
    mock_client.get_whem.assert_not_called()


# --- calc_daily_energy tests ---


def test_calc_daily_energy_normal() -> None:
    """Test daily energy calculation (lifetime - baseline) rounded."""
    data = LevitonData(daily_baselines={"breaker_1": 100.0})
    result = LevitonCoordinator.calc_daily_energy("breaker_1", 150.123, data)
    assert result == 50.12


def test_calc_daily_energy_none_inputs() -> None:
    """Test daily energy returns None for None lifetime or missing baseline."""
    data = LevitonData(daily_baselines={"breaker_1": 100.0})
    # None lifetime
    assert LevitonCoordinator.calc_daily_energy("breaker_1", None, data) is None
    # Missing baseline
    assert LevitonCoordinator.calc_daily_energy("breaker_2", 150.0, data) is None


async def test_async_update_data_rest_poll_refreshes(hass, mock_client) -> None:
    """Test REST fallback actually refreshes device data when WS is disconnected."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    whem = deepcopy(MOCK_WHEM)
    panel = deepcopy(MOCK_PANEL)
    coordinator.data = LevitonData(
        whems={whem.id: whem},
        panels={panel.id: panel},
        breakers={MOCK_BREAKER_GEN1.id: deepcopy(MOCK_BREAKER_GEN1)},
        cts={MOCK_CT.id: deepcopy(MOCK_CT)},
    )
    coordinator.ws = None  # WS is disconnected
    coordinator._residence_ids = [MOCK_RESIDENCE.id]

    # Set up fresh return values to verify data gets replaced
    fresh_whem = deepcopy(MOCK_WHEM)
    fresh_whem.rms_voltage_a = 121
    mock_client.get_whem = AsyncMock(return_value=fresh_whem)
    mock_client.get_whem_breakers = AsyncMock(return_value=[deepcopy(MOCK_BREAKER_GEN1)])
    mock_client.get_cts = AsyncMock(return_value=[deepcopy(MOCK_CT)])

    fresh_panel = deepcopy(MOCK_PANEL)
    fresh_panel.rms_voltage = 119
    mock_client.get_panel = AsyncMock(return_value=fresh_panel)
    mock_client.get_panel_breakers = AsyncMock(return_value=[deepcopy(MOCK_BREAKER_GEN2)])

    result = await coordinator._async_update_data()

    # Verify REST calls were made
    mock_client.get_whem.assert_called_once_with(whem.id)
    mock_client.get_panel.assert_called_once_with(panel.id)
    # Verify data was updated
    assert result.whems[whem.id].rms_voltage_a == 121
    assert result.panels[panel.id].rms_voltage == 119


async def test_discover_devices_breaker_fetch_failure(hass, mock_client) -> None:
    """Test graceful handling of breaker fetch failure within WHEM."""
    mock_client.get_whem_breakers = AsyncMock(
        side_effect=LevitonConnectionError("Breaker fetch failed")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)

    await coordinator._discover_devices()

    # WHEM itself should be found, but breakers from WHEM should be empty
    assert MOCK_WHEM.id in coordinator.data.whems
    # Only panel breakers should be present (panel breaker fetch still works)
    whem_breakers = [
        b for b in coordinator.data.breakers.values()
        if b.iot_whem_id == MOCK_WHEM.id
    ]
    assert len(whem_breakers) == 0
