"""Tests for the Leviton coordinator."""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aioleviton import LevitonAuthError, LevitonConnectionError

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from homeassistant.components.leviton_load_center.const import STATE_SOFTWARE_TRIP
from homeassistant.components.leviton_load_center.coordinator import (
    LevitonCoordinator,
    LevitonData,
)
from homeassistant.components.leviton_load_center.energy import (
    EnergyTracker,
    normalize_breaker_energy,
    normalize_ct_energy,
    calc_daily_energy,
)
from homeassistant.components.leviton_load_center.websocket import (
    needs_individual_breaker_subs,
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
    assert str(MOCK_CT.id) in coordinator.data.cts
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
        cts={str(MOCK_CT.id): deepcopy(MOCK_CT)},
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

    coordinator.ws_manager._handle_ws_notification(notification)

    assert coordinator.data.breakers[MOCK_BREAKER_GEN1.id].power == 500


async def test_ws_notification_whem_ct_update(hass, mock_client) -> None:
    """Test WebSocket notification updates CT data via WHEM parent."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
        cts={str(MOCK_CT.id): deepcopy(MOCK_CT)},
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

    coordinator.ws_manager._handle_ws_notification(notification)

    assert coordinator.data.cts[str(MOCK_CT.id)].active_power == 999


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

    coordinator.ws_manager._handle_ws_notification(notification)

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

    coordinator.ws_manager._handle_ws_notification(notification)

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

    coordinator.ws_manager._handle_ws_notification(notification)

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

    coordinator.ws_manager._handle_ws_notification(notification)

    assert coordinator.data.breakers[MOCK_BREAKER_GEN1.id].current_state == "Tripped"


async def test_ws_notification_direct_ct_update(hass, mock_client) -> None:
    """Test WebSocket notification for a direct CT update."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        cts={str(MOCK_CT.id): deepcopy(MOCK_CT)},
    )

    notification = {
        "modelName": "IotCt",
        "modelId": MOCK_CT.id,
        "data": {"activePower": 250},
    }

    coordinator.ws_manager._handle_ws_notification(notification)

    assert coordinator.data.cts[str(MOCK_CT.id)].active_power == 250


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
    coordinator.ws_manager._handle_ws_notification(notification)


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

    coordinator.ws_manager._handle_ws_notification(notification)


async def test_ws_disconnect_handler(hass, mock_client) -> None:
    """Test WebSocket disconnect handler clears ws and callback references."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.ws_manager.ws = MagicMock()
    coordinator.ws_manager._ws_remove_notification = MagicMock()
    coordinator.ws_manager._ws_remove_disconnect = MagicMock()

    coordinator.ws_manager._handle_ws_disconnect()

    assert coordinator.ws_manager.ws is None
    assert coordinator.ws_manager._ws_remove_notification is None
    assert coordinator.ws_manager._ws_remove_disconnect is None
    # Close the coroutine created by _handle_ws_disconnect to avoid
    # "coroutine was never awaited" warning during GC.
    coro = entry.async_create_background_task.call_args[0][1]
    coro.close()


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
    coordinator.ws_manager.ws = mock_ws

    mock_remove_notif = MagicMock()
    mock_remove_disc = MagicMock()
    coordinator.ws_manager._ws_remove_notification = mock_remove_notif
    coordinator.ws_manager._ws_remove_disconnect = mock_remove_disc

    await coordinator.async_shutdown()

    mock_remove_notif.assert_called_once()
    mock_remove_disc.assert_called_once()
    mock_client.set_panel_bandwidth.assert_called_once_with(
        MOCK_PANEL.id, enabled=False
    )
    mock_ws.disconnect.assert_called_once()
    assert coordinator.ws_manager.ws is None
    # Remove functions are nulled out so a second call is safe
    assert coordinator.ws_manager._ws_remove_notification is None
    assert coordinator.ws_manager._ws_remove_disconnect is None


async def test_async_shutdown_idempotent(hass, mock_client) -> None:
    """Test shutdown can be called twice without error (HA auto-calls it)."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        panels={MOCK_PANEL.id: deepcopy(MOCK_PANEL)},
    )

    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws_manager.ws = mock_ws
    coordinator.ws_manager._ws_remove_notification = MagicMock()
    coordinator.ws_manager._ws_remove_disconnect = MagicMock()

    await coordinator.async_shutdown()
    # Second call must not raise
    await coordinator.async_shutdown()


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
        "homeassistant.components.leviton_load_center.coordinator.ir"
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
        "homeassistant.components.leviton_load_center.coordinator.ir"
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
        "homeassistant.components.leviton_load_center.coordinator.ir"
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
        "homeassistant.components.leviton_load_center.coordinator.ir"
    ) as mock_ir:
        coordinator._check_firmware_updates()
        mock_ir.async_delete_issue.assert_called_once()


