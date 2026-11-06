# BC Alerts for Home Assistant

Power outages, road closures, water notices, weather alerts and emergencies for an area of British Columbia, with a pin on the map for each one. The default area is lower Vancouver Island. Weather alerts always cover all of Vancouver Island and Metro Vancouver. Air quality warnings are kept to the Capital Regional District.

| Feed | What it adds |
|---|---|
| BC Hydro | Outages, including whether your home is inside an outage area |
| DriveBC | Road closures and incidents, leaving out routine construction |
| Alertable | Water notices, local closures, weather and community notices |
| EmergencyInfoBC | Evacuation orders and alerts |
| Environment Canada | Weather warnings, watches and advisories, and air quality warnings |
| UVic | Campus emergencies from the University of Victoria's emergency page |

## Install

1. In HACS, add this repository as a custom repository of type Integration, then download it. Or copy `custom_components/bc_alerts` into your Home Assistant config folder.
2. Restart Home Assistant.
3. Go to Settings → Devices & services → Add integration → BC Alerts.

## Entities

- Counts: `sensor.bc_alerts_power_outages`, `_road_closures`, `_road_incidents`, `_water_notices`, `_emergencies`, `_weather_alerts`, `_air_quality`, `_community_notices`. Each lists its closest alerts in the `alerts` attribute.
- `binary_sensor.bc_alerts_outage_at_home` turns on when your home is inside a BC Hydro outage area.
- `binary_sensor.bc_alerts_water_notice_nearby` turns on when a water notice is within the distance you set.
- `binary_sensor.bc_alerts_uvic_emergency` turns on when UVic's emergency page reports an emergency.
- `binary_sensor.bc_alerts_feed_problem` turns on when a feed fails. The last good alerts stay in place until it recovers.

Add pins to a map card with `geo_location_sources: [bc_alerts]`.

Each kind of alert has its own pin picture. Weather pins show the hazard: wind, rain, snow, cold, frost, freezing rain, heat, fog, thunderstorms, tornadoes or storm surge. When two alerts cover the same area, both pins show the pair: wind and rain as a storm, wind and snow (or a winter storm) as a blizzard, wind and cold (or Arctic outflow) as outflow, and storm surge with wind or rain as a surge storm. Anything else, such as a special weather statement, gets the general weather pin.

## Limits

These feeds aren't documented public APIs, so any of them can change without notice. This project isn't affiliated with BC Hydro, DriveBC, Alertable, Environment Canada, UVic or the Province of BC. Don't rely on it for safety: use official alerts for that.

## Tests

`uv run --with pytest-homeassistant-custom-component python -m pytest tests --asyncio-mode=auto`
