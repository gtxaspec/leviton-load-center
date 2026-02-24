"""Tests for the Leviton button platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from aioleviton import LevitonConnectionError

from homeassistant.exceptions import HomeAssistantError

from homeassistant.components.leviton_load_center.button import (
    ALL_OFF_BUTTON_DESCRIPTION,
    ALL_ON_BUTTON_DESCRIPTION,
    IDENTIFY_BUTTON_DESCRIPTION,
    TRIP_ALL_BUTTON_DESCRIPTION,
    TRIP_BUTTON_DESCRIPTION,
    LevitonPanelTripAllButton,
    LevitonTripButton,
    LevitonWhemAllOffButton,
    LevitonWhemAllOnButton,
    LevitonWhemIdentifyButton,
    async_setup_entry,
)
from homeassistant.components.leviton_load_center.coordinator import LevitonData, LevitonRuntimeData
from homeassistant.components.leviton_load_center.entity import (
    breaker_device_info,
    panel_device_info,
    whem_device_info,
)

from .conftest import MOCK_BREAKER_GEN1, MOCK_BREAKER_GEN2, MOCK_PANEL, MOCK_WHEM


def _make_coordinator(data, mock_client):
    """Create a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.client = mock_client
    coordinator.async_request_refresh = AsyncMock()
    coordinator.config_entry.options = {}
    return coordinator


async def test_trip_button_press(mock_client) -> None:
    """Test trip button calls trip_breaker."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = breaker_device_info(breaker.id, data)
    button = LevitonTripButton(
        coordinator, TRIP_BUTTON_DESCRIPTION, breaker.id, dev_info
    )

    await button.async_press()

    mock_client.trip_breaker.assert_called_once_with(breaker.id)
    assert breaker.current_state == "SoftwareTrip"
    button.coordinator.async_set_updated_data.assert_called_once()


async def test_whem_identify_button_press(mock_client) -> None:
    """Test WHEM identify button calls identify_whem."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    coordinator = _make_coordinator(data, mock_client)
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemIdentifyButton(
        coordinator, IDENTIFY_BUTTON_DESCRIPTION, whem.id, dev_info
    )

    await button.async_press()

    mock_client.identify_whem.assert_called_once_with(whem.id)


# --- Platform setup tests ---


async def test_setup_trip_button_gen1_only() -> None:
    """Test trip button is created for Gen 1 only (not Gen 2)."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)  # is_smart=True, can_remote_on=False
    gen2 = deepcopy(MOCK_BREAKER_GEN2)  # is_smart=True, can_remote_on=True
    data = LevitonData(
        breakers={gen1.id: gen1, gen2.id: gen2},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    trip_buttons = [e for e in added_entities if isinstance(e, LevitonTripButton)]
    assert len(trip_buttons) == 1
    assert trip_buttons[0]._device_id == gen1.id


async def test_setup_whem_identify_button() -> None:
    """Test WHEM identify button is created for each WHEM."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    whem_buttons = [
        e for e in added_entities if isinstance(e, LevitonWhemIdentifyButton)
    ]
    assert len(whem_buttons) == 1
    assert whem_buttons[0]._device_id == whem.id


async def test_setup_no_breaker_identify_buttons() -> None:
    """Test breaker identify is NOT created as a button (it's a switch now)."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)
    gen2 = deepcopy(MOCK_BREAKER_GEN2)
    data = LevitonData(
        breakers={gen1.id: gen1, gen2.id: gen2},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    # Trip button for gen1 + WHEM buttons (identify, all_off, all_on)
    assert len(added_entities) == 4
    assert isinstance(added_entities[0], LevitonTripButton)
    assert isinstance(added_entities[1], LevitonWhemIdentifyButton)
    assert isinstance(added_entities[2], LevitonWhemAllOffButton)
    assert isinstance(added_entities[3], LevitonWhemAllOnButton)


async def test_setup_read_only_creates_no_buttons() -> None:
    """Test setup creates no buttons when read_only=True."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={gen1.id: gen1},
        whems={whem.id: whem},
    )
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {"read_only": True}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    assert len(added_entities) == 0


# --- Error path tests ---


async def test_trip_button_error_raises_ha_error(mock_client) -> None:
    """Test trip button raises HomeAssistantError on connection failure."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    mock_client.trip_breaker = AsyncMock(
        side_effect=LevitonConnectionError("Connection lost")
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = breaker_device_info(breaker.id, data)
    button = LevitonTripButton(
        coordinator, TRIP_BUTTON_DESCRIPTION, breaker.id, dev_info
    )


    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_whem_identify_error_raises_ha_error(mock_client) -> None:
    """Test WHEM identify raises HomeAssistantError on connection failure."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    mock_client.identify_whem = AsyncMock(
        side_effect=LevitonConnectionError("Connection lost")
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemIdentifyButton(
        coordinator, IDENTIFY_BUTTON_DESCRIPTION, whem.id, dev_info
    )


    with pytest.raises(HomeAssistantError):
        await button.async_press()


# --- WHEM identify button availability tests ---


