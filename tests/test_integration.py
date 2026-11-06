"""Load the integration in a real Home Assistant, serving saved feeds."""

from dataclasses import replace
import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.bc_alerts.api import (
    ALERTABLE_URL,
    CATEGORY_ROAD,
    CATEGORY_ROAD_CLOSURE,
    CATEGORY_WEATHER,
    DRIVEBC_URL,
    EVACUATION_URL,
    HYDRO_URL,
    UVIC_URL,
    WEATHER_URL,
    Alert,
)
from custom_components.bc_alerts.const import DOMAIN
from custom_components.bc_alerts.geo_location import (
    CATEGORY_IMAGES,
    pin_icon,
    pin_image,
)

FIXTURES = Path(__file__).parent / "fixtures"
AREA = {
    "south": 48.25,
    "west": -124.9,
    "north": 49.22,
    "east": -123.0,
    "island_only": True,
    "nearby_km": 25,
}


@pytest.fixture(autouse=True)
def enable_custom(enable_custom_integrations):
    """Let Home Assistant load the integration."""


def text(name: str) -> str:
    """Return a saved feed."""
    return (FIXTURES / name).read_text(encoding="utf-8")


def mock_feeds(aioclient_mock: AiohttpClientMocker, weather: str | None = None) -> None:
    """Serve every feed from its saved sample."""
    aioclient_mock.get(HYDRO_URL, text=text("hydro.json"))
    aioclient_mock.get(DRIVEBC_URL, text=text("drivebc.json"))
    aioclient_mock.get(ALERTABLE_URL, text=text("alertable.json"))
    aioclient_mock.get(EVACUATION_URL, text=text("evacuation.json"))
    aioclient_mock.get(WEATHER_URL, text=weather or text("weather.json"))
    aioclient_mock.get(UVIC_URL, text=text("uvic.html"))


