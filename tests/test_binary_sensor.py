"""Tests for the Leviton binary sensor platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

from homeassistant.components.leviton_load_center.binary_sensor import (
    CONNECTIVITY_DESCRIPTION,
    LevitonPanelConnectivity,
    LevitonWhemConnectivity,
    async_setup_entry,
)
from homeassistant.components.leviton_load_center.coordinator import (
    LevitonData,
    LevitonRuntimeData,
)
from homeassistant.components.leviton_load_center.entity import (
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


# --- Platform setup tests ---


async def test_setup_creates_whem_connectivity() -> None:
    """Test setup creates connectivity binary sensor for each WHEM."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    whem_sensors = [
        e for e in added_entities if isinstance(e, LevitonWhemConnectivity)
    ]
    assert len(whem_sensors) == 1
    assert whem_sensors[0]._device_id == whem.id


async def test_setup_creates_panel_connectivity() -> None:
    """Test setup creates connectivity binary sensor for each panel."""
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData(panels={panel.id: panel})
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    panel_sensors = [
        e for e in added_entities if isinstance(e, LevitonPanelConnectivity)
    ]
    assert len(panel_sensors) == 1
    assert panel_sensors[0]._device_id == panel.id
