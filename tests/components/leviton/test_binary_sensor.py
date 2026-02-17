"""Tests for the Leviton binary sensor platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.leviton.binary_sensor import (
    CONNECTIVITY_DESCRIPTION,
    LevitonPanelConnectivity,
    LevitonWhemConnectivity,
)
from homeassistant.components.leviton.coordinator import LevitonData
from homeassistant.components.leviton.entity import (
    panel_device_info,
    whem_device_info,
)

from .conftest import MOCK_PANEL, MOCK_WHEM


def test_whem_connectivity_on() -> None:
    """Test WHEM connectivity returns True when connected."""
    whem = deepcopy(MOCK_WHEM)
    whem.connected = True
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = whem_device_info(whem.id, data)
    sensor = LevitonWhemConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, whem.id, dev_info
    )
    assert sensor.is_on is True


def test_whem_connectivity_off() -> None:
    """Test WHEM connectivity returns False when disconnected."""
    whem = deepcopy(MOCK_WHEM)
    whem.connected = False
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = whem_device_info(whem.id, data)
    sensor = LevitonWhemConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, whem.id, dev_info
    )
    assert sensor.is_on is False


def test_whem_connectivity_missing() -> None:
    """Test WHEM connectivity returns None when WHEM not in data."""
    data = LevitonData()
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = MagicMock()
    sensor = LevitonWhemConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, "nonexistent", dev_info
    )
    assert sensor.is_on is None


def test_whem_connectivity_device_class() -> None:
    """Test WHEM connectivity has correct device class."""
    coordinator = MagicMock()
    coordinator.data = LevitonData()
    dev_info = MagicMock()
    sensor = LevitonWhemConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, "test_id", dev_info
    )
    assert sensor.device_class == BinarySensorDeviceClass.CONNECTIVITY


def test_panel_connectivity_online() -> None:
    """Test panel connectivity returns True when online."""
    panel = deepcopy(MOCK_PANEL)
    panel.online = "2026-02-15T23:22:12.000Z"
    panel.offline = None
    data = LevitonData(panels={panel.id: panel})
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = panel_device_info(panel.id, data)
    sensor = LevitonPanelConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, panel.id, dev_info
    )
    assert sensor.is_on is True


def test_panel_connectivity_offline() -> None:
    """Test panel connectivity returns False when offline."""
    panel = deepcopy(MOCK_PANEL)
    panel.online = "2026-02-15T23:22:12.000Z"
    panel.offline = "2026-02-16T01:00:00.000Z"
    data = LevitonData(panels={panel.id: panel})
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = panel_device_info(panel.id, data)
    sensor = LevitonPanelConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, panel.id, dev_info
    )
    assert sensor.is_on is False


def test_panel_connectivity_never_online() -> None:
    """Test panel connectivity returns False when never seen online."""
    panel = deepcopy(MOCK_PANEL)
    panel.online = None
    panel.offline = None
    data = LevitonData(panels={panel.id: panel})
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = panel_device_info(panel.id, data)
    sensor = LevitonPanelConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, panel.id, dev_info
    )
    assert sensor.is_on is False


def test_panel_connectivity_missing() -> None:
    """Test panel connectivity returns None when panel not in data."""
    data = LevitonData()
    coordinator = MagicMock()
    coordinator.data = data
    dev_info = MagicMock()
    sensor = LevitonPanelConnectivity(
        coordinator, CONNECTIVITY_DESCRIPTION, "nonexistent", dev_info
    )
    assert sensor.is_on is None
