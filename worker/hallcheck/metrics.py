"""Accuracy, and the honesty conditions attached to reporting it.

Two numbers, both in people.

MAE - mean absolute error - is how far off a typical reading is. It is reported
rather than MAPE because counts go to zero between meals. MAPE divides by the
true value: a single off-by-two at a true count of 1 contributes 200% and
swamps the mean, and at a true count of 0 it is undefined. MAE is also in the
unit the decision gets made in. "About 8 people longer than the model says" is
actionable; "40% off" is not.

Bias is the signed mean error, model minus human. Positive means the detector
over-counts. It is reported alongside MAE because the two describe different
failures: MAE 6 with bias 0 is a noisy detector, and MAE 6 with bias -6 is a
detector that systematically misses half the queue. The second is fixable and
the first mostly is not, so collapsing them loses the actionable half.

Every figure is reported with its n, and any stratum too small to support an
estimate is marked rather than quietly printed next to the others.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: Below this, a stratum's MAE is an anecdote. It is still shown - hiding it
#: would make coverage gaps invisible - but it is flagged everywhere it appears.
MIN_STRATUM_SIZE = 10

#: Resamples for the bootstrap interval. 2000 is plenty for a percentile
#: interval at this sample size and still runs instantly.
BOOTSTRAP_RESAMPLES = 2000


@dataclass(frozen=True, slots=True)
class Observation:
    """One paired reading: what a person counted, and what the model counted."""

    human_count: int
    model_count: int
    hall_id: str = ""
    meal: str = ""
    lighting: str = ""

    @property
    def error(self) -> int:
        """Model minus human. Positive means the model saw people who were not there."""
        return self.model_count - self.human_count


@dataclass(frozen=True, slots=True)
class Interval:
    low: float
    high: float

    def __str__(self) -> str:
        return f"[{self.low:.2f}, {self.high:.2f}]"


@dataclass(frozen=True, slots=True)
class Metrics:
    n: int
    mae: float
    bias: float
    rmse: float
    mae_interval: Interval | None = None

    @property
    def underpowered(self) -> bool:
        """Whether n is too small for these numbers to mean anything."""
        return self.n < MIN_STRATUM_SIZE


def mae(observations: Sequence[Observation]) -> float:
    if not observations:
        return math.nan
    return sum(abs(o.error) for o in observations) / len(observations)


def bias(observations: Sequence[Observation]) -> float:
    if not observations:
        return math.nan
    return sum(o.error for o in observations) / len(observations)


def rmse(observations: Sequence[Observation]) -> float:
    if not observations:
        return math.nan
    return math.sqrt(sum(o.error**2 for o in observations) / len(observations))


def bootstrap_mae_interval(
    observations: Sequence[Observation],
    *,
    confidence: float = 0.95,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = 0,
) -> Interval | None:
    """Percentile bootstrap interval for MAE.

    A point estimate from 180 labels invites being read as exact. Resampling
    the labels with replacement and taking percentiles of the resulting MAEs
    shows how much of the number is the detector and how much is which
    afternoons happened to get labelled.

    Seeded, because a confidence interval that moves every time the report is
    regenerated is not something anyone can check.
    """
    if len(observations) < 2:
        return None

    rng = random.Random(seed)
    n = len(observations)
    errors = [abs(o.error) for o in observations]

    estimates = []
    for _ in range(resamples):
        total = 0.0
        for _ in range(n):
            total += errors[rng.randrange(n)]
        estimates.append(total / n)

    estimates.sort()
    tail = (1.0 - confidence) / 2.0
    low = estimates[max(0, int(tail * resamples) - 1)]
    high = estimates[min(resamples - 1, int((1.0 - tail) * resamples))]
    return Interval(low=low, high=high)


def summarise(observations: Sequence[Observation], *, with_interval: bool = True) -> Metrics:
    return Metrics(
        n=len(observations),
        mae=mae(observations),
        bias=bias(observations),
        rmse=rmse(observations),
        mae_interval=bootstrap_mae_interval(observations) if with_interval else None,
    )


def group_by(observations: Iterable[Observation], attribute: str) -> dict[str, list[Observation]]:
    grouped: dict[str, list[Observation]] = {}
    for observation in observations:
        key = getattr(observation, attribute) or "unspecified"
        grouped.setdefault(key, []).append(observation)
    return dict(sorted(grouped.items()))
