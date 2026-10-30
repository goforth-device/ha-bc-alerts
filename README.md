# BC Alerts for Home Assistant

Power outages, road closures, water notices and emergencies for an area of British Columbia, with a pin on the map for each one. The default area is lower Vancouver Island.

| Feed | What it adds |
|---|---|
| BC Hydro | Outages, including whether your home is inside an outage area |
| DriveBC | Road closures and incidents, leaving out routine construction |
| Alertable | Water notices, local closures, weather and community notices |
| EmergencyInfoBC | Evacuation orders and alerts |

## Install

1. In HACS, add this repository as a custom repository of type Integration, then download it. Or copy `custom_components/bc_alerts` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Go to Settings → Devices & services → Add integration → BC Alerts.

## Entities

- Counts: `sensor.bc_alerts_power_outages`, `_road_closures`, `_road_incidents`, `_water_notices`, `_emergencies`, `_weather_alerts`, `_community_notices`. Each lists its closest alerts in the `alerts` attribute.
- `binary_sensor.bc_alerts_outage_at_home` turns on when your home is inside a BC Hydro outage area.
- `binary_sensor.bc_alerts_water_notice_nearby` turns on when a water notice is within the distance you set.
- `binary_sensor.bc_alerts_feed_problem` turns on when a feed fails. The last good alerts stay in place until it recovers.

Add pins to a map card with `geo_location_sources: [bc_alerts]`.

## Limits

These feeds aren't documented public APIs, so any of them can change without notice. This project isn't affiliated with BC Hydro, DriveBC, Alertable or the Province of BC. Don't rely on it for safety: use official alerts for that.

## Tests

`uv run --with pytest-homeassistant-custom-component python -m pytest tests --asyncio-mode=auto`
