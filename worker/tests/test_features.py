"""Sample construction, and the three leakage guards it exists to enforce."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pytest

from hallcheck.features import (
    Reading,
    build_features,
    build_samples,
    is_holiday,
    minute_of_meal,
    minutes_until,
)

START = datetime(2026, 3, 2, 12, 0, tzinfo=UTC)  # a Monday


def series(
    count_at_minute,
    *,
    minutes: int = 240,
    hall_id: str = "worcester",
    step: int = 10,
    camera_epoch: int = 1,
    start: datetime = START,
) -> list[Reading]:
    """Readings every `step` minutes, with counts from a callable."""
    return [
        Reading(
            hall_id=hall_id,
            ts=start + timedelta(minutes=m),
            count=count_at_minute(m),
            camera_epoch=camera_epoch,
        )
        for m in range(0, minutes + 1, step)
    ]


class TestBuildSamples:
    def test_target_is_the_count_one_horizon_ahead(self):
        readings = series(lambda m: m)
        samples = build_samples(readings, horizon_minutes=30, lags=(0,))

        first = samples[0]
        assert first.origin == START
        assert first.target_ts == START + timedelta(minutes=30)
        assert first.target == 30
        assert first.features["lag_0m"] == 0.0

    def test_lags_reach_backwards_only(self):
        readings = series(lambda m: m)
        samples = build_samples(readings, horizon_minutes=30, lags=(0, 10, 30))

        # The first sample that has 30 minutes of history behind it.
        sample = next(s for s in samples if s.origin == START + timedelta(minutes=30))
        assert sample.features["lag_0m"] == 30.0
        assert sample.features["lag_10m"] == 20.0
        assert sample.features["lag_30m"] == 0.0

    def test_no_feature_exceeds_the_origin(self):
        """The guard that matters most.

        Every value a sample carries must be knowable at the moment the
        forecast is made. The target is the only thing from the future.
        """
        readings = series(lambda m: m)
        samples = build_samples(readings, horizon_minutes=30, lags=(0, 10, 30))

        for sample in samples:
            for name, value in sample.features.items():
                if not name.startswith("lag_"):
                    continue
                # Counts equal minutes-since-start in this series, so a lag
                # value above the origin's own offset would be a future read.
                origin_offset = (sample.origin - START).total_seconds() / 60
                assert value <= origin_offset

    def test_drops_samples_with_a_missing_lag(self):
        readings = series(lambda m: m)
        samples = build_samples(readings, horizon_minutes=30, lags=(0, 60))

        # Nothing before START, so no sample can exist until 60 minutes in.
        assert min(s.origin for s in samples) == START + timedelta(minutes=60)

    def test_drops_samples_with_a_missing_target(self):
        readings = series(lambda m: m, minutes=60)
        samples = build_samples(readings, horizon_minutes=30, lags=(0,))

        assert max(s.origin for s in samples) == START + timedelta(minutes=30)

    def test_a_gap_is_not_imputed(self):
        """A missing count means the camera was not looked at.

        Filling it in would train the model on a number nobody measured.
        """
        readings = [r for r in series(lambda m: m) if r.ts != START + timedelta(minutes=30)]
        samples = build_samples(readings, horizon_minutes=30, lags=(0,))

        origins = {s.origin for s in samples}
        assert START not in origins, "the target for this origin is missing"
        assert START + timedelta(minutes=30) not in origins

    def test_halls_do_not_borrow_each_other_history(self):
        readings = series(lambda m: m, hall_id="worcester") + series(
            lambda m: m * 10, hall_id="franklin"
        )
        samples = build_samples(readings, horizon_minutes=30, lags=(0,))

        for sample in samples:
            expected = 10 if sample.hall_id == "franklin" else 1
            assert sample.target == ((sample.origin - START).total_seconds() / 60 + 30) * expected


class TestCameraEpochGuard:
    def test_no_sample_spans_a_camera_move(self):
        """Counts either side of a camera move are on different scales.

        Pairing a lag from before with a target from after teaches the model a
        step change that is an artefact of the hardware.
        """
        before = series(lambda m: 10, minutes=60, camera_epoch=1)
        after = [
            Reading(
                hall_id="worcester",
                ts=START + timedelta(minutes=m),
                count=40,
                camera_epoch=2,
            )
            for m in range(70, 181, 10)
        ]
        samples = build_samples(before + after, horizon_minutes=30, lags=(0, 30))

        for sample in samples:
            # Within an epoch the count is constant, so a sample that mixed
            # epochs would show a lag and target that disagree.
            assert sample.features["lag_0m"] == sample.target

    def test_an_roi_redraw_breaks_the_series_too(self):
        old = [
            Reading("worcester", START + timedelta(minutes=m), 10, 1, "v1")
            for m in range(0, 61, 10)
        ]
        new = [
            Reading("worcester", START + timedelta(minutes=m), 40, 1, "v2")
            for m in range(70, 181, 10)
        ]
        samples = build_samples(old + new, horizon_minutes=30, lags=(0,))

        for sample in samples:
            assert sample.features["lag_0m"] == sample.target


class TestBaselines:
    def _with_history(self) -> list[Reading]:
        # Three weeks, so both seasonal lookups exist for the last week.
        return [
            Reading(
                hall_id="worcester",
                ts=START - timedelta(days=days) + timedelta(minutes=m),
                # Encodes which day and slot a reading came from.
                count=days * 1000 + m,
            )
            for days in range(21, -1, -1)
            for m in range(0, 121, 10)
        ]

    def test_baselines_look_up_the_target_slot_not_the_origin(self):
        """The subtle one.

        "What was the count at 12:30 last Tuesday" is the prediction. Looking
        up 12:00 last Tuesday answers a different question and makes the
        baseline look worse than it is.
        """
        samples = build_samples(self._with_history(), horizon_minutes=30, lags=(0,))
        sample = next(s for s in samples if s.origin == START and s.hall_id == "worcester")

        # target_ts is START + 30m, which is day 0, minute 30.
        # Same slot last week is day 7 at minute 30 => 7 * 1000 + 30.
        assert sample.baselines["same_slot_last_week"] == 7030.0
        assert sample.baselines["same_slot_yesterday"] == 1030.0

    def test_a_baseline_is_none_when_the_history_does_not_reach(self):
        readings = series(lambda m: m)
        samples = build_samples(readings, horizon_minutes=30, lags=(0,))

        assert samples[0].baselines["same_slot_last_week"] is None
        assert not samples[0].has_all_baselines()

    def test_a_baseline_does_not_cross_a_camera_epoch(self):
        """The same rule the sample builder follows.

        Letting a baseline compare across a camera move, while the model is
        forbidden from doing so, would hand the model an unearned win.
        """
        history = [
            Reading("worcester", START - timedelta(days=7) + timedelta(minutes=m), 5, 1)
            for m in range(0, 121, 10)
        ]
        recent = [
            Reading("worcester", START + timedelta(minutes=m), 40, 2) for m in range(0, 121, 10)
        ]
        samples = build_samples(history + recent, horizon_minutes=30, lags=(0,))

        current = [s for s in samples if s.origin >= START]
        assert current
        assert all(s.baselines["same_slot_last_week"] is None for s in current)


class TestFeatureValues:
    def test_calendar_features(self):
        features = build_features(START, {0: 5})
        assert features["hour"] == 12.0
        assert features["weekday"] == 0.0  # Monday
        assert features["is_weekend"] == 0.0

    def test_weekend_flag(self):
        saturday = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
        assert build_features(saturday, {0: 5})["is_weekend"] == 1.0

    def test_deltas_capture_direction_of_travel(self):
        # A queue at 20 and climbing behaves differently from one clearing.
        climbing = build_features(START, {0: 20, 10: 12, 30: 4})
        clearing = build_features(START, {0: 20, 10: 28, 30: 36})

        assert climbing["delta_10m"] == 8.0
        assert clearing["delta_10m"] == -8.0

    def test_deltas_are_absent_without_the_lags_to_build_them(self):
        assert "delta_10m" not in build_features(START, {0: 20})

    def test_minutes_until_close(self):
        assert minutes_until(START, time(21, 0)) == 540.0
        assert minutes_until(START, time(11, 0)) == 0.0, "clamped, never negative"
        assert minutes_until(START, None) == -1.0

    def test_minute_of_meal(self):
        assert minute_of_meal(START, time(11, 30)) == 30.0
        assert minute_of_meal(START, None) == -1.0

    @pytest.mark.parametrize(
        "day,expected",
        [(date(2026, 12, 25), True), (date(2026, 7, 4), True), (date(2026, 3, 2), False)],
    )
    def test_fixed_holidays(self, day, expected):
        assert is_holiday(day) is expected
