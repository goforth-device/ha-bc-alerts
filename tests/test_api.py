"""Parse real feed samples. Runs without Home Assistant."""

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "bc_alerts_api", ROOT.parent / "custom_components" / "bc_alerts" / "api.py"
)
api = importlib.util.module_from_spec(spec)
sys.modules["bc_alerts_api"] = api
spec.loader.exec_module(api)

LOWER_ISLAND = api.Bounds(
    south=48.25, west=-124.9, north=49.22, east=-123.0, island_only=True
)
VICTORIA = (48.4284, -123.3656)
NOW = datetime(2026, 10, 30, 18, 0, tzinfo=UTC)


def fixture(name):
    """Load a saved feed."""
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def test_hydro_keeps_only_the_area():
    alerts = api.parse_hydro(fixture("hydro.json"), LOWER_ISLAND)
    assert alerts
    assert all(LOWER_ISLAND.contains(a.latitude, a.longitude) for a in alerts)
    names = " ".join(a.title for a in alerts)
    assert "Prince George" not in names
    assert "Vancouver" not in names


def test_hydro_polygon_is_lat_lon_and_contains_its_own_outage():
    alerts = api.parse_hydro(fixture("hydro.json"), LOWER_ISLAND)
    for alert in alerts:
        assert alert.polygon
        latitudes = [point[0] for point in alert.polygon]
        assert 48 < min(latitudes) < 50
        assert api.point_in_polygon(alert.latitude, alert.longitude, alert.polygon)


def test_home_is_not_in_any_outage():
    alerts = api.parse_hydro(fixture("hydro.json"), LOWER_ISLAND)
    assert not any(
        api.point_in_polygon(VICTORIA[0], VICTORIA[1], a.polygon) for a in alerts
    )


def test_point_in_polygon():
    square = ((0.0, 0.0), (0.0, 2.0), (2.0, 2.0), (2.0, 0.0))
    assert api.point_in_polygon(1.0, 1.0, square)
    assert not api.point_in_polygon(3.0, 1.0, square)
    assert not api.point_in_polygon(1.0, 1.0, ())


def test_drivebc_drops_other_regions_routine_work_and_future_events():
    alerts = api.parse_drivebc(fixture("drivebc.json"), LOWER_ISLAND, NOW)
    text = " ".join(a.detail for a in alerts)
    assert "Richmond" not in text
    assert "Highway 14" not in " ".join(a.title for a in alerts)
    assert not any(
        a.extra["severity"] == "MINOR" and a.category == api.CATEGORY_ROAD
        for a in alerts
    )


def test_drivebc_shows_a_closure_once_it_starts():
    during = datetime(2026, 11, 11, 19, 0, tzinfo=UTC)
    alerts = api.parse_drivebc(fixture("drivebc.json"), LOWER_ISLAND, during)
    closures = [a for a in alerts if a.category == api.CATEGORY_ROAD_CLOSURE]
    assert [a.title for a in closures] == ["Highway 14 closed"]


def test_alertable_finds_the_sooke_boil_water_advisory():
    alerts = api.parse_alertable(fixture("alertable.json"), LOWER_ISLAND)
    water = [a for a in alerts if a.category == api.CATEGORY_WATER]
    assert "Boil Water Advisory" in [a.title for a in water]
    assert not any(a.extra["issued_by"] == "DriveBC" for a in alerts)


def test_alertable_ended_alerts_are_dropped():
    payload = fixture("alertable.json")
    ended = {e["id"] for e in payload["entries"] if e["state"] == "ended"}
    alerts = api.parse_alertable(payload, LOWER_ISLAND)
    assert not {a.id.removeprefix("alertable-") for a in alerts} & ended


def test_evacuation_covers_polygons_and_multipolygons():
    alerts = api.parse_evacuation(fixture("evacuation.json"))
    assert alerts
    assert all(a.title.startswith("Evacuation ") for a in alerts)
    assert all(api.Bounds(48, -140, 60, -114).contains(a.latitude, a.longitude) for a in alerts)


def test_a_changed_feed_raises_a_feed_error():
    for parser, payload in (
        (lambda: api.parse_alertable({"items": []}, LOWER_ISLAND), None),
        (lambda: api.parse_drivebc({}, LOWER_ISLAND, NOW), None),
        (lambda: api.parse_evacuation({"error": {}}), None),
        (lambda: api.parse_hydro([{"id": 1}], LOWER_ISLAND), None),
    ):
        try:
            parser()
        except api.FEED_ERRORS:
            continue
        raise AssertionError("expected a feed error")


