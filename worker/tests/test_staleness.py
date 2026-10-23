"""The outage check: which cameras have stopped reporting."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hallcheck.models import Hall
from hallcheck.roi import Roi
from hallcheck.staleness import (
    LOOKBACK_HOURS,
    STALE_AFTER_HOURS,
    Freshness,
    check,
    last_seen_by_hall,
    render_report,
)

NOW = datetime(2026, 10, 20, 18, 0, tzinfo=UTC)


def hall(hall_id: str) -> Hall:
    return Hall(
        hall_id=hall_id,
        name=hall_id.replace("_", " ").title(),
        stream_url="https://example.invalid/stream",
        roi=Roi(
            version="v0-geometry-prior",
            vertices=((0.3, 0.35), (0.7, 0.35), (0.95, 1.0), (0.05, 1.0)),
        ),
        camera_epoch=1,
    )


def reading(hall_id: str, *, hours_ago: float) -> dict:
    return {"hall_id": hall_id, "ts": NOW - timedelta(hours=hours_ago), "count": 7}


class TestLastSeen:
    def test_takes_the_most_recent_per_hall(self):
        rows = [
            reading("a", hours_ago=9),
            reading("a", hours_ago=1),
            reading("a", hours_ago=5),
            reading("b", hours_ago=3),
        ]
        latest = last_seen_by_hall(rows)
        assert latest["a"] == NOW - timedelta(hours=1)
        assert latest["b"] == NOW - timedelta(hours=3)

    def test_parses_iso_strings(self):
        # Supabase hands back timestamps as strings; a local fake hands back
        # datetimes. Both reach this function.
        rows = [{"hall_id": "a", "ts": "2026-10-20T17:00:00+00:00", "count": 3}]
        assert last_seen_by_hall(rows)["a"] == datetime(2026, 10, 20, 17, 0, tzinfo=UTC)


class TestCheck:
    def test_recent_reading_is_fresh(self):
        report = check([hall("a")], [reading("a", hours_ago=0.5)], now=NOW)
        assert report.halls[0].status is Freshness.FRESH
        assert report.ok

    def test_old_reading_is_stale(self):
        report = check([hall("a")], [reading("a", hours_ago=STALE_AFTER_HOURS + 1)], now=NOW)
        assert report.halls[0].status is Freshness.STALE
        assert not report.ok

    def test_no_reading_at_all_is_silent(self):
        report = check([hall("a")], [], now=NOW)
        assert report.halls[0].status is Freshness.SILENT
        assert report.halls[0].last_seen is None

    def test_boundary_is_inclusive(self):
        # Exactly at the threshold is still fresh. The alternative makes the
        # check flap for one capture interval either side of the boundary.
        at = check([hall("a")], [reading("a", hours_ago=STALE_AFTER_HOURS)], now=NOW)
        assert at.halls[0].status is Freshness.FRESH

    def test_one_dead_camera_among_healthy_ones(self):
        # The case this check exists for: a rotated stream id takes out one
        # hall while the rest keep reporting, which drift cannot see because
        # the dead hall stops producing the readings drift compares.
        halls = [hall("worcester_north"), hall("worcester_south"), hall("berkshire")]
        rows = [
            reading("worcester_north", hours_ago=0.1),
            reading("berkshire", hours_ago=0.1),
            reading("worcester_south", hours_ago=30),
        ]
        report = check(halls, rows, now=NOW)
        failing = [h.hall_id for h in report.failing]
        assert failing == ["worcester_south"]
        assert not report.worker_is_down

    def test_every_hall_silent_reads_as_one_fault(self):
        halls = [hall("a"), hall("b"), hall("c")]
        report = check(halls, [], now=NOW)
        assert report.worker_is_down
        assert len(report.failing) == 3

    def test_a_single_hall_down_is_not_a_worker_outage(self):
        report = check([hall("a")], [], now=NOW)
        # One hall that is also the only hall is ambiguous, and the property
        # says "every hall", so it reports true. Documented rather than
        # pretended otherwise: with one camera there is no way to tell a dead
        # stream from a dead worker without looking.
        assert report.worker_is_down

    def test_halls_are_sorted_for_a_stable_report(self):
        report = check([hall("c"), hall("a"), hall("b")], [], now=NOW)
        assert [h.hall_id for h in report.halls] == ["a", "b", "c"]

    def test_threshold_is_overridable(self):
        rows = [reading("a", hours_ago=2)]
        assert check([hall("a")], rows, now=NOW, stale_after_hours=1).halls[0].status is (
            Freshness.STALE
        )
        assert check([hall("a")], rows, now=NOW, stale_after_hours=4).halls[0].status is (
            Freshness.FRESH
        )


class TestReport:
    def test_healthy_report_says_so_before_the_table(self):
        out = render_report(check([hall("a")], [reading("a", hours_ago=0.2)], now=NOW))
        assert "All halls reporting." in out
        assert out.index("All halls reporting.") < out.index("| Hall |")

    def test_single_hall_failure_names_the_likely_cause(self):
        halls = [hall("a"), hall("b")]
        rows = [reading("a", hours_ago=0.1)]
        out = render_report(check(halls, rows, now=NOW))
        assert "rotated stream id" in out
        assert "halls.stream_url" in out
        assert "1 of 2" in out

    def test_total_outage_points_at_the_process_not_the_streams(self):
        out = render_report(check([hall("a"), hall("b")], [], now=NOW))
        assert "Every hall is silent" in out
        assert "one fault, not 2" in out
        assert "before checking any stream URL" in out

    def test_silent_wording_does_not_claim_more_than_it_knows(self):
        # The query only looked back LOOKBACK_HOURS, so the report must not
        # say a hall "never" reported.
        out = render_report(check([hall("a")], [], now=NOW))
        assert f"last {LOOKBACK_HOURS}h" in out
        assert "never" not in out.lower()


@pytest.mark.parametrize(
    ("hours", "expected"),
    [(0.5, "30m"), (3.25, "3h15m"), (49, "2d1h")],
)
def test_age_formatting(hours, expected):
    report = check([hall("a")], [reading("a", hours_ago=hours)], now=NOW)
    assert expected in report.halls[0].describe()
