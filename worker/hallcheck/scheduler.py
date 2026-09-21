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
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from hallcheck.config import Settings
from hallcheck.detect import Detector
from hallcheck.pipeline import run_tick
from hallcheck.store import Store

log = logging.getLogger(__name__)


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