def test_area_keeps_the_gulf_islands_and_leaves_out_the_mainland():
    for place in (
        (48.794, -123.186),  # Lyall Harbour, Saturna
        (48.78, -123.05),  # East Point, Saturna
        (48.95, -123.5),  # Galiano
        (49.16, -123.75),  # Gabriola
        (49.17, -123.95),  # Nanaimo
    ):
        assert LOWER_ISLAND.contains(*place), place
    for place in (
        (49.125, -123.18),  # Steveston
        (49.007, -123.1),  # Tsawwassen
        (49.08, -123.06),  # Delta
        (49.21, -123.2),  # Vancouver
    ):
        assert not LOWER_ISLAND.contains(*place), place


def weather_feature(**overrides):
    """Return an Environment Canada feature like the live feed's."""
    properties = {
        "feature_id": "abc",
        "alert_code": "WNW",
        "alert_type": "warning",
        "alert_name_en": "wind warning",
        "feature_name_en": "Metro Vancouver",
        "status_en": "issued",
        "alert_text_en": "Strong winds.",
        "publication_datetime": "2026-10-30T19:00:00Z",
        "expiration_datetime": "2026-10-31T19:00:00Z",
    }
    return {
        "properties": {**properties, **overrides},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-123.2, 49.1], [-122.8, 49.1], [-122.8, 49.4]]],
        },
    }


def test_weather_keeps_storms_outside_the_crd():
    alerts = api.parse_weather({"features": [weather_feature()]}, NOW)
    assert [a.category for a in alerts] == [api.CATEGORY_WEATHER]
    assert alerts[0].title == "Wind warning: Metro Vancouver"
    assert 40 < alerts[0].latitude < 60


def test_air_quality_outside_the_crd_is_left_out():
    assert not api.parse_weather(fixture("weather.json"), NOW)
    duncan = weather_feature(alert_name_en="air quality warning")
    duncan["geometry"]["coordinates"] = [[[-124.2, 49.0], [-123.6, 48.5], [-123.56, 48.8]]]
    assert not api.parse_weather({"features": [duncan]}, NOW)


def test_air_quality_in_the_crd_gets_its_own_category():
    victoria = weather_feature(
        alert_name_en="air quality warning", feature_name_en="Greater Victoria"
    )
    victoria["geometry"]["coordinates"] = [[[-123.6, 48.4], [-123.3, 48.4], [-123.4, 48.7]]]
    alerts = api.parse_weather({"features": [victoria]}, NOW)
    assert [a.category for a in alerts] == [api.CATEGORY_AIR]
    assert alerts[0].title == "Air quality warning: Greater Victoria"


def test_crd_outline():
    for place in (
        VICTORIA,
        (48.65, -123.40),  # Sidney
        (48.37, -123.73),  # Sooke
        (48.55, -124.42),  # Port Renfrew
        (48.82, -123.50),  # Salt Spring
        (48.78, -123.17),  # Saturna
    ):
        assert api.point_in_polygon(*place, api.CRD_OUTLINE), place
    for place in (
        (48.78, -123.71),  # Duncan
        (48.65, -123.63),  # Shawnigan Lake
        (49.17, -123.94),  # Nanaimo
        (49.25, -123.10),  # Vancouver
        (48.10, -123.40),  # Port Angeles
    ):
        assert not api.point_in_polygon(*place, api.CRD_OUTLINE), place


def test_weather_skips_ended_and_expired_alerts():
    later = datetime(2026, 11, 1, tzinfo=UTC)
    payload = {"features": [weather_feature()]}
    assert len(api.parse_weather(payload, NOW)) == 1
    assert not api.parse_weather(payload, later)
    ended = {"features": [weather_feature(status_en="ended")]}
    assert not api.parse_weather(ended, NOW)


def test_alertable_leaves_weather_to_environment_canada():
    payload = {
        "entries": [
            {
                "id": "1",
                "point": "48.4 -123.4",
                "author_en": "Environment Canada",
                "event_en": "wind",
            }
        ]
    }
    assert not api.parse_alertable(payload, LOWER_ISLAND)


def test_uvic_quiet_page_has_no_alert():
    page = (ROOT / "fixtures" / "uvic.html").read_text(encoding="utf-8")
    assert api.parse_uvic(page) == []


def test_uvic_emergency_page_makes_one_alert():
    page = (ROOT / "fixtures" / "uvic.html").read_text(encoding="utf-8")
    page = page.replace(
        "There is currently no emergency at the University of Victoria.",
        "Gas leak near the Clearihue Building &amp; library. Avoid the area.",
    )
    alerts = api.parse_uvic(page)
    assert [a.id for a in alerts] == [api.UVIC_ALERT_ID]
    assert alerts[0].detail.startswith("Gas leak near the Clearihue Building & library")
    assert "Resources" not in alerts[0].detail


def test_uvic_page_redesign_is_a_feed_error():
    try:
        api.parse_uvic("<html><main>New design</main></html>")
    except api.FEED_ERRORS:
        return
    raise AssertionError("expected a feed error")


def test_distance():
    assert 15 < api.distance_km(*VICTORIA, 48.3537, -123.6144) < 25
