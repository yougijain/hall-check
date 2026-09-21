"""Predicting the count 30 minutes ahead, and finding out whether that is worth doing.

The baselines are the point of this module, not the gradient booster. Dining
hall traffic is close to a weekly periodic signal with a strong short-horizon
autocorrelation, so "the count right now" and "the count at this slot last
Tuesday" are both hard to beat. A model that cannot beat them is not earning
its complexity, and the honest outcome of this milestone is a table that says
so.

All four predictors are scored on identical rows so the comparison means
something.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from hallcheck.features import Sample

log = logging.getLogger(__name__)

#: Fraction of the timeline held out. A quarter of several weeks is a test
#: window of days, which is long enough to span every weekday.
DEFAULT_TEST_FRACTION = 0.25

#: Named so it can be reported alongside the seasonal ones. "The count right
#: now" is the baseline a 30-minute forecast most obviously has to beat.
PERSISTENCE = "persistence"

MODEL_NAME = "HistGradientBoostingRegressor"


class NotEnoughData(RuntimeError):
    """There is not enough history to train or to test on."""


@dataclass(frozen=True, slots=True)
class Split:
    train: list[Sample]
    test: list[Sample]
    cut: datetime

    def describe(self) -> str:
        return (
            f"train {len(self.train)} samples up to {self.cut.isoformat()}, "
            f"test {len(self.test)} samples after"
        )


@dataclass(frozen=True, slots=True)
class Score:
    name: str
    n: int
    mae: float


@dataclass(frozen=True, slots=True)
class ForecastReport:
    cut: datetime
    train_size: int
    test_size: int
    #: Test rows where every predictor could produce a number.
    comparable_size: int
    scores: list[Score] = field(default_factory=list)

    @property
    def best(self) -> Score | None:
        return min(self.scores, key=lambda s: s.mae) if self.scores else None

    @property
    def model_wins(self) -> bool:
        best = self.best
        return best is not None and best.name == MODEL_NAME


def time_split(samples: Sequence[Sample], test_fraction: float = DEFAULT_TEST_FRACTION) -> Split:
    """Split by time, with an embargo between the halves.

    Never at random. A random split puts 12:02 on a Tuesday in train and 12:04
    the same Tuesday in test. Those two rows are nearly the same observation -
    same queue, same people, two minutes apart - so the model scores well by
    having effectively memorised the test set through its neighbours. The
    reported number would be a fiction that collapses in production, where
    every prediction is about a timestamp nothing has seen.

    The embargo matters too, and is the part that is easy to get wrong. Train
    keeps only samples whose TARGET falls before the cut, and test keeps only
    samples whose ORIGIN falls after it. Splitting on the origin alone would
    leave training rows whose 30-minute-ahead target lands inside the test
    window - the model would have been shown test-period outcomes.
    """
    if len(samples) < 2:
        raise NotEnoughData(f"need at least 2 samples to split, got {len(samples)}")
    if not 0.0 < test_fraction < 1.0:
        raise ValueError(f"test_fraction must be between 0 and 1, got {test_fraction}")

    ordered = sorted(samples, key=lambda s: s.target_ts)
    cut_index = int(len(ordered) * (1.0 - test_fraction))
    cut = ordered[min(cut_index, len(ordered) - 1)].target_ts

    train = [s for s in ordered if s.target_ts < cut]
    test = [s for s in ordered if s.origin >= cut]

    if not train or not test:
        raise NotEnoughData(
            f"split left train={len(train)} test={len(test)}; the history is too short "
            "or too concentrated to hold out a time window"
        )
    return Split(train=train, test=test, cut=cut)


def feature_names(samples: Sequence[Sample]) -> list[str]:
    """A stable, sorted column order.

    Derived from the intersection across samples rather than from the first
    one: a column present in training and missing at prediction time would be
    silently filled with whatever happened to be in that position.
    """
    if not samples:
        return []
    common = set(samples[0].features)
    for sample in samples[1:]:
        common &= set(sample.features)
    return sorted(common)


def to_matrix(samples: Sequence[Sample], names: Sequence[str]):
    import numpy as np

    return np.array([[s.features[n] for n in names] for s in samples], dtype=float)


def to_targets(samples: Sequence[Sample]):
    import numpy as np

    return np.array([s.target for s in samples], dtype=float)


def comparable_subset(samples: Sequence[Sample]) -> list[Sample]:
    """Test rows every predictor can answer.

    The seasonal baselines need the target's own slot a day and a week back,
    which does not exist for the earliest history. Scoring the model on rows
    the baselines cannot reach would let it win by being asked easier
    questions. The count of rows this drops is reported rather than absorbed.
    """
    return [s for s in samples if s.has_all_baselines()]


def _mae(predictions: Sequence[float], actuals: Sequence[float]) -> float:
    return sum(abs(p - a) for p, a in zip(predictions, actuals, strict=True)) / len(actuals)


def fit(train: Sequence[Sample], names: Sequence[str], *, seed: int = 0):
    """Train the booster.

    HistGradientBoostingRegressor because the features are tabular and mixed,
    it handles missing values natively, and it trains on CPU in seconds. There
    is no GPU in this project and no reason for one.

    Absolute-error loss rather than squared error, so the objective matches the
    metric being reported. Squared error would chase the rare peak outliers at
    the cost of the ordinary readings that make up most of the day.
    """
    from sklearn.ensemble import HistGradientBoostingRegressor

    model = HistGradientBoostingRegressor(
        loss="absolute_error",
        max_iter=300,
        learning_rate=0.06,
        max_depth=6,
        min_samples_leaf=20,
        l2_regularization=1.0,
        early_stopping=True,
        # Validation split is the TAIL of the training window, not a random
        # sample of it, for the same reason the outer split is by time.
        validation_fraction=0.15,
        random_state=seed,
    )
    model.fit(to_matrix(train, names), to_targets(train))
    return model


def evaluate(split: Split, *, seed: int = 0) -> ForecastReport:
    """Score every predictor on the same held-out rows."""
    names = feature_names(split.train)
    if not names:
        raise NotEnoughData("no features available to train on")

    comparable = comparable_subset(split.test)
    if not comparable:
        raise NotEnoughData(
            "no test rows have both seasonal baselines available; the history does not "
            "yet reach a full week before the test window"
        )

    actuals = [float(s.target) for s in comparable]
    scores: list[Score] = []

    # Baselines first, and recorded whatever the model does. A table that only
    # shows the winner is not a comparison.
    for name in ("same_slot_last_week", "same_slot_yesterday"):
        predictions = [float(s.baselines[name]) for s in comparable]  # type: ignore[arg-type]
        scores.append(Score(name=name, n=len(comparable), mae=_mae(predictions, actuals)))

    persistence = [s.features["lag_0m"] for s in comparable]
    scores.append(Score(name=PERSISTENCE, n=len(comparable), mae=_mae(persistence, actuals)))

    model = fit(split.train, names, seed=seed)
    predicted = model.predict(to_matrix(comparable, names))
    scores.append(Score(name=MODEL_NAME, n=len(comparable), mae=_mae(list(predicted), actuals)))

    return ForecastReport(
        cut=split.cut,
        train_size=len(split.train),
        test_size=len(split.test),
        comparable_size=len(comparable),
        scores=scores,
    )


def render_markdown(report: ForecastReport) -> str:
    """The M4 table, generated rather than typed."""
    best = report.best
    lines = [
        "| Predictor | Test MAE |",
        "|---|---|",
    ]
    for score in sorted(report.scores, key=lambda s: s.mae):
        label = f"**{score.name}**" if best and score.name == best.name else score.name
        lines.append(f"| {label} | {score.mae:.2f} |")

    dropped = report.test_size - report.comparable_size
    lines += [
        "",
        f"Time split at `{report.cut.isoformat()}`: {report.train_size} training samples, "
        f"{report.comparable_size} test samples.",
    ]
    if dropped:
        lines.append(
            f"{dropped} further test rows were excluded because the seasonal baselines "
            "have no history that far back; every predictor is scored on identical rows."
        )

    if not report.model_wins:
        lines += [
            "",
            f"**The model does not win.** {best.name if best else 'A baseline'} is ahead, "
            "so the forecast does not ship. Dining hall traffic is close to a weekly "
            "periodic signal, and a gradient booster that cannot beat looking up last "
            "Tuesday is not earning its complexity.",
        ]
    return "\n".join(lines)
