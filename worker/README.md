# Hall Check worker

Grabs one frame from each dining hall stream every two minutes, counts the
people standing in that hall's queue region, writes the number to Postgres, and
throws the frame away.

Runs on CPU. No GPU, no fine-tuning, no training step.

## Quick start

```bash
cd worker
python -m venv .venv && source .venv/bin/activate
make install-dev

cp .env.example .env     # fill in SUPABASE_URL and SUPABASE_SERVICE_KEY
make once                # capture every hall exactly once and print the result
make run                 # start the loop and stay up
```

`ffmpeg` has to be on `PATH`. `apt install ffmpeg`, `brew install ffmpeg`, or use
the Dockerfile, which already has it.

The first `make run` downloads YOLO11n (about 6 MB) into the Ultralytics cache.
The Docker image bakes it in instead, so a deploy does not depend on that
download succeeding.

## What it does, in order

```
halls table ─► stream URL ─► ffmpeg (1 frame, to stdout)
                                 │
                                 ▼
                        decode in memory
                                 │
                                 ▼
                      YOLO11n, classes=[0]
                                 │
                                 ▼
                 keep boxes whose FEET are in the ROI
                                 │
                                 ▼
                            an integer ──► counts table
                                 │
                          frame zeroed and dropped
```

Three decisions in there are worth more than they look.

**The anchor is the feet, not the box centre.** A person occupies the floor they
stand on. Using the centre counts someone standing outside the region who leans
over its edge, and misses someone inside it near the boundary. The bias is not
even uniform, because boxes clipped by the frame edge have centres that drift
inward. `BoundingBox.anchor` in `hallcheck/roi.py`.

**Coordinates are normalised, not pixels.** Streams get re-encoded at different
resolutions without warning. A pixel polygon silently starts covering a
different part of the room when that happens; a polygon in [0, 1] does not.

**A failure writes nothing.** There is no zero fallback and no carry-forward of
the last known value. A row saying zero is a claim that a camera looked and saw
an empty room, and a fabricated one would teach the M4 forecast that occupancy
collapses whenever the network is bad. A gap in the data is honest. See
`test_a_failure_writes_nothing_rather_than_a_zero`.

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Environment into a validated `Settings`, once, at startup |
| `capture.py` | ffmpeg, yt-dlp resolution, and the context manager that destroys the frame |
| `detect.py` | YOLO11n wrapper. Public surface is an `int` |
| `roi.py` | Queue polygon, point-in-polygon, the foot anchor |
| `models.py` | `Hall` and `CountRecord`, mapped to and from database rows |
| `store.py` | Supabase reads and writes, plus an in-memory double for tests |
| `pipeline.py` | One tick: capture, count, store, isolate failures |
| `scheduler.py` | The always-on interval loop |
| `labeling.py` | Blind label collection: human count first, model count after |
| `metrics.py` | MAE, bias, RMSE, bootstrap intervals |
| `evaluate.py` | Stratified report, and the coverage rules that gate quoting it |
| `cli.py` | `run`, `once`, `label`, `evaluate` |

## Configuration

Everything comes from the environment; see `.env.example` for the full list
with commentary.

| Variable | Default | Notes |
|---|---|---|
| `SUPABASE_URL` | — | Required |
| `SUPABASE_SERVICE_KEY` | — | Required. Service role, not anon — the worker writes |
| `HALLCHECK_MODEL` | `yolo11n.pt` | Move to `yolo11s.pt` only if M2 error numbers justify it |
| `HALLCHECK_CONF_THRESHOLD` | `0.35` | Stamped onto every count; changing it starts a new series |
| `HALLCHECK_INTERVAL_SECONDS` | `120` | Capture cadence |
| `HALLCHECK_CAPTURE_TIMEOUT` | `30` | Must be shorter than the interval, or a dead camera starves the halls behind it |
| `HALLCHECK_STREAM_<HALL_ID>` | — | Override a hall's stream URL without touching the database |

Missing required variables are all reported in one error at startup. Finding
them one redeploy at a time is how a ten minute setup becomes an afternoon.

## Timestamps are snapped to a grid

Readings land on exact interval boundaries rather than wherever the scheduler
happened to fire. That is what makes "the same slot last week" an equality join
on `ts - 7 days` instead of a nearest-neighbour search over a tolerance window,
which is what the M4 baselines are built on. Sub-second jitter in when a tick
fires is not information about the dining hall, so nothing is lost.

Combined with the unique `(hall_id, ts)` constraint, it also makes the writer
idempotent: a retried tick upserts its own slot instead of adding a second
reading for the same moment.

## Tests

```bash
make test    # 146 tests, no network, no weights, no GPU
make lint
```

Nothing in the suite downloads a model or opens a socket. `torch` and
`ultralytics` are imported lazily by the modules that need them and faked in
the tests, which is why `requirements-ci.txt` can skip two gigabytes of
dependencies and CI finishes in under a minute.

The trade-off is named rather than hidden: CI does not catch a breaking change
in the Ultralytics API. The Docker build does, because it imports Ultralytics
to bake the weights in, and that runs on every deploy.

`tests/test_privacy.py` is the one to read first. It parses every module in the
package and fails the build if a call that could persist pixels appears in it.

## Collecting ground truth

```bash
python -m hallcheck.cli label worcester -n 10   # ten labels, one hall
python -m hallcheck.cli evaluate                # the accuracy table
```

`label` captures a frame, runs the detector, **says nothing**, asks for your
count, and only then shows both numbers. That ordering is the protocol, not a
nicety: a labeller who has already seen `23` writes `23`, and the resulting MAE
measures their suggestibility rather than the detector. It is enforced in code
and pinned by a test.

`evaluate` exits non-zero while any coverage gap remains, so it can gate the
README table from a script. Full protocol in
[`docs/measurement-protocol.md`](../docs/measurement-protocol.md).

## Deploying

`render.yaml` at the repository root defines the worker service. A resident
process rather than a cron job, because the counts are only useful if their
timestamps are accurate and hosted cron schedulers drift by minutes.

Roughly: one CPU core, ~700 MB resident with the model loaded, and four
captures every two minutes. Comfortable on a small instance.