async def setup_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add and load an entry."""
    entry = MockConfigEntry(domain=DOMAIN, data=AREA, unique_id=DOMAIN)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow_creates_one_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_feeds(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    bad = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**AREA, "south": 50.0}
    )
    assert bad["errors"] == {"base": "invalid_area"}

    done = await hass.config_entries.flow.async_configure(result["flow_id"], AREA)
    await hass.async_block_till_done()
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_entities_and_pins(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass.config.latitude = 48.4284
    hass.config.longitude = -123.3656
    mock_feeds(aioclient_mock)
    await setup_entry(hass)

    assert int(hass.states.get("sensor.bc_alerts_power_outages").state) > 0
    assert int(hass.states.get("sensor.bc_alerts_water_notices").state) > 0
    assert hass.states.get("binary_sensor.bc_alerts_outage_at_home").state == "off"
    assert hass.states.get("binary_sensor.bc_alerts_feed_problem").state == "off"
    assert hass.states.get("binary_sensor.bc_alerts_uvic_emergency").state == "off"
    assert hass.states.get("sensor.bc_alerts_air_quality").state == "0"

    water = hass.states.get("binary_sensor.bc_alerts_water_notice_nearby")
    assert water.state == "on"
    assert water.attributes["alerts"][0]["distance_km"] <= 25

    pins = hass.states.async_all("geo_location")
    assert pins
    assert all(pin.attributes["source"] == DOMAIN for pin in pins)
    assert all("latitude" in pin.attributes for pin in pins)

    images = Path(__file__).parent.parent / "custom_components/bc_alerts/images"
    pictures = {pin.attributes["entity_picture"] for pin in pins}
    assert "/bc_alerts_static/power.svg" in pictures
    assert "/bc_alerts_static/water.svg" in pictures
    assert all((images / picture.rsplit("/", 1)[1]).is_file() for picture in pictures)


async def test_air_quality_in_the_crd_gets_its_own_count_and_pin(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass.config.latitude = 48.4284
    hass.config.longitude = -123.3656
    feed = json.loads(text("weather.json"))
    feed["features"][0]["properties"]["expiration_datetime"] = None
    feed["features"][0]["geometry"]["coordinates"] = [
        [[-123.6, 48.4], [-123.3, 48.4], [-123.4, 48.7]]
    ]
    mock_feeds(aioclient_mock, json.dumps(feed))
    await setup_entry(hass)

    assert hass.states.get("sensor.bc_alerts_air_quality").state == "1"
    assert hass.states.get("sensor.bc_alerts_weather_alerts").state == "0"
    pins = hass.states.async_all("geo_location")
    pin = next(p for p in pins if p.attributes["category"] == "air_quality")
    assert pin.attributes["entity_picture"] == "/bc_alerts_static/air_quality.svg"


def test_every_pin_image_exists() -> None:
    images = Path(__file__).parent.parent / "custom_components/bc_alerts/images"
    assert all((images / name).is_file() for name in CATEGORY_IMAGES.values())
    assert (images / "road_work.svg").is_file()


def test_road_work_gets_the_striped_pin() -> None:
    work = Alert(
        id="1",
        source="DriveBC",
        category=CATEGORY_ROAD,
        title="Highway 1: Construction",
        detail="",
        latitude=48.4,
        longitude=-123.4,
        extra={"event_type": "CONSTRUCTION"},
    )
    crash = replace(work, extra={"event_type": "INCIDENT"})
    closed = replace(work, category=CATEGORY_ROAD_CLOSURE)
    assert pin_image(work).endswith("road_work.svg")
    assert pin_image(crash).endswith("road_incident.svg")
    assert pin_image(closed).endswith("road_closed.svg")


def weather(name: str, area: str = "Greater Victoria", detail: str = "") -> Alert:
    return Alert(
        id=f"{name}-{area}",
        source="Environment Canada",
        category=CATEGORY_WEATHER,
        title=f"{name}: {area}",
        detail=detail,
        latitude=48.4,
        longitude=-123.4,
        extra={"area": area},
    )


@pytest.mark.parametrize(
    ("names", "kind"),
    [
        (["Wind warning"], "wind"),
        (["Rainfall warning"], "rain"),
        (["Snowfall warning"], "snow"),
        (["Extreme cold warning"], "cold"),
        (["Frost advisory"], "frost"),
        (["Freezing rain warning"], "ice"),
        (["Heat warning"], "heat"),
        (["Fog advisory"], "fog"),
        (["Severe thunderstorm warning"], "thunder"),
        (["Tornado warning"], "tornado"),
        (["Storm surge warning"], "surge"),
        (["Winter storm warning"], "blizzard"),
        (["Arctic outflow warning"], "outflow"),
        (["Wind warning", "Rainfall warning"], "storm"),
        (["Wind warning", "Snowfall warning"], "blizzard"),
        (["Wind warning", "Extreme cold warning"], "outflow"),
        (["Storm surge warning", "Wind warning"], "surge_storm"),
        (["Special weather statement"], "general"),
    ],
)
def test_weather_pins_show_the_hazard(names: list[str], kind: str) -> None:
    alerts = [weather(name) for name in names]
    images = Path(__file__).parent.parent / "custom_components/bc_alerts/images"
    for alert in alerts:
        picture = pin_image(alert, alerts)
        expected = "weather.svg" if kind == "general" else f"weather_{kind}.svg"
        assert picture.endswith(f"/{expected}")
        assert (images / expected).is_file()
        assert pin_icon(alert, alerts).startswith("mdi:")


def test_weather_pins_only_combine_alerts_for_the_same_area() -> None:
    wind = weather("Wind warning")
    rain = weather("Rainfall warning", area="Howe Sound")
    assert pin_image(wind, [wind, rain]).endswith("weather_wind.svg")
    assert pin_image(rain, [wind, rain]).endswith("weather_rain.svg")


def test_a_statement_is_read_for_its_hazard() -> None:
    snow = weather("Special weather statement", detail="Heavy snow is expected over higher terrain.")
    assert pin_image(snow).endswith("weather_snow.svg")
    assert pin_image(weather("Wind warning")).endswith("weather_wind.svg")


async def test_outage_at_home_turns_on(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    rows = json.loads(text("hydro.json"))
    rows = [r for r in rows if r["municipality"] == "Metchosin"]
    hass.config.latitude = rows[0]["latitude"]
    hass.config.longitude = rows[0]["longitude"]
    mock_feeds(aioclient_mock)
    await setup_entry(hass)
    state = hass.states.get("binary_sensor.bc_alerts_outage_at_home")
    assert state.state == "on"
    assert state.attributes["customers_out"] == rows[0]["numCustomersOut"]


async def test_failed_feed_keeps_last_alerts_and_flags_a_problem(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_feeds(aioclient_mock)
    entry = await setup_entry(hass)
    before = hass.states.get("sensor.bc_alerts_power_outages").state

    aioclient_mock.clear_requests()
    aioclient_mock.get(HYDRO_URL, status=500)
    aioclient_mock.get(DRIVEBC_URL, text=text("drivebc.json"))
    aioclient_mock.get(ALERTABLE_URL, text=text("alertable.json"))
    aioclient_mock.get(EVACUATION_URL, text=text("evacuation.json"))
    aioclient_mock.get(WEATHER_URL, text=text("weather.json"))
    aioclient_mock.get(UVIC_URL, text=text("uvic.html"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.bc_alerts_power_outages").state == before
    problem = hass.states.get("binary_sensor.bc_alerts_feed_problem")
    assert problem.state == "on"
    assert "BC Hydro" in problem.attributes["failed_feeds"]


async def test_ended_alerts_lose_their_pins(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_feeds(aioclient_mock)
    entry = await setup_entry(hass)
    count = len(hass.states.async_all("geo_location"))
    assert count

    aioclient_mock.clear_requests()
    aioclient_mock.get(HYDRO_URL, text="[]")
    aioclient_mock.get(DRIVEBC_URL, text=text("drivebc.json"))
    aioclient_mock.get(ALERTABLE_URL, text=text("alertable.json"))
    aioclient_mock.get(EVACUATION_URL, text=text("evacuation.json"))
    aioclient_mock.get(WEATHER_URL, text=text("weather.json"))
    aioclient_mock.get(UVIC_URL, text=text("uvic.html"))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get("sensor.bc_alerts_power_outages").state == "0"
    assert len(hass.states.async_all("geo_location")) < count


async def test_unload_removes_the_pins(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_feeds(aioclient_mock)
    entry = await setup_entry(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert all(
        pin.state == "unavailable" for pin in hass.states.async_all("geo_location")
    ) or not hass.states.async_all("geo_location")