# --- Needs individual breaker subs tests ---


def test_needs_individual_breaker_subs_fw_2x() -> None:
    """Test FW 2.0.13 needs individual breaker subscriptions."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = "2.0.13"
    assert needs_individual_breaker_subs(whem) is True


def test_needs_individual_breaker_subs_fw_1x() -> None:
    """Test FW 1.7.6 does not need individual breaker subscriptions."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = "1.7.6"
    assert needs_individual_breaker_subs(whem) is False


def test_needs_individual_breaker_subs_fw_none() -> None:
    """Test None FW assumes newest (needs individual subs)."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = None
    assert needs_individual_breaker_subs(whem) is True


def test_needs_individual_breaker_subs_fw_unparseable() -> None:
    """Test unparseable FW assumes newest (needs individual subs)."""
    from copy import deepcopy

    whem = deepcopy(MOCK_WHEM)
    whem.version = "invalid"
    assert needs_individual_breaker_subs(whem) is True


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
    coordinator.ws_manager.ws = MagicMock()  # WS is connected

    result = await coordinator._async_update_data()

    assert result is coordinator.data
    mock_client.get_whem.assert_not_called()


async def test_async_update_data_ws_connected_polls_panels(
    hass, mock_client
) -> None:
    """Test REST poll refreshes LDATA panels even when WS is connected."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    panel = deepcopy(MOCK_PANEL)
    whem = deepcopy(MOCK_WHEM)
    coordinator.data = LevitonData(
        whems={whem.id: whem},
        panels={panel.id: panel},
        breakers={MOCK_BREAKER_GEN2.id: deepcopy(MOCK_BREAKER_GEN2)},
    )
    coordinator.ws_manager.ws = MagicMock()  # WS is connected

    fresh_panel = deepcopy(MOCK_PANEL)
    mock_client.get_panel = AsyncMock(return_value=fresh_panel)
    mock_client.get_panel_breakers = AsyncMock(
        return_value=[deepcopy(MOCK_BREAKER_GEN2)]
    )

    result = await coordinator._async_update_data()

    # LDATA panels are polled even with WS up
    mock_client.get_panel.assert_called_once_with(panel.id)
    mock_client.get_panel_breakers.assert_called_once_with(panel.id)
    # WHEMs are NOT polled when WS is connected
    mock_client.get_whem.assert_not_called()
    mock_client.get_whem_breakers.assert_not_called()
    assert result is coordinator.data


async def test_ws_watchdog_forces_reconnect_on_silence(
    hass, mock_client
) -> None:
    """Test watchdog forces reconnect when WS is silent for 90+ seconds."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()
    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws_manager.ws = mock_ws
    # Simulate last notification >90s ago
    coordinator.ws_manager._last_ws_notification = time.monotonic() - 120

    await coordinator.ws_manager._async_ws_watchdog(None)

    # Stale WS was disconnected
    mock_ws.disconnect.assert_called_once()
    assert coordinator.ws_manager.ws is None
    # Reconnection was triggered
    entry.async_create_background_task.assert_called_once()
    # Close the leaked coroutine
    coro = entry.async_create_background_task.call_args[0][1]
    coro.close()


async def test_ws_watchdog_no_action_when_fresh(
    hass, mock_client
) -> None:
    """Test watchdog does nothing when WS data is recent."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()
    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws_manager.ws = mock_ws
    # Recent notification
    coordinator.ws_manager._last_ws_notification = time.monotonic() - 10

    await coordinator.ws_manager._async_ws_watchdog(None)

    # WS was not touched
    mock_ws.disconnect.assert_not_called()
    assert coordinator.ws_manager.ws is mock_ws


# --- calc_daily_energy tests ---


def test_calc_daily_energy_normal() -> None:
    """Test daily energy calculation (lifetime - baseline) rounded."""
    data = LevitonData(daily_baselines={"breaker_1": 100.0})
    result = calc_daily_energy("breaker_1", 150.123, data)
    assert result == 50.12


def test_calc_daily_energy_none_inputs() -> None:
    """Test daily energy returns None for None lifetime or missing baseline."""
    data = LevitonData(daily_baselines={"breaker_1": 100.0})
    # None lifetime
    assert calc_daily_energy("breaker_1", None, data) is None
    # Missing baseline
    assert calc_daily_energy("breaker_2", 150.0, data) is None


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
        cts={str(MOCK_CT.id): deepcopy(MOCK_CT)},
    )
    coordinator.ws_manager.ws = None  # WS is disconnected
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


# --- Energy accumulation tests ---


