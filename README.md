# Leviton Load Center Integration for Home Assistant

Home Assistant integration for the [Leviton Smart Load Center](https://www.leviton.com/products/residential/load-centers) product family, providing real-time energy monitoring and breaker control through the Leviton cloud API.

Supports both hub types and accessories:
- **LWHEM** (Whole Home Energy Module) — with smart breakers and CT clamps
- **LDATA** (Data Acquisition Unit) — older generation, smart breakers only
- **LSBMA** (Standalone Bluetooth CT Clamp) — individual circuit monitoring via LWHEM

## Features

- Real-time power, current, voltage, and frequency monitoring
- Lifetime and daily energy tracking (compatible with HA Energy Dashboard)
- Remote breaker control (on/off for Gen 2, trip for Gen 1)
- Breaker identify (LED blink)
- CT clamp monitoring (LWHEM only)
- Per-leg measurements for 2-pole breakers and panel-level aggregates
- Firmware update notifications via HA repair issues
- Two-factor authentication support
- Automatic WebSocket reconnection with silence watchdog

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to Integrations
3. Click the three dots menu and select "Custom repositories"
4. Add `https://github.com/gtxaspec/leviton-load-center` with category "Integration"
5. Search for "Leviton Load Center" and install
6. Restart Home Assistant

### Manual

1. Copy `custom_components/leviton_load_center/` to your HA `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings > Devices & Services > Add Integration**
2. Search for **Leviton Load Center**
3. Enter your My Leviton app credentials (same as my.leviton.com)
4. If 2FA is enabled on your account, enter the verification code when prompted

### Options

| Option | Default | Description |
|--------|---------|-------------|
| 208V electrical system | Off | For commercial 208V split-phase systems. Changes 2-pole voltage calculations from 240V to 208V. |
| Read-only mode | Off | Disables all control entities (trip, on/off, identify). Only sensors and diagnostics are created. |
| Calculate current from power | Off | Derives amperage from power/voltage instead of the raw `rmsCurrent` field for higher precision. |
| Hide non-smart breakers | Off | Hides basic breakers that don't have an LSBMA CT sensor attached. |

## Entities

### Smart Breaker (per breaker)

| Entity | Type | Notes |
|--------|------|-------|
| Watts | Sensor | Real-time power consumption |
| Amps | Sensor | Current draw |
| Daily energy | Sensor | Energy since midnight (kWh), for HA Energy Dashboard |
| Breaker status | Sensor | currentState (ON, SoftwareTrip, etc.) |
| Operational status | Sensor | operationalState |
| Remote status | Sensor | Gen 2 only (RemoteON/RemoteOFF) |
| Breaker on/off | Switch | Gen 2 only (`canRemoteOn: true`) |
| Trip | Button | All smart breakers |
| Identify LED | Switch | Blink the breaker's LED |
| Connectivity | Binary sensor | BLE connection to hub |
| Diagnostics | Sensors | Lifetime energy, amp rating, BLE RSSI, firmware versions, position, leg, poles, serial |

### CT Clamp (LWHEM only)

| Entity | Type | Notes |
|--------|------|-------|
| Watts | Sensor | Combined power (both legs) |
| Amps | Sensor | Combined current (both legs) |
| Diagnostics | Sensors | Per-leg power/current, lifetime energy, lifetime energy import, usage type |

### LWHEM Hub

| Entity | Type | Notes |
|--------|------|-------|
| Voltage / Voltage leg 1 / Voltage leg 2 | Sensor | Panel voltage |
| Frequency / Frequency leg 1 / Frequency leg 2 | Sensor | Line frequency |
| Watts / Watts leg 1 / Watts leg 2 | Sensor | Aggregated from CTs, falls back to breaker sum if no CTs |
| Amps / Amps leg 1 / Amps leg 2 | Sensor | Aggregated from CTs, falls back to breaker sum if no CTs |
| Daily energy | Sensor | Panel-level daily energy (CT-based or breaker sum fallback) |
| Identify | Button | Blink the LWHEM LED |
| Diagnostics | Sensors | Firmware (main, BLE), firmware update status, IP, MAC, WiFi RSSI, serial, residence ID, lifetime energy |

### LDATA Panel

| Entity | Type | Notes |
|--------|------|-------|
| Voltage / Voltage leg 1 / Voltage leg 2 | Sensor | Panel voltage |
| Frequency / Frequency leg 1 / Frequency leg 2 | Sensor | Line frequency |
| Watts / Watts leg 1 / Watts leg 2 | Sensor | Aggregated from breakers |
| Amps / Amps leg 1 / Amps leg 2 | Sensor | Aggregated from breakers |
| Daily energy | Sensor | Panel-level daily energy |
| Connectivity | Binary sensor | Online/offline status |
| Diagnostics | Sensors | Firmware (main, BCM, BSM, BSM radio, NCM), firmware update status, WiFi RSSI/SSID/mode, serial, residence ID, lifetime energy |

## Architecture

### Data Flow

```
Leviton Cloud API
        |
        +-- REST API: initial discovery, fallback polling (10-min interval)
        |
        +-- WebSocket
                |
                +-- IotWhem subscription (hub status + CT data, all FW)
                +-- ResidentialBreakerPanel subscription (LDATA hub + breaker data)
                +-- Individual ResidentialBreaker subscriptions (FW 2.0.0+ only)
```

### WebSocket Management

The Leviton cloud server enforces a **hard 60-minute WebSocket timeout** that terminates push notifications regardless of client activity. This integration handles it with three mechanisms:

| Mechanism | Interval | Purpose |
|-----------|----------|---------|
| Proactive reconnect | Every 55 min | Cycle the WS connection before the 60-min server cutoff |
| Silence watchdog | Every 30 sec | If no WS data for 90 seconds, force immediate reconnect |
| Bandwidth keepalive | Every 60 sec | Toggle bandwidth `1→0→1` on WHEMs to keep CTs pushing at high frequency |

On each reconnect, setting `bandwidth=1` triggers a full state flood from the server, providing automatic catch-up of any data missed during the brief reconnect gap.

### Comparison with the Official App

The official Leviton Android app (v3.94.1) uses a significantly more aggressive polling strategy:

| | This Integration | Official App |
|---|---|---|
| API calls/day | ~4,500 | ~12,000 |
| `GET /apiversion` | Not used | Every 10 seconds |
| Bandwidth PUT | 3 PUTs per WHEM, every 60s (1→0→1) | 2 PUTs per WHEM, every 50s |
| 60-min WS timeout | Proactive reconnect at 55 min | Not handled (WS dies, no reconnect) |
| Silence detection | 90-second watchdog | None |
| Data source | WebSocket push (real-time) | WebSocket push (real-time) |

This integration achieves the same real-time data delivery with **~3x fewer API calls** while also solving the 60-minute timeout that the official app does not address.

### Energy Tracking

Energy values require special handling because the Leviton cloud reports `energyConsumption` as **period deltas** (not lifetime totals) when `bandwidth=1` is active. The integration:

1. Caches known lifetime values and accumulates WS deltas on top
2. Detects and corrects stale delta values on REST polls
3. Clamps `TOTAL_INCREASING` sensors to a high-water mark to prevent float drift
4. Snapshots midnight baselines for daily energy calculation (lifetime minus baseline)

### Firmware-Aware Subscriptions

The integration detects WHEM firmware version and subscribes accordingly:

| Firmware | Strategy |
|----------|----------|
| FW 1.x | Subscribe to IotWhem only (delivers all child breaker + CT data) |
| FW 2.0.0+ | Subscribe to IotWhem (CT data) + individual ResidentialBreaker models |

LDATA panels deliver all child breaker data via the hub subscription on all firmware versions.

## Requirements

- A Leviton Smart Load Center (LWHEM and/or LDATA)
- A My Leviton account (my.leviton.com)
- Home Assistant 2024.1 or later
- Internet connection (cloud API, no local control)

## API Usage

This integration is designed to be a respectful consumer of the Leviton cloud API. It relies on WebSocket push notifications as its primary data source, only falling back to REST polling when the WebSocket connection is unavailable. Compared to the official Leviton mobile app, this integration generates approximately **3x fewer API calls** (~4,500/day vs ~12,000/day for a single WHEM) while delivering the same real-time data. We aim to minimize server load and avoid any unnecessary strain on Leviton's infrastructure.

## Planned Features

- Over-voltage / under-voltage binary sensors (API fields available on WHEMs and breakers)
- Energy import sensors for breakers (tracked internally, useful for solar installations)
- Energy history via cloud endpoints (`getAllEnergyConsumptionFor*` — alternative to lifetime delta calculation)

## Library

This integration uses [aioleviton](https://github.com/gtxaspec/aioleviton), an async Python library for the Leviton cloud API.

## Disclaimer

This is a do-it-yourself project for Leviton Load Center product users and is not affiliated with, endorsed by, or sponsored by Leviton Manufacturing Co., Inc. "Leviton" and all related product names are trademarks of Leviton Manufacturing Co., Inc. This integration interacts with Leviton's cloud services using your own account credentials. Use at your own risk.

## License

MIT
