"""Which cameras have stopped reporting.

This is an outage check, and it exists because the drift check cannot be one.

Drift compares counts to counts: it needs MIN_READINGS_PER_SLOT observations in
a slot before it will say anything at all. So a camera that stops reporting
makes the drift check go *quiet*, not loud - the signal degrades to
`insufficient_data` and the hall silently drops out of the report. The failure
mode that most wants an alarm is the one that disables the alarm.

The likeliest cause over a long collection is a rotated stream id. A YouTube
live stream that restarts comes back under a new video id, the stored
stream_url resolves to nothing, and that hall stops producing counts while
every other hall carries on. Nothing else in this project notices. The
evidence shows up weeks later as a hole in the history, at which point the
readings are not recoverable.

Opening hours are deliberately not consulted. `pipeline.run_tick` captures
every active hall on every tick regardless of the clock - `opens_at` and
`closes_at` are presentation, used by the site to say "Closed" instead of a
number. A healthy hall therefore produces a reading every interval, all night,
and "no readings for six hours" means something is broken rather than shut.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from hallcheck.models import Hall

#: How long a hall may go without a reading before it is called stale.
#:
#: The capture interval is 120 seconds, so six hours is 180 consecutive missed
#: captures. Short enough to catch a stream that rotated its id this morning,
#: long enough that a redeploy, a transient network failure or a provider
#: hiccup does not page anyone. A threshold near the capture interval would
#: fire constantly and be ignored, which is the same as not having one.
STALE_AFTER_HOURS = 6

#: How far back to look for a hall's most recent reading.
#:
#: Bounds the query rather than the verdict. A hall with no reading in this
#: window is reported as silent for *at least* this long - the check does not
#: claim to know whether it ever reported, because the data it asked for
#: cannot distinguish "never configured" from "down since last week". Both
#: need a human either way.
LOOKBACK_HOURS = 24


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    SILENT = "silent"


@dataclass(frozen=True, slots=True)
class HallFreshness:
    hall_id: str
    status: Freshness
    last_seen: datetime | None
    age: timedelta | None

    @property
    def ok(self) -> bool:
        return self.status is Freshness.FRESH

    def describe(self) -> str:
        if self.status is Freshness.FRESH:
            return f"last reading {_age(self.age)} ago"
        if self.status is Freshness.STALE:
            return f"no reading for {_age(self.age)}"
        return f"no reading in the last {LOOKBACK_HOURS}h"


@dataclass(frozen=True, slots=True)
class StalenessReport:
    halls: tuple[HallFreshness, ...]
    checked_at: datetime

    @property
    def failing(self) -> tuple[HallFreshness, ...]:
        return tuple(h for h in self.halls if not h.ok)

    @property
    def worker_is_down(self) -> bool:
        """Every hall is silent, which is one fault rather than many.

        A rotated stream id takes out one camera. A worker that has stopped,
        lost its credentials, or cannot reach the database takes out all of
        them at once. Reporting five alerts for a single dead process sends
        whoever is on the other end to five stream URLs instead of to the
        process, so the distinction is worth drawing explicitly.
        """
        return bool(self.halls) and all(not h.ok for h in self.halls)

    @property
    def ok(self) -> bool:
        return not self.failing


def _age(delta: timedelta | None) -> str:
    if delta is None:
        return "unknown"
    hours, seconds = divmod(int(delta.total_seconds()), 3600)
    minutes = seconds // 60
    if hours >= 24:
        days, hours = divmod(hours, 24)
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m"


def last_seen_by_hall(readings: Iterable[dict]) -> dict[str, datetime]:
    """Most recent reading timestamp per hall.

    Takes the raw rows `Store.counts_since` returns rather than a parsed type,
    because that is what every other caller of it does and a second shape for
    the same rows is a thing to keep in sync for no benefit.
    """
    latest: dict[str, datetime] = {}
    for row in readings:
        hall_id = row["hall_id"]
        ts = row["ts"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        current = latest.get(hall_id)
        if current is None or ts > current:
            latest[hall_id] = ts
    return latest


def check(
    halls: Sequence[Hall],
    readings: Iterable[dict],
    *,
    now: datetime,
    stale_after_hours: int = STALE_AFTER_HOURS,
) -> StalenessReport:
    """Classify every active hall by how long since it last reported."""
    latest = last_seen_by_hall(readings)
    threshold = timedelta(hours=stale_after_hours)

    results = []
    for hall in sorted(halls, key=lambda h: h.hall_id):
        last = latest.get(hall.hall_id)
        if last is None:
            results.append(HallFreshness(hall.hall_id, Freshness.SILENT, None, None))
            continue
        age = now - last
        status = Freshness.FRESH if age <= threshold else Freshness.STALE
        results.append(HallFreshness(hall.hall_id, status, last, age))

    return StalenessReport(halls=tuple(results), checked_at=now)


def render_report(report: StalenessReport) -> str:
    """A report that states the conclusion before the table.

    The table is what gets pasted into the runbook's incident log; the line
    above it is what gets read.
    """
    lines = [
        "# Stream freshness",
        "",
        f"Checked {report.checked_at.isoformat(timespec='seconds')}, "
        f"stale after {STALE_AFTER_HOURS}h without a reading.",
        "",
    ]

    if report.worker_is_down:
        lines += [
            "**Every hall is silent.** That is one fault, not "
            f"{len(report.halls)}: the worker is stopped, out of credentials, "
            "or cannot reach the database. Check the process before checking "
            "any stream URL.",
            "",
        ]
    elif report.ok:
        lines += ["All halls reporting.", ""]
    else:
        names = ", ".join(h.hall_id for h in report.failing)
        lines += [
            f"**{len(report.failing)} of {len(report.halls)} halls not "
            f"reporting: {names}.** A single hall going quiet while the others "
            "continue is usually a rotated stream id - the live stream "
            "restarted under a new video id and the stored stream_url no "
            "longer resolves. Fix by updating halls.stream_url; no redeploy "
            "needed.",
            "",
        ]

    lines += ["| Hall | Status | Detail |", "|---|---|---|"]
    for hall in report.halls:
        mark = {Freshness.FRESH: "ok", Freshness.STALE: "STALE", Freshness.SILENT: "SILENT"}
        lines.append(f"| {hall.hall_id} | {mark[hall.status]} | {hall.describe()} |")

    return "\n".join(lines) + "\n"