def test_normalize_breaker_energy_discards_delta() -> None:
    """Test WS energy deltas are discarded to avoid double-counting."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 3400.0
    breaker.energy_consumption_2 = 100.0
    breaker.energy_import = 50.0

    ws_data = {
        "id": breaker.id,
        "energyConsumption": 0.5,
        "energyConsumption2": 0.1,
        "energyImport": 0.02,
        "power": 120,
    }

    normalize_breaker_energy(ws_data, breaker)

    # Small deltas removed — server's next lifetime update includes them
    assert "energyConsumption" not in ws_data
    assert "energyConsumption2" not in ws_data
    assert "energyImport" not in ws_data
    # Non-energy fields should be unchanged
    assert ws_data["power"] == 120


def test_normalize_breaker_energy_none_current() -> None:
    """Test accumulation when current energy is None (treats as 0)."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = None

    ws_data = {"energyConsumption": 0.5}

    normalize_breaker_energy(ws_data, breaker)

    assert ws_data["energyConsumption"] == 0.5


def test_normalize_breaker_energy_no_energy_fields() -> None:
    """Test accumulation with no energy fields in WS data is a no-op."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    original_energy = breaker.energy_consumption

    ws_data = {"power": 120, "rmsCurrent": 1}

    normalize_breaker_energy(ws_data, breaker)

    # No energy fields modified
    assert "energyConsumption" not in ws_data
    assert breaker.energy_consumption == original_energy


def test_normalize_breaker_energy_lifetime_passthrough() -> None:
    """Test WS value larger than current is treated as lifetime, not delta."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 3400.0

    ws_data = {"energyConsumption": 3400.5}

    normalize_breaker_energy(ws_data, breaker)

    # Value exceeds current — left as-is (lifetime replacement)
    assert ws_data["energyConsumption"] == 3400.5


def test_accumulate_lifetime_tracks_server_when_current_higher() -> None:
    """Test lifetime mode uses server value even when our rounded value is higher.

    After delta accumulation, round() can inflate our value slightly above
    the server's actual lifetime. The lifetime branch must use the server
    value directly (not max) so energy tracking doesn't stall.
    """
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 3427.55  # our rounded value

    # Server lifetime is 3427.546 — slightly lower than our rounded value
    ws_data = {"energyConsumption": 3427.546}

    normalize_breaker_energy(ws_data, breaker)

    # Should follow the server value, not stay stuck at 3427.55
    assert ws_data["energyConsumption"] == 3427.546


def test_normalize_ct_energy_lifetime_passthrough() -> None:
    """Test WS CT value larger than current is treated as lifetime."""
    ct = deepcopy(MOCK_CT)
    ct.energy_consumption = 5000.0

    ws_data = {"energyConsumption": 5001.0}

    normalize_ct_energy(ws_data, ct)

    assert ws_data["energyConsumption"] == 5001.0


def test_normalize_ct_energy_discards_delta() -> None:
    """Test WS CT energy deltas are discarded to avoid double-counting."""
    ct = deepcopy(MOCK_CT)
    ct.energy_consumption = 5000.0
    ct.energy_consumption_2 = 4500.0
    ct.energy_import = 100.0
    ct.energy_import_2 = 90.0

    ws_data = {
        "energyConsumption": 1.0,
        "energyConsumption2": 0.5,
        "energyImport": 0.1,
        "energyImport2": 0.05,
    }

    normalize_ct_energy(ws_data, ct)

    # All small deltas removed
    assert "energyConsumption" not in ws_data
    assert "energyConsumption2" not in ws_data
    assert "energyImport" not in ws_data
    assert "energyImport2" not in ws_data


def test_ws_breaker_energy_delta_discarded_via_whem(hass, mock_client) -> None:
    """Test WS breaker energy deltas are discarded via IotWhem handler."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 3400.0
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
        breakers={breaker.id: breaker},
    )

    notification = {
        "modelName": "IotWhem",
        "modelId": MOCK_WHEM.id,
        "data": {
            "ResidentialBreaker": [
                {"id": breaker.id, "energyConsumption": 0.25}
            ],
        },
    }

    coordinator.ws_manager._handle_ws_notification(notification)

    # Delta discarded — energy unchanged
    assert coordinator.data.breakers[breaker.id].energy_consumption == 3400.0


def test_ws_breaker_energy_lifetime_applied_direct(hass, mock_client) -> None:
    """Test WS breaker lifetime values are applied via direct handler."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.energy_consumption = 1500.0
    coordinator.data = LevitonData(
        breakers={breaker.id: breaker},
    )

    notification = {
        "modelName": "ResidentialBreaker",
        "modelId": breaker.id,
        "data": {"energyConsumption": 1500.5},
    }

    coordinator.ws_manager._handle_ws_notification(notification)

    # Lifetime value applied directly
    assert coordinator.data.breakers[breaker.id].energy_consumption == 1500.5


