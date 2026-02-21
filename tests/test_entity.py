"""Tests for the Leviton base entity and device info helpers."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from homeassistant.components.leviton_load_center.const import DOMAIN
from homeassistant.components.leviton_load_center.coordinator import LevitonData
from homeassistant.components.leviton_load_center.entity import (
    LevitonBreakerControlEntity,
    LevitonEntity,
    breaker_device_info,
    ct_device_info,
    panel_device_info,
    whem_device_info,
)

from .conftest import (
    MOCK_BREAKER_GEN1,
    MOCK_BREAKER_GEN2,
    MOCK_CT,
    MOCK_PANEL,
    MOCK_WHEM,
)


def test_whem_device_info() -> None:
    """Test WHEM device info is built correctly."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    info = whem_device_info(whem.id, data)

    assert (DOMAIN, whem.id) in info["identifiers"]
    assert info["name"] == "Main Panel"
    assert info["manufacturer"] == whem.manufacturer
    assert info["model"] == "LWHEM"
    assert info["sw_version"] == whem.version
    assert info["serial_number"] == whem.serial


def test_whem_device_info_no_name() -> None:
    """Test WHEM device info uses fallback name."""
    whem = deepcopy(MOCK_WHEM)
    whem.name = ""
    data = LevitonData(whems={whem.id: whem})
    info = whem_device_info(whem.id, data)
    assert info["name"] == f"LWHEM {whem.id}"


def test_panel_device_info() -> None:
    """Test panel device info is built correctly."""
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData(panels={panel.id: panel})
    info = panel_device_info(panel.id, data)

    assert (DOMAIN, panel.id) in info["identifiers"]
    assert info["name"] == "Breaker Panel 1"
    assert info["manufacturer"] == "Leviton"
    assert info["model"] == "LDATA"
    assert info["sw_version"] == panel.package_ver
    assert info["serial_number"] == panel.id


def test_panel_device_info_no_name() -> None:
    """Test panel device info uses fallback name."""
    panel = deepcopy(MOCK_PANEL)
    panel.name = ""
    data = LevitonData(panels={panel.id: panel})
    info = panel_device_info(panel.id, data)
    assert info["name"] == f"Panel {panel.id}"


def test_breaker_device_info_with_whem_parent() -> None:
    """Test breaker device info with WHEM as parent."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    info = breaker_device_info(breaker.id, data)

    assert (DOMAIN, breaker.id) in info["identifiers"]
    assert info["name"] == "Kitchen"
    assert info["manufacturer"] == "Leviton"
    assert info["model"] == "LB115-DS"
    assert info["via_device"] == (DOMAIN, MOCK_WHEM.id)
    assert info["serial_number"] == "ABC123"


def test_breaker_device_info_with_panel_parent() -> None:
    """Test breaker device info with panel as parent."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.iot_whem_id = None
    breaker.residential_breaker_panel_id = MOCK_PANEL.id
    data = LevitonData(
        breakers={breaker.id: breaker},
        panels={MOCK_PANEL.id: MOCK_PANEL},
    )
    info = breaker_device_info(breaker.id, data)

    assert info["via_device"] == (DOMAIN, MOCK_PANEL.id)


def test_breaker_device_info_no_parent() -> None:
    """Test breaker device info with no parent hub."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.iot_whem_id = None
    breaker.residential_breaker_panel_id = None
    data = LevitonData(breakers={breaker.id: breaker})
    info = breaker_device_info(breaker.id, data)

    assert info.get("via_device") is None


def test_breaker_device_info_no_name() -> None:
    """Test breaker device info uses position-based fallback name."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.name = ""
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    info = breaker_device_info(breaker.id, data)
    assert info["name"] == f"Breaker {breaker.position}"


