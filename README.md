# Hall Check

Live dining hall occupancy at UMass Amherst, estimated from the public video
streams the university already publishes.

**Privacy rule, before anything else: Hall Check stores counts, never frames.**
A frame is pulled into memory, a person detector returns a number, the number is
written to Postgres, and the frame is discarded in the same function call.
Nothing decodes to an image on disk, in object storage, or in a log line. There
is no code path in this repository that persists pixels, and
[`worker/tests/test_privacy.py`](worker/tests/test_privacy.py) fails the build if
one is added.

---

## The problem

Between 12:00 and 12:30 the line at Worcester runs out the door. At 12:45 it is
empty. Students have no way to tell which of those they are walking into, so
they walk over, look, and leave — or they queue for twenty minutes because they
guessed wrong. The information exists: the dining halls stream publicly. Nobody
turns it into a number.

Hall Check turns it into a number, shows it on a page, and forecasts it thirty
minutes out so you can decide before you leave your dorm.

Who it serves: undergraduates deciding where and when to eat. That is the whole
audience. It is a small problem, and the value is entirely in whether the number
is correct and current.

## Architecture

```
  UMass HLS streams (public)
            │
            │  one frame every 2 min, held in memory
            ▼
  ┌─────────────────────┐
  │ worker/  (Render)   │
  │                     │
  │  capture ──► detect ──► ROI filter ──► count
  │  ffmpeg     YOLO11n    polygon         int
  │                     │        frame discarded here
  └─────────┬───────────┘
            │  INSERT counts(hall_id, ts, count, ...)
            ▼
  ┌─────────────────────┐        ┌──────────────────────┐
  │ Supabase Postgres   │◄───────│ forecast (30 min)    │
  │  counts             │        │ HistGradientBoosting │
  │  labels             │        └──────────────────────┘
  │  halls              │
  └─────────┬───────────┘
            │  anon key, read-only via RLS
            ▼
  ┌─────────────────────┐
  │ web/  (Vercel)      │  current count + today's curve
  │  Next.js            │
  └─────────────────────┘
```

One repository, two deployment targets. `worker/` runs as an always-on Render
service with an APScheduler loop; `web/` is a Vercel project with its root
directory set to `web/`. They share only the database.

Detection runs on a schedule, not on every frame. At 2-minute intervals a CPU
box keeps up comfortably, the counts are as fresh as the decision they inform,
and the cost stays under a dollar a day. Running the detector on all 30 fps
would cost roughly 3,600× more compute to answer the same question.

## Repository layout

| Path | What it is |
|---|---|
| `db/migrations/` | Ordered SQL migrations. The schema is the contract between worker and web. |
| `worker/hallcheck/` | Capture, detection, ROI, storage, scheduling, labeling, forecasting, drift. |
| `worker/tests/` | Unit tests. No network, no model weights, no GPU. |
| `web/` | Next.js app deployed to Vercel. |
| `docs/` | Measurement protocol, privacy policy, operational runbook. |

## Data model

```sql
counts(hall_id, ts, count, model_version, conf_threshold, roi_version)
labels(hall_id, ts, human_count, model_count, meal, lighting, notes)
halls(hall_id, name, stream_url, roi_polygon, camera_epoch)
```

Two columns carry more weight than they look like they do.

`roi_polygon` bounds the queue region. Counting the whole frame counts people
eating at tables and calls it a line, which is a different quantity that happens
to correlate. Every count records the `roi_version` it was produced under, so
redrawing a polygon does not silently rewrite history.

`camera_epoch` increments whenever a camera is moved, re-aimed, or refocused. A
count from before the move and a count from after it are measurements of
different things on different scales. Comparing them — in a forecast, in a drift
check, in a chart — produces a confident wrong answer. The epoch makes that
comparison something you have to opt into.

## Measurement protocol (M2)

Accuracy claims are worth what the labels behind them are worth, so the protocol
is fixed before the numbers are.

- **Label count:** 150–250 paired observations.
- **Procedure:** the stream plays, a human counts the people inside the ROI, and
  the model count for the same timestamp is recorded alongside it. The human
  count is written before the model count is revealed.
- **Stratification:** every label carries `meal` (breakfast / lunch / dinner),
  `lighting` (daylight / dark), and `hall_id`. Coverage across all three is a
  release requirement, not a nice-to-have — an MAE measured only at lunch in
  daylight tells you nothing about dinner in January.
- **Reported metrics:** MAE and signed bias, overall and broken out per hall and
  per lighting condition.