def test_ws_ct_energy_delta_discarded(hass, mock_client) -> None:
    """Test WS CT energy deltas are discarded."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    ct = deepcopy(MOCK_CT)
    ct.energy_consumption = 5000.0
    coordinator.data = LevitonData(
        cts={str(ct.id): ct},
    )

    notification = {
        "modelName": "IotCt",
        "modelId": ct.id,
        "data": {"energyConsumption": 0.5},
    }

    coordinator.ws_manager._handle_ws_notification(notification)

    # Delta discarded — energy unchanged
    assert coordinator.data.cts[str(ct.id)].energy_consumption == 5000.0


async def test_correct_energy_values_detects_deltas(hass, mock_client) -> None:
    """Test energy correction detects REST deltas and corrects them."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 0.25  # REST returned a delta
    coordinator.data = LevitonData(
        breakers={breaker.id: breaker},
    )

    # Simulate cached lifetime from previous session
    coordinator.energy._lifetime_store = MagicMock()
    coordinator.energy._lifetime_store.async_load = AsyncMock(
        return_value={breaker.id: 3400.0}
    )
    coordinator.energy._lifetime_store.async_save = AsyncMock()

    await coordinator.energy.correct_energy_values(coordinator.data)

    # Should be corrected: cached + delta
    assert coordinator.data.breakers[breaker.id].energy_consumption == 3400.25
    coordinator.energy._lifetime_store.async_save.assert_called_once()


async def test_correct_energy_values_lifetime_passthrough(hass, mock_client) -> None:
    """Test energy correction passes through actual lifetime values."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 3410.0  # REST returned lifetime
    coordinator.data = LevitonData(
        breakers={breaker.id: breaker},
    )

    # Cached value is lower (previous session)
    coordinator.energy._lifetime_store = MagicMock()
    coordinator.energy._lifetime_store.async_load = AsyncMock(
        return_value={breaker.id: 3400.0}
    )
    coordinator.energy._lifetime_store.async_save = AsyncMock()

    await coordinator.energy.correct_energy_values(coordinator.data)

    # Should be unchanged (REST value is lifetime, not delta)
    assert coordinator.data.breakers[breaker.id].energy_consumption == 3410.0


async def test_correct_energy_values_first_run(hass, mock_client) -> None:
    """Test energy correction on first run with no cached values."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.energy_consumption = 3400.0
    coordinator.data = LevitonData(
        breakers={breaker.id: breaker},
    )

    # No cached values
    coordinator.energy._lifetime_store = MagicMock()
    coordinator.energy._lifetime_store.async_load = AsyncMock(return_value=None)
    coordinator.energy._lifetime_store.async_save = AsyncMock()

    await coordinator.energy.correct_energy_values(coordinator.data)

    # Should be unchanged, and value cached
    assert coordinator.data.breakers[breaker.id].energy_consumption == 3400.0
    coordinator.energy._lifetime_store.async_save.assert_called_once()


async def test_async_setup_full_flow(
    hass, mock_client, mock_websocket, mock_config_entry
) -> None:
    """Test the full _async_setup flow exercises all setup steps end-to-end.

    Verifies that async_config_entry_first_refresh calls _discover_devices,
    _correct_energy_values, _connect_websocket, _load_daily_baselines,
    _check_firmware_updates, and registers the midnight handler.
    """
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # 1. Discovery populated all device types
    assert MOCK_WHEM.id in coordinator.data.whems
    assert MOCK_PANEL.id in coordinator.data.panels
    assert MOCK_BREAKER_GEN1.id in coordinator.data.breakers
    assert MOCK_BREAKER_GEN2.id in coordinator.data.breakers
    assert str(MOCK_CT.id) in coordinator.data.cts
    assert MOCK_RESIDENCE.id in coordinator.data.residences

    # 2. WebSocket connected and subscribed
    assert coordinator.ws_manager.ws is not None
    mock_websocket.connect.assert_called_once()
    # Subscribed to WHEM + panel at minimum
    assert mock_websocket.subscribe.call_count >= 2
    # Bandwidth reset (discovery) then 1→0→1 toggle (WS connect)
    assert mock_client.set_whem_bandwidth.call_count == 4
    mock_client.set_whem_bandwidth.assert_any_call(MOCK_WHEM.id, bandwidth=0)
    mock_client.set_whem_bandwidth.assert_any_call(MOCK_WHEM.id, bandwidth=1)
    assert mock_client.set_panel_bandwidth.call_count == 2
    mock_client.set_panel_bandwidth.assert_any_call(MOCK_PANEL.id, enabled=False)
    mock_client.set_panel_bandwidth.assert_any_call(MOCK_PANEL.id, enabled=True)

    # 3. Daily baselines snapshotted (first run, no stored data)
    assert len(coordinator.data.daily_baselines) > 0
    assert MOCK_BREAKER_GEN1.id in coordinator.data.daily_baselines
    assert MOCK_BREAKER_GEN2.id in coordinator.data.daily_baselines
    assert f"ct_{MOCK_CT.id}" in coordinator.data.daily_baselines

    # 4. Midnight handler registered
    assert coordinator._midnight_unsub is not None


