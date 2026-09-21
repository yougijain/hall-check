"""Noticing when a camera has stopped looking at the same room.

Cameras move. Someone bumps a mount, maintenance re-aims a lens, a display
screen gets repositioned in front of it. From that moment the ROI covers a
different piece of the world and every count is measuring something else.

What makes this dangerous is that the counts stay plausible. They are still
small integers, they still rise at lunch, and nothing about the data announces
that it changed meaning. Without a check, the first sign is somebody
mentioning the site has felt wrong for a while, which could be weeks.

So: per camera, compare the last 24 hours against the trailing 14 days, slot by
slot, and raise a signal when the shift is too large and too widespread to be a
quiet Tuesday.

Everything about the comparison is chosen to avoid crying wolf, because an
alert that fires on ordinary variation gets muted and then it may as well not
exist.

**Same slot, always.** A 24-hour median compared against a 14-day median
without matching the time of day measures the meal schedule, not the camera.
Each time-of-day slot is compared only with itself.

**Medians within a slot, pooled across slots.** Each slot's level is a median
over hundreds of readings, so one freak dinner rush cannot move it. The slots
are then pooled rather than median-ed together, because a service day is mostly
shoulder and the median slot is a quiet one - taking a median across slots
reports what happened to the empty hours and discards the part of the day where
a moved camera shows up.

**Relative AND absolute.** A hall going from 30 to 15 is a real event; 2 to 1
is noise with the same relative magnitude. Both thresholds must be exceeded.

**Busy slots only.** Slots whose baseline sits near zero are excluded. Closed
hours carry no information about where the camera is pointing and would
otherwise dominate the comparison.

**One epoch only.** Readings from before a recorded camera move are not
comparable to readings after it. A move we already know about is not drift, it
is history, and the baseline restarts from it.
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from hallcheck.features import Reading

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Thresholds. These are choices, not discoveries; docs/runbook.md argues them.
# --------------------------------------------------------------------------

#: Time-of-day bucket width. Half an hour is wide enough that a couple of
#: missed captures still leave a usable median, and narrow enough that lunch
#: does not get averaged with mid-afternoon.
SLOT_MINUTES = 30

#: What "now" means for the comparison.
RECENT_WINDOW_HOURS = 24

#: What "normal" means. Two weeks covers both weekend days twice and is short
#: enough to adapt after a term begins.
BASELINE_WINDOW_DAYS = 14

#: Slots quieter than this in the baseline are ignored. A camera pointed at a
#: wall and a hall that is genuinely closed look identical at a count of 1.
MIN_BASELINE_MEDIAN = 4.0

#: Fewer comparable slots than this and there is not enough of the day covered
#: to tell a moved camera from a slow morning.
MIN_COMPARABLE_SLOTS = 6

#: Readings needed in a slot before its median is trusted, in each window.
MIN_READINGS_PER_SLOT = 3

#: A sustained shift of this size, in both terms at once, is outside what
#: weather, exams and a quiet week produce.
ALERT_RELATIVE_CHANGE = 0.40
ALERT_ABSOLUTE_CHANGE = 4.0


class DriftStatus(StrEnum):
    OK = "ok"
    ALERT = "alert"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True, slots=True)
class SlotComparison:
    slot: int  #: minutes since local midnight, floored to SLOT_MINUTES
    recent_median: float
    baseline_median: float

    @property
    def absolute_change(self) -> float:
        return self.recent_median - self.baseline_median

    @property
    def relative_change(self) -> float:
        return self.absolute_change / self.baseline_median

    @property
    def label(self) -> str:
        hours, minutes = divmod(self.slot, 60)
        return f"{hours:02d}:{minutes:02d}"


@dataclass(frozen=True, slots=True)
class DriftSignal:
    hall_id: str
    camera_epoch: int
    status: DriftStatus
    comparisons: tuple[SlotComparison, ...] = ()
    reason: str = ""

    @property
    def absolute_change(self) -> float:
        """Average shift per compared slot, in people.

        Pooled across slots rather than taking the median of the per-slot
        changes, and this distinction is not cosmetic. A service day is mostly
        shoulder: half a dozen busy slots at lunch and dinner, and twenty quiet
        ones either side. The median slot is a quiet one, so a median-of-changes
        statistic reports what happened to the shoulders and effectively
        discards the part of the day that carries the signal.

        That was not a hypothetical. A simulated camera re-aimed to see a third
        of the queue produced a 60% drop and did not alert, because the median
        slot's baseline was 5 people and 60% of 5 is under the absolute
        threshold.

        Robustness still comes from the median taken WITHIN each slot, over
        hundreds of readings, which is where a freak dinner rush would
        otherwise do damage.
        """
        if not self.comparisons:
            return 0.0
        total = sum(c.absolute_change for c in self.comparisons)
        return total / len(self.comparisons)

    @property
    def relative_change(self) -> float:
        """Total-occupancy-weighted change across the compared slots.

        Same reasoning as `absolute_change`: pooling means the busy slots,
        where a moved camera actually shows up, carry proportionate weight.
        """
        if not self.comparisons:
            return 0.0
        baseline_total = sum(c.baseline_median for c in self.comparisons)
        if baseline_total == 0:
            return 0.0
        return sum(c.absolute_change for c in self.comparisons) / baseline_total

    @property
    def direction(self) -> str:
        return "down" if self.absolute_change < 0 else "up"

    def describe(self) -> str:
        if self.status is DriftStatus.INSUFFICIENT_DATA:
            return f"{self.hall_id}: no comparison possible ({self.reason})"
        change = (
            f"{self.relative_change:+.0%} ({self.absolute_change:+.1f} people) "
            f"across {len(self.comparisons)} slots"
        )
        if self.status is DriftStatus.ALERT:
            return (
                f"{self.hall_id}: DRIFT {self.direction} {change}, "
                f"epoch {self.camera_epoch}. Inspect the stream; if the camera has "
                f"moved, bump halls.camera_epoch."
            )
        return f"{self.hall_id}: ok, {change}"


def slot_of(moment: datetime, slot_minutes: int = SLOT_MINUTES) -> int:
    """Minutes since midnight, floored to the slot width."""
    minutes = moment.hour * 60 + moment.minute
    return minutes - (minutes % slot_minutes)


def _medians_by_slot(
    readings: Sequence[Reading], slot_minutes: int, min_readings: int
) -> dict[int, float]:
    buckets: dict[int, list[int]] = {}
    for reading in readings:
        buckets.setdefault(slot_of(reading.ts, slot_minutes), []).append(reading.count)
    return {
        slot: statistics.median(counts)
        for slot, counts in buckets.items()
        if len(counts) >= min_readings
    }


def check_hall(
    readings: Sequence[Reading],
    *,
    now: datetime,
    slot_minutes: int = SLOT_MINUTES,
    recent_hours: int = RECENT_WINDOW_HOURS,
    baseline_days: int = BASELINE_WINDOW_DAYS,
    min_baseline_median: float = MIN_BASELINE_MEDIAN,
    min_slots: int = MIN_COMPARABLE_SLOTS,
    min_readings_per_slot: int = MIN_READINGS_PER_SLOT,
    relative_threshold: float = ALERT_RELATIVE_CHANGE,
    absolute_threshold: float = ALERT_ABSOLUTE_CHANGE,
) -> DriftSignal:
    """Compare one camera's last day against its recent fortnight."""
    if not readings:
        return DriftSignal("", 0, DriftStatus.INSUFFICIENT_DATA, reason="no readings")

    hall_id = readings[0].hall_id

    # Only the current epoch. A recorded camera move is not drift, and its
    # baseline starts over from the move.
    epoch = max(r.camera_epoch for r in readings)
    in_epoch = [r for r in readings if r.camera_epoch == epoch]

    recent_start = now - timedelta(hours=recent_hours)
    baseline_start = recent_start - timedelta(days=baseline_days)

    recent = [r for r in in_epoch if recent_start <= r.ts <= now]
    # Half-open, so the last 24 hours are never also part of their own baseline.
    baseline = [r for r in in_epoch if baseline_start <= r.ts < recent_start]

    if not recent:
        return DriftSignal(
            hall_id, epoch, DriftStatus.INSUFFICIENT_DATA, reason="no readings in the last day"
        )
    if not baseline:
        return DriftSignal(
            hall_id,
            epoch,
            DriftStatus.INSUFFICIENT_DATA,
            reason=f"no baseline history in epoch {epoch}",
        )

    recent_medians = _medians_by_slot(recent, slot_minutes, min_readings_per_slot)
    baseline_medians = _medians_by_slot(baseline, slot_minutes, min_readings_per_slot)

    comparisons = tuple(
        SlotComparison(
            slot=slot,
            recent_median=recent_medians[slot],
            baseline_median=baseline_medians[slot],
        )
        for slot in sorted(set(recent_medians) & set(baseline_medians))
        # Closed hours say nothing about where the camera points, and a
        # baseline near zero makes the relative change meaningless.
        if baseline_medians[slot] >= min_baseline_median
    )

    if len(comparisons) < min_slots:
        return DriftSignal(
            hall_id,
            epoch,
            DriftStatus.INSUFFICIENT_DATA,
            comparisons=comparisons,
            reason=(
                f"only {len(comparisons)} busy slots overlap both windows, "
                f"need {min_slots}; likely an outage rather than a moved camera"
            ),
        )

    signal = DriftSignal(hall_id, epoch, DriftStatus.OK, comparisons=comparisons)

    # Both thresholds, together. Either one alone fires on something ordinary:
    # relative alone on a quiet slot, absolute alone on the busiest hall.
    breached = (
        abs(signal.relative_change) >= relative_threshold
        and abs(signal.absolute_change) >= absolute_threshold
    )
    if breached:
        return DriftSignal(hall_id, epoch, DriftStatus.ALERT, comparisons=comparisons)
    return signal


def check_all(readings: Sequence[Reading], *, now: datetime, **kwargs) -> list[DriftSignal]:
    """Run the check per hall. Halls are independent cameras."""
    by_hall: dict[str, list[Reading]] = {}
    for reading in readings:
        by_hall.setdefault(reading.hall_id, []).append(reading)

    return [check_hall(group, now=now, **kwargs) for _, group in sorted(by_hall.items())]


def render_report(signals: Sequence[DriftSignal]) -> str:
    alerts = [s for s in signals if s.status is DriftStatus.ALERT]
    lines = [signal.describe() for signal in signals]

    if alerts:
        lines.append("")
        lines.append(f"{len(alerts)} camera(s) drifting. Runbook: docs/runbook.md#camera-drift")
    return "\n".join(lines)
