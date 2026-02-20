"""Tests for the Leviton switch platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.leviton_load_center.coordinator import LevitonData, LevitonRuntimeData
from homeassistant.components.leviton_load_center.entity import breaker_device_info
from homeassistant.components.leviton_load_center.switch import (
    BREAKER_SWITCH_DESCRIPTION,
    IDENTIFY_SWITCH_DESCRIPTION,
    LevitonBreakerIdentifySwitch,
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


def _make_identify_switch(breaker, data, mock_client) -> LevitonBreakerIdentifySwitch:
    """Create a breaker identify switch with mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.client = mock_client
    dev_info = breaker_device_info(breaker.id, data)
    switch = LevitonBreakerIdentifySwitch(
        coordinator, IDENTIFY_SWITCH_DESCRIPTION, breaker.id, dev_info
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


@pytest.mark.parametrize("state", ["NotCommunicating", "CommunicationFailure", "COMMUNICATING"])
def test_is_on_communication_states(state) -> None:
    """Test switch stays on during communication state changes."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.remote_state = ""
    breaker.current_state = state
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_switch(breaker, data, MagicMock())
    assert switch.is_on is True


@pytest.mark.parametrize("state", [
    "GFCIFault", "SoftwareTrip", "OverloadTrip", "ShortCircuitTrip",
])
def test_is_on_trip_states(state) -> None:
    """Test switch shows off for trip/fault states."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.remote_state = ""
    breaker.current_state = state
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


# --- Identify switch tests ---


def test_identify_is_on() -> None:
    """Test identify switch reflects blink_led state."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.blink_led = True
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_identify_switch(breaker, data, MagicMock())
    assert switch.is_on is True


def test_identify_is_off() -> None:
    """Test identify switch returns False when LED not blinking."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.blink_led = False
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_identify_switch(breaker, data, MagicMock())
    assert switch.is_on is False


def test_identify_breaker_missing() -> None:
    """Test identify switch returns None when breaker not in data."""
    data = LevitonData()
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = MagicMock()
    switch = LevitonBreakerIdentifySwitch(
        coordinator, IDENTIFY_SWITCH_DESCRIPTION, "nonexistent", dev_info
    )
    assert switch.is_on is None


async def test_identify_turn_on(mock_client) -> None:
    """Test turning on identify calls blink_led."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_identify_switch(breaker, data, mock_client)

    await switch.async_turn_on()

    mock_client.blink_led.assert_called_once_with(breaker.id)
    assert breaker.blink_led is True


async def test_identify_turn_off(mock_client) -> None:
    """Test turning off identify calls stop_blink_led."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.blink_led = True
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    switch = _make_identify_switch(breaker, data, mock_client)

    await switch.async_turn_off()

    mock_client.stop_blink_led.assert_called_once_with(breaker.id)
    assert breaker.blink_led is False


# --- Platform setup tests ---


async def test_setup_creates_switches_for_gen2_and_identify() -> None:
    """Test setup creates breaker switch for Gen 2 and identify for all smart."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)  # can_remote_on=False, is_smart=True
    gen2 = deepcopy(MOCK_BREAKER_GEN2)  # can_remote_on=True, is_smart=True
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

    breaker_switches = [e for e in added_entities if isinstance(e, LevitonBreakerSwitch)]
    identify_switches = [e for e in added_entities if isinstance(e, LevitonBreakerIdentifySwitch)]
    # Gen 2 only gets breaker switch
    assert len(breaker_switches) == 1
    assert breaker_switches[0]._device_id == gen2.id
    # Both smart breakers get identify switch
    assert len(identify_switches) == 2


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


