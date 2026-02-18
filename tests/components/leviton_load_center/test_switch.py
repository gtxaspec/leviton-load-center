"""Tests for the Leviton switch platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.leviton_load_center.coordinator import LevitonData, LevitonRuntimeData
from homeassistant.components.leviton_load_center.entity import breaker_device_info
from homeassistant.components.leviton_load_center.switch import (
    BREAKER_SWITCH_DESCRIPTION,
    LevitonBreakerSwitch,
    async_setup_entry,
)

from .conftest import MOCK_BREAKER_GEN1, MOCK_BREAKER_GEN2, MOCK_WHEM


def _make_switch(breaker, data, mock_client) -> LevitonBreakerSwitch:
    """Create a breaker switch with mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.client = mock_client
    dev_info = breaker_device_info(breaker.id, data)
    switch = LevitonBreakerSwitch(
        coordinator, BREAKER_SWITCH_DESCRIPTION, breaker.id, dev_info
    )
    return switch


def test_is_on_remote_on() -> None:
    """Test switch is_on when remoteState=RemoteON."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.remote_state = "RemoteON"
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, MagicMock())
    assert switch.is_on is True


def test_is_on_remote_off() -> None:
    """Test switch is_on returns False when remoteState=RemoteOFF."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.remote_state = "RemoteOFF"
    breaker.current_state = "ManualON"  # WS never updates currentState
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, MagicMock())
    assert switch.is_on is False


def test_is_on_manual_on() -> None:
    """Test switch is_on when no remote state and currentState=ManualON."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.remote_state = ""
    breaker.current_state = "ManualON"
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, MagicMock())
    assert switch.is_on is True


def test_is_on_manual_off() -> None:
    """Test switch is_on returns False when no remote state and tripped."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.remote_state = ""
    breaker.current_state = "ManualOFF"
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, MagicMock())
    assert switch.is_on is False


def test_is_on_breaker_missing() -> None:
    """Test switch is_on returns None when breaker not in data."""
    data = LevitonData()
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = MagicMock()
    switch = LevitonBreakerSwitch(
        coordinator, BREAKER_SWITCH_DESCRIPTION, "nonexistent", dev_info
    )
    assert switch.is_on is None


async def test_turn_on(mock_client) -> None:
    """Test turning on a breaker calls turn_on_breaker."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, mock_client)

    await switch.async_turn_on()

    mock_client.turn_on_breaker.assert_called_once_with(breaker.id)


async def test_turn_off(mock_client) -> None:
    """Test turning off a breaker calls turn_off_breaker."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, mock_client)

    await switch.async_turn_off()

    mock_client.turn_off_breaker.assert_called_once_with(breaker.id)


# --- Platform setup tests ---


async def test_setup_creates_switches_for_gen2_only() -> None:
    """Test setup creates switches for Gen 2 (can_remote_on) only, not Gen 1."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)  # can_remote_on=False
    gen2 = deepcopy(MOCK_BREAKER_GEN2)  # can_remote_on=True
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

    assert len(added_entities) == 1
    assert added_entities[0]._device_id == gen2.id


async def test_setup_read_only_creates_no_switches() -> None:
    """Test setup creates no switches when read_only=True."""
    gen2 = deepcopy(MOCK_BREAKER_GEN2)
    data = LevitonData(
        breakers={gen2.id: gen2},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {"read_only": True}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    assert len(added_entities) == 0