async def test_async_setup_ws_failure_degrades_gracefully(
    hass, mock_config_entry
) -> None:
    """Test that WebSocket connection failure doesn't prevent setup."""
    with patch(
        "homeassistant.components.leviton_load_center.LevitonClient",
        autospec=True,
    ) as mock_cls:
        client = mock_cls.return_value
        client.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)
        client.token = MOCK_TOKEN
        client.user_id = MOCK_USER_ID
        client._auth_token = MOCK_AUTH_TOKEN
        client._session = MagicMock()
        client.get_permissions = AsyncMock(return_value=[MOCK_PERMISSION])
        client.get_residences = AsyncMock(return_value=[MOCK_RESIDENCE])
        client.get_whems = AsyncMock(return_value=[MOCK_WHEM])
        client.get_whem = AsyncMock(return_value=MOCK_WHEM)
        client.get_panels = AsyncMock(return_value=[MOCK_PANEL])
        client.get_panel = AsyncMock(return_value=MOCK_PANEL)
        client.get_whem_breakers = AsyncMock(
            return_value=[MOCK_BREAKER_GEN1, MOCK_BREAKER_GEN2]
        )
        client.get_panel_breakers = AsyncMock(return_value=[])
        client.get_cts = AsyncMock(return_value=[MOCK_CT])
        client.set_whem_bandwidth = AsyncMock()
        client.set_panel_bandwidth = AsyncMock()

        # WS connect fails
        mock_ws = MagicMock()
        mock_ws.connect = AsyncMock(
            side_effect=LevitonConnectionError("WS connect failed")
        )
        client.create_websocket = MagicMock(return_value=mock_ws)

        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data.coordinator

    # Setup succeeded despite WS failure
    assert MOCK_WHEM.id in coordinator.data.whems
    assert coordinator.ws_manager.ws is None  # WS not available
    assert len(coordinator.data.daily_baselines) > 0  # baselines still set


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


# --- clamp_increasing tests ---


def test_clamp_increasing_normal(hass) -> None:
    """Test clamp_increasing passes through increasing values."""
    tracker = EnergyTracker(hass, "test_entry")
    assert tracker.clamp_increasing("key1", 100.0) == 100.0
    assert tracker.clamp_increasing("key1", 100.5) == 100.5
    assert tracker.clamp_increasing("key1", 200.0) == 200.0


def test_clamp_increasing_clamps_decrease(hass) -> None:
    """Test clamp_increasing clamps a decreasing value to high-water mark."""
    tracker = EnergyTracker(hass, "test_entry")
    tracker.clamp_increasing("key1", 100.0)
    # Value drops — should clamp to 100.0
    assert tracker.clamp_increasing("key1", 99.999) == 100.0
    assert tracker.clamp_increasing("key1", 50.0) == 100.0
    # But a new high is passed through
    assert tracker.clamp_increasing("key1", 100.001) == 100.001


def test_clamp_increasing_independent_keys(hass) -> None:
    """Test clamp_increasing tracks keys independently."""
    tracker = EnergyTracker(hass, "test_entry")
    tracker.clamp_increasing("a", 100.0)
    tracker.clamp_increasing("b", 200.0)
    assert tracker.clamp_increasing("a", 50.0) == 100.0
    assert tracker.clamp_increasing("b", 50.0) == 200.0


# --- handle_midnight test ---


async def test_handle_midnight(hass) -> None:
    """Test midnight handler snapshots baselines and saves."""
    tracker = EnergyTracker(hass, "test_entry")
    tracker._baseline_store = MagicMock()
    tracker._baseline_store.async_save = AsyncMock()
    tracker._lifetime_store = MagicMock()
    tracker._lifetime_store.async_save = AsyncMock()

    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(
        breakers={breaker.id: breaker},
    )

    await tracker.handle_midnight(data)

    # Baseline snapshotted
    assert breaker.id in data.daily_baselines
    # Both stores saved
    tracker._baseline_store.async_save.assert_called_once()
    saved_data = tracker._baseline_store.async_save.call_args[0][0]
    assert "date" in saved_data
    assert "baselines" in saved_data
    assert breaker.id in saved_data["baselines"]
    tracker._lifetime_store.async_save.assert_called_once()


