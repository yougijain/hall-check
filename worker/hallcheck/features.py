"""Turning a series of counts into supervised examples for a 30-minute forecast.

Every design decision here is about one risk: a model that scores well because
it was shown something it will not have at prediction time. Three specific
guards, in the order they matter.

**No feature may use the future.** A sample made at time `t` sees counts at `t`
and before, and nothing else. The target is the count at `t + 30 minutes`,
which is exactly the thing that will not be known when the prediction is
actually needed.

**No sample may span a camera epoch or an ROI version change.** Counts either
side of a camera move are measurements of different things on different scales.
A lag feature from before a move, paired with a target from after it, teaches
the model a step change that is an artefact of the hardware rather than
anything about the dining hall.

**Samples are built from an exact timestamp index, not a nearest-neighbour
search.** The worker snaps captures to the interval grid, so `t - 7 days` is a
dictionary lookup. A tolerance window would silently pair a lunch reading with
a mid-afternoon one when a capture is missing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

#: How far ahead the forecast predicts. Long enough to be worth acting on -
#: the walk across campus - and short enough that the current count still
#: carries most of the signal.
HORIZON_MINUTES = 30

#: How far back the lag features reach, in minutes before the origin.
DEFAULT_LAGS = (0, 10, 20, 30, 60)

#: Offsets the seasonal-naive baselines look back by.
WEEK = timedelta(days=7)
DAY = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class Reading:
    """One row of `counts`, with the two columns that gate comparability."""

    hall_id: str
    ts: datetime
    count: int
    camera_epoch: int = 1
    roi_version: str = "v1"

    @property
    def scale(self) -> tuple[int, str]:
        """What makes two readings comparable. Differ here and they are not."""
        return (self.camera_epoch, self.roi_version)


@dataclass(frozen=True, slots=True)
class Sample:
    """One supervised example."""

    hall_id: str
    #: When the forecast is made. Everything in `features` is known by now.
    origin: datetime
    #: What the forecast is about: origin + horizon.
    target_ts: datetime
    target: int
    features: dict[str, float]
    #: Seasonal-naive predictions for the same target, where history allows.
    baselines: dict[str, float | None] = field(default_factory=dict)

    def has_all_baselines(self) -> bool:
        return bool(self.baselines) and all(v is not None for v in self.baselines.values())


def index_readings(readings: Iterable[Reading]) -> dict[tuple[str, datetime], Reading]:
    """Exact (hall, timestamp) lookup, which the capture grid makes possible."""
    return {(r.hall_id, r.ts): r for r in readings}


def is_holiday(day: date) -> bool:
    """Fixed-date US holidays that close or empty the dining halls.

    Deliberately not a full academic calendar. Thanksgiving, spring break and
    finals move year to year and matter more than these do; wiring them in
    means maintaining a table of dates, which is a data problem rather than a
    modelling one. This covers the fixed dates and the feature is left in place
    for the rest to be added to.
    """
    fixed = {(1, 1), (7, 4), (11, 11), (12, 24), (12, 25), (12, 31)}
    return (day.month, day.day) in fixed


def minutes_until(moment: datetime, closes_at: time | None) -> float:
    """Minutes from `moment` to closing, clamped at zero, or -1 when unknown.

    A sentinel rather than a NaN: HistGradientBoostingRegressor treats NaN as
    missing and learns a split for it, which is fine, but -1 keeps the feature
    readable when the vectors are inspected by hand.
    """
    if closes_at is None:
        return -1.0

    close_today = moment.replace(
        hour=closes_at.hour, minute=closes_at.minute, second=0, microsecond=0
    )
    delta = (close_today - moment).total_seconds() / 60.0
    return max(0.0, delta)


def minute_of_meal(moment: datetime, opens_at: time | None) -> float:
    """Minutes since service opened. -1 when hours are unknown."""
    if opens_at is None:
        return -1.0

    open_today = moment.replace(hour=opens_at.hour, minute=opens_at.minute, second=0, microsecond=0)
    return max(0.0, (moment - open_today).total_seconds() / 60.0)


def build_features(
    origin: datetime,
    lag_counts: dict[int, int],
    *,
    opens_at: time | None = None,
    closes_at: time | None = None,
) -> dict[str, float]:
    """Everything known at `origin`.

    The lag features are the ones the calendar features have to beat. Over
    thirty minutes the current count is far and away the strongest predictor,
    and a model that ignored it in favour of 'it is Tuesday at noon' would be
    worse than the clock. They are not in the original feature sketch for this
    milestone; they are here because leaving them out would be modelling
    malpractice for this horizon.
    """
    features: dict[str, float] = {
        "hour": float(origin.hour),
        "minute": float(origin.minute),
        "weekday": float(origin.weekday()),
        "is_weekend": float(origin.weekday() >= 5),
        "minute_of_meal": minute_of_meal(origin, opens_at),
        "minutes_until_close": minutes_until(origin, closes_at),
        "is_holiday": float(is_holiday(origin.date())),
    }

    for lag, count in sorted(lag_counts.items()):
        features[f"lag_{lag}m"] = float(count)

    # Direction of travel. A queue at 20 and climbing behaves very differently
    # from one at 20 and clearing, and a tree cannot derive the difference from
    # two separate lag columns without spending splits on it.
    if 0 in lag_counts and 10 in lag_counts:
        features["delta_10m"] = float(lag_counts[0] - lag_counts[10])
    if 0 in lag_counts and 30 in lag_counts:
        features["delta_30m"] = float(lag_counts[0] - lag_counts[30])

    return features


def build_samples(
    readings: Sequence[Reading],
    *,
    horizon_minutes: int = HORIZON_MINUTES,
    lags: Sequence[int] = DEFAULT_LAGS,
    hours: dict[str, tuple[time | None, time | None]] | None = None,
) -> list[Sample]:
    """Every supervised example the history supports.

    A sample is emitted only when the target, every lag, and the origin all
    exist and all share one camera epoch and ROI version. Anything else is
    dropped rather than imputed: a gap in the counts means the camera was not
    looked at, and inventing a value there would train the model on fiction.
    """
    index = index_readings(readings)
    horizon = timedelta(minutes=horizon_minutes)
    service_hours = hours or {}

    samples: list[Sample] = []
    for reading in sorted(readings, key=lambda r: (r.hall_id, r.ts)):
        origin = reading.ts
        target = index.get((reading.hall_id, origin + horizon))
        if target is None or target.scale != reading.scale:
            continue

        lag_counts: dict[int, int] = {}
        for lag in lags:
            lagged = index.get((reading.hall_id, origin - timedelta(minutes=lag)))
            if lagged is None or lagged.scale != reading.scale:
                break
            lag_counts[lag] = lagged.count
        else:
            opens_at, closes_at = service_hours.get(reading.hall_id, (None, None))
            samples.append(
                Sample(
                    hall_id=reading.hall_id,
                    origin=origin,
                    target_ts=target.ts,
                    target=target.count,
                    features=build_features(
                        origin, lag_counts, opens_at=opens_at, closes_at=closes_at
                    ),
                    baselines=_baselines_for(index, reading, target.ts),
                )
            )

    return samples


def _baselines_for(
    index: dict[tuple[str, datetime], Reading],
    origin_reading: Reading,
    target_ts: datetime,
) -> dict[str, float | None]:
    """Seasonal-naive predictions for the same target the model is aiming at.

    Both look up the target's own slot in the past rather than the origin's.
    "What was the count at 12:30 last Tuesday" is the prediction; "what was it
    at 12:00 last Tuesday" would be answering a different question and would
    make the baseline look worse than it is.

    A lookup that lands on a different camera epoch returns None. Comparing a
    count from before a camera move against one from after it is exactly the
    mistake `camera_epoch` exists to prevent, and letting a baseline do it
    would flatter the model.
    """
    results: dict[str, float | None] = {}
    for name, offset in (("same_slot_last_week", WEEK), ("same_slot_yesterday", DAY)):
        past = index.get((origin_reading.hall_id, target_ts - offset))
        results[name] = (
            float(past.count) if past is not None and past.scale == origin_reading.scale else None
        )
    return results
