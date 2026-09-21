"""The split, the fair comparison, and the table that reports the outcome."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from hallcheck.features import Reading, Sample, build_samples
from hallcheck.forecast import (
    MODEL_NAME,
    PERSISTENCE,
    ForecastReport,
    NotEnoughData,
    Score,
    comparable_subset,
    evaluate,
    feature_names,
    render_markdown,
    time_split,
)

# A Monday, at the start of service.
START = datetime(2026, 2, 2, 7, 0, tzinfo=UTC)

STEP_MINUTES = 30
READINGS_PER_DAY = 24  # 07:00 to 19:00
LAGS = (0, 30, 60)


def weekly_shape(day_index: int, slot: int) -> int:
    """A count that depends only on weekday and time of day.

    Identical every week by construction, which makes 'same slot last week'
    exactly right and gives the baseline test something deterministic to
    assert.
    """
    weekday = day_index % 7
    lunch = 30 * math.exp(-(((slot - 10) / 2.0) ** 2))
    dinner = 24 * math.exp(-(((slot - 20) / 2.5) ** 2))
    weekend_damping = 0.5 if weekday >= 5 else 1.0
    return max(0, round((lunch + dinner) * weekend_damping))


def periodic_readings(days: int = 28, hall_id: str = "worcester") -> list[Reading]:
    readings = []
    for day in range(days):
        for slot in range(READINGS_PER_DAY):
            readings.append(
                Reading(
                    hall_id=hall_id,
                    ts=START + timedelta(days=day, minutes=slot * STEP_MINUTES),
                    count=weekly_shape(day, slot),
                )
            )
    return readings


def periodic_samples(days: int = 28) -> list[Sample]:
    return build_samples(periodic_readings(days), horizon_minutes=STEP_MINUTES, lags=LAGS)


class TestTimeSplit:
    def test_every_training_target_precedes_the_cut(self):
        split = time_split(periodic_samples())
        assert all(s.target_ts < split.cut for s in split.train)

    def test_every_test_origin_follows_the_cut(self):
        split = time_split(periodic_samples())
        assert all(s.origin >= split.cut for s in split.test)

    def test_the_embargo_keeps_training_targets_out_of_the_test_window(self):
        """The part that is easy to get wrong.

        Splitting on the origin alone leaves training rows whose
        30-minute-ahead target lands inside the test window. The model would
        have been shown test-period outcomes, and the reported MAE would be a
        fiction.
        """
        split = time_split(periodic_samples())
        latest_train_target = max(s.target_ts for s in split.train)
        earliest_test_origin = min(s.origin for s in split.test)

        assert latest_train_target <= earliest_test_origin

    def test_no_test_sample_appears_in_training(self):
        split = time_split(periodic_samples())
        train_keys = {(s.hall_id, s.origin) for s in split.train}
        test_keys = {(s.hall_id, s.origin) for s in split.test}
        assert not (train_keys & test_keys)

    def test_the_test_window_is_the_most_recent_history(self):
        split = time_split(periodic_samples())
        assert min(s.origin for s in split.test) > max(s.origin for s in split.train)

    def test_test_fraction_controls_the_split_point(self):
        samples = periodic_samples()
        small = time_split(samples, test_fraction=0.1)
        large = time_split(samples, test_fraction=0.4)

        assert len(large.test) > len(small.test)
        assert large.cut < small.cut

    def test_refuses_an_impossible_fraction(self):
        samples = periodic_samples()
        for fraction in (0.0, 1.0, -0.2, 1.5):
            with pytest.raises(ValueError):
                time_split(samples, test_fraction=fraction)

    def test_refuses_to_split_almost_nothing(self):
        with pytest.raises(NotEnoughData):
            time_split([])


class TestComparableSubset:
    def test_keeps_only_rows_every_predictor_can_answer(self):
        # Two weeks is enough that the later rows have both lookups and the
        # earlier ones do not.
        samples = periodic_samples(days=14)
        comparable = comparable_subset(samples)

        assert 0 < len(comparable) < len(samples)
        assert all(s.has_all_baselines() for s in comparable)

    def test_the_earliest_week_cannot_be_comparable(self):
        samples = periodic_samples(days=14)
        first_week_end = START + timedelta(days=7)
        assert all(s.origin >= first_week_end for s in comparable_subset(samples))


class TestFeatureNames:
    def test_is_sorted_and_stable(self):
        names = feature_names(periodic_samples(days=10))
        assert names == sorted(names)

    def test_uses_only_columns_present_in_every_sample(self):
        """A column in training but missing at prediction time would be filled
        with whatever happened to sit in that position."""
        samples = periodic_samples(days=10)
        odd = Sample(
            hall_id="worcester",
            origin=START,
            target_ts=START + timedelta(minutes=30),
            target=5,
            features={**samples[0].features, "an_extra_column": 1.0},
        )
        assert "an_extra_column" not in feature_names([*samples, odd])

    def test_empty_input(self):
        assert feature_names([]) == []


class TestEvaluate:
    def test_every_predictor_is_scored_on_identical_rows(self):
        """Without this the comparison is meaningless.

        The seasonal baselines cannot answer the earliest history. Scoring the
        model on rows they cannot reach would let it win by being asked easier
        questions.
        """
        report = evaluate(time_split(periodic_samples()))

        assert {s.name for s in report.scores} == {
            "same_slot_last_week",
            "same_slot_yesterday",
            PERSISTENCE,
            MODEL_NAME,
        }
        assert len({s.n for s in report.scores}) == 1
        assert report.comparable_size == report.scores[0].n

    def test_the_weekly_baseline_is_exact_on_a_perfectly_weekly_signal(self):
        # The series repeats every 7 days by construction, so looking up the
        # same slot last week is the right answer every time. If this drifts
        # from zero, the baseline is looking up the wrong slot.
        report = evaluate(time_split(periodic_samples()))
        weekly = next(s for s in report.scores if s.name == "same_slot_last_week")

        assert weekly.mae == pytest.approx(0.0)

    def test_baselines_are_recorded_even_when_the_model_loses(self):
        report = evaluate(time_split(periodic_samples()))
        assert len(report.scores) == 4, "a table that shows only the winner is not a comparison"

    def test_is_deterministic(self):
        split = time_split(periodic_samples())
        first = evaluate(split, seed=11)
        second = evaluate(split, seed=11)

        assert [(s.name, round(s.mae, 9)) for s in first.scores] == [
            (s.name, round(s.mae, 9)) for s in second.scores
        ]

    def test_raises_when_no_test_row_has_both_baselines(self):
        # Four days of history: nothing can look back a full week.
        with pytest.raises(NotEnoughData, match="seasonal baselines"):
            evaluate(time_split(periodic_samples(days=4)))


class TestRenderMarkdown:
    def _report(self, scores: list[Score]) -> ForecastReport:
        return ForecastReport(
            cut=START,
            train_size=1000,
            test_size=260,
            comparable_size=240,
            scores=scores,
        )

    def test_orders_by_error_and_marks_the_winner(self):
        markdown = render_markdown(
            self._report(
                [
                    Score("same_slot_last_week", 240, 4.1),
                    Score(MODEL_NAME, 240, 2.6),
                    Score(PERSISTENCE, 240, 3.2),
                ]
            )
        )
        lines = [line for line in markdown.splitlines() if line.startswith("|")]

        assert f"**{MODEL_NAME}**" in lines[2]
        assert lines[2].index("2.6") > 0

    def test_says_so_plainly_when_a_baseline_wins(self):
        """The honest outcome of this milestone, if that is how it lands."""
        markdown = render_markdown(
            self._report(
                [
                    Score("same_slot_last_week", 240, 2.1),
                    Score(MODEL_NAME, 240, 3.8),
                ]
            )
        )
        assert "**The model does not win.**" in markdown
        assert "does not ship" in markdown

    def test_reports_the_rows_that_were_excluded(self):
        markdown = render_markdown(self._report([Score(MODEL_NAME, 240, 2.6)]))
        assert "20 further test rows were excluded" in markdown
        assert "identical rows" in markdown

    def test_states_the_split_point(self):
        markdown = render_markdown(self._report([Score(MODEL_NAME, 240, 2.6)]))
        assert START.isoformat() in markdown
