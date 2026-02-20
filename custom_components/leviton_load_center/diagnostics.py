"""Diagnostics for the Leviton integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

from .coordinator import LevitonConfigEntry

TO_REDACT_WHEM = {"token", "mac", "localIP", "regKey", "connectedNetwork"}
TO_REDACT_PANEL = {"installerEmail", "installerPhoneNumber", "wifiSSID"}
TO_REDACT_BREAKER = {"serialNumber"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LevitonConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Leviton config entry."""
    data = entry.runtime_data.coordinator.data

    return {
        "whems": {
            whem_id: async_redact_data(whem.raw, TO_REDACT_WHEM)
            for whem_id, whem in data.whems.items()
        },
        "panels": {
            panel_id: async_redact_data(panel.raw, TO_REDACT_PANEL)
            for panel_id, panel in data.panels.items()
        },
        "breakers": {
            breaker_id: async_redact_data(breaker.raw, TO_REDACT_BREAKER)
            for breaker_id, breaker in data.breakers.items()
        },
        "cts": {
            ct_id: ct.raw
            for ct_id, ct in data.cts.items()
        },
    }
