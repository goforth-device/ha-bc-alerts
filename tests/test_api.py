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


def test_distance():
    assert 15 < api.distance_km(*VICTORIA, 48.3537, -123.6144) < 25
