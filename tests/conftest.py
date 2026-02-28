"""Common fixtures for Leviton tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aioleviton import AuthToken, Breaker, Ct, Panel, Permission, Residence, Whem

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.components.leviton_load_center.const import DOMAIN

MOCK_EMAIL = "test@example.com"
MOCK_PASSWORD = "testpassword123"
MOCK_TOKEN = "xxxxxxxxxxxxxxxxxxxxxxxxxTEST_TOKEN_NOT_REALxxxxxxxxxxxxxxxxx"
MOCK_USER_ID = "00000000-0000-4000-8000-000000000001"

MOCK_AUTH_TOKEN = AuthToken(
    token=MOCK_TOKEN,
    ttl=5184000,
    created="2026-02-15T10:28:31.957Z",
    user_id=MOCK_USER_ID,
    user={
        "id": MOCK_USER_ID,
        "firstName": "Test",
        "lastName": "User",
        "email": MOCK_EMAIL,
    },
)

MOCK_PERMISSION = Permission(
    id=1,
    access="owner",
    status="active",
    person_id=MOCK_USER_ID,
    residence_id=None,
    residential_account_id=9999999,
)

MOCK_RESIDENCE = Residence(
    id=100001,
    name="Test Home",
    status="HOME",
    timezone_id="America/Los_Angeles",
    residential_account_id=9999999,
    energy_cost=0.64,
)

MOCK_WHEM = Whem(
    id="TEST_0000_0001",
    name="Main Panel",
    model="LWHEM",
    serial="TEST_0000_0001",
    manufacturer="Leviton Manufacturing Co., Inc.",
    version="1.7.6",
    version_ble="1.2.2",
    connected=True,
    local_ip="192.168.1.100",
    mac="AA:BB:CC:DD:EE:FF",
    rssi=-36,
    residence_id=100001,
    rms_voltage_a=119,
    rms_voltage_b=122,
    frequency_a=60,
    frequency_b=60,
    panel_size=20,
    breaker_count=10,
    bandwidth=2,
    identify=None,
    raw={},
)

MOCK_PANEL = Panel(
    id="LDATA-TEST0-TEST0-00001",
    name="Breaker Panel 1",
    model="DAU",
    manufacturer="Leviton",
    breaker_count=2,
    panel_size=30,
    status="READY",
    commissioned=True,
    residence_id=100001,
    bandwidth=1,
    rms_voltage=120,
    rms_voltage_2=0,
    wifi_mode="Client",
    wifi_rssi=-21,
    wifi_ssid="TestNetwork",
    version_bcm="0.0.10",
    version_bcm_radio="",
    version_bsm="0.1.47",
    version_bsm_radio="FWB7553000122",
    version_ncm="0.3.9",
    package_ver="0.1.91",
    online="2026-02-15T23:22:12.000Z",
    offline=None,
    raw={},
)

MOCK_BREAKER_GEN1 = Breaker(
    id="AABBCCDDEEF1",
    name="Kitchen",
    model="LB115-DS",
    branch_type="Outlets",
    position=1,
    poles=1,
    current_rating=15,
    current_state="ManualON",
    current_state_2=None,
    operational_state="Normal",
    power=120,
    power_2=None,
    rms_current=1,
    rms_current_2=None,
    rms_voltage=None,
    rms_voltage_2=None,
    energy_consumption=3402.017,
    energy_consumption_2=None,
    energy_import=None,
    energy_import_2=None,
    line_frequency=None,
    line_frequency_2=None,
    ble_rssi=-38,
    connected=True,
    remote_trip=False,
    remote_state="",
    remote_on=False,
    can_remote_on=False,
    firmware_version_ble="FWC3480000113",
    firmware_version_meter="FWC0780000100",
    firmware_version_silabs="FWC2422000100",
    firmware_version_gfci=None,
    firmware_version_afci=None,
    hw_version="AFGF-01",
    serial_number="ABC123",
    locked=False,
    blink_led=False,
    lsbma_id=None,
    lsbma_id_2=None,
    lsbma_parent_id=None,
    iot_whem_id="TEST_0000_0001",
    residential_breaker_panel_id=None,
    raw={},
)

MOCK_BREAKER_GEN2 = Breaker(
    id="AABBCCDDEEF2",
    name="Bedroom",
    model="LB120-DST",
    branch_type="Outlets",
    position=3,
    poles=1,
    current_rating=20,
    current_state="ManualON",
    current_state_2=None,
    operational_state="Normal",
    power=204,
    power_2=None,
    rms_current=2,
    rms_current_2=None,
    rms_voltage=None,
    rms_voltage_2=None,
    energy_consumption=1500.0,
    energy_consumption_2=None,
    energy_import=None,
    energy_import_2=None,
    line_frequency=None,
    line_frequency_2=None,
    ble_rssi=-44,
    connected=True,
    remote_trip=False,
    remote_state="RemoteON",
    remote_on=True,
    can_remote_on=True,
    firmware_version_ble="FWC3480000113",
    firmware_version_meter="FWC0780000100",
    firmware_version_silabs="FWC2422000100",
    firmware_version_gfci="FWC1234000100",
    firmware_version_afci=None,
    hw_version="AFGF-01",
    serial_number="DEF456",
    locked=False,
    blink_led=False,
    lsbma_id=None,
    lsbma_id_2=None,
    lsbma_parent_id=None,
    iot_whem_id="TEST_0000_0001",
    residential_breaker_panel_id=None,
    raw={},
)

MOCK_CT = Ct(
    id=7873,
    name="",
    channel=1,
    iot_whem_id="TEST_0000_0001",
    active_power=196,
    active_power_2=153,
    energy_consumption=5000.0,
    energy_consumption_2=4500.0,
    energy_import=100.0,
    energy_import_2=90.0,
    rms_current=8,
    rms_current_2=6,
    connected=True,
    usage_type="GRID_POWER",
    raw={},
)


@pytest.fixture
def mock_config_entry_data() -> dict:
    """Return mock config entry data."""
    return {
        CONF_EMAIL: MOCK_EMAIL,
        CONF_PASSWORD: MOCK_PASSWORD,
    }


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create and register a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_EMAIL,
        data={CONF_EMAIL: MOCK_EMAIL, CONF_PASSWORD: MOCK_PASSWORD},
        unique_id=MOCK_EMAIL.lower(),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Return a mocked LevitonClient."""
    with patch(
        "homeassistant.components.leviton_load_center.LevitonClient",
        autospec=True,
    ) as mock_cls:
        client = mock_cls.return_value
        client.login = AsyncMock(return_value=MOCK_AUTH_TOKEN)
        client.token = MOCK_TOKEN
        client.user_id = MOCK_USER_ID
        client._auth_token = MOCK_AUTH_TOKEN
        client._session = MagicMock()
        client.get_permissions = AsyncMock(return_value=[MOCK_PERMISSION])
        client.get_residences = AsyncMock(return_value=[MOCK_RESIDENCE])
        client.get_whems = AsyncMock(return_value=[MOCK_WHEM])
        client.get_whem = AsyncMock(return_value=MOCK_WHEM)
        client.get_panels = AsyncMock(return_value=[MOCK_PANEL])
        client.get_panel = AsyncMock(return_value=MOCK_PANEL)
        client.get_whem_breakers = AsyncMock(
            return_value=[MOCK_BREAKER_GEN1, MOCK_BREAKER_GEN2]
        )
        client.get_panel_breakers = AsyncMock(return_value=[])
        client.get_cts = AsyncMock(return_value=[MOCK_CT])
        client.trip_breaker = AsyncMock()
        client.turn_on_breaker = AsyncMock()
        client.turn_off_breaker = AsyncMock()
        client.blink_led = AsyncMock()
        client.stop_blink_led = AsyncMock()
        client.identify_whem = AsyncMock()
        client.set_panel_bandwidth = AsyncMock()
        client.set_whem_bandwidth = AsyncMock()
        # create_websocket returns a mock WS (used by mock_websocket fixture)
        ws = MagicMock()
        ws.connect = AsyncMock()
        ws.disconnect = AsyncMock()
        ws.subscribe = AsyncMock()
        ws.unsubscribe = AsyncMock()
        ws.on_notification = MagicMock(return_value=MagicMock())
        ws.on_disconnect = MagicMock(return_value=MagicMock())
        client.create_websocket = MagicMock(return_value=ws)
        client._mock_ws = ws  # expose for mock_websocket fixture
        yield client


@pytest.fixture
def mock_websocket(mock_client: AsyncMock) -> Generator[MagicMock]:
    """Return the mocked LevitonWebSocket from mock_client.create_websocket()."""
    yield mock_client._mock_ws
