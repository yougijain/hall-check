"""Capture, count, store - once per hall per tick.

The whole product is this file plus the four modules it calls. Everything else
is scaffolding around it.

Two rules shape the error handling:

1. One hall's failure must not affect another's. A dead stream at Franklin is
   not a reason for Worcester to stop reporting, so every hall is wrapped
   independently and the tick reports partial success.
2. A failure writes nothing. There is no "0" fallback and no last-known-value
   carry-forward, because a row that says zero is a claim that a camera looked
   and saw an empty room. A gap is honest; a fabricated zero teaches the
   forecast that the hall empties out whenever the network is bad.
"""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass
from datetime import UTC, datetime

from hallcheck.capture import CaptureError, capture_frame
from hallcheck.config import Settings
from hallcheck.detect import DetectionError, Detector
from hallcheck.models import CountRecord, Hall
from hallcheck.store import Store, StoreError

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TickResult:
    hall_id: str
    count: int | None
    latency_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def align_timestamp(moment: datetime, interval_seconds: int) -> datetime:
    """Snap a capture time down to the capture grid.

    Readings land on exact interval boundaries rather than wherever the
    scheduler happened to fire. This is what makes "the same slot last week" an
    equality join on `ts - 7 days` instead of a nearest-neighbour search over a
    tolerance window, and it is why the forecast baselines in M4 are cheap.

    Sub-second jitter in when the tick fires is not information about the
    dining hall, so nothing is lost by discarding it.
    """
    epoch_seconds = int(moment.timestamp())
    aligned = epoch_seconds - (epoch_seconds % interval_seconds)
    return datetime.fromtimestamp(aligned, tz=UTC)


def capture_hall(
    hall: Hall,
    detector: Detector,
    store: Store,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> TickResult:
    """Read one hall and persist the result. Never raises."""
    started = _time.monotonic()
    moment = now or datetime.now(tz=UTC)
    ts = align_timestamp(moment, settings.interval_seconds)

    stream_url = settings.stream_url_for(hall.hall_id, hall.stream_url)
    if not stream_url:
        return TickResult(hall.hall_id, None, 0, "no stream URL configured")

    try:
        with capture_frame(stream_url, timeout=settings.capture_timeout) as frame:
            # The frame is only alive inside this block. Reduce it to an
            # integer here or lose it.
            count = detector.count_in_roi(frame, hall.roi)
    except (CaptureError, DetectionError) as exc:
        latency_ms = int((_time.monotonic() - started) * 1000)
        log.warning("hall %s failed: %s", hall.hall_id, exc)
        return TickResult(hall.hall_id, None, latency_ms, str(exc))

    latency_ms = int((_time.monotonic() - started) * 1000)
    record = CountRecord(
        hall_id=hall.hall_id,
        ts=ts,
        count=count,
        model_version=detector.model_version,
        conf_threshold=settings.conf_threshold,
        roi_version=hall.roi.version,
        camera_epoch=hall.camera_epoch,
        latency_ms=latency_ms,
    )

    try:
        store.record_count(record)
    except StoreError as exc:
        log.error("hall %s counted %d but the write failed: %s", hall.hall_id, count, exc)
        return TickResult(hall.hall_id, count, latency_ms, str(exc))

    log.info("hall %s count=%d latency=%dms ts=%s", hall.hall_id, count, latency_ms, ts.isoformat())
    return TickResult(hall.hall_id, count, latency_ms)


def run_tick(
    detector: Detector,
    store: Store,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> list[TickResult]:
    """Capture every active hall once.

    Halls are read sequentially. Four ffmpeg processes in parallel on a free
    tier box contend for the same single core and make every capture slower
    than doing them one at a time; the interval is two minutes and a sequential
    pass takes seconds.
    """
    try:
        halls = store.active_halls()
    except StoreError as exc:
        log.error("could not list halls, skipping tick: %s", exc)
        return []

    if not halls:
        log.warning("no active halls configured; nothing to capture")
        return []

    results = [capture_hall(hall, detector, store, settings, now=now) for hall in halls]

    failures = [r for r in results if not r.ok]
    if failures:
        log.warning(
            "tick finished with %d/%d halls failing: %s",
            len(failures),
            len(results),
            ", ".join(f"{r.hall_id} ({r.error})" for r in failures),
        )
    return results
