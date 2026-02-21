"""Tests for the Leviton diagnostics."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

from homeassistant.components.leviton_load_center.coordinator import (
    LevitonData,
    LevitonRuntimeData,
)
from homeassistant.components.leviton_load_center.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import MOCK_BREAKER_GEN1, MOCK_CT, MOCK_PANEL, MOCK_WHEM


async def test_diagnostics_output(hass) -> None:
    """Test diagnostics returns expected structure with redacted data."""
    whem = deepcopy(MOCK_WHEM)
    whem.raw = {"id": whem.id, "name": "Test", "mac": "AA:BB:CC", "token": "secret"}
    panel = deepcopy(MOCK_PANEL)
    panel.raw = {"id": panel.id, "wifiSSID": "MyNetwork"}
    breaker = deepcopy(MOCK_BREAKER_GEN1)
    breaker.raw = {"id": breaker.id, "serialNumber": "SN123", "power": 120}
    ct = deepcopy(MOCK_CT)
    ct.raw = {"id": ct.id, "activePower": 196}

    data = LevitonData(
        whems={whem.id: whem},
        panels={panel.id: panel},
        breakers={breaker.id: breaker},
        cts={str(ct.id): ct},
    )

    coordinator = MagicMock()
    coordinator.data = data

    entry = MagicMock()
    entry.runtime_data = LevitonRuntimeData(
        client=MagicMock(), coordinator=coordinator
    )

    result = await async_get_config_entry_diagnostics(hass, entry)

    # Check structure
    assert "whems" in result
    assert "panels" in result
    assert "breakers" in result
    assert "cts" in result

    # Check WHEM redaction
    whem_diag = result["whems"][whem.id]
    assert whem_diag["mac"] == "**REDACTED**"
    assert whem_diag["token"] == "**REDACTED**"
    assert whem_diag["name"] == "Test"

    # Check panel redaction
    panel_diag = result["panels"][panel.id]
    assert panel_diag["wifiSSID"] == "**REDACTED**"

    # Check breaker redaction
    breaker_diag = result["breakers"][breaker.id]
    assert breaker_diag["serialNumber"] == "**REDACTED**"
    assert breaker_diag["power"] == 120

    # Check CTs are not redacted (no sensitive fields)
    ct_diag = result["cts"][str(ct.id)]
    assert ct_diag["activePower"] == 196
