"""Tests for the Leviton sensor platform."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from aioleviton import Breaker, Ct, Whem

from homeassistant.components.leviton_load_center.coordinator import LevitonData
from homeassistant.components.leviton_load_center.entity import should_include_breaker
from homeassistant.components.leviton_load_center.sensor import async_setup_entry
from homeassistant.components.leviton_load_center.sensor_descriptions import (
    BREAKER_SENSORS,
    CT_SENSORS,
    PANEL_SENSORS,
    WHEM_SENSORS,
    _breaker_leg,
    _breaker_protect_fw,
    _breaker_status,
    _calc_current,
    _panel_daily_energy,
    _panel_frequency,
    _panel_leg_current,
    _panel_leg_power,
    _panel_total_current,
    _panel_total_energy,
    _panel_total_power,
    _whem_daily_energy,
    _whem_leg_current,
    _whem_leg_power,
    _whem_total_current,
    _whem_total_energy,
    _whem_total_power,
)

from homeassistant.components.leviton_load_center.coordinator import LevitonRuntimeData

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


@pytest.mark.parametrize("position,expected", [
    (1, "1"), (2, "1"),    # row 1 → Leg 1
    (3, "2"), (4, "2"),    # row 2 → Leg 2
    (5, "1"), (6, "1"),    # row 3 → Leg 1
    (7, "2"), (8, "2"),    # row 4 → Leg 2
    (17, "1"), (18, "1"),  # row 9 → Leg 1
    (19, "2"), (20, "2"),  # row 10 → Leg 2
])
def test_breaker_leg_by_position(position, expected) -> None:
    """Test breaker leg assignment follows paired-row pattern."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.poles = 1
    breaker.position = position
    assert _breaker_leg(breaker) == expected


@pytest.mark.parametrize("raw,expected", [
    ("ManualON", "on"),
    ("ManualOFF", "off"),
    ("COMMUNICATING", "connecting"),
    ("NotCommunicating", "offline"),
    ("CommunicationFailure", "offline"),
    ("UNDEFINED", "offline"),
    ("SoftwareTrip", "software_trip"),
    ("GFCIFault", "gfci_fault"),
    ("AFCISerialArc15AFault", "afci_fault"),
    ("OverCurrentTripPhase1", "overcurrent_trip"),
    ("OverloadTrip", "overload_trip"),
    ("ShortCircuitTrip", "short_circuit_trip"),
    ("UpstreamFault", "upstream_fault"),
    ("SomeUnknownState", None),
    (None, None),
])
def test_breaker_status_mapping(raw, expected) -> None:
    """Test breaker status maps raw currentState to display values."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.current_state = raw
    assert _breaker_status(breaker) == expected


def test_breaker_protect_fw_gfci() -> None:
    """Test protect firmware returns SiLabs first when present."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    # SiLabs takes priority over GFCI
    assert _breaker_protect_fw(breaker) == "FWC2422000100"


def test_breaker_protect_fw_none() -> None:
    """Test protect firmware returns None when no protection FW."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.firmware_version_silabs = None
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


def test_calc_current_whem_voltage_leg2() -> None:
    """Test calculated current falls back to WHEM voltage_b for leg 2 breaker."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = 244
    breaker.poles = 1
    breaker.position = 3  # row 2 → leg 2 → uses voltage_b
    breaker.rms_voltage = None
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData(whems={whem.id: whem})
    options = {"calculated_current": True}
    result = _calc_current(breaker, data, options)
    # MOCK_WHEM.rms_voltage_b = 122, so 244/122 = 2.0
    assert result == 2.0


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
    data = LevitonData(cts={str(ct.id): ct})
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
    data = LevitonData(cts={str(ct.id): ct})
    result = _whem_total_current(whem, data)
    # rms_current=8 + rms_current_2=6 = 14
    assert result == 14


def test_whem_total_energy() -> None:
    """Test WHEM total energy sums CT energy values."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={str(ct.id): ct})
    result = _whem_total_energy(whem, data)
    # 5000.0 + 4500.0 = 9500.0
    assert result == 9500.0


def test_whem_leg_power() -> None:
    """Test WHEM leg power returns correct leg value."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={str(ct.id): ct})
    assert _whem_leg_power(whem, data, 1) == 196
    assert _whem_leg_power(whem, data, 2) == 153


def test_whem_leg_current() -> None:
    """Test WHEM leg current returns correct leg value."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={str(ct.id): ct})
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
    assert should_include_breaker(breaker, {}) is True


def test_should_exclude_lsbma() -> None:
    """Test LSBMA breaker is excluded."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "LSBMA"
    assert should_include_breaker(breaker, {}) is False