async def test_load_baselines_same_day(hass) -> None:
    """Test loading baselines from storage when date matches today."""
    from homeassistant.util import dt as dt_util

    tracker = EnergyTracker(hass, "test_entry")
    tracker._baseline_store = MagicMock()

    today = dt_util.now().date().isoformat()
    stored = {"date": today, "baselines": {"breaker1": 100.0}}
    tracker._baseline_store.async_load = AsyncMock(return_value=stored)
    tracker._baseline_store.async_save = AsyncMock()

    data = LevitonData()
    await tracker.load_daily_baselines(data)

    assert data.daily_baselines == {"breaker1": 100.0}
    tracker._baseline_store.async_save.assert_not_called()


async def test_load_baselines_stale_date(hass) -> None:
    """Test re-snapshotting when stored baselines are from a previous day."""
    from homeassistant.util import dt as dt_util

    tracker = EnergyTracker(hass, "test_entry")
    tracker._baseline_store = MagicMock()

    stored = {"date": "2026-01-01", "baselines": {"breaker1": 100.0}}
    tracker._baseline_store.async_load = AsyncMock(return_value=stored)
    tracker._baseline_store.async_save = AsyncMock()

    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(breakers={breaker.id: breaker})
    await tracker.load_daily_baselines(data)

    # Should have re-snapshotted with current lifetime values
    assert breaker.id in data.daily_baselines
    tracker._baseline_store.async_save.assert_called_once()
    saved_data = tracker._baseline_store.async_save.call_args[0][0]
    assert saved_data["date"] == dt_util.now().date().isoformat()
    assert breaker.id in saved_data["baselines"]


async def test_load_baselines_no_stored(hass) -> None:
    """Test fresh snapshot when no baselines exist in storage."""
    tracker = EnergyTracker(hass, "test_entry")
    tracker._baseline_store = MagicMock()
    tracker._baseline_store.async_load = AsyncMock(return_value=None)
    tracker._baseline_store.async_save = AsyncMock()

    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(breakers={breaker.id: breaker})
    await tracker.load_daily_baselines(data)

    assert breaker.id in data.daily_baselines
    tracker._baseline_store.async_save.assert_called_once()
    saved_data = tracker._baseline_store.async_save.call_args[0][0]
    assert "date" in saved_data
    assert "baselines" in saved_data


# --- _async_ws_refresh test ---


async def test_ws_refresh_reconnects(hass, mock_client) -> None:
    """Test WS refresh disconnects and reconnects."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
    )
    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws_manager.ws = mock_ws
    coordinator.ws_manager._ws_remove_disconnect = MagicMock()
    coordinator.ws_manager._ws_remove_notification = MagicMock()

    await coordinator.ws_manager._async_ws_refresh(None)

    # Old WS was disconnected
    mock_ws.disconnect.assert_called_once()
    # New WS connect was attempted
    mock_client.create_websocket.assert_called()


async def test_ws_refresh_noop_when_disconnected(hass, mock_client) -> None:
    """Test WS refresh does nothing when already disconnected."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()
    coordinator.ws_manager.ws = None

    await coordinator.ws_manager._async_ws_refresh(None)

    # No WS operations attempted
    mock_client.create_websocket.assert_not_called()


# --- _async_bandwidth_keepalive test ---


async def test_bandwidth_keepalive_toggles(hass, mock_client) -> None:
    """Test bandwidth keepalive toggles 1->0->1 for each WHEM."""
    from unittest.mock import call

    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    whem = deepcopy(MOCK_WHEM)
    coordinator.data = LevitonData(whems={whem.id: whem})
    coordinator.ws_manager.ws = MagicMock()

    await coordinator.ws_manager._async_bandwidth_keepalive(None)

    assert mock_client.set_whem_bandwidth.call_args_list == [
        call(whem.id, bandwidth=1),
        call(whem.id, bandwidth=0),
        call(whem.id, bandwidth=1),
    ]


async def test_bandwidth_keepalive_noop_when_disconnected(hass, mock_client) -> None:
    """Test bandwidth keepalive does nothing when WS is disconnected."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)})
    coordinator.ws_manager.ws = None

    await coordinator.ws_manager._async_bandwidth_keepalive(None)

    mock_client.set_whem_bandwidth.assert_not_called()


async def test_bandwidth_keepalive_handles_error(hass, mock_client) -> None:
    """Test bandwidth keepalive handles connection error gracefully."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)})
    coordinator.ws_manager.ws = MagicMock()
    mock_client.set_whem_bandwidth = AsyncMock(
        side_effect=LevitonConnectionError("fail")
    )

    # Should not raise
    await coordinator.ws_manager._async_bandwidth_keepalive(None)


