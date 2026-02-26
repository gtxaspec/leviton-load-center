"""Energy tracking and correction for the Leviton integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aioleviton import Breaker, Ct

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from .coordinator import LevitonData

STORAGE_VERSION = 1
BASELINE_STORAGE_VERSION = 2

# (ws_key, model_attr) tuples for energy fields
_BREAKER_ENERGY_FIELDS = (
    ("energyConsumption", "energy_consumption"),
    ("energyConsumption2", "energy_consumption_2"),
    ("energyImport", "energy_import"),
)

_CT_ENERGY_FIELDS = (
    ("energyConsumption", "energy_consumption"),
    ("energyConsumption2", "energy_consumption_2"),
    ("energyImport", "energy_import"),
    ("energyImport2", "energy_import_2"),
)

# (model_attr, cache_key_suffix) tuples for lifetime cache
_BREAKER_CACHE_FIELDS = (
    ("energy_consumption", ""),
    ("energy_consumption_2", "_2"),
    ("energy_import", "_import"),
)

_CT_CACHE_FIELDS = (
    ("energy_consumption", ""),
    ("energy_consumption_2", "_2"),
    ("energy_import", "_import"),
    ("energy_import_2", "_import_2"),
)


def _normalize_energy(
    ws_data: dict[str, Any],
    model: Breaker | Ct,
    fields: tuple[tuple[str, str], ...],
) -> None:
    """Normalize WS energy values so model.update() always sets lifetime totals.

    The Leviton WS delivers energyConsumption in two modes:
    - bandwidth=2 (normal): full lifetime totals — use directly.
    - bandwidth=1 (streaming): period deltas — discard, because the
      server's next lifetime update already includes the energy.
      Accumulating deltas would double-count.

    Detection: if the WS value is >50% of the model's current lifetime,
    it's a lifetime total. Otherwise it's a bandwidth=1 delta — remove
    it from ws_data so model.update() preserves the current lifetime.
    """
    for ws_key, attr in fields:
        raw = ws_data.get(ws_key)
        if raw is not None:
            current = getattr(model, attr) or 0
            if current == 0 or raw > current * 0.5:
                # Lifetime total (or first value) — use server value
                ws_data[ws_key] = round(raw, 3)
            else:
                # Bandwidth=1 delta — discard to avoid double-counting
                del ws_data[ws_key]


def normalize_breaker_energy(
    breaker_data: dict[str, Any], breaker: Breaker
) -> None:
    """Normalize WS breaker energy: accept lifetimes, discard deltas."""
    _normalize_energy(breaker_data, breaker, _BREAKER_ENERGY_FIELDS)


def normalize_ct_energy(
    ct_data: dict[str, Any], ct: Ct
) -> None:
    """Normalize WS CT energy: accept lifetimes, discard deltas."""
    _normalize_energy(ct_data, ct, _CT_ENERGY_FIELDS)


def calc_daily_energy(
    breaker_id: str, lifetime: float | None, data: LevitonData
) -> float | None:
    """Get daily energy for a breaker (current lifetime - midnight baseline)."""
    if lifetime is None:
        return None
    baseline = data.daily_baselines.get(breaker_id)
    if baseline is None:
        return None
    daily = lifetime - baseline
    return round(max(0.0, daily), 2)


@callback
def snapshot_daily_baselines(data: LevitonData) -> None:
    """Record current lifetime energy as the daily baseline."""
    for breaker_id, breaker in data.breakers.items():
        if breaker.energy_consumption is not None:
            energy = breaker.energy_consumption
            if breaker.poles == 2:
                energy += breaker.energy_consumption_2 or 0
            data.daily_baselines[breaker_id] = round(energy, 3)
    for ct_id, ct in data.cts.items():
        ct_total = (ct.energy_consumption or 0) + (
            ct.energy_consumption_2 or 0
        )
        data.daily_baselines[f"ct_{ct_id}"] = round(ct_total, 3)


def _correct_device_energy(
    device_id: str,
    device: Breaker | Ct,
    stored: dict[str, float],
    fields: tuple[tuple[str, str], ...],
    key_prefix: str,
) -> bool:
    """Correct delta energy values for a single device. Returns True if changed."""
    changed = False
    for attr, key_suffix in fields:
        rest_val = getattr(device, attr)
        if rest_val is None:
            continue
        cache_key = f"{key_prefix}{device_id}{key_suffix}"
        cached_val = stored.get(cache_key)
        if cached_val is not None and rest_val < cached_val * 0.5:
            corrected = round(cached_val + rest_val, 3)
            LOGGER.debug(
                "Energy correction %s%s/%s: REST=%s (delta), "
                "cached=%s, corrected=%s",
                key_prefix, getattr(device, "name", device_id),
                attr, rest_val, cached_val, corrected,
            )
            setattr(device, attr, corrected)
            stored[cache_key] = corrected
            changed = True
        elif cached_val is None or rest_val > cached_val:
            stored[cache_key] = rest_val
            changed = True
    return changed


def _collect_device_energy(
    device_id: str,
    device: Breaker | Ct,
    stored: dict[str, float],
    fields: tuple[tuple[str, str], ...],
    key_prefix: str,
) -> None:
    """Collect current energy values from a device into the stored dict."""
    for attr, key_suffix in fields:
        val = getattr(device, attr)
        if val is not None:
            stored[f"{key_prefix}{device_id}{key_suffix}"] = val


class EnergyTracker:
    """Manages energy correction, lifetime caching, and daily baselines."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize energy tracking stores."""
        self._baseline_store: Store[dict[str, Any]] = Store(
            hass, BASELINE_STORAGE_VERSION, f"{DOMAIN}.{entry_id}.daily_baselines"
        )
        self._lifetime_store: Store[dict[str, float]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}.lifetime_energy"
        )
        self._energy_high_water: dict[str, float] = {}

    async def correct_energy_values(self, data: LevitonData) -> None:
        """Detect and correct delta energy values from the REST API.

        When bandwidth=1 (streaming mode), the WHEM reports energyConsumption
        as a period delta instead of the lifetime total. This can happen on
        restart if the previous session left bandwidth=1 active.

        We detect this by comparing REST values against cached lifetime values.
        If the REST value is significantly smaller, it's a delta and we correct
        it by adding it to the cached lifetime.
        """
        stored: dict[str, float] = await self._lifetime_store.async_load() or {}
        changed = False

        for breaker_id, breaker in data.breakers.items():
            changed |= _correct_device_energy(
                breaker_id, breaker, stored, _BREAKER_CACHE_FIELDS, ""
            )

        for ct_id, ct in data.cts.items():
            changed |= _correct_device_energy(
                ct_id, ct, stored, _CT_CACHE_FIELDS, "ct_"
            )

        if changed:
            await self._lifetime_store.async_save(stored)

    async def _save_baselines(self, data: LevitonData) -> None:
        """Persist daily baselines with today's date."""
        await self._baseline_store.async_save({
            "date": dt_util.now().date().isoformat(),
            "baselines": dict(data.daily_baselines),
        })

    async def load_daily_baselines(self, data: LevitonData) -> None:
        """Load daily baselines from storage, or snapshot current values.

        If stored baselines are from a previous day (e.g. HA restarted after
        midnight), re-snapshot so daily energy starts fresh for today.
        """
        stored = await self._baseline_store.async_load()
        today = dt_util.now().date().isoformat()
        if stored:
            stored_date = stored.get("date")
            baselines = stored.get("baselines", {})
            if stored_date == today:
                data.daily_baselines = baselines
                LOGGER.debug(
                    "Loaded %d daily baselines from storage", len(baselines)
                )
                return
            LOGGER.debug(
                "Stored baselines are from %s, re-snapshotting for %s",
                stored_date, today,
            )
        else:
            LOGGER.debug("No stored baselines, snapshotting current values")
        snapshot_daily_baselines(data)
        await self._save_baselines(data)

    async def save_lifetime_energy(self, data: LevitonData) -> None:
        """Persist current lifetime energy values for delta detection."""
        stored: dict[str, float] = {}
        for breaker_id, breaker in data.breakers.items():
            _collect_device_energy(breaker_id, breaker, stored, _BREAKER_CACHE_FIELDS, "")
        for ct_id, ct in data.cts.items():
            _collect_device_energy(ct_id, ct, stored, _CT_CACHE_FIELDS, "ct_")
        await self._lifetime_store.async_save(stored)

    async def handle_midnight(self, data: LevitonData) -> None:
        """Reset daily energy baselines at midnight and persist."""
        LOGGER.debug("Midnight reset: snapshotting daily energy baselines")
        snapshot_daily_baselines(data)
        await self._save_baselines(data)
        await self.save_lifetime_energy(data)

    def clamp_increasing(self, key: str, value: float) -> float:
        """Ensure a TOTAL_INCREASING value never decreases.

        IEEE 754 float arithmetic can cause sums of independently-rounded
        values to fluctuate by ±0.001.  This clamps to the high-water mark
        so HA's recorder never sees a decrease.  Resets on restart (fresh
        REST values have no accumulation rounding drift).
        """
        prev = self._energy_high_water.get(key)
        if prev is not None and value < prev:
            LOGGER.debug(
                "Clamped decreasing energy %s: %s -> %s", key, value, prev
            )
            return prev
        self._energy_high_water[key] = value
        return value