def test_should_exclude_dummy_when_hide_enabled() -> None:
    """Test placeholder breaker is excluded with hide_dummy enabled."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE-1"
    breaker.lsbma_id = None
    options = {"hide_dummy": True}
    assert should_include_breaker(breaker, options) is False


def test_should_include_dummy_with_lsbma() -> None:
    """Test placeholder with LSBMA is included even with hide_dummy."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE-1"
    breaker.lsbma_id = "some_lsbma"
    options = {"hide_dummy": True}
    assert should_include_breaker(breaker, options) is True


def test_should_include_dummy_when_hide_disabled() -> None:
    """Test placeholder breaker is included when hide_dummy disabled."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE-1"
    breaker.lsbma_id = None
    options = {"hide_dummy": False}
    assert should_include_breaker(breaker, options) is True


# --- Voltage averaging tests ---


def test_whem_voltage_averages_both_legs() -> None:
    """Test WHEM voltage averages both legs correctly."""
    desc = next(d for d in WHEM_SENSORS if d.key == "voltage")
    whem = deepcopy(MOCK_WHEM)
    # rms_voltage_a=119, rms_voltage_b=122 → (119+122)/2 = 120.5
    assert desc.value_fn(whem, LevitonData()) == 120.5


def test_whem_voltage_one_leg_none() -> None:
    """Test WHEM voltage uses only non-None leg."""
    desc = next(d for d in WHEM_SENSORS if d.key == "voltage")
    whem = deepcopy(MOCK_WHEM)
    whem.rms_voltage_b = None
    assert desc.value_fn(whem, LevitonData()) == 119.0


def test_panel_voltage_averages_both_legs() -> None:
    """Test panel voltage averages both legs when both present."""
    desc = next(d for d in PANEL_SENSORS if d.key == "voltage")
    panel = deepcopy(MOCK_PANEL)
    panel.rms_voltage = 120
    panel.rms_voltage_2 = 118
    assert desc.value_fn(panel, LevitonData()) == 119.0


def test_panel_voltage_returns_zero_when_both_zero() -> None:
    """Test panel voltage returns 0.0 when both legs read 0V (valid measurement)."""
    desc = next(d for d in PANEL_SENSORS if d.key == "voltage")
    panel = deepcopy(MOCK_PANEL)
    panel.rms_voltage = 0
    panel.rms_voltage_2 = 0
    assert desc.value_fn(panel, LevitonData()) == 0.0


def test_panel_voltage_returns_none_when_both_none() -> None:
    """Test panel voltage returns None when both legs are None."""
    desc = next(d for d in PANEL_SENSORS if d.key == "voltage")
    panel = deepcopy(MOCK_PANEL)
    panel.rms_voltage = None
    panel.rms_voltage_2 = None
    assert desc.value_fn(panel, LevitonData()) is None


# --- Protect firmware fallback chain tests ---


def test_breaker_protect_fw_gfci_when_no_silabs() -> None:
    """Test protect firmware returns GFCI when SiLabs is absent."""
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.firmware_version_silabs = None
    assert _breaker_protect_fw(breaker) == "FWC1234000100"


def test_breaker_protect_fw_afci_fallback() -> None:
    """Test protect firmware returns AFCI when SiLabs and GFCI absent."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.firmware_version_silabs = None
    breaker.firmware_version_gfci = None
    breaker.firmware_version_afci = "FWC9999000100"
    assert _breaker_protect_fw(breaker) == "FWC9999000100"


# --- CT None leg handling tests ---


def test_ct_power_with_none_leg() -> None:
    """Test CT total power handles None leg2 via or-0 fallback."""
    ct = deepcopy(MOCK_CT)
    ct.active_power_2 = None
    desc = next(d for d in CT_SENSORS if d.key == "power")
    # 196 + 0 (None fallback) = 196
    assert desc.value_fn(ct, LevitonData()) == 196


def test_ct_energy_with_none_legs() -> None:
    """Test CT lifetime energy handles None values."""
    ct = deepcopy(MOCK_CT)
    ct.energy_consumption = None
    ct.energy_consumption_2 = None
    desc = next(d for d in CT_SENSORS if d.key == "lifetime_energy")
    assert desc.value_fn(ct, LevitonData()) == 0


# --- WHEM/panel leg edge cases ---