**Why MAE and not MAPE.** Counts go to zero between meals. MAPE divides by the
true value, so a single off-by-two at a true count of 1 contributes 200% and
swamps the mean; at a true count of 0 it is undefined. MAE is in people, which
is the unit the decision is made in — "the line is about 8 people longer than
the model says" is actionable, "the model is 40% off" is not.

**Why bias sits next to MAE.** They describe different failures. MAE 6 with
bias 0 is a noisy detector; MAE 6 with bias −6 is a detector that
systematically misses half the queue. The second is fixable and the first
mostly is not, so collapsing them loses the actionable half. Bias is model
minus human, so negative means under-counting.

**Status: not yet measured.** The harness is built and tested; the labels are
not collected yet. `hallcheck evaluate` generates the table below and exits
non-zero while any coverage gap remains, so the figure cannot be quoted before
the conditions are covered. Full protocol, including the counting rules and the
known limitations, in
[`docs/measurement-protocol.md`](docs/measurement-protocol.md).

| Stratum | n | MAE (95% CI) | Bias | RMSE |
|---|---|---|---|---|
| **Overall** | — | — | — | — |

The interval is a seeded percentile bootstrap. A point estimate from 180 labels
invites being read as exact; the interval shows how much of the number is the
detector and how much is which afternoons happened to get labelled.

## Forecast (M4)

Predict the count 30 minutes ahead. Two baselines are recorded before the model
is trained, and both stay in the table permanently:

1. **Same slot last week** — same weekday, same time of day, 7 days back.
2. **Same slot yesterday** — same time of day, 1 day back.

These are strong. Dining hall traffic is close to a weekly periodic signal, and
a gradient boosting model that cannot beat "look at last Tuesday" is not earning
its complexity.

Features: hour, minute-of-meal, weekday, minutes until close, the menu items for
that meal, exam and holiday flags, optionally weather.

**The split is by time, never at random.** A random split puts 12:02 on a
Tuesday in train and 12:04 the same Tuesday in test. Those two rows are almost
the same observation, so the model scores well by having memorised the test set
through its neighbours. The reported number would be a fiction that collapses in
production, where every prediction is about a timestamp the model has never
seen. Train on the earliest weeks, test on the most recent, evaluate baselines
and model on that same held-out window.

**Status: not yet measured.**

| Model | Test MAE |
|---|---|
| Baseline: same slot last week | — |
| Baseline: same slot yesterday | — |
| HistGradientBoostingRegressor | — |

If the model loses, the table says so and the model does not ship. That result
is not a failure of the project; it is the project working.

## Drift (M5)

Cameras move. Someone bumps a mount, maintenance re-aims a lens, a screen gets
repositioned, and from that moment the ROI covers a different piece of the
world. The counts stay plausible, which is what makes it dangerous.

Per camera, Hall Check compares a rolling 24-hour median against the trailing
14-day median for the same time slot. A sustained divergence past the threshold
in [`docs/runbook.md`](docs/runbook.md) raises an alert, which is the signal to
inspect the stream and increment `camera_epoch`.

The same-slot comparison matters: comparing a 24-hour median to a 14-day median
without matching the time of day just measures the meal schedule.

## What this does not prove

- **Occlusion biases the count downward exactly when it matters most.** At peak,
  people stand behind each other. The detector sees the front of the line and
  loses the back of it, so error is not symmetric — the model under-counts worst
  at the moment the answer is most useful. A single MAE figure averaged across
  the day hides this, which is why the tables are stratified.
- **The ROI is a proxy for a line, not a line.** It is a fixed polygon over a
  region where a queue usually forms. People standing in it who are not queueing
  are counted; a queue that spills outside it is not. The number tracks the
  quantity of interest; it is not the quantity of interest.
- **One camera per hall.** A hall with two entrances is being measured at one of
  them. Nothing in the counts reveals what the other one is doing.
- **Accuracy is measured on labels a single person produced.** There is no
  second annotator and therefore no inter-rater agreement. The human count is
  treated as ground truth; at high occupancy it is also an estimate.
- **Correct is not the same as calibrated.** MAE says how far off the count is.
  It does not say whether "23 people" means the same wait on a Monday as it does
  on a Friday.

## Running it

See [`worker/README.md`](worker/README.md) for the worker and
[`web/README.md`](web/README.md) for the site. Neither requires a GPU.

## Licence

MIT. See [LICENSE](LICENSE).
