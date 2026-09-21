"""Drift detection: catching a moved camera without looking at the site."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from hallcheck.drift import (
    DriftStatus,
    check_all,
    check_hall,
    render_report,
    slot_of,
)
from hallcheck.features import Reading

NOW = datetime(2026, 3, 16, 12, 0, tzinfo=UTC)
STEP_MINUTES = 2


def readings(
    *,
    days_back: int,
    days_forward: int = 0,
    counts,
    hall_id: str = "worcester",
    camera_epoch: int = 1,
    open_hour: int = 7,
    close_hour: int = 21,
):
    """Captures every two minutes during service hours, over a span of days.

    `counts` is called with (days_before_now, minutes_since_midnight).
    """
    out = []
    start = NOW - timedelta(days=days_back)
    total_days = days_back + days_forward
    for day in range(total_days + 1):
        at_day = start + timedelta(days=day)
        for minute in range(open_hour * 60, close_hour * 60, STEP_MINUTES):
            ts = at_day.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
                minutes=minute
            )
            if ts > NOW:
                continue
            days_before = (NOW - ts).total_seconds() / 86400
            out.append(Reading(hall_id, ts, max(0, counts(days_before, minute)), camera_epoch))
    return out


def steady(level: float):
    """A hall with a normal lunch and dinner shape, the same every day."""

    def shape(_days_before, minute):
        lunch = 30 * _bump(minute, 12 * 60, 60)
        dinner = 24 * _bump(minute, 18 * 60, 75)
        return round((lunch + dinner + 6) * level)

    return shape


def _bump(minute, centre, width):
    delta = (minute - centre) / width
    return max(0.0, 1.0 - delta * delta)


class TestSlotOf:
    @pytest.mark.parametrize(
        "at,expected",
        [
            (NOW.replace(hour=12, minute=0), 720),
            (NOW.replace(hour=12, minute=29), 720),
            (NOW.replace(hour=12, minute=30), 750),
            (NOW.replace(hour=0, minute=5), 0),
        ],
    )
    def test_floors_to_the_slot_width(self, at, expected):
        assert slot_of(at) == expected


class TestStableCamera:
    def test_an_unchanged_camera_is_ok(self):
        signal = check_hall(readings(days_back=20, counts=steady(1.0)), now=NOW)

        assert signal.status is DriftStatus.OK
        assert abs(signal.relative_change) < 0.05

    def test_ordinary_day_to_day_variation_does_not_fire(self):
        """The alert has to survive a quiet Tuesday.

        An alert that fires on normal variation gets muted, and a muted alert
        may as well not exist.
        """
        import random

        rng = random.Random(3)
        base = steady(1.0)

        def wobbly(days_before, minute):
            # A different busyness multiplier each day, plus per-reading noise.
            day_factor = 0.82 + 0.36 * ((int(days_before) * 7919) % 100) / 100
            return round(base(days_before, minute) * day_factor + rng.gauss(0, 1.5))

        signal = check_hall(readings(days_back=20, counts=wobbly), now=NOW)
        assert signal.status is DriftStatus.OK


class TestMovedCamera:
    def test_a_camera_that_now_sees_less_of_the_queue_alerts(self):
        """The event this exists to catch.

        The counts stay plausible - still small integers, still rising at
        lunch - so nothing else in the system notices.
        """
        base = steady(1.0)

        def moved(days_before, minute):
            # Yesterday the mount was bumped and the ROI now covers a third of
            # the queue.
            return round(base(days_before, minute) * (0.35 if days_before < 1 else 1.0))

        signal = check_hall(readings(days_back=20, counts=moved), now=NOW)

        assert signal.status is DriftStatus.ALERT
        assert signal.direction == "down"
        assert signal.relative_change < -0.4

    def test_a_camera_that_now_sees_more_alerts_too(self):
        base = steady(1.0)

        def widened(days_before, minute):
            return round(base(days_before, minute) * (2.2 if days_before < 1 else 1.0))

        signal = check_hall(readings(days_back=20, counts=widened), now=NOW)

        assert signal.status is DriftStatus.ALERT
        assert signal.direction == "up"

    def test_a_modest_hall_losing_most_of_its_queue_still_alerts(self):
        """Regression: pooling across slots, not taking a median of them.

        A service day is mostly shoulder - a handful of busy slots at lunch and
        dinner, twenty quiet ones either side - so the median slot is a quiet
        one. Taking the median of the per-slot changes therefore reports what
        happened to the empty hours and discards the part of the day where a
        moved camera actually shows up.

        This hall peaks around 20 but its median slot sits near 5. Under the
        old statistic a 70% drop came out as -3 people, under the 4-person
        threshold, and did not alert.
        """

        def shoulder_heavy(days_before, minute):
            level = 20 * _bump(minute, 12 * 60, 55) + 16 * _bump(minute, 18 * 60, 70) + 5
            return round(level * 0.7 * (0.3 if days_before < 1 else 1.0))

        signal = check_hall(readings(days_back=20, counts=shoulder_heavy), now=NOW)

        assert signal.status is DriftStatus.ALERT
        assert signal.relative_change < -0.5

    def test_the_message_says_what_to_do(self):
        base = steady(1.0)
        signal = check_hall(
            readings(
                days_back=20,
                counts=lambda d, m: round(base(d, m) * (0.3 if d < 1 else 1.0)),
            ),
            now=NOW,
        )
        assert "camera_epoch" in signal.describe()


class TestThresholdsActTogether:
    def test_a_quiet_hall_halving_is_not_an_alert(self):
        """2 people becoming 1 is the same relative shift as 30 becoming 15.

        Relative change alone would fire on it constantly.
        """
        base = steady(0.12)  # peaks around 4

        def halved(days_before, minute):
            return round(base(days_before, minute) * (0.4 if days_before < 1 else 1.0))

        signal = check_hall(readings(days_back=20, counts=halved), now=NOW)
        assert signal.status is not DriftStatus.ALERT

    def test_a_large_absolute_shift_that_is_relatively_small_is_not_an_alert(self):
        """A busy hall running 5-6 people lighter is a quiet week, not a mount.

        Absolute change alone would fire on it, which is why both thresholds
        have to be breached together.
        """

        def busy_then_slightly_quieter(days_before, minute):
            # Flat and high through service, so the median across slots is the
            # level rather than an average over the shoulders.
            level = 20
            return round(level * (0.72 if days_before < 1 else 1.0))

        signal = check_hall(readings(days_back=20, counts=busy_then_slightly_quieter), now=NOW)

        assert abs(signal.absolute_change) >= 4.0, "precondition: absolute threshold breached"
        assert abs(signal.relative_change) < 0.40, "precondition: relative threshold is not"
        assert signal.status is not DriftStatus.ALERT


class TestDataSufficiency:
    def test_an_outage_is_reported_as_insufficient_data_not_drift(self):
        """A dead worker must not look like a moved camera.

        They need completely different responses, and conflating them sends
        somebody to check a lens when the container is down.
        """
        history = readings(days_back=20, counts=steady(1.0))
        # Everything from the last 24 hours is missing.
        with_outage = [r for r in history if r.ts < NOW - timedelta(hours=24)]

        signal = check_hall(with_outage, now=NOW)

        assert signal.status is DriftStatus.INSUFFICIENT_DATA
        assert "last day" in signal.reason

    def test_a_partial_day_does_not_have_enough_slots(self):
        history = readings(days_back=20, counts=steady(1.0))
        # Only one hour survived in the recent window.
        recent_cut = NOW - timedelta(hours=1)
        trimmed = [r for r in history if r.ts < NOW - timedelta(hours=24) or r.ts >= recent_cut]

        signal = check_hall(trimmed, now=NOW)

        assert signal.status is DriftStatus.INSUFFICIENT_DATA
        assert "outage" in signal.reason

    def test_no_readings_at_all(self):
        assert check_hall([], now=NOW).status is DriftStatus.INSUFFICIENT_DATA

    def test_closed_hours_are_excluded_from_the_comparison(self):
        signal = check_hall(readings(days_back=20, counts=steady(1.0)), now=NOW)

        # Service runs 07:00-21:00 here; nothing outside it should be compared,
        # and the near-empty early and late slots should be filtered too.
        for comparison in signal.comparisons:
            assert 7 * 60 <= comparison.slot < 21 * 60
            assert comparison.baseline_median >= 4.0


class TestCameraEpoch:
    def test_a_recorded_move_restarts_the_baseline_instead_of_alerting(self):
        """A move we already know about is history, not drift.

        Comparing across it would fire an alert for something already handled,
        and would do it every day for two weeks.
        """
        old = readings(days_back=20, counts=steady(1.0), camera_epoch=1)
        old = [r for r in old if r.ts < NOW - timedelta(hours=24)]
        new = [
            Reading(r.hall_id, r.ts, round(r.count * 0.3), 2)
            for r in readings(days_back=20, counts=steady(1.0))
            if r.ts >= NOW - timedelta(hours=24)
        ]

        signal = check_hall(old + new, now=NOW)

        assert signal.status is DriftStatus.INSUFFICIENT_DATA
        assert signal.camera_epoch == 2
        assert "epoch 2" in signal.reason

    def test_the_signal_reports_the_epoch_it_examined(self):
        signal = check_hall(readings(days_back=20, counts=steady(1.0)), now=NOW)
        assert signal.camera_epoch == 1


class TestWindows:
    def test_the_recent_window_is_not_part_of_its_own_baseline(self):
        """Otherwise a real shift is diluted by the very readings that show it."""
        base = steady(1.0)
        signal = check_hall(
            readings(
                days_back=20,
                counts=lambda d, m: round(base(d, m) * (0.35 if d < 1 else 1.0)),
            ),
            now=NOW,
        )
        # A fortnight of unchanged history, so the baseline should be the
        # original level rather than pulled toward the new one.
        for comparison in signal.comparisons:
            assert comparison.recent_median < comparison.baseline_median * 0.6


class TestCheckAll:
    def test_halls_are_checked_independently(self):
        base = steady(1.0)
        healthy = readings(days_back=20, counts=base, hall_id="franklin")
        moved = readings(
            days_back=20,
            counts=lambda d, m: round(base(d, m) * (0.3 if d < 1 else 1.0)),
            hall_id="worcester",
        )

        signals = {s.hall_id: s for s in check_all(healthy + moved, now=NOW)}

        assert signals["franklin"].status is DriftStatus.OK
        assert signals["worcester"].status is DriftStatus.ALERT

    def test_report_points_at_the_runbook_when_something_fires(self):
        base = steady(1.0)
        moved = readings(
            days_back=20, counts=lambda d, m: round(base(d, m) * (0.3 if d < 1 else 1.0))
        )
        report = render_report(check_all(moved, now=NOW))

        assert "DRIFT" in report
        assert "docs/runbook.md" in report

    def test_a_clean_report_does_not_mention_the_runbook(self):
        report = render_report(check_all(readings(days_back=20, counts=steady(1.0)), now=NOW))
        assert "docs/runbook.md" not in report