def test_whem_leg_power_no_matching_cts() -> None:
    """Test WHEM leg power returns None when no CTs belong to WHEM."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData()  # no CTs
    assert _whem_leg_power(whem, data, 1) is None


def test_whem_leg_current_no_matching_cts() -> None:
    """Test WHEM leg current returns None when no CTs belong to WHEM."""
    whem = deepcopy(MOCK_WHEM)
    data = LevitonData()  # no CTs
    assert _whem_leg_current(whem, data, 1) is None


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
    """Test protect firmware exists when any protection FW present."""
    desc = next(d for d in BREAKER_SENSORS if d.key == "firmware_protect")
    assert desc.exists_fn(MOCK_BREAKER_GEN2) is True  # has SiLabs + GFCI
    # Gen1 also has SiLabs firmware
    breaker_no_fw = deepcopy(MOCK_BREAKER_GEN1)
    breaker_no_fw.firmware_version_silabs = None
    assert desc.exists_fn(breaker_no_fw) is False  # no SiLabs/GFCI/AFCI


# --- WHEM daily energy tests ---


def test_whem_daily_energy_with_baselines() -> None:
    """Test WHEM daily energy sums (ct_total - baseline) across CTs."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    # ct total = 5000 + 4500 = 9500, baseline = 9000 → daily = 500
    data = LevitonData(
        cts={str(ct.id): ct},
        daily_baselines={f"ct_{ct.id}": 9000.0},
    )
    result = _whem_daily_energy(whem, data)
    assert result == 500.0


def test_whem_daily_energy_negative_clamped_to_zero() -> None:
    """Test WHEM daily energy clamps negative values to 0 (meter reset)."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    # ct total = 5000 + 4500 = 9500, baseline = 10000 → negative → clamped to 0
    data = LevitonData(
        cts={str(ct.id): ct},
        daily_baselines={f"ct_{ct.id}": 10000.0},
    )
    result = _whem_daily_energy(whem, data)
    assert result == 0.0


def test_whem_daily_energy_no_baselines() -> None:
    """Test WHEM daily energy returns None when no baselines exist."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    data = LevitonData(cts={str(ct.id): ct}, daily_baselines={})
    result = _whem_daily_energy(whem, data)
    assert result is None


def test_whem_daily_energy_no_matching_cts() -> None:
    """Test WHEM daily energy returns None when no CTs belong to WHEM."""
    whem = deepcopy(MOCK_WHEM)
    ct = deepcopy(MOCK_CT)
    ct.iot_whem_id = "other_whem"
    data = LevitonData(
        cts={str(ct.id): ct},
        daily_baselines={f"ct_{ct.id}": 9000.0},
    )
    result = _whem_daily_energy(whem, data)
    assert result is None


# --- Panel daily energy tests ---


def test_panel_daily_energy_with_baselines() -> None:
    """Test panel daily energy sums breaker daily energy."""
    panel = deepcopy(MOCK_PANEL)
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.residential_breaker_panel_id = panel.id
    # energy_consumption=1500, baseline=1400 → daily=100
    data = LevitonData(
        breakers={breaker.id: breaker},
        daily_baselines={breaker.id: 1400.0},
    )
    result = _panel_daily_energy(panel, data)
    assert result == 100.0


def test_panel_daily_energy_no_baselines() -> None:
    """Test panel daily energy returns None when baselines missing."""
    panel = deepcopy(MOCK_PANEL)
    breaker = deepcopy(MOCK_BREAKER_GEN2)
    breaker.residential_breaker_panel_id = panel.id
    data = LevitonData(
        breakers={breaker.id: breaker},
        daily_baselines={},
    )
    result = _panel_daily_energy(panel, data)
    assert result is None


# --- Panel leg power tests ---


@pytest.mark.parametrize("leg,expected", [(1, 100), (2, 200)])
def test_panel_leg_power(leg, expected) -> None:
    """Test panel leg power sums only the breakers on that leg."""
    panel = deepcopy(MOCK_PANEL)
    b1 = deepcopy(MOCK_BREAKER_GEN1)
    b1.residential_breaker_panel_id = panel.id
    b1.position = 1  # leg 1
    b1.power = 100
    b2 = deepcopy(MOCK_BREAKER_GEN2)
    b2.residential_breaker_panel_id = panel.id
    b2.position = 3  # leg 2
    b2.power = 200
    data = LevitonData(breakers={b1.id: b1, b2.id: b2})
    assert _panel_leg_power(panel, data, leg) == expected


def test_panel_leg_power_no_breakers() -> None:
    """Test panel leg power returns None when no breakers match."""
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData()
    result = _panel_leg_power(panel, data, 1)
    assert result is None


# --- Panel leg current tests ---


