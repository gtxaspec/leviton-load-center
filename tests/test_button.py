"""Tests for the Leviton button platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.leviton_load_center.button import (
    IDENTIFY_BUTTON_DESCRIPTION,
    TRIP_BUTTON_DESCRIPTION,
    LevitonTripButton,
    LevitonWhemIdentifyButton,
    async_setup_entry,
)
from homeassistant.components.leviton_load_center.coordinator import LevitonData, LevitonRuntimeData
from homeassistant.components.leviton_load_center.entity import (
    breaker_device_info,
    whem_device_info,
)

from .conftest import MOCK_BREAKER_GEN1, MOCK_BREAKER_GEN2, MOCK_WHEM


def _make_coordinator(data, mock_client):
    """Create a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.client = mock_client
    coordinator.async_request_refresh = AsyncMock()
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

    # Only trip button for gen1 + WHEM identify button, no breaker identify buttons
    assert len(added_entities) == 2
    assert isinstance(added_entities[0], LevitonTripButton)
    assert isinstance(added_entities[1], LevitonWhemIdentifyButton)


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