def test_ct_device_info() -> None:
    """Test CT device info is built correctly."""
    ct = deepcopy(MOCK_CT)
    data = LevitonData(
        cts={str(ct.id): ct},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    info = ct_device_info(str(ct.id), data)

    assert (DOMAIN, str(ct.id)) in info["identifiers"]
    assert info["name"] == f"CT Channel {ct.channel}"
    assert info["manufacturer"] == "Leviton"
    assert info["model"] == "LWHEM CT"
    assert info["via_device"] == (DOMAIN, MOCK_WHEM.id)


def test_ct_device_info_with_name() -> None:
    """Test CT device info uses provided name."""
    ct = deepcopy(MOCK_CT)
    ct.name = "Grid Power"
    data = LevitonData(
        cts={str(ct.id): ct},
        whems={MOCK_WHEM.id: MOCK_WHEM},
    )
    info = ct_device_info(str(ct.id), data)
    assert info["name"] == "Grid Power"


def test_ct_device_info_no_whem() -> None:
    """Test CT device info with no WHEM parent."""
    ct = deepcopy(MOCK_CT)
    ct.iot_whem_id = "nonexistent"
    data = LevitonData(cts={str(ct.id): ct})
    info = ct_device_info(str(ct.id), data)
    assert info.get("via_device") is None


def test_entity_unique_id() -> None:
    """Test entity unique ID is formatted correctly."""
    coordinator = MagicMock()
    coordinator.config_entry.unique_id = "test@example.com"
    description = MagicMock()
    description.key = "power"
    dev_info = MagicMock()
    entity = LevitonEntity(coordinator, description, "device123", dev_info)
    assert entity.unique_id == "test@example.com_device123_power"


# --- Available property tests ---


def test_entity_available_whem_present() -> None:
    """Test entity is available when device_id is in whems."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, whem.id, MagicMock())
    entity._collection = "whems"
    assert entity.available is True


def test_entity_available_breaker_present() -> None:
    """Test entity is available when device_id is in breakers."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData(breakers={breaker.id: breaker})
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, breaker.id, MagicMock())
    assert entity.available is True


def test_entity_available_ct_present() -> None:
    """Test entity is available when numeric device_id is in cts."""
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={str(ct.id): ct})
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, str(ct.id), MagicMock())
    entity._collection = "cts"
    assert entity.available is True


def test_entity_available_device_missing() -> None:
    """Test entity is unavailable when device_id is not in any dict."""
    data = LevitonData()
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, "nonexistent", MagicMock())
    assert entity.available is False


def test_entity_available_coordinator_unavailable() -> None:
    """Test entity is unavailable when coordinator.last_update_success=False."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = False
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, whem.id, MagicMock())
    entity._collection = "whems"
    assert entity.available is False


# --- Parent hub offline tests ---


def test_entity_available_breaker_whem_offline() -> None:
    """Test breaker entity is unavailable when parent WHEM is offline."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    whem = deepcopy(MOCK_WHEM)
    whem.connected = False
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={whem.id: whem},
    )
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, breaker.id, MagicMock())
    assert entity.available is False


def test_entity_available_breaker_panel_offline() -> None:
    """Test breaker entity is unavailable when parent panel is offline."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.iot_whem_id = None
    breaker.residential_breaker_panel_id = MOCK_PANEL.id
    panel = deepcopy(MOCK_PANEL)
    panel.offline = "2026-01-01T00:00:00Z"
    panel.online = None
    data = LevitonData(
        breakers={breaker.id: breaker},
        panels={panel.id: panel},
    )
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "power"
    entity = LevitonEntity(coordinator, description, breaker.id, MagicMock())
    assert entity.available is False


# --- LevitonBreakerControlEntity available tests ---


@pytest.mark.parametrize("state", [
    "NotCommunicating", "CommunicationFailure", "UNDEFINED",
])
def test_control_entity_unavailable_offline_states(state) -> None:
    """Test control entity is unavailable when breaker is in offline state."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.current_state = state
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={whem.id: whem},
    )
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "breaker"
    entity = LevitonBreakerControlEntity(
        coordinator, description, breaker.id, MagicMock()
    )
    assert entity.available is False


def test_control_entity_available_normal_state() -> None:
    """Test control entity is available when breaker is in normal state."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.current_state = "ManualON"
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(
        breakers={breaker.id: breaker},
        whems={whem.id: whem},
    )
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "breaker"
    entity = LevitonBreakerControlEntity(
        coordinator, description, breaker.id, MagicMock()
    )
    assert entity.available is True


def test_control_entity_unavailable_breaker_missing() -> None:
    """Test control entity is unavailable when breaker not in data."""
    data = LevitonData()
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = True
    description = MagicMock()
    description.key = "breaker"
    entity = LevitonBreakerControlEntity(
        coordinator, description, "nonexistent", MagicMock()
    )
    assert entity.available is False
