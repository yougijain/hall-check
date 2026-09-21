"""The accuracy arithmetic, and the guards around quoting it."""

from __future__ import annotations

import math

import pytest

from hallcheck.evaluate import build_report, find_coverage_gaps, render_markdown, to_observations
from hallcheck.metrics import (
    MIN_STRATUM_SIZE,
    Observation,
    bias,
    bootstrap_mae_interval,
    group_by,
    mae,
    rmse,
    summarise,
)


def obs(human: int, model: int, **kwargs) -> Observation:
    return Observation(human_count=human, model_count=model, **kwargs)


class TestPointEstimates:
    def test_mae_is_the_mean_absolute_error(self):
        assert mae([obs(10, 12), obs(10, 7), obs(10, 10)]) == pytest.approx(5 / 3)

    def test_bias_is_signed_model_minus_human(self):
        # Over-counting by 2 and under-counting by 3 nets to -0.5 per reading.
        assert bias([obs(10, 12), obs(10, 7)]) == pytest.approx(-0.5)

    def test_bias_is_zero_for_symmetric_error(self):
        assert bias([obs(10, 12), obs(10, 8)]) == pytest.approx(0.0)

    def test_mae_and_bias_separate_noise_from_a_systematic_miss(self):
        """The reason both are reported.

        Both sets have MAE 4. The first is a noisy detector; the second misses
        four people every single time. Only the second is fixable, and a
        report showing MAE alone cannot tell them apart.
        """
        noisy = [obs(20, 24), obs(20, 16), obs(20, 24), obs(20, 16)]
        systematic = [obs(20, 16), obs(20, 16), obs(20, 16), obs(20, 16)]

        assert mae(noisy) == pytest.approx(mae(systematic))
        assert bias(noisy) == pytest.approx(0.0)
        assert bias(systematic) == pytest.approx(-4.0)

    def test_rmse_punishes_the_large_miss(self):
        occasional_blowout = [obs(10, 10), obs(10, 10), obs(10, 10), obs(10, 30)]
        assert rmse(occasional_blowout) > mae(occasional_blowout)

    def test_empty_input_is_not_a_number_rather_than_zero(self):
        # Zero error would read as a perfect detector.
        assert math.isnan(mae([]))
        assert math.isnan(bias([]))
        assert math.isnan(rmse([]))


class TestBootstrap:
    def test_the_interval_brackets_the_point_estimate(self):
        observations = [obs(20, 20 + (i % 7) - 3) for i in range(80)]
        interval = bootstrap_mae_interval(observations)

        assert interval is not None
        assert interval.low <= mae(observations) <= interval.high

    def test_a_noisier_sample_gives_a_wider_interval(self):
        tight = [obs(20, 21) for _ in range(60)]
        loose = [obs(20, 20 + (i % 21) - 10) for i in range(60)]

        tight_interval = bootstrap_mae_interval(tight)
        loose_interval = bootstrap_mae_interval(loose)

        assert tight_interval is not None and loose_interval is not None
        assert (loose_interval.high - loose_interval.low) > (
            tight_interval.high - tight_interval.low
        )

    def test_is_deterministic(self):
        # An interval that moves every time the report is regenerated is not
        # something a reader can check against the repository.
        observations = [obs(20, 20 + (i % 9) - 4) for i in range(50)]
        assert bootstrap_mae_interval(observations) == bootstrap_mae_interval(observations)

    def test_returns_nothing_when_there_is_nothing_to_resample(self):
        assert bootstrap_mae_interval([]) is None
        assert bootstrap_mae_interval([obs(10, 12)]) is None


class TestSummarise:
    def test_flags_a_stratum_too_small_to_estimate_from(self):
        assert summarise([obs(10, 11)] * (MIN_STRATUM_SIZE - 1)).underpowered
        assert not summarise([obs(10, 11)] * MIN_STRATUM_SIZE).underpowered


class TestGroupBy:
    def test_groups_and_sorts(self):
        grouped = group_by(
            [obs(1, 1, hall_id="worcester"), obs(1, 1, hall_id="franklin")], "hall_id"
        )
        assert list(grouped) == ["franklin", "worcester"]

    def test_blank_values_become_a_visible_bucket(self):
        # Silently dropping them would make the totals not add up.
        grouped = group_by([obs(1, 1, lighting="")], "lighting")
        assert list(grouped) == ["unspecified"]