# --- _reconnect_websocket tests ---


async def test_reconnect_succeeds_on_first_attempt(hass, mock_client) -> None:
    """Test reconnect succeeds on first attempt after delay."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)})

    with patch("homeassistant.components.leviton_load_center.websocket.asyncio.sleep", new_callable=AsyncMock):
        await coordinator.ws_manager._reconnect()

    assert coordinator.ws_manager._reconnecting is False
    assert coordinator.ws_manager.ws is not None


async def test_reconnect_retries_on_connection_error(hass, mock_client) -> None:
    """Test reconnect retries when API is unreachable."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)})

    # First 2 get_permissions fail, then succeed
    mock_client.get_permissions = AsyncMock(
        side_effect=[
            LevitonConnectionError("unreachable"),
            LevitonConnectionError("unreachable"),
            [MOCK_PERMISSION],
            [MOCK_PERMISSION],
            [MOCK_PERMISSION],
        ]
    )

    with patch("homeassistant.components.leviton_load_center.websocket.asyncio.sleep", new_callable=AsyncMock):
        await coordinator.ws_manager._reconnect()

    assert coordinator.ws_manager._reconnecting is False
    # Got through 2 failures + successful connect
    assert mock_client.get_permissions.call_count >= 3


async def test_reconnect_auth_error_triggers_reauth(hass, mock_client) -> None:
    """Test reconnect triggers reauth flow on auth error."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()

    mock_client.get_permissions = AsyncMock(
        side_effect=LevitonAuthError("Token expired")
    )

    with patch("homeassistant.components.leviton_load_center.websocket.asyncio.sleep", new_callable=AsyncMock):
        await coordinator.ws_manager._reconnect()

    entry.async_start_reauth.assert_called_once()
    assert coordinator.ws_manager._reconnecting is False


async def test_reconnect_all_attempts_fail(hass, mock_client) -> None:
    """Test reconnect gives up after all attempts fail."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)})

    # get_permissions works but WS connect always fails
    mock_ws = MagicMock()
    mock_ws.connect = AsyncMock(
        side_effect=LevitonConnectionError("WS fail")
    )
    mock_ws.disconnect = AsyncMock()
    mock_ws.subscribe = AsyncMock()
    mock_ws.on_notification = MagicMock(return_value=MagicMock())
    mock_ws.on_disconnect = MagicMock(return_value=MagicMock())
    mock_client.create_websocket = MagicMock(return_value=mock_ws)

    with patch("homeassistant.components.leviton_load_center.websocket.asyncio.sleep", new_callable=AsyncMock):
        await coordinator.ws_manager._reconnect()

    assert coordinator.ws_manager._reconnecting is False
    assert coordinator.ws_manager.ws is None


async def test_ws_connect_whem_sub_failure(hass, mock_client, mock_websocket) -> None:
    """Test connect() handles WHEM bandwidth/subscription failure gracefully."""
    mock_client.set_whem_bandwidth = AsyncMock(
        side_effect=LevitonConnectionError("bandwidth fail")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)})

    await coordinator.ws_manager.connect()

    # WS connected despite WHEM subscription failure
    assert coordinator.ws_manager.ws is not None


async def test_ws_connect_panel_sub_failure(hass, mock_client, mock_websocket) -> None:
    """Test connect() handles panel bandwidth/subscription failure gracefully."""
    mock_client.set_panel_bandwidth = AsyncMock(
        side_effect=LevitonConnectionError("bandwidth fail")
    )
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(panels={MOCK_PANEL.id: deepcopy(MOCK_PANEL)})

    await coordinator.ws_manager.connect()

    assert coordinator.ws_manager.ws is not None


