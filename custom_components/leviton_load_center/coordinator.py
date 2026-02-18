"""DataUpdateCoordinator for the Leviton integration."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from aioleviton import (
    Breaker,
    Ct,
    LevitonAuthError,
    LevitonClient,
    LevitonConnectionError,
    LevitonWebSocket,
    Panel,
    Residence,
    Whem,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER

STORAGE_VERSION = 1

type LevitonConfigEntry = ConfigEntry[LevitonRuntimeData]


@dataclass(kw_only=True)
class LevitonRuntimeData:
    """Runtime data for the Leviton integration."""

    client: LevitonClient
    coordinator: LevitonCoordinator


@dataclass
class LevitonData:
    """All discovered device data."""

    whems: dict[str, Whem] = field(default_factory=dict)
    panels: dict[str, Panel] = field(default_factory=dict)
    breakers: dict[str, Breaker] = field(default_factory=dict)
    cts: dict[int, Ct] = field(default_factory=dict)
    residences: dict[int, Residence] = field(default_factory=dict)
    daily_baselines: dict[str, float] = field(default_factory=dict)


class LevitonCoordinator(DataUpdateCoordinator[LevitonData]):
    """Coordinator managing Leviton device data via WebSocket + REST fallback."""

    config_entry: LevitonConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: LevitonConfigEntry,
        client: LevitonClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=LOGGER,
            name="Leviton",
            config_entry=entry,
            update_interval=timedelta(minutes=10),
        )
        self.client = client
        self.ws: LevitonWebSocket | None = None
        self._last_ws_notification: float = 0.0
        self._residence_ids: list[int] = []
        self._ws_remove_notification: Any = None
        self._ws_remove_disconnect: Any = None
        self._midnight_unsub: Any = None
        self._baseline_store = Store[dict[str, float]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.daily_baselines"
        )
        self._lifetime_store = Store[dict[str, float]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.lifetime_energy"
        )

    @callback
    def async_set_updated_data(self, data: LevitonData) -> None:
        """Update data and notify listeners with clear log message."""
        self._async_unsub_refresh()
        self._debounced_refresh.async_cancel()
        self.data = data
        self.last_update_success = True
        LOGGER.debug("WebSocket push update")
        if self._listeners:
            self._schedule_refresh()
        self.async_update_listeners()

    async def _async_setup(self) -> None:
        """Discover devices and connect WebSocket on first refresh."""
        await self._discover_devices()
        await self._correct_energy_values()
        await self._connect_websocket()
        await self._load_daily_baselines()
        self._check_firmware_updates()
        self._midnight_unsub = async_track_time_change(
            self.hass, self._handle_midnight, hour=0, minute=0, second=0
        )

    async def _correct_energy_values(self) -> None:
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

        for breaker_id, breaker in self.data.breakers.items():
            rest_val = breaker.energy_consumption
            if rest_val is None:
                continue
            cached_val = stored.get(breaker_id)
            if cached_val is not None and rest_val < cached_val * 0.5:
                # REST returned a delta — correct to lifetime
                corrected = round(cached_val + rest_val, 3)
                LOGGER.debug(
                    "Energy correction %s: REST=%s (delta), cached=%s, "
                    "corrected=%s",
                    breaker.name, rest_val, cached_val, corrected,
                )
                breaker.energy_consumption = corrected
                stored[breaker_id] = corrected
                changed = True
            else:
                # REST returned lifetime (or first run) — cache it
                if cached_val is None or rest_val > cached_val:
                    stored[breaker_id] = rest_val
                    changed = True

        for ct_id, ct in self.data.cts.items():
            for attr, key_suffix in (
                ("energy_consumption", ""),
                ("energy_consumption_2", "_2"),
                ("energy_import", "_import"),
                ("energy_import_2", "_import_2"),
            ):
                rest_val = getattr(ct, attr)
                if rest_val is None:
                    continue
                cache_key = f"ct_{ct_id}{key_suffix}"
                cached_val = stored.get(cache_key)
                if cached_val is not None and rest_val < cached_val * 0.5:
                    corrected = round(cached_val + rest_val, 3)
                    setattr(ct, attr, corrected)
                    stored[cache_key] = corrected
                    changed = True
                elif cached_val is None or rest_val > cached_val:
                    stored[cache_key] = rest_val
                    changed = True

        if changed:
            await self._lifetime_store.async_save(stored)

    async def _load_daily_baselines(self) -> None:
        """Load daily baselines from storage, or snapshot current values."""
        stored = await self._baseline_store.async_load()
        if stored:
            self.data.daily_baselines = stored
        else:
            self._snapshot_daily_baselines()
            await self._baseline_store.async_save(self.data.daily_baselines)

    @callback
    def _snapshot_daily_baselines(self) -> None:
        """Record current lifetime energy as the daily baseline."""
        for breaker_id, breaker in self.data.breakers.items():
            if breaker.energy_consumption is not None:
                energy = breaker.energy_consumption
                if breaker.poles == 2:
                    energy += breaker.energy_consumption_2 or 0
                self.data.daily_baselines[breaker_id] = round(energy, 3)
        for ct_id, ct in self.data.cts.items():
            ct_total = (ct.energy_consumption or 0) + (
                ct.energy_consumption_2 or 0
            )
            self.data.daily_baselines[f"ct_{ct_id}"] = ct_total

    async def _async_handle_midnight(self) -> None:
        """Reset daily energy baselines at midnight and persist."""
        self._snapshot_daily_baselines()
        await self._baseline_store.async_save(self.data.daily_baselines)
        await self._save_lifetime_energy()
        self.async_set_updated_data(self.data)

    async def _save_lifetime_energy(self) -> None:
        """Persist current lifetime energy values for delta detection."""
        stored: dict[str, float] = {}
        for breaker_id, breaker in self.data.breakers.items():
            if breaker.energy_consumption is not None:
                stored[breaker_id] = breaker.energy_consumption
        for ct_id, ct in self.data.cts.items():
            for attr, key_suffix in (
                ("energy_consumption", ""),
                ("energy_consumption_2", "_2"),
                ("energy_import", "_import"),
                ("energy_import_2", "_import_2"),
            ):
                val = getattr(ct, attr)
                if val is not None:
                    stored[f"ct_{ct_id}{key_suffix}"] = val
        await self._lifetime_store.async_save(stored)

    @callback
    def _handle_midnight(self, _now: Any) -> None:
        """Schedule the async midnight handler."""
        self.config_entry.async_create_background_task(
            self.hass,
            self._async_handle_midnight(),
            "leviton_midnight_reset",
        )

    @staticmethod
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

    async def _discover_devices(self) -> None:
        """Discover all residences, hubs, breakers, and CTs."""
        try:
            permissions = await self.client.get_permissions()
        except LevitonAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except LevitonConnectionError as err:
            raise UpdateFailed(str(err)) from err

        # Collect residence IDs from two sources in permissions:
        # 1. Direct residenceId on the permission (admin/shared access)
        # 2. Via residentialAccountId -> account -> residences (owner access)
        residence_ids: set[int] = set()
        account_ids: set[int] = set()

        for perm in permissions:
            if perm.residence_id is not None:
                residence_ids.add(perm.residence_id)
            if perm.residential_account_id is not None:
                account_ids.add(perm.residential_account_id)

        # Also fetch residences via account path
        residences: dict[int, Residence] = {}
        for account_id in account_ids:
            try:
                account_residences = await self.client.get_residences(account_id)
                for res in account_residences:
                    residences[res.id] = res
                    residence_ids.add(res.id)
            except LevitonConnectionError as err:
                LOGGER.warning(
                    "Failed to fetch residences for account %s: %s",
                    account_id,
                    err,
                )

        self._residence_ids = list(residence_ids)
        self.data = LevitonData(residences=residences)

        LOGGER.debug(
            "Discovered %d residences: %s", len(self._residence_ids), self._residence_ids
        )

        # Discover hubs and their children in each residence
        for residence_id in self._residence_ids:
            await self._discover_residence_devices(residence_id)

    async def _discover_residence_devices(self, residence_id: int) -> None:
        """Discover all devices in a single residence."""
        LOGGER.debug("Discovering devices in residence %s", residence_id)

        # LWHEM hubs
        try:
            whems = await self.client.get_whems(residence_id)
            LOGGER.debug("Found %d WHEMs in residence %s", len(whems), residence_id)
            for whem in whems:
                self.data.whems[whem.id] = whem
                # Get breakers for this WHEM
                try:
                    breakers = await self.client.get_whem_breakers(whem.id)
                    for breaker in breakers:
                        self.data.breakers[breaker.id] = breaker
                except LevitonConnectionError:
                    LOGGER.warning(
                        "Failed to fetch breakers for WHEM %s", whem.id
                    )
                # Get CTs for this WHEM
                try:
                    cts = await self.client.get_cts(whem.id)
                    for ct in cts:
                        self.data.cts[ct.id] = ct
                except LevitonConnectionError:
                    LOGGER.warning(
                        "Failed to fetch CTs for WHEM %s", whem.id
                    )
        except LevitonConnectionError:
            LOGGER.warning(
                "Failed to fetch WHEMs for residence %s", residence_id
            )

        # DAU panels
        try:
            panels = await self.client.get_panels(residence_id)
            for panel in panels:
                self.data.panels[panel.id] = panel
                # Get breakers for this panel
                try:
                    breakers = await self.client.get_panel_breakers(panel.id)
                    for breaker in breakers:
                        self.data.breakers[breaker.id] = breaker
                except LevitonConnectionError:
                    LOGGER.warning(
                        "Failed to fetch breakers for panel %s", panel.id
                    )
        except LevitonConnectionError:
            LOGGER.warning(
                "Failed to fetch panels for residence %s", residence_id
            )

    async def _connect_websocket(self) -> None:
        """Connect WebSocket and subscribe to all hubs."""
        if not self.client.token or not self.client.user_id:
            return

        try:
            self.ws = self.client.create_websocket()
            await self.ws.connect()
        except LevitonConnectionError:
            LOGGER.warning("WebSocket connection failed, using REST polling only")
            self.ws = None
            return

        # Reset staleness clock on new connection
        self._last_ws_notification = time.monotonic()

        # Register callbacks
        self._ws_remove_notification = self.ws.on_notification(
            self._handle_ws_notification
        )
        self._ws_remove_disconnect = self.ws.on_disconnect(
            self._handle_ws_disconnect
        )

        # Subscribe to all LWHEM hubs and enable bandwidth
        for whem_id in self.data.whems:
            try:
                await self.client.set_whem_bandwidth(whem_id, bandwidth=1)
                await self.ws.subscribe("IotWhem", whem_id)
            except LevitonConnectionError:
                LOGGER.warning("Failed to subscribe to WHEM %s", whem_id)

        # Subscribe to all DAU panels and enable bandwidth
        for panel_id in self.data.panels:
            try:
                await self.client.set_panel_bandwidth(panel_id, enabled=True)
                await self.ws.subscribe("ResidentialBreakerPanel", panel_id)
            except LevitonConnectionError:
                LOGGER.warning("Failed to subscribe to panel %s", panel_id)

        # Subscribe to individual breakers for WHEMs on FW 2.0.0+.
        # FW 2.0.13+ stopped delivering breaker updates as nested arrays
        # in IotWhem notifications. Individual subscriptions are required.
        # On older FW, the hub subscription covers breakers -- skip to
        # avoid duplicate notifications and wasted bandwidth.
        # CTs are always delivered via the hub subscription on all FW.
        for whem_id, whem in self.data.whems.items():
            if not self._needs_individual_breaker_subs(whem):
                LOGGER.debug(
                    "WHEM %s on FW %s: hub subscription covers breakers",
                    whem_id,
                    whem.version,
                )
                continue
            LOGGER.debug(
                "WHEM %s on FW %s: subscribing to individual breakers",
                whem_id,
                whem.version,
            )
            for breaker_id, breaker in self.data.breakers.items():
                if breaker.iot_whem_id != whem_id:
                    continue
                try:
                    await self.ws.subscribe("ResidentialBreaker", breaker_id)
                except LevitonConnectionError:
                    LOGGER.debug(
                        "Failed to subscribe to breaker %s", breaker_id
                    )

        # Bandwidth is set once on connect (above). The WHEM auto-reverts
        # from 1 to 2 within seconds, and 2 is sufficient for real-time push.
        # The app re-sends every ~25s, but we haven't observed bandwidth
        # dropping back to 0 on its own -- avoid unnecessary API calls.

    @staticmethod
    def _needs_individual_breaker_subs(whem: Whem) -> bool:
        """Check if a WHEM needs individual breaker subscriptions.

        FW 2.0.0+ stopped delivering breaker updates as nested arrays in
        IotWhem parent notifications. Individual ResidentialBreaker
        subscriptions are required. On older FW (1.x), the hub subscription
        delivers all child updates and individual subs are redundant.
        """
        if whem.version is None:
            return True  # Assume newest FW if unknown
        try:
            parts = tuple(int(x) for x in whem.version.split("."))
            return parts >= (2, 0, 0)
        except (ValueError, AttributeError):
            return True  # Assume newest FW if unparseable

    @callback
    def _check_firmware_updates(self) -> None:
        """Create or clear repair issues for available firmware updates."""
        for whem_id, whem in self.data.whems.items():
            issue_id = f"firmware_update_{whem_id}"
            downloaded = whem.raw.get("downloaded")
            if downloaded and downloaded != whem.version:
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="firmware_update_available",
                    translation_placeholders={
                        "device_name": whem.name or f"LWHEM {whem_id}",
                        "current_version": whem.version or "unknown",
                        "new_version": downloaded,
                    },
                    learn_more_url="https://www.leviton.com/support",
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        for panel_id, panel in self.data.panels.items():
            issue_id = f"firmware_update_{panel_id}"
            update_avail = panel.raw.get("updateAvailability")
            if update_avail and update_avail != "UP_TO_DATE":
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="firmware_update_available",
                    translation_placeholders={
                        "device_name": panel.name or f"Panel {panel_id}",
                        "current_version": panel.package_ver or "unknown",
                        "new_version": panel.raw.get("updateVersion", "available"),
                    },
                    learn_more_url="https://www.leviton.com/support",
                )
            else:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    @staticmethod
    def _accumulate_breaker_energy(
        breaker_data: dict[str, Any], breaker: Breaker
    ) -> None:
        """Convert WS energy deltas to accumulated lifetime values.

        The WS delivers energyConsumption as a delta (energy since last report),
        not the lifetime total that the REST API returns. We accumulate deltas
        onto the current lifetime value so sensors stay correct.

        Safety: if the WS value exceeds the current lifetime, it cannot be a
        delta and is treated as a lifetime replacement (left as-is).
        """
        for ws_key, attr in (
            ("energyConsumption", "energy_consumption"),
            ("energyConsumption2", "energy_consumption_2"),
            ("energyImport", "energy_import"),
        ):
            delta = breaker_data.get(ws_key)
            if delta is not None:
                current = getattr(breaker, attr) or 0
                if current > 0 and delta > current:
                    continue
                breaker_data[ws_key] = round(current + delta, 3)

    @staticmethod
    def _accumulate_ct_energy(
        ct_data: dict[str, Any], ct: Ct
    ) -> None:
        """Convert WS energy deltas to accumulated lifetime values for CTs.

        Safety: if the WS value exceeds the current lifetime, it cannot be a
        delta and is treated as a lifetime replacement (left as-is).
        """
        for ws_key, attr in (
            ("energyConsumption", "energy_consumption"),
            ("energyConsumption2", "energy_consumption_2"),
            ("energyImport", "energy_import"),
            ("energyImport2", "energy_import_2"),
        ):
            delta = ct_data.get(ws_key)
            if delta is not None:
                current = getattr(ct, attr) or 0
                if current > 0 and delta > current:
                    continue
                ct_data[ws_key] = round(current + delta, 3)

    @callback
    def _handle_ws_notification(self, notification: dict[str, Any]) -> None:
        """Process a WebSocket push notification."""
        self._last_ws_notification = time.monotonic()
        model_name = notification.get("modelName", "")
        model_id = notification.get("modelId")
        data = notification.get("data", {})

        if not data or model_id is None:
            return

        updated = False

        if model_name == "IotWhem":
            # Check for child breaker updates
            if "ResidentialBreaker" in data:
                for breaker_data in data["ResidentialBreaker"]:
                    breaker_id = breaker_data.get("id")
                    if breaker_id and breaker_id in self.data.breakers:
                        breaker = self.data.breakers[breaker_id]
                        self._accumulate_breaker_energy(breaker_data, breaker)
                        if breaker_data.get("remoteTrip") and not breaker.can_remote_on:
                            breaker_data.setdefault("currentState", "SoftwareTrip")
                        breaker.update(breaker_data)
                        updated = True

            # Check for child CT updates
            if "IotCt" in data:
                for ct_data in data["IotCt"]:
                    ct_id = ct_data.get("id")
                    if ct_id and ct_id in self.data.cts:
                        self._accumulate_ct_energy(ct_data, self.data.cts[ct_id])
                        self.data.cts[ct_id].update(ct_data)
                        updated = True

            # WHEM own property updates (exclude child arrays)
            whem_data = {
                k: v
                for k, v in data.items()
                if k not in ("ResidentialBreaker", "IotCt")
            }
            if whem_data and str(model_id) in self.data.whems:
                self.data.whems[str(model_id)].update(whem_data)
                updated = True

        elif model_name == "ResidentialBreakerPanel":
            # Check for child breaker updates
            if "ResidentialBreaker" in data:
                for breaker_data in data["ResidentialBreaker"]:
                    breaker_id = breaker_data.get("id")
                    if breaker_id and breaker_id in self.data.breakers:
                        breaker = self.data.breakers[breaker_id]
                        self._accumulate_breaker_energy(breaker_data, breaker)
                        if breaker_data.get("remoteTrip") and not breaker.can_remote_on:
                            breaker_data.setdefault("currentState", "SoftwareTrip")
                        breaker.update(breaker_data)
                        updated = True

            # Panel own property updates
            panel_data = {
                k: v for k, v in data.items() if k != "ResidentialBreaker"
            }
            if panel_data and str(model_id) in self.data.panels:
                self.data.panels[str(model_id)].update(panel_data)
                updated = True

        elif model_name == "ResidentialBreaker":
            breaker_id = str(model_id)
            if breaker_id in self.data.breakers:
                breaker = self.data.breakers[breaker_id]
                self._accumulate_breaker_energy(data, breaker)
                # Gen 1 breakers physically trip — synthesize currentState
                # since WS never delivers it for remote commands.
                if data.get("remoteTrip") and not breaker.can_remote_on:
                    data.setdefault("currentState", "SoftwareTrip")
                breaker.update(data)
                updated = True

        elif model_name == "IotCt":
            ct_id = model_id
            if isinstance(ct_id, int) and ct_id in self.data.cts:
                self._accumulate_ct_energy(data, self.data.cts[ct_id])
                self.data.cts[ct_id].update(data)
                updated = True

        if updated:
            self.async_set_updated_data(self.data)

    @callback
    def _handle_ws_disconnect(self) -> None:
        """Handle WebSocket disconnect - schedule reconnection."""
        LOGGER.warning("WebSocket disconnected, falling back to REST polling")
        self.ws = None
        # Schedule a reconnection attempt
        self.config_entry.async_create_background_task(
            self.hass,
            self._reconnect_websocket(),
            "leviton_ws_reconnect",
        )

    async def _async_update_data(self) -> LevitonData:
        """Periodic REST polling - runs as fallback or staleness recovery.

        Normally WebSocket push keeps data fresh. This runs every 10 minutes
        and skips if WS delivered a notification recently. If WS appears
        connected but hasn't delivered data in 3+ minutes, treat it as stale
        and do a REST poll + trigger reconnection.
        """
        if self.ws is not None:
            silence = time.monotonic() - self._last_ws_notification
            if self._last_ws_notification > 0 and silence > 180:
                LOGGER.warning(
                    "WebSocket silent for %d seconds, forcing REST poll "
                    "and reconnecting",
                    int(silence),
                )
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._reconnect_websocket(),
                    "leviton_ws_reconnect",
                )
            else:
                LOGGER.debug("WebSocket connected, skipping REST poll")
                return self.data

        LOGGER.debug("Running REST poll")
        try:
            # Refresh WHEM hubs and their children
            for whem_id in list(self.data.whems):
                whem = await self.client.get_whem(whem_id)
                self.data.whems[whem_id] = whem

                breakers = await self.client.get_whem_breakers(whem_id)
                for breaker in breakers:
                    self.data.breakers[breaker.id] = breaker

                cts = await self.client.get_cts(whem_id)
                for ct in cts:
                    self.data.cts[ct.id] = ct

            # Refresh DAU panels and their children
            for panel_id in list(self.data.panels):
                panel = await self.client.get_panel(panel_id)
                self.data.panels[panel_id] = panel

                breakers = await self.client.get_panel_breakers(panel_id)
                for breaker in breakers:
                    self.data.breakers[breaker.id] = breaker

        except LevitonAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except LevitonConnectionError as err:
            raise UpdateFailed(str(err)) from err

        return self.data

    async def _reconnect_websocket(self) -> None:
        """Attempt to reconnect WebSocket with exponential backoff."""
        delays = [10, 30, 60, 120, 300]  # seconds
        for attempt, delay in enumerate(delays, 1):
            LOGGER.debug(
                "WebSocket reconnection attempt %d in %d seconds", attempt, delay
            )
            await asyncio.sleep(delay)

            # Validate token before attempting WS reconnect (WS module
            # can't distinguish auth failures from connection failures)
            try:
                await self.client.get_permissions()
            except LevitonAuthError as err:
                LOGGER.warning("Token expired during reconnection: %s", err)
                raise ConfigEntryAuthFailed(err) from err
            except LevitonConnectionError:
                LOGGER.debug(
                    "API unreachable during reconnection attempt %d", attempt
                )
                continue

            try:
                await self._connect_websocket()
                if self.ws is not None:
                    LOGGER.info("WebSocket reconnected successfully")
                    return
            except Exception:
                LOGGER.debug("WebSocket reconnection attempt %d failed", attempt)
        LOGGER.warning(
            "WebSocket reconnection failed after %d attempts, "
            "using REST polling (10-min interval)",
            len(delays),
        )

    async def async_shutdown(self) -> None:
        """Clean up WebSocket and bandwidth settings."""
        # Clean up scheduled tasks
        if self._midnight_unsub:
            self._midnight_unsub()
        # Clean up notification callbacks
        if self._ws_remove_notification:
            self._ws_remove_notification()
        if self._ws_remove_disconnect:
            self._ws_remove_disconnect()

        # Disable bandwidth on all hubs (data may be None if setup failed early)
        if self.data is None:
            return
        for panel_id in self.data.panels:
            try:
                await self.client.set_panel_bandwidth(panel_id, enabled=False)
            except LevitonConnectionError:
                LOGGER.debug(
                    "Failed to disable bandwidth for panel %s", panel_id
                )
        for whem_id in self.data.whems:
            try:
                await self.client.set_whem_bandwidth(whem_id, bandwidth=0)
            except LevitonConnectionError:
                LOGGER.debug(
                    "Failed to disable bandwidth for WHEM %s", whem_id
                )

        # Disconnect WebSocket
        if self.ws:
            await self.ws.disconnect()
            self.ws = None
