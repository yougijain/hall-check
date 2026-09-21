"""Collecting ground truth.

The protocol has one rule that matters more than the rest: the human count is
recorded before the model count is revealed.

Anchoring is not a hypothetical here. Counting people in a crowded frame is
genuinely hard, the honest answer is often "somewhere around twenty", and a
labeller who has already seen "23" will write 23. Every label collected that
way drags MAE toward zero and the resulting number is a measurement of the
labeller's suggestibility rather than the detector's accuracy.

So the ordering is structural rather than a convention to remember. The model
count is computed first and held in a local; the prompt is called; only then is
anything about the model written or displayed. `tests/test_labeling.py` asserts
that nothing carrying the model count reaches the operator before their answer
is in.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, time

from hallcheck.capture import CaptureError, capture_frame
from hallcheck.config import Settings
from hallcheck.detect import DetectionError, Detector
from hallcheck.models import Hall, LabelRecord
from hallcheck.pipeline import align_timestamp

log = logging.getLogger(__name__)

Prompt = Callable[[str], str]
Output = Callable[[str], None]

MEALS = ("breakfast", "lunch", "dinner", "closed")
LIGHTING = ("daylight", "dark")


class LabelAborted(RuntimeError):
    """The operator backed out. Nothing is written."""


def infer_meal(local: time) -> str:
    """A default for the meal field, from the clock.

    A suggestion the operator confirms, not a derived fact. Service hours shift
    on weekends and during breaks, and the operator is looking at the hall.
    """
    if time(7, 0) <= local < time(10, 30):
        return "breakfast"
    if time(10, 30) <= local < time(15, 0):
        return "lunch"
    if time(16, 30) <= local < time(21, 30):
        return "dinner"
    return "closed"


def parse_count(raw: str) -> int:
    """Read a count, refusing anything that is not one.

    Silently coercing a typo would put a wrong ground truth into the set that
    every accuracy claim rests on, and nothing downstream could ever detect it.
    """
    text = raw.strip()
    if not text:
        raise LabelAborted("no count entered")
    if text.lower() in {"q", "quit", "abort"}:
        raise LabelAborted("aborted by operator")
    if not text.isdigit():
        raise ValueError(f"expected a whole number of people, got {raw!r}")
    return int(text)


def choose(prompt: Prompt, question: str, options: tuple[str, ...], default: str) -> str:
    """Ask for one of a fixed set, accepting empty for the default."""
    answer = prompt(f"{question} [{'/'.join(options)}] ({default}): ").strip().lower()
    if not answer:
        return default
    if answer in options:
        return answer
    matches = [option for option in options if option.startswith(answer)]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(f"expected one of {', '.join(options)}, got {answer!r}")


def capture_model_count(
    hall: Hall, detector: Detector, settings: Settings
) -> tuple[int | None, str | None]:
    """Count the queue now, or explain why it could not be counted.

    Returns `(None, reason)` rather than raising, because a label is still
    worth collecting when the stream is down. The human count is real, the
    pairing can happen later, and `model_count` stays null until it does.
    """
    stream_url = settings.stream_url_for(hall.hall_id, hall.stream_url)
    if not stream_url:
        return None, "no stream URL configured"

    try:
        with capture_frame(stream_url, timeout=settings.capture_timeout) as frame:
            return detector.count_in_roi(frame, hall.roi), None
    except (CaptureError, DetectionError) as exc:
        return None, str(exc)


def run_label_session(
    hall: Hall,
    detector: Detector,
    settings: Settings,
    *,
    prompt: Prompt,
    output: Output,
    local_now: time | None = None,
    now: datetime | None = None,
    meal: str | None = None,
    lighting: str | None = None,
) -> LabelRecord:
    """Collect one label.

    The order of the first three statements is the protocol. Do not reorder
    them: the model count is obtained and kept in a local, the operator is
    asked for theirs, and only afterwards is anything about the model shown.
    """
    moment = now or datetime.now(tz=UTC)
    ts = align_timestamp(moment, settings.interval_seconds)

    # 1. Count, and say nothing about it.
    model_count, failure = capture_model_count(hall, detector, settings)

    # 2. Ask. The operator has seen nothing from step 1.
    output(f"\n{hall.name} — counting the queue region as of {ts.isoformat()}")
    if failure:
        output(f"  (the stream could not be captured: {failure})")
    output("  Count the people inside the queue area. Enter q to abort.")
    human_count = parse_count(prompt("  People in the queue: "))

    chosen_meal = meal or choose(
        prompt, "  Meal", MEALS, infer_meal(local_now or datetime.now().time())
    )
    chosen_lighting = lighting or choose(prompt, "  Lighting", LIGHTING, "daylight")
    note = prompt("  Note (optional): ").strip() or None

    # 3. Now it is safe to reveal.
    record = LabelRecord(
        hall_id=hall.hall_id,
        ts=ts,
        human_count=human_count,
        model_count=model_count,
        meal=chosen_meal,
        lighting=chosen_lighting,
        model_version=getattr(detector, "model_version", None),
        conf_threshold=settings.conf_threshold,
        roi_version=hall.roi.version,
        camera_epoch=hall.camera_epoch,
        notes=note,
    )

    if model_count is None:
        output("  Model: not available. Stored with model_count null.")
    else:
        output(f"  You: {human_count}   Model: {model_count}   Error: {record.error:+d}")

    return record
