"""Tests for the Leviton sensor platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from aioleviton import Breaker, Ct, Whem

from homeassistant.components.leviton.coordinator import LevitonData
from homeassistant.components.leviton.sensor import (
    BREAKER_SENSORS,
    CT_SENSORS,
    PANEL_SENSORS,
    WHEM_SENSORS,
    _breaker_leg,
    _breaker_protect_fw,
    _calc_current,
    _panel_total_current,
    _panel_total_energy,
    _panel_total_power,
    _should_include_breaker,
    _whem_leg_current,
    _whem_leg_power,
    _whem_total_current,
    _whem_total_energy,
    _whem_total_power,
)

from .conftest import (
    MOCK_BREAKER_GEN1,
    MOCK_BREAKER_GEN2,
    MOCK_CT,
    MOCK_PANEL,
    MOCK_WHEM,
)


# --- Helper function tests ---


def test_breaker_leg_2_pole() -> None:
    """Test breaker leg returns 'Both' for 2-pole."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.poles = 2
    assert _breaker_leg(breaker) == "Both"


def test_breaker_leg_odd_position() -> None:
    """Test breaker leg returns '1' for odd position."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.poles = 1
    breaker.position = 1
    assert _breaker_leg(breaker) == "1"


def test_breaker_leg_even_position() -> None:
    """Test breaker leg returns '2' for even position."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.poles = 1
    breaker.position = 2
    assert _breaker_leg(breaker) == "2"


def test_breaker_protect_fw_gfci() -> None:
    """Test protect firmware returns GFCI version."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    assert _breaker_protect_fw(breaker) == "FWC1234000100"


def test_breaker_protect_fw_none() -> None:
    """Test protect firmware returns None when neither GFCI nor AFCI."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    assert _breaker_protect_fw(breaker) is None


def test_calc_current_no_calc() -> None:
    """Test calculated current disabled returns raw rmsCurrent."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    data = LevitonData()
    options = {"calculated_current": False}
    assert _calc_current(breaker, data, options) == breaker.rms_current


def test_calc_current_calc_enabled() -> None:
    """Test calculated current from power/voltage."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = 240
    breaker.poles = 1
    breaker.rms_voltage = 120
    data = LevitonData()
    options = {"calculated_current": True}
    result = _calc_current(breaker, data, options)
    assert result == 2.0


def test_calc_current_2_pole_240v() -> None:
    """Test calculated current uses 240V for 2-pole breakers."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = 480
    breaker.poles = 2
    breaker.rms_voltage = None
    data = LevitonData()
    options = {"calculated_current": True, "voltage_208": False}
    result = _calc_current(breaker, data, options)
    assert result == 2.0


def test_calc_current_2_pole_208v() -> None:
    """Test calculated current uses 208V when option enabled."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = 416
    breaker.poles = 2
    breaker.rms_voltage = None
    data = LevitonData()
    options = {"calculated_current": True, "voltage_208": True}
    result = _calc_current(breaker, data, options)
    assert result == 2.0


def test_calc_current_from_whem_voltage() -> None:
    """Test calculated current falls back to WHEM voltage."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = 119
    breaker.poles = 1
    breaker.position = 1
    breaker.rms_voltage = None
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    options = {"calculated_current": True}
    result = _calc_current(breaker, data, options)
    # MOCK_WHEM.rms_voltage_a = 119, so 119/119 = 1.0
    assert result == 1.0


def test_calc_current_no_power() -> None:
    """Test calculated current returns raw value when no power."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = None
    data = LevitonData()
    options = {"calculated_current": True}
    result = _calc_current(breaker, data, options)
    assert result == breaker.rms_current


def test_whem_total_power() -> None:
    """Test WHEM total power sums CT active_power values."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={ct.id: ct})
    result = _whem_total_power(whem, data)
    # active_power=196 + active_power_2=153 = 349
    assert result == 349


def test_whem_total_power_no_cts() -> None:
    """Test WHEM total power returns None with no CTs."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData()
    result = _whem_total_power(whem, data)
    assert result is None


def test_whem_total_current() -> None:
    """Test WHEM total current sums CT rms_current values."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={ct.id: ct})
    result = _whem_total_current(whem, data)
    # rms_current=8 + rms_current_2=6 = 14
    assert result == 14


def test_whem_total_energy() -> None:
    """Test WHEM total energy sums CT energy values."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={ct.id: ct})
    result = _whem_total_energy(whem, data)
    # 5000.0 + 4500.0 = 9500.0
    assert result == 9500.0


def test_whem_leg_power() -> None:
    """Test WHEM leg power returns correct leg value."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={ct.id: ct})
    assert _whem_leg_power(whem, data, 1) == 196
    assert _whem_leg_power(whem, data, 2) == 153


def test_whem_leg_current() -> None:
    """Test WHEM leg current returns correct leg value."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={ct.id: ct})
    assert _whem_leg_current(whem, data, 1) == 8
    assert _whem_leg_current(whem, data, 2) == 6


def test_panel_total_power() -> None:
    """Test panel total power sums breaker power values."""
    panel = deepcopy(MOCK_PANEL)
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.residential_breaker_panel_id = panel.id
    data = LevitonData(breakers={breaker.id: breaker})
    result = _panel_total_power(panel, data)
    assert result == 204


def test_panel_total_power_no_breakers() -> None:
    """Test panel total power returns None with no matching breakers."""
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData()
    result = _panel_total_power(panel, data)
    assert result is None


def test_panel_total_current() -> None:
    """Test panel total current sums breaker current values."""
    panel = deepcopy(MOCK_PANEL)
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.residential_breaker_panel_id = panel.id
    data = LevitonData(breakers={breaker.id: breaker})
    result = _panel_total_current(panel, data)
    assert result == 2


