"""Tests for the Leviton button platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

from homeassistant.components.button import ButtonDeviceClass
from homeassistant.components.leviton.button import (
    IDENTIFY_BUTTON_DESCRIPTION,
    TRIP_BUTTON_DESCRIPTION,
    LevitonBreakerIdentifyButton,
    LevitonTripButton,
    LevitonWhemIdentifyButton,
)
from homeassistant.components.leviton.coordinator import LevitonData
from homeassistant.components.leviton.entity import (
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
    coordinator.async_request_refresh.assert_called_once()


def test_trip_button_device_class() -> None:
    """Test trip button has RESTART device class."""
    coordinator = MagicMock()
    coordinator.data = LevitonData()
    dev_info = MagicMock()
    button = LevitonTripButton(
        coordinator, TRIP_BUTTON_DESCRIPTION, "test_id", dev_info
    )
    assert button.device_class == ButtonDeviceClass.RESTART


async def test_breaker_identify_button_press(mock_client) -> None:
    """Test breaker identify button calls blink_led."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    coordinator = _make_coordinator(data, mock_client)
    dev_info = breaker_device_info(breaker.id, data)
    button = LevitonBreakerIdentifyButton(
        coordinator, IDENTIFY_BUTTON_DESCRIPTION, breaker.id, dev_info
    )

    await button.async_press()

    mock_client.blink_led.assert_called_once_with(breaker.id)


def test_breaker_identify_button_device_class() -> None:
    """Test breaker identify button has IDENTIFY device class."""
    coordinator = MagicMock()
    coordinator.data = LevitonData()
    dev_info = MagicMock()
    button = LevitonBreakerIdentifyButton(
        coordinator, IDENTIFY_BUTTON_DESCRIPTION, "test_id", dev_info
    )
    assert button.device_class == ButtonDeviceClass.IDENTIFY


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


def test_whem_identify_button_device_class() -> None:
    """Test WHEM identify button has IDENTIFY device class."""
    coordinator = MagicMock()
    coordinator.data = LevitonData()
    dev_info = MagicMock()
    button = LevitonWhemIdentifyButton(
        coordinator, IDENTIFY_BUTTON_DESCRIPTION, "test_id", dev_info
    )
    assert button.device_class == ButtonDeviceClass.IDENTIFY