class TestToObservations:
    def test_drops_labels_with_no_model_count(self):
        """A label captured while the worker was down is not an observation.

        It is still a real human count and can be paired later, but averaging
        it in would compare the model against nothing.
        """
        rows = [
            {
                "human_count": 10,
                "model_count": 12,
                "hall_id": "w",
                "meal": "lunch",
                "lighting": "daylight",
            },
            {
                "human_count": 14,
                "model_count": None,
                "hall_id": "w",
                "meal": "lunch",
                "lighting": "daylight",
            },
        ]
        observations = to_observations(rows)
        assert len(observations) == 1
        assert observations[0].human_count == 10


class TestCoverageGaps:
    def _spread(self, n: int) -> list[Observation]:
        meals = ["breakfast", "lunch", "dinner"]
        lighting = ["daylight", "dark"]
        halls = ["worcester", "franklin"]
        return [
            obs(
                20,
                21,
                hall_id=halls[i % len(halls)],
                meal=meals[i % len(meals)],
                lighting=lighting[i % len(lighting)],
            )
            for i in range(n)
        ]

    def test_full_coverage_has_no_gaps(self):
        gaps = find_coverage_gaps(self._spread(180), known_halls=["worcester", "franklin"])
        assert gaps == []

    def test_too_few_labels_is_a_gap(self):
        gaps = find_coverage_gaps(self._spread(30), known_halls=["worcester", "franklin"])
        assert any("30 paired labels" in gap for gap in gaps)

    def test_a_missing_condition_is_named(self):
        """The failure this exists to prevent.

        MAE measured only at lunch in daylight says nothing about dinner in
        January, and quoting it as though it did is the dishonest version of
        this project.
        """
        lunch_only = [
            obs(20, 21, hall_id="worcester", meal="lunch", lighting="daylight") for _ in range(200)
        ]
        gaps = find_coverage_gaps(lunch_only, known_halls=["worcester"])

        assert any("no labels at breakfast" in gap for gap in gaps)
        assert any("no labels at dinner" in gap for gap in gaps)
        assert any("no labels in dark" in gap for gap in gaps)

    def test_a_hall_with_no_labels_is_named(self):
        gaps = find_coverage_gaps(
            self._spread(180), known_halls=["worcester", "franklin", "hampshire"]
        )
        assert any("no labels for hampshire" in gap for gap in gaps)


class TestReport:
    def test_a_well_covered_set_is_reportable(self):
        observations = TestCoverageGaps()._spread(180)
        report = build_report(observations, known_halls=["worcester", "franklin"])

        assert report.reportable
        assert report.overall.n == 180
        assert set(report.by_lighting) == {"daylight", "dark"}
        assert set(report.by_meal) == {"breakfast", "lunch", "dinner"}

    def test_a_thin_set_is_not_reportable(self):
        report = build_report(
            [obs(20, 21, hall_id="worcester", meal="lunch", lighting="daylight")] * 12,
            known_halls=["worcester"],
        )
        assert not report.reportable


class TestRenderMarkdown:
    def test_renders_a_table_with_the_overall_row(self):
        report = build_report(
            TestCoverageGaps()._spread(180), known_halls=["worcester", "franklin"]
        )
        markdown = render_markdown(report)

        assert "| Stratum | n | MAE (95% CI) | Bias | RMSE |" in markdown
        assert "**Overall**" in markdown
        assert "By lighting" in markdown

    def test_an_unreportable_set_says_so_at_the_top(self):
        report = build_report([obs(20, 21, meal="lunch", lighting="daylight")] * 5)
        markdown = render_markdown(report)

        assert markdown.startswith("> **Not yet reportable.**")
        assert "no labels at dinner" in markdown

    def test_underpowered_strata_are_flagged_in_place(self):
        observations = [
            obs(20, 21, hall_id="worcester", meal="lunch", lighting="daylight") for _ in range(180)
        ] + [obs(20, 30, hall_id="worcester", meal="dinner", lighting="dark") for _ in range(3)]
        markdown = render_markdown(build_report(observations))

        # The thin dinner stratum still appears - hiding it would make the
        # coverage gap invisible - but it carries a warning marker.
        assert "dinner" in markdown
        assert "⚠" in markdown

    def test_bias_sign_is_explained(self):
        markdown = render_markdown(build_report(TestCoverageGaps()._spread(180)))
        assert "positive means the detector over-counts" in markdown
