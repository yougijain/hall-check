"""The always-on loop.

Why a resident worker rather than a cron trigger: the counts are only useful if
the timestamp on them is the timestamp you think it is. GitHub Actions cron
drifts by minutes under load and offers no guarantee about when a job starts;
platform hobby-tier crons come with their own frequency caps and cold starts.
A two-minute grid is not something either of them can hold. An APScheduler
interval job inside a process that stays up is accurate to the second and costs
less than the free tier it runs on.

Three scheduler settings carry the operational behaviour:

* `max_instances=1` - a tick that overruns must not have the next one start
  underneath it. Two concurrent passes fight over ffmpeg and the CPU and both
  take longer than one would.
* `coalesce=True` - after a pause (a redeploy, a suspended container), run the
  backlog once rather than firing every tick that was missed. Those frames are
  gone; replaying the schedule would only write the current count under a dozen
  past timestamps.
* `misfire_grace_time` - a tick that is more than one interval late has missed
  its slot. Skip it and wait for the next one rather than recording a stale
  reading at a fresh timestamp.
"""

from __future__ import annotations

import logging
import signal
import sys
from datetime import UTC
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from hallcheck.config import Settings
from hallcheck.detect import Detector
from hallcheck.drift import DriftStatus, check_all, render_report
from hallcheck.features import Reading
from hallcheck.pipeline import run_tick
from hallcheck.store import Store

log = logging.getLogger(__name__)


def run_drift_check(store: Store) -> None:
    """Compare every camera's last day against its trailing fortnight.

    Logged rather than raised. A drifting camera is not an emergency that
    should take the capture loop down - the counts keep arriving, they have
    just stopped meaning what they did - but it does need a human to look at
    the stream and decide whether to bump `camera_epoch`.
    """
    from datetime import datetime, timedelta

    from hallcheck.drift import BASELINE_WINDOW_DAYS, RECENT_WINDOW_HOURS

    now = datetime.now(tz=UTC)
    lookback = timedelta(days=BASELINE_WINDOW_DAYS, hours=RECENT_WINDOW_HOURS)

    try:
        rows = store.counts_since(now - lookback)
    except Exception as exc:  # the capture loop must survive this
        log.error("drift check could not read counts: %s", exc)
        return

    readings = [
        Reading(
            hall_id=row["hall_id"],
            ts=datetime.fromisoformat(row["ts"]),
            count=int(row["count"]),
            camera_epoch=int(row.get("camera_epoch") or 1),
            roi_version=str(row.get("roi_version") or "v1"),
        )
        for row in rows
    ]

    signals = check_all(readings, now=now)
    # Not `signal`: this module imports the stdlib `signal` for the SIGTERM
    # handler in serve(), and shadowing it here is a trap waiting for whoever
    # next adds a line to this function.
    for result in signals:
        if result.status is DriftStatus.ALERT:
            log.error("DRIFT %s", result.describe())
        else:
            log.info("drift check: %s", result.describe())

    if any(s.status is DriftStatus.ALERT for s in signals):
        log.error("drift report:\n%s", render_report(signals))


def build_scheduler(detector: Detector, store: Store, settings: Settings) -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_tick,
        trigger=IntervalTrigger(seconds=settings.interval_seconds),
        args=[detector, store, settings],
        id="capture",
        name="capture every active hall",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=settings.interval_seconds,
        replace_existing=True,
    )

    # Once a day, in the small hours: the check needs a full day of readings
    # to compare, and running it more often would re-report the same drift
    # every hour until someone acts on it.
    scheduler.add_job(
        run_drift_check,
        trigger=CronTrigger(hour=8, minute=0),
        args=[store],
        id="drift",
        name="check every camera for drift",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    return scheduler


def serve(detector: Detector, store: Store, settings: Settings) -> None:
    """Run until told to stop.

    Weights are loaded before the first tick so the several-second startup cost
    is paid here, where it is visible in the deploy log, instead of inside a
    tick where it looks like a slow camera.
    """
    detector.load()  # type: ignore[attr-defined]  # protocol members are the hot path

    scheduler = build_scheduler(detector, store, settings)

    def _stop(signum: int, _frame: FrameType | None) -> None:
        log.info("signal %s received, shutting down", signal.Signals(signum).name)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    log.info(
        "starting capture loop: every %ds, model %s",
        settings.interval_seconds,
        settings.model_version,
    )
    # One pass immediately, so a deploy is confirmed working within seconds
    # rather than after a full interval of silence.
    run_tick(detector, store, settings)
    scheduler.start()