def test_whem_identify_available_offline() -> None:
    """Test WHEM identify button is unavailable when WHEM is disconnected."""
    whem = deepcopy(MOCK_WHEM)
    whem.connected = False
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemIdentifyButton(
        coordinator, IDENTIFY_BUTTON_DESCRIPTION, whem.id, dev_info
    )
    button._collection = "whems"
    assert button.available is False


# --- Bulk control button tests ---


async def test_all_off_button_gen2_turn_off_gen1_trip(mock_client) -> None:
    """Test All Off turns off Gen 2 breakers and trips Gen 1 breakers."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)
    gen2 = deepcopy(MOCK_BREAKER_GEN2)
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={gen1.id: gen1, gen2.id: gen2},
        whems={whem.id: whem},
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemAllOffButton(
        coordinator, ALL_OFF_BUTTON_DESCRIPTION, whem.id, dev_info
    )

    await button.async_press()

    mock_client.trip_breaker.assert_called_once_with(gen1.id)
    mock_client.turn_off_breaker.assert_called_once_with(gen2.id)
    assert gen1.current_state == "SoftwareTrip"
    assert gen2.remote_state == "RemoteOFF"
    coordinator.async_set_updated_data.assert_called_once()


async def test_all_on_button_skips_gen1(mock_client) -> None:
    """Test All On only turns on Gen 2 breakers, skips Gen 1."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)
    gen2 = deepcopy(MOCK_BREAKER_GEN2)
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={gen1.id: gen1, gen2.id: gen2},
        whems={whem.id: whem},
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemAllOnButton(
        coordinator, ALL_ON_BUTTON_DESCRIPTION, whem.id, dev_info
    )

    await button.async_press()

    mock_client.turn_on_breaker.assert_called_once_with(gen2.id)
    assert gen2.remote_state == "RemoteON"
    # Gen 1 state unchanged
    assert gen1.current_state == "ManualON"
    coordinator.async_set_updated_data.assert_called_once()


async def test_trip_all_button_trips_all_panel_breakers(mock_client) -> None:
    """Test Trip All trips all breakers on a panel."""
    panel = deepcopy(MOCK_PANEL)
    b1 = deepcopy(MOCK_BREAKER_GEN1)
    b1.iot_whem_id = None
    b1.residential_breaker_panel_id = panel.id
    b2 = deepcopy(MOCK_BREAKER_GEN2)
    b2.iot_whem_id = None
    b2.residential_breaker_panel_id = panel.id
    data = LevitonData(
        breakers={b1.id: b1, b2.id: b2},
        panels={panel.id: panel},
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = panel_device_info(panel.id, data)
    button = LevitonPanelTripAllButton(
        coordinator, TRIP_ALL_BUTTON_DESCRIPTION, panel.id, dev_info
    )

    await button.async_press()

    assert mock_client.trip_breaker.call_count == 2
    mock_client.trip_breaker.assert_any_call(b1.id)
    mock_client.trip_breaker.assert_any_call(b2.id)
    assert b1.current_state == "SoftwareTrip"
    assert b2.current_state == "SoftwareTrip"
    coordinator.async_set_updated_data.assert_called_once()


async def test_all_off_button_only_targets_own_whem(mock_client) -> None:
    """Test All Off only affects breakers belonging to its WHEM."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)  # belongs to MOCK_WHEM
    gen2 = deepcopy(MOCK_BREAKER_GEN2)
    gen2.iot_whem_id = "OTHER_WHEM"  # different WHEM
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={gen1.id: gen1, gen2.id: gen2},
        whems={whem.id: whem},
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemAllOffButton(
        coordinator, ALL_OFF_BUTTON_DESCRIPTION, whem.id, dev_info
    )

    await button.async_press()

    # Only gen1 should be tripped (belongs to this WHEM)
    mock_client.trip_breaker.assert_called_once_with(gen1.id)
    mock_client.turn_off_breaker.assert_not_called()


async def test_all_off_error_raises_ha_error(mock_client) -> None:
    """Test All Off raises HomeAssistantError on connection failure."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={gen1.id: gen1},
        whems={whem.id: whem},
    )
    mock_client.trip_breaker = AsyncMock(
        side_effect=LevitonConnectionError("Connection lost")
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = whem_device_info(whem.id, data)
    button = LevitonWhemAllOffButton(
        coordinator, ALL_OFF_BUTTON_DESCRIPTION, whem.id, dev_info
    )

    with pytest.raises(HomeAssistantError):
        await button.async_press()


async def test_setup_panel_trip_all_button() -> None:
    """Test Trip All button is created for each panel."""
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData(panels={panel.id: panel})
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    trip_all = [e for e in added_entities if isinstance(e, LevitonPanelTripAllButton)]
    assert len(trip_all) == 1
    assert trip_all[0]._device_id == panel.id


async def test_setup_whem_all_off_all_on_buttons() -> None:
    """Test All Off and All On buttons are created for each WHEM."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    all_off = [e for e in added_entities if isinstance(e, LevitonWhemAllOffButton)]
    all_on = [e for e in added_entities if isinstance(e, LevitonWhemAllOnButton)]
    assert len(all_off) == 1
    assert len(all_on) == 1
    assert all_off[0]._device_id == whem.id
    assert all_on[0]._device_id == whem.id
