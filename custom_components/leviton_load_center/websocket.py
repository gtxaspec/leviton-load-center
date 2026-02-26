"""WebSocket management for the Leviton integration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from aioleviton import LevitonConnectionError, LevitonAuthError, LevitonWebSocket, Whem

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_time_interval

from .const import LOGGER, STATE_SOFTWARE_TRIP
from .energy import normalize_breaker_energy, normalize_ct_energy

if TYPE_CHECKING:
    from .coordinator import LevitonCoordinator


def needs_individual_breaker_subs(whem: Whem) -> bool:
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
        LOGGER.debug(
            "Could not parse WHEM FW version '%s', assuming >=2.0.0",
            whem.version,
        )
        return True  # Assume newest FW if unparseable


class WebSocketManager:
    """Manages WebSocket connection lifecycle and notifications."""

    def __init__(self, coordinator: LevitonCoordinator) -> None:
        """Initialize the WebSocket manager."""
        self.coordinator = coordinator
        self.ws: LevitonWebSocket | None = None
        self._last_ws_notification: float = 0.0
        self._reconnecting: bool = False
        self._ws_remove_notification: Callable[[], None] | None = None
        self._ws_remove_disconnect: Callable[[], None] | None = None
        self._keepalive_unsub: Callable[[], None] | None = None
        self._watchdog_unsub: Callable[[], None] | None = None
        self._bandwidth_unsub: Callable[[], None] | None = None

    async def connect(self) -> None:
        """Connect WebSocket and subscribe to all hubs."""
        coordinator = self.coordinator
        client = coordinator.client

        if not client.token or not client.user_id:
            return

        try:
            self.ws = client.create_websocket()
            await self.ws.connect()
        except LevitonConnectionError:
            LOGGER.warning(
                "WebSocket connection failed, using REST polling only",
                exc_info=True,
            )
            self.ws = None
            return

        LOGGER.debug("WebSocket connected")

        # Reset staleness clock on new connection
        self._last_ws_notification = time.monotonic()

        # Register callbacks
        self._ws_remove_notification = self.ws.on_notification(
            self._handle_ws_notification
        )
        self._ws_remove_disconnect = self.ws.on_disconnect(
            self._handle_ws_disconnect
        )

        data = coordinator.data

        # Subscribe to all LWHEM hubs and trigger energy data immediately
        # via 1→0→1 bandwidth toggle (same as the periodic keepalive).
        for whem_id in data.whems:
            try:
                await client.set_whem_bandwidth(whem_id, bandwidth=1)
                await client.set_whem_bandwidth(whem_id, bandwidth=0)
                await client.set_whem_bandwidth(whem_id, bandwidth=1)
                await self.ws.subscribe("IotWhem", whem_id)
            except LevitonConnectionError:
                LOGGER.warning("Failed to subscribe to WHEM %s", whem_id)

        # Subscribe to all DAU panels and enable bandwidth
        for panel_id in data.panels:
            try:
                await client.set_panel_bandwidth(panel_id, enabled=True)
                await self.ws.subscribe("ResidentialBreakerPanel", panel_id)
            except LevitonConnectionError:
                LOGGER.warning("Failed to subscribe to panel %s", panel_id)

        # Subscribe to individual breakers for WHEMs on FW 2.0.0+.
        # FW 2.0.13+ stopped delivering breaker updates as nested arrays
        # in IotWhem notifications. Individual subscriptions are required.
        # On older FW, the hub subscription covers breakers -- skip to
        # avoid duplicate notifications and wasted bandwidth.
        # CTs are always delivered via the hub subscription on all FW.
        for whem_id, whem in data.whems.items():
            if not needs_individual_breaker_subs(whem):
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
            for breaker_id, breaker in data.breakers.items():
                if breaker.iot_whem_id != whem_id:
                    continue
                try:
                    await self.ws.subscribe("ResidentialBreaker", breaker_id)
                except LevitonConnectionError:
                    LOGGER.warning(
                        "Failed to subscribe to breaker %s", breaker_id
                    )

        # Bandwidth is set once on connect (above). The WHEM auto-reverts
        # from 1 to 2 within seconds, and 2 is sufficient for real-time push.
        # The app re-sends every ~25s, but we haven't observed bandwidth
        # dropping back to 0 on its own -- avoid unnecessary API calls.

        # Start periodic API keepalive to prevent server-side session timeout.
        # The Leviton server drops WS push after ~60 min of API inactivity.
        self._start_keepalive()

    async def shutdown(self) -> None:
        """Clean up WebSocket callbacks and disconnect."""
        coordinator = self.coordinator

        if self._ws_remove_notification:
            self._ws_remove_notification()
            self._ws_remove_notification = None
        if self._ws_remove_disconnect:
            self._ws_remove_disconnect()
            self._ws_remove_disconnect = None
        self._stop_keepalive()

        # Disable bandwidth on all hubs (data may be None if setup failed early)
        if coordinator.data is None:
            return
        for panel_id in coordinator.data.panels:
            try:
                await coordinator.client.set_panel_bandwidth(
                    panel_id, enabled=False
                )
            except LevitonConnectionError:
                LOGGER.debug(
                    "Failed to disable bandwidth for panel %s", panel_id
                )
        for whem_id in coordinator.data.whems:
            try:
                await coordinator.client.set_whem_bandwidth(
                    whem_id, bandwidth=0
                )
            except LevitonConnectionError:
                LOGGER.debug(
                    "Failed to disable bandwidth for WHEM %s", whem_id
                )

        # Disconnect WebSocket
        if self.ws:
            await self.ws.disconnect()
            self.ws = None

    @callback
    def _start_keepalive(self) -> None:
        """Schedule periodic WS reconnection, silence watchdog, and bandwidth keepalive.

        The Leviton server hard-kills WS push notifications after exactly
        60 minutes regardless of any REST API activity. Neither bandwidth
        PUTs nor /apiversion polling prevent this (confirmed via 57-hour
        traffic capture of the official app which has the same problem).

        Three mechanisms:
        1. Proactive reconnect every 55 minutes (before the 60-min cutoff).
        2. Silence watchdog every 30 seconds — if no WS data for 90 seconds,
           force an immediate reconnect (catches silent connection drops).
        3. Bandwidth PUT every 60 seconds for WHEMs — keeps CTs pushing
           data at high frequency. Without this, CTs only update every
           2-12 minutes after bandwidth auto-reverts from 1 to 2.
        """
        self._stop_keepalive()
        hass = self.coordinator.hass
        entry = self.coordinator.config_entry
        self._keepalive_unsub = async_track_time_interval(
            hass, self._async_ws_refresh, timedelta(minutes=55)
        )
        entry.async_on_unload(self._keepalive_unsub)
        self._watchdog_unsub = async_track_time_interval(
            hass, self._async_ws_watchdog, timedelta(seconds=30)
        )
        entry.async_on_unload(self._watchdog_unsub)
        if self.coordinator.data.whems:
            self._bandwidth_unsub = async_track_time_interval(
                hass, self._async_bandwidth_keepalive, timedelta(seconds=60)
            )
            entry.async_on_unload(self._bandwidth_unsub)

    @callback
    def _stop_keepalive(self) -> None:
        """Stop periodic WS refresh, watchdog, and bandwidth keepalive."""
        if self._keepalive_unsub:
            self._keepalive_unsub()
            self._keepalive_unsub = None
        if self._watchdog_unsub:
            self._watchdog_unsub()
            self._watchdog_unsub = None
        if self._bandwidth_unsub:
            self._bandwidth_unsub()
            self._bandwidth_unsub = None

    async def _async_ws_refresh(self, _now: Any) -> None:
        """Proactively reconnect WS before the 60-minute server timeout."""
        if self.ws is None:
            return
        LOGGER.debug("Proactive WS refresh (55-min cycle)")
        # Remove disconnect callback before disconnecting to prevent
        # _handle_ws_disconnect from also triggering a reconnect.
        if self._ws_remove_disconnect:
            self._ws_remove_disconnect()
        self._ws_remove_disconnect = None
        self._ws_remove_notification = None
        await self.ws.disconnect()
        self.ws = None
        await self.connect()

    async def _async_ws_watchdog(self, _now: Any) -> None:
        """Force reconnect if WS has been silent for 90+ seconds."""
        if self.ws is None or self._reconnecting:
            return
        silence = time.monotonic() - self._last_ws_notification
        if silence < 90:
            return
        LOGGER.warning(
            "WS silent for %d seconds, forcing reconnect", int(silence)
        )
        # Remove disconnect callback before disconnecting to prevent
        # _handle_ws_disconnect from also triggering a reconnect.
        if self._ws_remove_disconnect:
            self._ws_remove_disconnect()
        self._ws_remove_disconnect = None
        self._ws_remove_notification = None
        await self.ws.disconnect()
        self.ws = None
        self._stop_keepalive()
        if not self._reconnecting:
            self.coordinator.config_entry.async_create_background_task(
                self.coordinator.hass,
                self._reconnect(),
                "leviton_ws_reconnect",
            )

    async def _async_bandwidth_keepalive(self, _now: Any) -> None:
        """Toggle bandwidth 1->0->1 on WHEMs to trigger fresh CT data push.

        The WHEM needs to see a 0->1 transition to push new readings.
        Just sending 1 repeatedly doesn't trigger a refresh after the
        initial auto-revert from 1 to 2.
        """
        if self.ws is None:
            return
        client = self.coordinator.client
        for whem_id in self.coordinator.data.whems:
            try:
                await client.set_whem_bandwidth(whem_id, bandwidth=1)
                await client.set_whem_bandwidth(whem_id, bandwidth=0)
                await client.set_whem_bandwidth(whem_id, bandwidth=1)
            except LevitonConnectionError:
                LOGGER.warning(
                    "Bandwidth keepalive failed for WHEM %s", whem_id
                )

    def _apply_breaker_ws_update(
        self, breaker_data: dict[str, Any]
    ) -> bool:
        """Apply a single breaker update from a WS notification.

        Accumulates energy deltas and synthesizes currentState for Gen 1 trips.
        Returns True if a known breaker was updated.
        """
        data = self.coordinator.data
        breaker_id = breaker_data.get("id")
        if not breaker_id or breaker_id not in data.breakers:
            return False
        breaker = data.breakers[breaker_id]
        normalize_breaker_energy(breaker_data, breaker)
        if breaker_data.get("remoteTrip") and not breaker.can_remote_on:
            breaker_data.setdefault("currentState", STATE_SOFTWARE_TRIP)
        breaker.update(breaker_data)
        return True

    @callback
    def _handle_ws_notification(self, notification: dict[str, Any]) -> None:
        """Process a WebSocket push notification."""
        self._last_ws_notification = time.monotonic()
        model_name = notification.get("modelName", "")
        model_id = notification.get("modelId")
        data_payload = notification.get("data", {})

        if not data_payload or model_id is None:
            LOGGER.debug(
                "WS notification dropped: empty data or no modelId (modelName=%s)",
                model_name,
            )
            return

        coordinator_data = self.coordinator.data
        breaker_ids: list[str] = []
        ct_ids: list[str] = []
        hub_updated = False

        if model_name == "IotWhem":
            # Check for child breaker updates
            if "ResidentialBreaker" in data_payload:
                for breaker_data in data_payload["ResidentialBreaker"]:
                    if self._apply_breaker_ws_update(breaker_data):
                        breaker_ids.append(breaker_data.get("id", "?"))

            # Check for child CT updates
            if "IotCt" in data_payload:
                for ct_data in data_payload["IotCt"]:
                    ct_id = ct_data.get("id")
                    if ct_id is not None:
                        ct_key = str(ct_id)
                        if ct_key in coordinator_data.cts:
                            normalize_ct_energy(
                                ct_data, coordinator_data.cts[ct_key]
                            )
                            coordinator_data.cts[ct_key].update(ct_data)
                            ct_ids.append(ct_key)

            # WHEM own property updates (exclude child arrays)
            whem_data = {
                k: v
                for k, v in data_payload.items()
                if k not in ("ResidentialBreaker", "IotCt")
            }
            if whem_data and str(model_id) in coordinator_data.whems:
                coordinator_data.whems[str(model_id)].update(whem_data)
                hub_updated = True

        elif model_name == "ResidentialBreakerPanel":
            # Check for child breaker updates
            if "ResidentialBreaker" in data_payload:
                for breaker_data in data_payload["ResidentialBreaker"]:
                    if self._apply_breaker_ws_update(breaker_data):
                        breaker_ids.append(breaker_data.get("id", "?"))

            # Panel own property updates
            panel_data = {
                k: v
                for k, v in data_payload.items()
                if k != "ResidentialBreaker"
            }
            if panel_data and str(model_id) in coordinator_data.panels:
                coordinator_data.panels[str(model_id)].update(panel_data)
                hub_updated = True

        elif model_name == "ResidentialBreaker":
            # Direct breaker update — data IS the breaker payload
            data_payload["id"] = str(model_id)
            if self._apply_breaker_ws_update(data_payload):
                breaker_ids.append(str(model_id))

        elif model_name == "IotCt":
            ct_key = str(model_id)
            if ct_key in coordinator_data.cts:
                normalize_ct_energy(
                    data_payload, coordinator_data.cts[ct_key]
                )
                coordinator_data.cts[ct_key].update(data_payload)
                ct_ids.append(ct_key)

        else:
            LOGGER.debug(
                "WS notification ignored: unknown model %s/%s",
                model_name, model_id,
            )
            return

        if breaker_ids or ct_ids or hub_updated:
            parts = [f"{model_name} {model_id}"]
            if hub_updated:
                parts.append("hub(%s)" % ", ".join(
                    k for k in data_payload
                    if k not in ("ResidentialBreaker", "IotCt")
                ))
            if breaker_ids:
                parts.append("breakers(%s)" % " ".join(breaker_ids))
            if ct_ids:
                parts.append("CTs(%s)" % " ".join(ct_ids))
            LOGGER.debug("WS update: %s", ", ".join(parts))
            self.coordinator.async_set_updated_data(coordinator_data)

    @callback
    def _handle_ws_disconnect(self) -> None:
        """Handle WebSocket disconnect - schedule reconnection."""
        LOGGER.warning("WebSocket disconnected, falling back to REST polling")
        self.ws = None
        self._ws_remove_notification = None
        self._ws_remove_disconnect = None
        self._stop_keepalive()
        if not self._reconnecting:
            self.coordinator.config_entry.async_create_background_task(
                self.coordinator.hass,
                self._reconnect(),
                "leviton_ws_reconnect",
            )

    async def _reconnect(self) -> None:
        """Attempt to reconnect WebSocket with exponential backoff."""
        if self._reconnecting:
            LOGGER.debug("WebSocket reconnection already in progress")
            return
        self._reconnecting = True
        coordinator = self.coordinator
        try:
            delays = [10, 30, 60, 120, 300]  # seconds
            for attempt, delay in enumerate(delays, 1):
                LOGGER.debug(
                    "WebSocket reconnection attempt %d in %d seconds",
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)

                # Validate token before attempting WS reconnect (WS module
                # can't distinguish auth failures from connection failures)
                try:
                    await coordinator.client.get_permissions()
                except LevitonAuthError as err:
                    LOGGER.warning(
                        "Token expired during reconnection: %s", err
                    )
                    coordinator.config_entry.async_start_reauth(
                        coordinator.hass
                    )
                    return
                except LevitonConnectionError:
                    LOGGER.debug(
                        "API unreachable during reconnection attempt %d",
                        attempt,
                    )
                    continue

                try:
                    await self.connect()
                    if self.ws is not None:
                        LOGGER.info("WebSocket reconnected successfully")
                        return
                except (LevitonConnectionError, OSError):
                    LOGGER.debug(
                        "WebSocket reconnection attempt %d failed",
                        attempt,
                        exc_info=True,
                    )
            LOGGER.warning(
                "WebSocket reconnection failed after %d attempts, "
                "using REST polling (10-min interval)",
                len(delays),
            )
        except asyncio.CancelledError:
            LOGGER.debug("WebSocket reconnection cancelled")
            raise
        finally:
            self._reconnecting = False
