# Runbook

## Camera drift

### What it is

A camera moves. Someone bumps a mount, maintenance re-aims a lens, a display
screen is repositioned in front of it. From that moment the ROI covers a
different piece of the room and every count is measuring something else.

What makes this the most dangerous failure in the project is that the counts
stay plausible. They are still small integers, they still rise at lunch, and
nothing in the data announces that it changed meaning. Without a check, the
first sign is somebody mentioning the site has felt wrong lately — and by then
the drift is in the forecast's training data.

### The check

Per camera, once a day:

1. Bucket readings into 30-minute slots by time of day.
2. Take the median for each slot over the **last 24 hours**.
3. Take the median for each slot over the **preceding 14 days**.
4. Compare each slot with itself, and take the median of those changes.

```bash
python -m hallcheck.cli drift    # exits non-zero if anything is drifting
```

It also runs automatically at 08:00 UTC inside the worker; alerts appear in the
logs at `ERROR`.

### The thresholds, and why these

| Setting | Value | Reasoning |
|---|---|---|
| Slot width | 30 min | Wide enough that a few missed captures still leave a usable median, narrow enough that lunch is not averaged with mid-afternoon |
| Recent window | 24 hours | A full service day, so every slot has a same-slot counterpart |
| Baseline window | 14 days | Covers both weekend days twice; short enough to re-settle after term starts |
| Minimum baseline median | 4 people | Below this a slot says nothing about where the camera points. A lens facing a wall and a genuinely empty hall are identical at a count of 1 |
| Minimum comparable slots | 6 | Fewer than this means an outage, not a moved camera |
| Minimum readings per slot | 3 | One reading is not a median |
| Alert relative change | ≥ 40% | Outside what weather, exams and a quiet week produce |
| Alert absolute change | ≥ 4 people | Stops a quiet slot firing on noise |

**Both thresholds have to be breached at once.** Either alone fires on
something ordinary:

- *Relative alone* fires whenever a quiet hall goes from 2 people to 1. Same
  50% shift as 30 to 15, nothing like the same event.
- *Absolute alone* fires on the busiest hall every time it has a light week. A
  5-person swing at a peak of 60 is a Tuesday.

**Medians, not means**, everywhere. One freak dinner rush or a tour group
walking through the frame should not move a baseline that is supposed to
represent normal.

**Same slot, always.** Comparing a 24-hour median against a 14-day median
without matching the time of day measures the meal schedule and nothing else.

**One camera epoch only.** A recorded camera move is not drift, it is history.
The baseline restarts from the move, and the check reports
`insufficient_data` until a fortnight of new history accumulates. That silence
is correct: we already know the camera moved.

These numbers are guesses informed by how dining halls behave, not values tuned
against data — there is no history to tune against yet. Revisit them after the
first real incident, and record the change here.

### When an alert fires

1. **Open the stream and look at it.** This takes thirty seconds and settles
   most cases. Has the framing changed?
2. **If the camera has moved**, and you are keeping the new framing:
   - Redraw `halls.roi_polygon` against a current frame.
   - Bump `halls.camera_epoch`.
   - Bump `halls.roi_version` if the polygon changed.
   - Record it in the log below.

   Do not backfill or adjust historical counts. They were correct measurements
   of what the camera saw; the epoch is what tells every later query not to
   compare across the boundary.
3. **If the camera has not moved**, the alert is telling you about the world,
   not the hardware. A closed servery, a changed meal schedule, a building
   works project. Record it below and consider whether the thresholds need
   revisiting.
4. **If the stream is dead**, this is not drift. The check reports
   `insufficient_data` for an outage precisely so the two do not get confused —
   they need completely different responses, and conflating them sends somebody
   to check a lens when the container is down.

### What the check will not catch

- **A camera that moves and lands somewhere with similar occupancy.** The
  statistic is occupancy, so a move that does not change it is invisible here.
- **Slow drift.** A mount sagging a millimetre a week never breaches 40% within
  a single 24-hour window, and the 14-day baseline follows it down. This
  catches step changes.
- **A move during an outage.** The check needs a fortnight of post-move history
  before it can say anything, so a camera that moves while the worker is down
  starts its new baseline immediately and the step change is never seen.
- **Detector changes dressed as camera changes.** Switching model or confidence
  threshold shifts every count at once and looks exactly like drift. Change one
  thing at a time, and remember that `model_version` records the threshold for
  this reason.

### Incident log

Every alert goes here, fired-in-anger or false, with what it turned out to be.
The log is the only evidence that the thresholds are set anywhere near right.

| Date | Hall | Change | Cause | Action |
|---|---|---|---|---|
| — | — | — | — | *No incidents recorded yet. The check is deployed and has not fired.* |

---

## Worker not recording counts

Symptom: the site shows "No recent data" for every hall.

1. `python -m hallcheck.cli once` — captures each hall and prints the result per
   hall, so a dead camera is immediately distinguishable from a dead worker.
2. A hall reporting `no stream URL configured` has an empty `halls.stream_url`.
3. `ffmpeg exited` with a 403 or 404 usually means a resolved stream URL has
   expired. The worker caches resolutions for 30 minutes; a restart clears it.
4. Check that the worker process is up at all. A failed capture writes nothing,
   by design — gaps in `counts` are the expected signature of an outage, not a
   run of zeros.

## Counts look wrong but the camera has not moved

Check `roi_version` on the hall page. If the polygon was redrawn, counts before
and after are on different scales and the site is showing the new one against
an older mental model. That is working as intended.

If the polygon is unchanged, the next question is whether `model_version`
changed — it includes the confidence threshold, because the same weights at a
different cutoff produce a different series.
