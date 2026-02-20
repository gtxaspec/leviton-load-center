"""DataUpdateCoordinator for the Leviton integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from aioleviton import (
    Breaker,
    Ct,
    LevitonAuthError,
    LevitonClient,
    LevitonConnectionError,
    Panel,
    Residence,
    Whem,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, LOGGER
from .energy import (
    EnergyTracker,
    accumulate_breaker_energy,
    accumulate_ct_energy,
    calc_daily_energy,
    snapshot_daily_baselines,
)
from .websocket import WebSocketManager, needs_individual_breaker_subs

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
    cts: dict[str, Ct] = field(default_factory=dict)
    residences: dict[int, Residence] = field(default_factory=dict)
    daily_baselines: dict[str, float] = field(default_factory=dict)


class LevitonCoordinator(DataUpdateCoordinator[LevitonData]):
    """Coordinator managing Leviton device data via WebSocket + REST fallback."""

    config_entry: LevitonConfigEntry

    # Static method re-exports for backward compat (tests call these)
    _accumulate_breaker_energy = staticmethod(accumulate_breaker_energy)
    _accumulate_ct_energy = staticmethod(accumulate_ct_energy)
    calc_daily_energy = staticmethod(calc_daily_energy)
    _needs_individual_breaker_subs = staticmethod(needs_individual_breaker_subs)

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
        self._residence_ids: list[int] = []
        self._midnight_unsub = None

        # Delegated subsystems
        self.energy = EnergyTracker(hass, entry.entry_id)
        self.ws_manager = WebSocketManager(self)

    # --- Proxy properties for backward compat (tests access these) ---

    @property
    def ws(self) -> Any:
        """Proxy to ws_manager.ws."""
        return self.ws_manager.ws

    @ws.setter
    def ws(self, value: Any) -> None:
        self.ws_manager.ws = value

    @property
    def _last_ws_notification(self) -> float:
        return self.ws_manager._last_ws_notification

    @_last_ws_notification.setter
    def _last_ws_notification(self, value: float) -> None:
        self.ws_manager._last_ws_notification = value

    @property
    def _reconnecting(self) -> bool:
        return self.ws_manager._reconnecting

    @_reconnecting.setter
    def _reconnecting(self, value: bool) -> None:
        self.ws_manager._reconnecting = value

    @property
    def _ws_remove_notification(self) -> Any:
        return self.ws_manager._ws_remove_notification

    @_ws_remove_notification.setter
    def _ws_remove_notification(self, value: Any) -> None:
        self.ws_manager._ws_remove_notification = value

    @property
    def _ws_remove_disconnect(self) -> Any:
        return self.ws_manager._ws_remove_disconnect

    @_ws_remove_disconnect.setter
    def _ws_remove_disconnect(self, value: Any) -> None:
        self.ws_manager._ws_remove_disconnect = value

    @property
    def _lifetime_store(self) -> Any:
        return self.energy._lifetime_store

    @_lifetime_store.setter
    def _lifetime_store(self, value: Any) -> None:
        self.energy._lifetime_store = value

    # --- Delegation methods (tests call these on coordinator) ---

    async def _connect_websocket(self) -> None:
        await self.ws_manager.connect()

    @callback
    def _handle_ws_notification(self, notification: dict[str, Any]) -> None:
        self.ws_manager._handle_ws_notification(notification)

    @callback
    def _handle_ws_disconnect(self) -> None:
        self.ws_manager._handle_ws_disconnect()

    async def _async_ws_watchdog(self, _now: Any = None) -> None:
        await self.ws_manager._async_ws_watchdog(_now)

    async def _async_ws_refresh(self, _now: Any = None) -> None:
        await self.ws_manager._async_ws_refresh(_now)

    async def _async_bandwidth_keepalive(self, _now: Any = None) -> None:
        await self.ws_manager._async_bandwidth_keepalive(_now)

    def _apply_breaker_ws_update(self, breaker_data: dict[str, Any]) -> bool:
        return self.ws_manager._apply_breaker_ws_update(breaker_data)

    async def _reconnect_websocket(self) -> None:
        await self.ws_manager._reconnect()

    async def _correct_energy_values(self) -> None:
        await self.energy.correct_energy_values(self.data)

    async def _load_daily_baselines(self) -> None:
        await self.energy.load_daily_baselines(self.data)

    async def _save_lifetime_energy(self) -> None:
        await self.energy.save_lifetime_energy(self.data)

    @callback
    def _snapshot_daily_baselines(self) -> None:
        snapshot_daily_baselines(self.data)

    def clamp_increasing(self, key: str, value: float) -> float:
        return self.energy.clamp_increasing(key, value)

    # --- Core coordinator logic ---

    async def _async_setup(self) -> None:
        """Discover devices and connect WebSocket on first refresh."""
        await self._discover_devices()
        await self._correct_energy_values()
        await self._connect_websocket()
        await self._load_daily_baselines()
        self._check_firmware_updates()
        self._midnight_unsub = async_track_time_change(
            self.hass, self._async_handle_midnight, hour=0, minute=0, second=0
        )
        self.config_entry.async_on_unload(self._midnight_unsub)

    async def _async_handle_midnight(self, _now: Any) -> None:
        """Reset daily energy baselines at midnight and persist."""
        await self.energy.handle_midnight(self.data)
        self.async_set_updated_data(self.data)

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
                LOGGER.debug(
                    "  WHEM %s: %s (FW %s)", whem.id, whem.name, whem.version
                )
                self.data.whems[whem.id] = whem
                # Reset bandwidth before fetching breakers/CTs to ensure
                # REST API returns lifetime energy (not deltas from a
                # previous session that left bandwidth=1 active).
                # Brief delay lets the WHEM process the change.
                try:
                    await self.client.set_whem_bandwidth(whem.id, bandwidth=0)
                    await asyncio.sleep(2)
                except LevitonConnectionError:
                    LOGGER.debug(
                        "Failed to reset bandwidth for WHEM %s", whem.id
                    )
                # Get breakers for this WHEM
                try:
                    breakers = await self.client.get_whem_breakers(whem.id)
                    for breaker in breakers:
                        self.data.breakers[breaker.id] = breaker
                        LOGGER.debug(
                            "    Breaker %s: %s (pos %d, serial %s)",
                            breaker.id, breaker.name, breaker.position,
                            breaker.serial_number,
                        )
                    LOGGER.debug(
                        "  Found %d breakers for WHEM %s", len(breakers), whem.id
                    )
                except LevitonConnectionError:
                    LOGGER.warning(
                        "Failed to fetch breakers for WHEM %s", whem.id
                    )
                # Get CTs for this WHEM
                try:
                    cts = await self.client.get_cts(whem.id)
                    for ct in cts:
                        self.data.cts[str(ct.id)] = ct
                        LOGGER.debug(
                            "    CT %s: %s (ch %d)",
                            ct.id, ct.name, ct.channel,
                        )
                    LOGGER.debug(
                        "  Found %d CTs for WHEM %s", len(cts), whem.id
                    )
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
            LOGGER.debug(
                "Found %d LDATAs in residence %s", len(panels), residence_id
            )
            for panel in panels:
                LOGGER.debug(
                    "  LDATA %s: %s (FW %s)",
                    panel.id, panel.name, panel.package_ver,
                )
                self.data.panels[panel.id] = panel
                # Reset bandwidth before fetching breakers
                try:
                    await self.client.set_panel_bandwidth(
                        panel.id, enabled=False
                    )
                    await asyncio.sleep(2)
                except LevitonConnectionError:
                    LOGGER.debug(
                        "Failed to reset bandwidth for panel %s", panel.id
                    )
                # Get breakers for this panel
                try:
                    breakers = await self.client.get_panel_breakers(panel.id)
                    for breaker in breakers:
                        self.data.breakers[breaker.id] = breaker
                        LOGGER.debug(
                            "    Breaker %s: %s (pos %d, serial %s)",
                            breaker.id, breaker.name, breaker.position,
                            breaker.serial_number,
                        )
                    LOGGER.debug(
                        "  Found %d breakers for LDATA %s",
                        len(breakers), panel.id,
                    )
                except LevitonConnectionError:
                    LOGGER.warning(
                        "Failed to fetch breakers for panel %s", panel.id
                    )
        except LevitonConnectionError:
            LOGGER.warning(
                "Failed to fetch panels for residence %s", residence_id
            )

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

    async def _async_update_data(self) -> LevitonData:
        """Periodic REST polling (every 10 minutes).

        When WS is connected, WHEM data is fully pushed so only LDATA panels
        need REST polling (WS delivers power/current but not energy for LDATA).
        When WS is down, all devices are refreshed via REST.
        """
        ws_connected = self.ws is not None

        if ws_connected and not self.data.panels:
            # WS covers everything, no LDATA panels to poll
            return self.data

        LOGGER.debug(
            "Running REST poll (ws=%s, whems=%d, panels=%d)",
            "up" if ws_connected else "down",
            len(self.data.whems),
            len(self.data.panels),
        )

        try:
            # WHEM hubs: skip when WS is connected (fully pushed)
            if not ws_connected:
                for whem_id in list(self.data.whems):
                    whem = await self.client.get_whem(whem_id)
                    self.data.whems[whem_id] = whem

                    breakers = await self.client.get_whem_breakers(whem_id)
                    for breaker in breakers:
                        self.data.breakers[breaker.id] = breaker

                    cts = await self.client.get_cts(whem_id)
                    for ct in cts:
                        self.data.cts[str(ct.id)] = ct

            # DAU panels: always poll (WS only delivers power/current, not energy)
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

        # Correct any bandwidth=1 delta values and update the lifetime cache
        await self._correct_energy_values()
        await self._save_lifetime_energy()

        return self.data

    async def async_shutdown(self) -> None:
        """Clean up WebSocket and bandwidth settings."""
        LOGGER.debug("Shutting down coordinator")
        await super().async_shutdown()
        await self.ws_manager.shutdown()
