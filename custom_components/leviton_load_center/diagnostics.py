"""Diagnostics for the Leviton integration."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import LevitonConfigEntry

TO_REDACT_WHEM = {"token", "mac", "localIP", "regKey", "connectedNetwork"}
TO_REDACT_PANEL = {"installerEmail", "installerPhoneNumber", "wifiSSID"}
TO_REDACT_BREAKER = {"serialNumber"}


def _redact_dict(data: dict[str, Any], keys_to_redact: set[str]) -> dict[str, Any]:
    """Redact sensitive keys from a dictionary."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        if key in keys_to_redact:
            result[key] = "**REDACTED**"
        else:
            result[key] = value
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LevitonConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Leviton config entry."""
    data = entry.runtime_data.coordinator.data

    return {
        "whems": {
            whem_id: _redact_dict(whem.raw, TO_REDACT_WHEM)
            for whem_id, whem in data.whems.items()
        },
        "panels": {
            panel_id: _redact_dict(panel.raw, TO_REDACT_PANEL)
            for panel_id, panel in data.panels.items()
        },
        "breakers": {
            breaker_id: _redact_dict(breaker.raw, TO_REDACT_BREAKER)
            for breaker_id, breaker in data.breakers.items()
        },
        "cts": {
            ct_id: ct.raw
            for ct_id, ct in data.cts.items()
        },
    }
