"""Constants for the Leviton integration."""

from __future__ import annotations

import logging

DOMAIN = "leviton"
LOGGER = logging.getLogger(__package__)

CONF_VOLTAGE_208 = "voltage_208"
CONF_READ_ONLY = "read_only"
CONF_CALCULATED_CURRENT = "calculated_current"
CONF_HIDE_DUMMY = "hide_dummy"

DEFAULT_VOLTAGE_208 = False
DEFAULT_READ_ONLY = False
DEFAULT_CALCULATED_CURRENT = False
DEFAULT_HIDE_DUMMY = False

VOLTAGE_240 = 240
VOLTAGE_208 = 208
