"""Sensor entity descriptions for the Leviton integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from aioleviton import Breaker, Ct, Panel, Whem

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_CALCULATED_CURRENT,
    CONF_VOLTAGE_208,
    DEFAULT_CALCULATED_CURRENT,
    DEFAULT_VOLTAGE_208,
    STATE_AFCI_MISWIRE,
    STATE_AFCI_PARALLEL_FAULT,
    STATE_AFCI_SERIAL_ARC_10A,
    STATE_AFCI_SERIAL_ARC_15A,
    STATE_AFCI_SERIAL_ARC_20A,
    STATE_AFCI_SERIAL_ARC_30A,
    STATE_AFCI_SERIAL_ARC_5A,
    STATE_COMMUNICATION_FAILURE,
    STATE_COMMUNICATING,
    STATE_GFCI_FAULT,
    STATE_MANUAL_OFF,
    STATE_MANUAL_ON,
    STATE_NOT_COMMUNICATING,
    STATE_OVERCURRENT_TRIP_1,
    STATE_OVERCURRENT_TRIP_2,
    STATE_OVERLOAD_TRIP,
    STATE_REMOTE_OFF,
    STATE_REMOTE_ON,
    STATE_SHORT_CIRCUIT_TRIP,
    STATE_SOFTWARE_TRIP,
    STATE_UNDEFINED,
    STATE_UPSTREAM_FAULT,
    VOLTAGE_120,
    VOLTAGE_208,
    VOLTAGE_240,
)
from .coordinator import LevitonData
from .energy import calc_daily_energy


# --- Description dataclasses ---


@dataclass(frozen=True, kw_only=True)
class LevitonBreakerSensorDescription(SensorEntityDescription):
    """Describe a Leviton breaker sensor."""

    value_fn: Callable[[Breaker, LevitonData, Mapping[str, Any]], Any]
    exists_fn: Callable[[Breaker], bool] = lambda _: True


@dataclass(frozen=True, kw_only=True)
class LevitonCtSensorDescription(SensorEntityDescription):
    """Describe a Leviton CT sensor."""

    value_fn: Callable[[Ct, LevitonData], Any]


@dataclass(frozen=True, kw_only=True)
class LevitonWhemSensorDescription(SensorEntityDescription):
    """Describe a Leviton WHEM sensor."""

    value_fn: Callable[[Whem, LevitonData], Any]


@dataclass(frozen=True, kw_only=True)
class LevitonPanelSensorDescription(SensorEntityDescription):
    """Describe a Leviton DAU panel sensor."""

    value_fn: Callable[[Panel, LevitonData], Any]


# --- Helper functions (must be defined before descriptions that use them) ---


def _breaker_power(breaker: Breaker) -> int | None:
    """Total power across all poles of a breaker."""
    if breaker.power is None:
        return None
    if breaker.poles == 2:
        return breaker.power + (breaker.power_2 or 0)
    return breaker.power


_BREAKER_STATUS_MAP: dict[str, str] = {
    STATE_MANUAL_ON: "on",
    STATE_MANUAL_OFF: "off",
    STATE_COMMUNICATING: "connecting",
    STATE_NOT_COMMUNICATING: "offline",
    STATE_COMMUNICATION_FAILURE: "offline",
    STATE_UNDEFINED: "offline",
    STATE_SOFTWARE_TRIP: "software_trip",
    STATE_GFCI_FAULT: "gfci_fault",
    STATE_AFCI_MISWIRE: "afci_miswire",
    STATE_AFCI_PARALLEL_FAULT: "afci_fault",
    STATE_AFCI_SERIAL_ARC_5A: "afci_fault",
    STATE_AFCI_SERIAL_ARC_10A: "afci_fault",
    STATE_AFCI_SERIAL_ARC_15A: "afci_fault",
    STATE_AFCI_SERIAL_ARC_20A: "afci_fault",
    STATE_AFCI_SERIAL_ARC_30A: "afci_fault",
    STATE_OVERCURRENT_TRIP_1: "overcurrent_trip",
    STATE_OVERCURRENT_TRIP_2: "overcurrent_trip",
    STATE_OVERLOAD_TRIP: "overload_trip",
    STATE_SHORT_CIRCUIT_TRIP: "short_circuit_trip",
    STATE_UPSTREAM_FAULT: "upstream_fault",
}

BREAKER_STATUS_OPTIONS: list[str] = sorted(set(_BREAKER_STATUS_MAP.values()))

REMOTE_STATUS_MAP: dict[str, str] = {
    STATE_REMOTE_ON: "on",
    STATE_REMOTE_OFF: "off",
}

REMOTE_STATUS_OPTIONS: list[str] = sorted(REMOTE_STATUS_MAP.values())


def _breaker_status(breaker: Breaker) -> str | None:
    """Map raw currentState to an enum option key."""
    if breaker.current_state is None:
        return None
    return _BREAKER_STATUS_MAP.get(breaker.current_state)


def _breaker_energy(breaker: Breaker) -> float | None:
    """Total lifetime energy across all poles of a breaker."""
    if breaker.energy_consumption is None:
        return None
    if breaker.poles == 2:
        return round(
            breaker.energy_consumption + (breaker.energy_consumption_2 or 0), 3
        )
    return breaker.energy_consumption


def _breaker_leg(breaker: Breaker) -> str:
    """Determine which leg a breaker is on based on position.

    Standard US split-phase panel: legs alternate in pairs of two.
    Leg 1: positions 1,2, 5,6, 9,10, 13,14, 17,18, ...
    Leg 2: positions 3,4, 7,8, 11,12, 15,16, 19,20, ...
    """
    if breaker.poles == 2:
        return "Both"
    if ((breaker.position - 1) // 2) % 2 == 0:
        return "1"
    return "2"


def _breaker_protect_fw(breaker: Breaker) -> str | None:
    """Get the protection firmware (SiLabs for dual-sensing, or GFCI/AFCI)."""
    return (
        breaker.firmware_version_silabs
        or breaker.firmware_version_gfci
        or breaker.firmware_version_afci
    )


def _calc_current(
    breaker: Breaker, data: LevitonData, options: dict[str, Any]
) -> float | None:
    """Calculate current, optionally from power/voltage."""
    use_calc = options.get(CONF_CALCULATED_CURRENT, DEFAULT_CALCULATED_CURRENT)
    if not use_calc:
        return breaker.rms_current

    power = _breaker_power(breaker)
    if power is None:
        return breaker.rms_current

    if breaker.poles == 2:
        use_208 = options.get(CONF_VOLTAGE_208, DEFAULT_VOLTAGE_208)
        divisor = float(VOLTAGE_208 if use_208 else VOLTAGE_240)
    else:
        divisor = float(VOLTAGE_120)
        if breaker.rms_voltage:
            divisor = float(breaker.rms_voltage)
        elif breaker.iot_whem_id and breaker.iot_whem_id in data.whems:
            whem = data.whems[breaker.iot_whem_id]
            if _is_on_leg(breaker.position, 1) and whem.rms_voltage_a:
                divisor = float(whem.rms_voltage_a)
            elif _is_on_leg(breaker.position, 2) and whem.rms_voltage_b:
                divisor = float(whem.rms_voltage_b)

    if divisor == 0:
        return breaker.rms_current

    return round(power / divisor, 2)


def _whem_total_power(whem: Whem, data: LevitonData) -> int | None:
    """Sum CT power for a WHEM hub, falling back to breaker sum."""
    total = 0
    found = False
    for ct in data.cts.values():
        if ct.iot_whem_id == whem.id:
            total += (ct.active_power or 0) + (ct.active_power_2 or 0)
            found = True
    if found:
        return total
    for breaker in data.breakers.values():
        if breaker.iot_whem_id == whem.id:
            total += _breaker_power(breaker) or 0
            found = True
    return total if found else None


def _whem_total_current(whem: Whem, data: LevitonData) -> int | None:
    """Sum CT current for a WHEM hub, falling back to breaker sum."""
    total = 0
    found = False
    for ct in data.cts.values():
        if ct.iot_whem_id == whem.id:
            total += (ct.rms_current or 0) + (ct.rms_current_2 or 0)
            found = True
    if found:
        return total
    for breaker in data.breakers.values():
        if breaker.iot_whem_id == whem.id:
            total += breaker.rms_current or 0
            found = True
    return total if found else None


def _whem_total_energy(whem: Whem, data: LevitonData) -> float | None:
    """Sum CT energy for a WHEM hub, falling back to breaker sum."""
    total = 0.0
    found = False
    for ct in data.cts.values():
        if ct.iot_whem_id == whem.id:
            total += (ct.energy_consumption or 0) + (
                ct.energy_consumption_2 or 0
            )
            found = True
    if found:
        return round(total, 3)
    for breaker in data.breakers.values():
        if breaker.iot_whem_id == whem.id:
            total += _breaker_energy(breaker) or 0
            found = True
    return round(total, 3) if found else None


def _whem_daily_energy(whem: Whem, data: LevitonData) -> float | None:
    """Sum CT daily energy for a WHEM hub, falling back to breaker sum."""
    total = 0.0
    found = False
    for ct in data.cts.values():
        if ct.iot_whem_id == whem.id:
            ct_total = (ct.energy_consumption or 0) + (
                ct.energy_consumption_2 or 0
            )
            baseline = data.daily_baselines.get(f"ct_{ct.id}")
            if baseline is not None:
                daily = ct_total - baseline
                total += max(0.0, daily)
                found = True
    if found:
        return round(total, 2)
    for breaker in data.breakers.values():
        if breaker.iot_whem_id == whem.id:
            daily = calc_daily_energy(breaker.id, _breaker_energy(breaker), data)
            if daily is not None:
                total += daily
                found = True
    return round(total, 2) if found else None


def _whem_voltage(whem: Whem, data: LevitonData) -> float | None:
    """Average non-None voltage legs for a WHEM hub."""
    vals = [v for v in (whem.rms_voltage_a, whem.rms_voltage_b) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _whem_frequency(whem: Whem, data: LevitonData) -> float | None:
    """Average non-None frequency legs for a WHEM hub."""
    vals = [v for v in (whem.frequency_a, whem.frequency_b) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _whem_leg_power(whem: Whem, data: LevitonData, leg: int) -> int | None:
    """Get CT power for a specific leg."""
    for ct in data.cts.values():
        if ct.iot_whem_id == whem.id:
            return ct.active_power if leg == 1 else ct.active_power_2
    return None


def _whem_leg_current(whem: Whem, data: LevitonData, leg: int) -> int | None:
    """Get CT current for a specific leg."""
    for ct in data.cts.values():
        if ct.iot_whem_id == whem.id:
            return ct.rms_current if leg == 1 else ct.rms_current_2
    return None


def _panel_voltage(panel: Panel, data: LevitonData) -> float | None:
    """Average non-None voltage legs for a DAU panel."""
    vals = [v for v in (panel.rms_voltage, panel.rms_voltage_2) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _panel_total_power(panel: Panel, data: LevitonData) -> int | None:
    """Sum breaker power for a DAU panel."""
    total = 0
    found = False
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id == panel.id:
            total += _breaker_power(breaker) or 0
            found = True
    return total if found else None


def _panel_total_current(panel: Panel, data: LevitonData) -> int | None:
    """Sum breaker current for a DAU panel.

    For 2-pole breakers, current is the same on both poles (series circuit),
    so we only count pole 1 to avoid double-counting.
    """
    total = 0
    found = False
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id == panel.id:
            total += breaker.rms_current or 0
            found = True
    return total if found else None


def _panel_total_energy(panel: Panel, data: LevitonData) -> float | None:
    """Sum breaker energy for a DAU panel."""
    total = 0.0
    found = False
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id == panel.id:
            total += _breaker_energy(breaker) or 0
            found = True
    return round(total, 3) if found else None


def _panel_daily_energy(panel: Panel, data: LevitonData) -> float | None:
    """Sum breaker daily energy for a DAU panel."""
    total = 0.0
    found = False
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id == panel.id:
            daily = calc_daily_energy(
                breaker.id, _breaker_energy(breaker), data
            )
            if daily is not None:
                total += daily
                found = True
    return round(total, 2) if found else None


def _is_on_leg(position: int, leg: int) -> bool:
    """Check if a breaker position is on the given leg (1 or 2).

    Leg 1: positions 1,2, 5,6, 9,10, 13,14, 17,18, ...
    Leg 2: positions 3,4, 7,8, 11,12, 15,16, 19,20, ...
    """
    on_leg1 = ((position - 1) // 2) % 2 == 0
    return on_leg1 if leg == 1 else not on_leg1


def _panel_leg_power(panel: Panel, data: LevitonData, leg: int) -> int | None:
    """Sum breaker power for a specific leg of a DAU panel."""
    total = 0
    found = False
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id != panel.id:
            continue
        if _is_on_leg(breaker.position, leg):
            total += breaker.power or 0
            found = True
    return total if found else None


def _panel_leg_current(
    panel: Panel, data: LevitonData, leg: int
) -> int | None:
    """Sum breaker current for a specific leg of a DAU panel."""
    total = 0
    found = False
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id != panel.id:
            continue
        if _is_on_leg(breaker.position, leg):
            total += breaker.rms_current or 0
            found = True
    return total if found else None


def _panel_frequency_avg(panel: Panel, data: LevitonData) -> float | None:
    """Average frequency across both legs of a DAU panel."""
    vals = [
        v
        for v in (_panel_frequency(panel, data, 1), _panel_frequency(panel, data, 2))
        if v is not None
    ]
    return sum(vals) / len(vals) if vals else None


def _panel_frequency(
    panel: Panel, data: LevitonData, leg: int
) -> float | None:
    """Get line frequency from the first breaker on a leg of a DAU panel.

    Each breaker reports its own leg's frequency in line_frequency.
    line_frequency_2 is the second pole of a 2-pole breaker, not the second leg.
    """
    for breaker in data.breakers.values():
        if breaker.residential_breaker_panel_id != panel.id:
            continue
        if not _is_on_leg(breaker.position, leg):
            continue
        if breaker.line_frequency:
            return breaker.line_frequency
    return None


def _ct_energy(ct: Ct) -> float:
    """Total lifetime energy across both legs of a CT."""
    return round((ct.energy_consumption or 0) + (ct.energy_consumption_2 or 0), 3)


# --- Breaker sensor descriptions ---

BREAKER_SENSORS: tuple[LevitonBreakerSensorDescription, ...] = (
    LevitonBreakerSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b, _d, _o: _breaker_power(b),
        exists_fn=lambda b: b.is_smart or b.has_lsbma,
    ),
    LevitonBreakerSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_calc_current,
        exists_fn=lambda b: b.is_smart or b.has_lsbma,
    ),
    LevitonBreakerSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda b, d, _o: calc_daily_energy(
            b.id, _breaker_energy(b), d
        ),
        exists_fn=lambda b: b.is_smart or b.has_lsbma,
    ),
    LevitonBreakerSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: _breaker_energy(b),
        exists_fn=lambda b: b.is_smart or b.has_lsbma,
    ),
    LevitonBreakerSensorDescription(
        key="breaker_status",
        translation_key="breaker_status",
        device_class=SensorDeviceClass.ENUM,
        options=BREAKER_STATUS_OPTIONS,
        value_fn=lambda b, _d, _o: _breaker_status(b),
        exists_fn=lambda b: b.is_smart,
    ),
    LevitonBreakerSensorDescription(
        key="remote_status",
        translation_key="remote_status",
        device_class=SensorDeviceClass.ENUM,
        options=REMOTE_STATUS_OPTIONS,
        value_fn=lambda b, _d, _o: REMOTE_STATUS_MAP.get(b.remote_state or ""),
        exists_fn=lambda b: b.is_gen2,
    ),
    # Diagnostics
    LevitonBreakerSensorDescription(
        key="amp_rating",
        translation_key="amp_rating",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.current_rating,
        exists_fn=lambda b: b.is_smart,
    ),
    LevitonBreakerSensorDescription(
        key="ble_mac",
        translation_key="ble_mac",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: format_mac(b.id) if b.is_smart else None,
        exists_fn=lambda b: b.is_smart,
    ),
    LevitonBreakerSensorDescription(
        key="ble_rssi",
        translation_key="ble_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.ble_rssi,
        exists_fn=lambda b: b.is_smart,
    ),
    LevitonBreakerSensorDescription(
        key="firmware_ble",
        translation_key="firmware_ble",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.firmware_version_ble,
        exists_fn=lambda b: b.is_smart,
    ),
    LevitonBreakerSensorDescription(
        key="firmware_meter",
        translation_key="firmware_meter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.firmware_version_meter,
        exists_fn=lambda b: b.is_smart,
    ),
    LevitonBreakerSensorDescription(
        key="firmware_protect",
        translation_key="firmware_protect",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: _breaker_protect_fw(b),
        exists_fn=lambda b: b.is_smart and bool(_breaker_protect_fw(b)),
    ),
    LevitonBreakerSensorDescription(
        key="leg",
        translation_key="leg",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: _breaker_leg(b),
    ),
    LevitonBreakerSensorDescription(
        key="poles",
        translation_key="poles",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.poles,
    ),
    LevitonBreakerSensorDescription(
        key="position",
        translation_key="position",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.position,
    ),
    LevitonBreakerSensorDescription(
        key="serial_number",
        translation_key="serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda b, _d, _o: b.serial_number,
        exists_fn=lambda b: b.is_smart,
    ),
)

# --- CT sensor descriptions ---

CT_SENSORS: tuple[LevitonCtSensorDescription, ...] = (
    LevitonCtSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c, _d: (c.active_power or 0) + (c.active_power_2 or 0),
    ),
    LevitonCtSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c, _d: (c.rms_current or 0) + (c.rms_current_2 or 0),
    ),
    LevitonCtSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda c, d: calc_daily_energy(
            f"ct_{c.id}", _ct_energy(c), d
        ),
    ),
    # Diagnostics
    LevitonCtSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: _ct_energy(c),
    ),
    LevitonCtSensorDescription(
        key="current_leg1",
        translation_key="current_leg1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: c.rms_current,
    ),
    LevitonCtSensorDescription(
        key="current_leg2",
        translation_key="current_leg2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: c.rms_current_2,
    ),
    LevitonCtSensorDescription(
        key="power_leg1",
        translation_key="power_leg1",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: c.active_power,
    ),
    LevitonCtSensorDescription(
        key="power_leg2",
        translation_key="power_leg2",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: c.active_power_2,
    ),
    LevitonCtSensorDescription(
        key="lifetime_energy_import",
        translation_key="lifetime_energy_import",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: round(
            (c.energy_import or 0) + (c.energy_import_2 or 0), 3
        ),
    ),
    LevitonCtSensorDescription(
        key="usage_type",
        translation_key="usage_type",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c, _d: c.usage_type,
    ),
)

# --- WHEM sensor descriptions ---

WHEM_SENSORS: tuple[LevitonWhemSensorDescription, ...] = (
    LevitonWhemSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_whem_total_power,
    ),
    LevitonWhemSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_whem_total_current,
    ),
    LevitonWhemSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=_whem_daily_energy,
    ),
    LevitonWhemSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_whem_voltage,
    ),
    LevitonWhemSensorDescription(
        key="voltage_leg1",
        translation_key="voltage_leg1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, _d: w.rms_voltage_a,
    ),
    LevitonWhemSensorDescription(
        key="voltage_leg2",
        translation_key="voltage_leg2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, _d: w.rms_voltage_b,
    ),
    LevitonWhemSensorDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_whem_frequency,
    ),
    LevitonWhemSensorDescription(
        key="frequency_leg1",
        translation_key="frequency_leg1",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, _d: w.frequency_a,
    ),
    LevitonWhemSensorDescription(
        key="frequency_leg2",
        translation_key="frequency_leg2",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, _d: w.frequency_b,
    ),
    LevitonWhemSensorDescription(
        key="power_leg1",
        translation_key="power_leg1",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, d: _whem_leg_power(w, d, 1),
    ),
    LevitonWhemSensorDescription(
        key="power_leg2",
        translation_key="power_leg2",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, d: _whem_leg_power(w, d, 2),
    ),
    LevitonWhemSensorDescription(
        key="current_leg1",
        translation_key="current_leg1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, d: _whem_leg_current(w, d, 1),
    ),
    LevitonWhemSensorDescription(
        key="current_leg2",
        translation_key="current_leg2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda w, d: _whem_leg_current(w, d, 2),
    ),
    # Diagnostics
    LevitonWhemSensorDescription(
        key="firmware_ble",
        translation_key="firmware_ble",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: w.version_ble,
    ),
    LevitonWhemSensorDescription(
        key="firmware_main",
        translation_key="firmware_main",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: w.version,
    ),
    LevitonWhemSensorDescription(
        key="ip_address",
        translation_key="ip_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: w.local_ip,
    ),
    LevitonWhemSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_whem_total_energy,
    ),
    LevitonWhemSensorDescription(
        key="mac_address",
        translation_key="mac_address",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: format_mac(w.mac) if w.mac else None,
    ),
    LevitonWhemSensorDescription(
        key="residence_id",
        translation_key="residence_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: w.residence_id,
    ),
    LevitonWhemSensorDescription(
        key="serial_number",
        translation_key="serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: w.serial,
    ),
    LevitonWhemSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: w.rssi,
    ),
    LevitonWhemSensorDescription(
        key="firmware_update",
        translation_key="firmware_update",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda w, _d: (
            w.raw.get("downloaded")
            if w.raw.get("downloaded") and w.raw.get("downloaded") != w.version
            else "Up to date"
        ),
    ),
)

# --- DAU panel sensor descriptions ---

PANEL_SENSORS: tuple[LevitonPanelSensorDescription, ...] = (
    LevitonPanelSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_panel_total_power,
    ),
    LevitonPanelSensorDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_panel_total_current,
    ),
    LevitonPanelSensorDescription(
        key="energy",
        translation_key="energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=_panel_daily_energy,
    ),
    LevitonPanelSensorDescription(
        key="voltage",
        translation_key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_panel_voltage,
    ),
    LevitonPanelSensorDescription(
        key="voltage_leg1",
        translation_key="voltage_leg1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, _d: p.rms_voltage,
    ),
    LevitonPanelSensorDescription(
        key="voltage_leg2",
        translation_key="voltage_leg2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, _d: p.rms_voltage_2,
    ),
    LevitonPanelSensorDescription(
        key="current_leg1",
        translation_key="current_leg1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, d: _panel_leg_current(p, d, 1),
    ),
    LevitonPanelSensorDescription(
        key="current_leg2",
        translation_key="current_leg2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, d: _panel_leg_current(p, d, 2),
    ),
    LevitonPanelSensorDescription(
        key="power_leg1",
        translation_key="power_leg1",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, d: _panel_leg_power(p, d, 1),
    ),
    LevitonPanelSensorDescription(
        key="power_leg2",
        translation_key="power_leg2",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, d: _panel_leg_power(p, d, 2),
    ),
    LevitonPanelSensorDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_panel_frequency_avg,
    ),
    LevitonPanelSensorDescription(
        key="frequency_leg1",
        translation_key="frequency_leg1",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, d: _panel_frequency(p, d, 1),
    ),
    LevitonPanelSensorDescription(
        key="frequency_leg2",
        translation_key="frequency_leg2",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda p, d: _panel_frequency(p, d, 2),
    ),
    # Diagnostics
    LevitonPanelSensorDescription(
        key="firmware_bcm",
        translation_key="firmware_bcm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.version_bcm,
    ),
    LevitonPanelSensorDescription(
        key="firmware_bsm",
        translation_key="firmware_bsm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.version_bsm,
    ),
    LevitonPanelSensorDescription(
        key="firmware_bsm_radio",
        translation_key="firmware_bsm_radio",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.version_bsm_radio,
    ),
    LevitonPanelSensorDescription(
        key="firmware_main",
        translation_key="firmware_main",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.package_ver,
    ),
    LevitonPanelSensorDescription(
        key="firmware_ncm",
        translation_key="firmware_ncm",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.version_ncm,
    ),
    LevitonPanelSensorDescription(
        key="lifetime_energy",
        translation_key="lifetime_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_panel_total_energy,
    ),
    LevitonPanelSensorDescription(
        key="residence_id",
        translation_key="residence_id",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.residence_id,
    ),
    LevitonPanelSensorDescription(
        key="serial_number",
        translation_key="serial_number",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.id,
    ),
    LevitonPanelSensorDescription(
        key="wifi_mode",
        translation_key="wifi_mode",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.wifi_mode,
    ),
    LevitonPanelSensorDescription(
        key="wifi_rssi",
        translation_key="wifi_rssi",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.wifi_rssi,
    ),
    LevitonPanelSensorDescription(
        key="wifi_ssid",
        translation_key="wifi_ssid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: p.wifi_ssid,
    ),
    LevitonPanelSensorDescription(
        key="firmware_update",
        translation_key="firmware_update",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda p, _d: (
            p.raw.get("updateVersion")
            if p.raw.get("updateAvailability")
            and p.raw.get("updateAvailability") != "UP_TO_DATE"
            else "Up to date"
        ),
    ),
)
