"""Turn saved bcferriesapi.ca data into ferry alerts."""

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.bc_alerts.ferries import (
    BC_TIME,
    _iso,
    notice_alerts,
    notice_cancellations,
    parse_legacy_sailings,
    parse_v2,
    sailing_alerts,
    summary,
)

FIXTURES = Path(__file__).parent / "fixtures"
# 10:30 am in Victoria, which keeps daylight time all year from 2026.
NOW = datetime(2026, 11, 24, 17, 30, tzinfo=UTC)


def fixture(name):
    """Load saved ferry data."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_v2_keeps_only_this_route_and_its_notices():
    sailings, notices = parse_v2(fixture("ferry_v2.json"))
    assert list(sailings) == ["SWBTSA"]
    assert [n["title"] for n in notices] == ["Sailing Delay"]


def test_v2_reads_departures_and_fill():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    nine, eleven = sailings["SWBTSA"][1:3]
    assert nine.delay_minutes == 25
    assert nine.fill is None
    assert eleven.full
    assert eleven.scheduled == datetime(2026, 11, 24, 11, 0, tzinfo=BC_TIME)
    assert sailings["SWBTSA"][4].fill is None


def test_swartz_bay_late_departure_and_wait():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    alerts = {
        a.extra["kind"]: a for a in sailing_alerts("SWBTSA", sailings["SWBTSA"], NOW)
    }
    assert set(alerts) == {"delayed", "wait"}
    assert alerts["delayed"].title == "Swartz Bay 9:00 am sailing left 25 min late"
    assert alerts["wait"].title == "1-sailing wait at Swartz Bay"
    assert "1:00 pm (Coastal Celebration, 23% space)" in alerts["wait"].detail
    assert (alerts["wait"].latitude, alerts["wait"].longitude) == (48.6889, -123.4103)


def test_sailing_that_has_not_left_counts_as_late():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    later = datetime(2026, 11, 24, 18, 20, tzinfo=UTC)  # 11:20 am
    titles = [a.title for a in sailing_alerts("SWBTSA", sailings["SWBTSA"], later)]
    assert "Swartz Bay 11:00 am sailing hasn't left, 20 min late" in titles


def test_legacy_list_rolls_over_to_tomorrow_and_reads_cancellations():
    sailings = parse_legacy_sailings(fixture("ferry_tsa_swb.json"), "TSASWB", NOW)
    assert [s.scheduled.day for s in sailings] == [24, 24, 24, 25]
    assert sailings[1].cancelled
    alerts = {a.extra["kind"]: a for a in sailing_alerts("TSASWB", sailings, NOW)}
    assert alerts["cancelled"].title == "Tsawwassen 1:00 pm sailing cancelled"
    assert alerts["wait"].title == "1-sailing wait at Tsawwassen"
    assert "3:00 pm" in alerts["wait"].detail


def test_quiet_route_has_no_alerts():
    payload = fixture("ferry_tsa_swb.json")
    for row in payload["sailings"]:
        row.update(isCancelled=False, fill=40, carFill=40, vesselStatus="")
    sailings = parse_legacy_sailings(payload, "TSASWB", NOW)
    assert sailing_alerts("TSASWB", sailings, NOW) == []


def test_notice_alert():
    _, notices = parse_v2(fixture("ferry_v2.json"))
    (alert,) = notice_alerts(notices)
    assert alert.id == "ferry-notice-8804000000001"
    assert alert.extra["kind"] == "delay"
    assert alert.updated == datetime(2026, 11, 24, 17, 10, 0, 500000, tzinfo=UTC)


def test_information_notices_are_left_out_unless_another_copy_says_otherwise():
    route = {"routeCode": "SWBTSA", "dataStatus": "available", "sailings": []}
    notice = {"id": 1, "title": "", "type": "information", "routeCodes": ["SWBTSA"]}
    payload = {
        "routes": [
            {**route, "notices": [notice]},
            {
                **route,
                "routeCode": "TSANAN",
                "notices": [
                    {**notice, "title": "Sailing Cancellations", "type": "cancellation"}
                ],
            },
        ]
    }
    _, notices = parse_v2(payload)
    (alert,) = notice_alerts(notices)
    assert alert.title == "Sailing Cancellations"
    assert alert.extra["kind"] == "cancellation"


def test_summary_lists_upcoming_sailings():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    rows = summary(sailings["SWBTSA"], NOW)
    assert [r["status"] for r in rows] == [
        "Left 9:25 am (25 min late)",
        "Full",
        "23% space",
        "Scheduled",
    ]


def test_nanosecond_timestamps():
    assert _iso("2026-11-24T15:36:45.267641498Z") == datetime(
        2026, 11, 24, 15, 36, 45, 267641, tzinfo=UTC
    )
    assert _iso("2026-11-24T15:36:45Z") == datetime(
        2026, 11, 24, 15, 36, 45, tzinfo=UTC
    )


def test_home_assistant_time_zone_is_used():
    whitehorse = ZoneInfo("America/Whitehorse")
    sailings, _ = parse_v2(fixture("ferry_v2.json"), whitehorse)
    assert sailings["SWBTSA"][2].scheduled.tzinfo is whitehorse


def test_a_sailing_that_never_left_is_dropped_after_a_few_hours():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    evening = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)  # 3:30 pm
    titles = [a.title for a in sailing_alerts("SWBTSA", sailings["SWBTSA"], evening)]
    assert not any("11:00 am" in t for t in titles)
    assert any("1:00 pm" in t for t in titles)


def test_a_full_sailing_that_is_boarding_is_not_a_wait():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    boarding = datetime(2026, 11, 24, 18, 3, tzinfo=UTC)  # 11:03 am
    kinds = [
        a.extra["kind"] for a in sailing_alerts("SWBTSA", sailings["SWBTSA"], boarding)
    ]
    assert "wait" not in kinds


TONIGHT_NOTICE = {
    "id": 8804220415752,
    "type": "cancellation",
    "title": "Sailing Cancellations - Adverse Weather",
    "routeCodes": ["SWBTSA", "TSASWB"],
    "body": (
        "Reissued: 7:08 pm To ensure the safety of our customers and crew, the "
        "following sailings between Tsawwassen (Vancouver) and Swartz Bay "
        "(Victoria) must be cancelled for tonight, November 24. Cancelled "
        "Sailings: 7:00 pm departing Tsawwassen 7:00 pm departing Swartz Bay "
        "9:00 pm departing Tsawwassen 9:00 pm departing Swartz Bay"
    ),
}


def test_sailings_named_in_a_cancellation_notice_are_cancelled():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    notice = dict(
        TONIGHT_NOTICE,
        body="Cancelled: 1:00 pm departing Swartz Bay, 3:00 pm departing Tsawwassen",
    )
    marked = notice_cancellations(sailings, [notice], NOW)["SWBTSA"]
    by_time = {s.scheduled.strftime("%H:%M"): s for s in marked}
    assert by_time["13:00"].cancelled
    # 3:00 pm departs Tsawwassen, the other direction.
    assert not any(s.cancelled for t, s in by_time.items() if t != "13:00")
    titles = [a.title for a in sailing_alerts("SWBTSA", marked, NOW)]
    assert "Swartz Bay 1:00 pm sailing cancelled" in titles
    row = next(r for r in summary(marked, NOW) if r["time"] == "1:00 pm")
    assert row["status"] == "Cancelled"


def test_tonights_notice_text_names_both_directions():
    sailings, _ = parse_v2(fixture("ferry_v2.json"))
    seven = next(s for s in sailings["SWBTSA"] if s.scheduled.hour == 11)
    evening = {
        "SWBTSA": [
            seven.__class__(
                route="SWBTSA",
                scheduled=seven.scheduled.replace(hour=h),
                vessel="Spirit",
            )
            for h in (19, 21)
        ],
        "TSASWB": [
            seven.__class__(
                route="TSASWB",
                scheduled=seven.scheduled.replace(hour=h),
                vessel="Spirit",
            )
            for h in (17, 19, 21)
        ],
    }
    at_740 = datetime(2026, 11, 25, 2, 40, tzinfo=UTC)
    marked = notice_cancellations(evening, [TONIGHT_NOTICE], at_740)
    assert [s.cancelled for s in marked["SWBTSA"]] == [True, True]
    assert [s.cancelled for s in marked["TSASWB"]] == [False, True, True]
    kinds = {
        a.extra["kind"] for a in sailing_alerts("SWBTSA", marked["SWBTSA"], at_740)
    }
    assert kinds == {"cancelled"}  # no "hasn't left, 40 min late"


def test_delay_notices_cancel_nothing():
    sailings, notices = parse_v2(fixture("ferry_v2.json"))
    marked = notice_cancellations(sailings, notices, NOW)
    assert not any(s.cancelled for s in marked["SWBTSA"])