@pytest.mark.parametrize("leg,expected", [(1, 5), (2, 10)])
def test_panel_leg_current(leg, expected) -> None:
    """Test panel leg current sums only the breakers on that leg."""
    panel = deepcopy(MOCK_PANEL)
    b1 = deepcopy(MOCK_BREAKER_GEN1)
    b1.residential_breaker_panel_id = panel.id
    b1.position = 1  # leg 1
    b1.rms_current = 5
    b2 = deepcopy(MOCK_BREAKER_GEN2)
    b2.residential_breaker_panel_id = panel.id
    b2.position = 3  # leg 2
    b2.rms_current = 10
    data = LevitonData(breakers={b1.id: b1, b2.id: b2})
    assert _panel_leg_current(panel, data, leg) == expected


# --- Panel frequency tests ---


@pytest.mark.parametrize("position,leg,freq", [(1, 1, 60.0), (3, 2, 60.1)])
def test_panel_frequency(position, leg, freq) -> None:
    """Test panel frequency returns line_frequency from the correct leg."""
    panel = deepcopy(MOCK_PANEL)
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.residential_breaker_panel_id = panel.id
    breaker.position = position
    breaker.line_frequency = freq
    data = LevitonData(breakers={breaker.id: breaker})
    assert _panel_frequency(panel, data, leg) == freq


def test_panel_frequency_no_breakers() -> None:
    """Test panel frequency returns None when no breakers match."""
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData()
    result = _panel_frequency(panel, data, 1)
    assert result is None


# --- Calc current edge case ---


def test_calc_current_zero_divisor() -> None:
    """Test calculated current returns rms_current when voltage=0."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.power = 120
    breaker.poles = 1
    breaker.rms_voltage = 0
    data = LevitonData()
    options = {"calculated_current": True}
    result = _calc_current(breaker, data, options)
    assert result == breaker.rms_current


# --- Platform setup tests ---


async def test_sensor_setup_entry_creates_entities() -> None:
    """Test async_setup_entry creates correct number of sensor entities."""
    gen1 = deepcopy(MOCK_BREAKER_GEN1)  # is_smart=True
    gen2 = deepcopy(MOCK_BREAKER_GEN2)  # is_smart=True
    ct = deepcopy(MOCK_CT)
    whem = deepcopy(MOCK_WHEM)
    panel = deepcopy(MOCK_PANEL)
    data = LevitonData(
        breakers={gen1.id: gen1, gen2.id: gen2},
        cts={str(ct.id): ct},
        whems={whem.id: whem},
        panels={panel.id: panel},
    )
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    from homeassistant.components.leviton_load_center.sensor import (
        LevitonBreakerSensor,
        LevitonCtSensor,
        LevitonPanelSensor,
        LevitonWhemSensor,
    )
    breaker_sensors = [e for e in added_entities if isinstance(e, LevitonBreakerSensor)]
    ct_sensors = [e for e in added_entities if isinstance(e, LevitonCtSensor)]
    whem_sensors = [e for e in added_entities if isinstance(e, LevitonWhemSensor)]
    panel_sensors = [e for e in added_entities if isinstance(e, LevitonPanelSensor)]

    # Both breakers are smart, exact count from exists_fn
    expected_breaker = sum(1 for d in BREAKER_SENSORS if d.exists_fn(gen1)) + sum(
        1 for d in BREAKER_SENSORS if d.exists_fn(gen2)
    )
    assert len(breaker_sensors) == expected_breaker
    # 1 CT × 10 descriptions
    assert len(ct_sensors) == len(CT_SENSORS)
    # 1 WHEM × 22 descriptions
    assert len(whem_sensors) == len(WHEM_SENSORS)
    # 1 panel × 25 descriptions
    assert len(panel_sensors) == len(PANEL_SENSORS)
    # Total is sum of all
    assert len(added_entities) == len(breaker_sensors) + len(ct_sensors) + len(whem_sensors) + len(panel_sensors)


async def test_sensor_setup_skips_unused_cts() -> None:
    """Test async_setup_entry skips CTs with usage_type NOT_USED."""
    ct = deepcopy(MOCK_CT)
    ct.usage_type = "NOT_USED"
    data = LevitonData(cts={str(ct.id): ct})
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    assert len(added_entities) == 0


async def test_sensor_setup_skips_excluded_breakers() -> None:
    """Test async_setup_entry skips placeholder breakers when hide_dummy=True."""
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.model = "NONE"
    breaker.lsbma_id = None
    data = LevitonData(
        breakers={breaker.id: breaker},
    )
    coordinator = MagicMock()
    coordinator.data = data
    entry = MagicMock()
    entry.options = {"hide_dummy": True}
    entry.runtime_data = LevitonRuntimeData(client=MagicMock(), coordinator=coordinator)

    added_entities = []
    await async_setup_entry(MagicMock(), entry, added_entities.extend)

    assert len(added_entities) == 0
