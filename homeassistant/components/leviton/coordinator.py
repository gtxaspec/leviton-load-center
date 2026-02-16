"""DataUpdateCoordinator for the Leviton integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from aiolevtion import (
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
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import LOGGER

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
            update_interval=timedelta(minutes=5),
        )
        self.client = client
        self.ws: LevitonWebSocket | None = None
        self._residence_ids: list[int] = []
        self._ws_remove_notification: Any = None
        self._ws_remove_disconnect: Any = None

    async def _async_setup(self) -> None:
        """Discover devices and connect WebSocket on first refresh."""
        await self._discover_devices()
        await self._connect_websocket()

    async def _discover_devices(self) -> None:
        """Discover all residences, hubs, breakers, and CTs."""
        try:
            permissions = await self.client.get_permissions()
        except LevitonAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except LevitonConnectionError as err:
            raise UpdateFailed(str(err)) from err

        # Collect all account IDs from permissions
        account_ids: set[int] = set()
        for perm in permissions:
            if perm.residential_account_id is not None:
                account_ids.add(perm.residential_account_id)

        # Get residences from each account
        residences: dict[int, Residence] = {}
        for account_id in account_ids:
            try:
                account_residences = await self.client.get_residences(account_id)
                for res in account_residences:
                    residences[res.id] = res
            except LevitonConnectionError as err:
                LOGGER.warning(
                    "Failed to fetch residences for account %s: %s",
                    account_id,
                    err,
                )

        self._residence_ids = list(residences.keys())
        self.data = LevitonData(residences=residences)

        # Discover hubs and their children in each residence
        for residence_id in self._residence_ids:
            await self._discover_residence_devices(residence_id)

    async def _discover_residence_devices(self, residence_id: int) -> None:
        """Discover all devices in a single residence."""
        # LWHEM hubs
        try:
            whems = await self.client.get_whems(residence_id)
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

        auth_token = self.client._auth_token
        if auth_token is None:
            return

        try:
            self.ws = LevitonWebSocket(
                session=self.client._session,
                token=auth_token.token,
                user_id=auth_token.user_id,
                user=auth_token.user,
                token_created=auth_token.created,
                token_ttl=auth_token.ttl,
            )
            await self.ws.connect()
        except LevitonConnectionError:
            LOGGER.warning("WebSocket connection failed, using REST polling only")
            self.ws = None
            return

        # Register callbacks
        self._ws_remove_notification = self.ws.on_notification(
            self._handle_ws_notification
        )
        self._ws_remove_disconnect = self.ws.on_disconnect(
            self._handle_ws_disconnect
        )

        # Subscribe to all LWHEM hubs
        for whem_id in self.data.whems:
            try:
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

    @callback
    def _handle_ws_notification(self, notification: dict[str, Any]) -> None:
        """Process a WebSocket push notification."""
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
                        self.data.breakers[breaker_id].update(breaker_data)
                        updated = True

            # Check for child CT updates
            if "IotCt" in data:
                for ct_data in data["IotCt"]:
                    ct_id = ct_data.get("id")
                    if ct_id and ct_id in self.data.cts:
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
                        self.data.breakers[breaker_id].update(breaker_data)
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
                self.data.breakers[breaker_id].update(data)
                updated = True

        elif model_name == "IotCt":
            ct_id = model_id
            if isinstance(ct_id, int) and ct_id in self.data.cts:
                self.data.cts[ct_id].update(data)
                updated = True

        if updated:
            self.async_set_updated_data(self.data)

    @callback
    def _handle_ws_disconnect(self) -> None:
        """Handle WebSocket disconnect."""
        LOGGER.info("WebSocket disconnected, relying on REST polling")
        self.ws = None

    async def _async_update_data(self) -> LevitonData:
        """Fallback REST polling - refresh all device data."""
        try:
            # Refresh WHEM hubs
            for whem_id in list(self.data.whems):
                whem = await self.client.get_whem(whem_id)
                self.data.whems[whem_id] = whem

                breakers = await self.client.get_whem_breakers(whem_id)
                for breaker in breakers:
                    self.data.breakers[breaker.id] = breaker

                cts = await self.client.get_cts(whem_id)
                for ct in cts:
                    self.data.cts[ct.id] = ct

            # Refresh DAU panels
            for panel_id in list(self.data.panels):
                panel = await self.client.get_panel(panel_id)
                self.data.panels[panel_id] = panel

                breakers = await self.client.get_panel_breakers(panel_id)
                for breaker in breakers:
                    self.data.breakers[breaker.id] = breaker

            # Check for new devices in residences
            for residence_id in self._residence_ids:
                await self._discover_residence_devices(residence_id)

        except LevitonAuthError as err:
            raise ConfigEntryAuthFailed(err) from err
        except LevitonConnectionError as err:
            raise UpdateFailed(str(err)) from err

        return self.data

    async def async_shutdown(self) -> None:
        """Clean up WebSocket and bandwidth settings."""
        # Clean up notification callbacks
        if self._ws_remove_notification:
            self._ws_remove_notification()
        if self._ws_remove_disconnect:
            self._ws_remove_disconnect()

        # Disable DAU bandwidth
        for panel_id in self.data.panels:
            try:
                await self.client.set_panel_bandwidth(panel_id, enabled=False)
            except LevitonConnectionError:
                LOGGER.debug(
                    "Failed to disable bandwidth for panel %s", panel_id
                )

        # Disconnect WebSocket
        if self.ws:
            await self.ws.disconnect()
            self.ws = None