def test_panel_total_energy() -> None:
    """Test panel total energy sums breaker energy values."""
    panel = deepcopy(MOCK_PANEL)
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.residential_breaker_panel_id = panel.id
    data = LevitonData(breakers={breaker.id: breaker})
    result = _panel_total_energy(panel, data)
    assert result == 1500.0


# --- Should-include tests ---


def test_should_include_smart_breaker() -> None:
    """Test smart breaker is included."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    assert _should_include_breaker(breaker, {}) is True


def test_should_exclude_lsbma() -> None:
    """Test LSBMA breaker is excluded."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "LSBMA"
    assert _should_include_breaker(breaker, {}) is False


def test_should_exclude_dummy_when_hide_enabled() -> None:
    """Test placeholder breaker is excluded with hide_dummy enabled."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE-1"
    breaker.lsbma_id = None
    options = {"hide_dummy": True}
    assert _should_include_breaker(breaker, options) is False


def test_should_include_dummy_with_lsbma() -> None:
    """Test placeholder with LSBMA is included even with hide_dummy."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE-1"
    breaker.lsbma_id = "some_lsbma"
    options = {"hide_dummy": True}
    assert _should_include_breaker(breaker, options) is True


def test_should_include_dummy_when_hide_disabled() -> None:
    """Test placeholder breaker is included when hide_dummy disabled."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE-1"
    breaker.lsbma_id = None
    options = {"hide_dummy": False}
    assert _should_include_breaker(breaker, options) is True


# --- Description count tests ---


def test_breaker_sensor_descriptions_count() -> None:
    """Test breaker sensor descriptions tuple has expected entries."""
    assert len(BREAKER_SENSORS) == 16


def test_ct_sensor_descriptions_count() -> None:
    """Test CT sensor descriptions tuple has expected entries."""
    assert len(CT_SENSORS) == 8


def test_whem_sensor_descriptions_count() -> None:
    """Test WHEM sensor descriptions tuple has expected entries."""
    assert len(WHEM_SENSORS) == 20


def test_panel_sensor_descriptions_count() -> None:
    """Test panel sensor descriptions tuple has expected entries."""
    assert len(PANEL_SENSORS) == 16


# --- Value function tests for key sensor types ---


def test_breaker_power_value_fn() -> None:
    """Test breaker power value function."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "power")
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    assert desc.value_fn(breaker, LevitonData(), {}) == 120


def test_breaker_status_value_fn() -> None:
    """Test breaker status value function."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "breaker_status")
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    assert desc.value_fn(breaker, LevitonData(), {}) == "ManualON"


def test_breaker_position_value_fn() -> None:
    """Test breaker position value function."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "position")
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    assert desc.value_fn(breaker, LevitonData(), {}) == 1


def test_ct_power_value_fn() -> None:
    """Test CT total power value function."""
    desc = next(d for d in CT_SENSORS if d.key == "power")
    ct = deepcopy(MOCK_CT)
    assert desc.value_fn(ct) == 349  # 196 + 153


def test_ct_current_value_fn() -> None:
    """Test CT total current value function."""
    desc = next(d for d in CT_SENSORS if d.key == "current")
    ct = deepcopy(MOCK_CT)
    assert desc.value_fn(ct) == 14  # 8 + 6


def test_ct_leg1_power_value_fn() -> None:
    """Test CT leg1 power value function."""
    desc = next(d for d in CT_SENSORS if d.key == "power_leg1")
    ct = deepcopy(MOCK_CT)
    assert desc.value_fn(ct) == 196


def test_whem_voltage_value_fn() -> None:
    """Test WHEM voltage value function (average of legs)."""
    desc = next(d for d in WHEM_SENSORS if d.key == "voltage")
    whem = deepcopy(MOCK_WHEM)
    result = desc.value_fn(whem, LevitonData())
    # (119 + 122) / 2 = 120.5
    assert result == 120.5


def test_whem_frequency_value_fn() -> None:
    """Test WHEM frequency value function."""
    desc = next(d for d in WHEM_SENSORS if d.key == "frequency")
    whem = deepcopy(MOCK_WHEM)
    assert desc.value_fn(whem, LevitonData()) == 60


def test_panel_voltage_value_fn() -> None:
    """Test panel voltage value function."""
    desc = next(d for d in PANEL_SENSORS if d.key == "voltage")
    panel = deepcopy(MOCK_PANEL)
    assert desc.value_fn(panel, LevitonData()) == 120


def test_panel_firmware_main_value_fn() -> None:
    """Test panel firmware main value function."""
    desc = next(d for d in PANEL_SENSORS if d.key == "firmware_main")
    panel = deepcopy(MOCK_PANEL)
    assert desc.value_fn(panel, LevitonData()) == "0.1.91"


# --- Exists function tests ---


def test_breaker_power_exists_smart() -> None:
    """Test power exists for smart breakers."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "power")
    assert desc.exists_fn(MOCK_BREAKER_GEN1) is True


def test_breaker_power_exists_placeholder() -> None:
    """Test power does not exist for placeholder breakers."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "power")
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE"
    assert desc.exists_fn(breaker) is False


def test_breaker_remote_status_exists_gen2() -> None:
    """Test remote_status exists for Gen 2 breakers."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "remote_status")
    assert desc.exists_fn(MOCK_BREAKER_GEN2) is True
    assert desc.exists_fn(MOCK_BREAKER_GEN1) is False


def test_breaker_protect_fw_exists() -> None:
    """Test protect firmware exists only when GFCI or AFCI present."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "firmware_protect")
    assert desc.exists_fn(MOCK_BREAKER_GEN2) is True  # has GFCI
    assert desc.exists_fn(MOCK_BREAKER_GEN1) is False  # no GFCI/AFCI