async def test_ws_connect_fw2_individual_breaker_subs(
    hass, mock_client, mock_websocket
) -> None:
    """Test connect() subscribes to individual breakers on FW 2.x."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    whem = deepcopy(MOCK_WHEM)
    whem.version = "2.0.13"
    breaker = deepcopy(MOCK_BREAKER_GEN1)  # iot_whem_id matches MOCK_WHEM
    breaker_other = deepcopy(MOCK_BREAKER_GEN2)
    breaker_other.iot_whem_id = "other_whem"  # doesn't match → skipped
    coordinator.data = LevitonData(
        whems={whem.id: whem},
        breakers={breaker.id: breaker, breaker_other.id: breaker_other},
    )

    await coordinator.ws_manager.connect()

    subscribe_calls = [call.args for call in mock_websocket.subscribe.call_args_list]
    assert ("IotWhem", whem.id) in subscribe_calls
    assert ("ResidentialBreaker", breaker.id) in subscribe_calls
    # Other breaker NOT subscribed (different WHEM)
    assert ("ResidentialBreaker", breaker_other.id) not in subscribe_calls


async def test_ws_connect_breaker_sub_failure(
    hass, mock_client, mock_websocket
) -> None:
    """Test connect() handles individual breaker subscription failure gracefully."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    whem = deepcopy(MOCK_WHEM)
    whem.version = "2.0.13"
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    coordinator.data = LevitonData(
        whems={whem.id: whem},
        breakers={breaker.id: breaker},
    )

    # Individual breaker subscribe fails
    call_count = 0
    original_subscribe = mock_websocket.subscribe

    async def selective_fail(model, model_id):
        nonlocal call_count
        call_count += 1
        if model == "ResidentialBreaker":
            raise LevitonConnectionError("breaker sub fail")

    mock_websocket.subscribe = AsyncMock(side_effect=selective_fail)

    await coordinator.ws_manager.connect()

    # WS still connected despite breaker sub failure
    assert coordinator.ws_manager.ws is not None


def test_apply_breaker_ws_update_gen1_trip_synthesis(hass, mock_client) -> None:
    """Test Gen 1 remoteTrip synthesizes currentState=SoftwareTrip."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN1)  # can_remote_on=False
    breaker.current_state = "ManualON"
    coordinator.data = LevitonData(breakers={breaker.id: breaker})

    result = coordinator.ws_manager._apply_breaker_ws_update(
        {"id": breaker.id, "remoteTrip": True}
    )

    assert result is True
    assert breaker.current_state == STATE_SOFTWARE_TRIP


def test_apply_breaker_ws_update_gen2_no_trip_synthesis(hass, mock_client) -> None:
    """Test Gen 2 remoteTrip does NOT synthesize (can_remote_on=True)."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    breaker = deepcopy(MOCK_BREAKER_GEN2)  # can_remote_on=True
    breaker.current_state = "ManualON"
    coordinator.data = LevitonData(breakers={breaker.id: breaker})

    coordinator.ws_manager._apply_breaker_ws_update(
        {"id": breaker.id, "remoteTrip": True}
    )

    # Gen 2 breaker does not get synthesized SoftwareTrip
    assert breaker.current_state == "ManualON"


async def test_ws_shutdown_bandwidth_errors_graceful(hass, mock_client) -> None:
    """Test shutdown handles bandwidth disable errors gracefully."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData(
        whems={MOCK_WHEM.id: deepcopy(MOCK_WHEM)},
        panels={MOCK_PANEL.id: deepcopy(MOCK_PANEL)},
    )
    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws_manager.ws = mock_ws

    mock_client.set_panel_bandwidth = AsyncMock(
        side_effect=LevitonConnectionError("fail")
    )
    mock_client.set_whem_bandwidth = AsyncMock(
        side_effect=LevitonConnectionError("fail")
    )

    # Should not raise
    await coordinator.async_shutdown()

    # WS still disconnected despite bandwidth errors
    mock_ws.disconnect.assert_called_once()
    assert coordinator.ws_manager.ws is None


async def test_ws_watchdog_cleans_up_callbacks(hass, mock_client) -> None:
    """Test watchdog removes disconnect callback before forcing reconnect."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()
    mock_ws = MagicMock()
    mock_ws.disconnect = AsyncMock()
    coordinator.ws_manager.ws = mock_ws
    mock_remove_disconnect = MagicMock()
    coordinator.ws_manager._ws_remove_disconnect = mock_remove_disconnect
    coordinator.ws_manager._last_ws_notification = time.monotonic() - 120

    await coordinator.ws_manager._async_ws_watchdog(None)

    mock_remove_disconnect.assert_called_once()
    mock_ws.disconnect.assert_called_once()
    assert coordinator.ws_manager.ws is None
    coro = entry.async_create_background_task.call_args[0][1]
    coro.close()


async def test_reconnect_cancelled(hass, mock_client) -> None:
    """Test reconnect handles CancelledError and re-raises it."""
    entry = MagicMock()
    coordinator = _make_coordinator(hass, entry, mock_client)
    coordinator.data = LevitonData()

    with patch(
        "homeassistant.components.leviton_load_center.websocket.asyncio.sleep",
        new_callable=AsyncMock,
    ) as mock_sleep:
        mock_sleep.side_effect = asyncio.CancelledError()
        with pytest.raises(asyncio.CancelledError):
            await coordinator.ws_manager._reconnect()

    # _reconnecting is cleaned up in the finally block
    assert coordinator.ws_manager._reconnecting is False
