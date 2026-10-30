"""Constants for BC Alerts."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "bc_alerts"
UPDATE_INTERVAL = timedelta(minutes=5)
IMAGES_URL = "/bc_alerts_static"

CONF_SOUTH = "south"
CONF_WEST = "west"
CONF_NORTH = "north"
CONF_EAST = "east"
CONF_NEARBY_KM = "nearby_km"
CONF_ISLAND_ONLY = "island_only"

# Lower Vancouver Island and the southern Gulf Islands, from Port Renfrew and
# Port Alberni across to Saturna. CONF_ISLAND_ONLY keeps the Lower Mainland out.
DEFAULT_SOUTH = 48.25
DEFAULT_WEST = -124.9
DEFAULT_NORTH = 49.22
DEFAULT_EAST = -123.0
DEFAULT_NEARBY_KM = 25
DEFAULT_ISLAND_ONLY = True
