# Deploying Hall Check

Three pieces, in this order: the database, the worker, the site. Each one is
useless without the one before it.

**Before any of it works, read [Two things that gate everything](#two-things-that-gate-everything)
at the bottom.** A correctly deployed Hall Check with the default configuration
records nothing at all, on purpose.

---

## 1. Supabase

Create a project, then apply the migrations in order:

```bash
psql "$SUPABASE_DB_URL" -f db/migrations/0001_init.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0002_rls_and_read_views.sql
psql "$SUPABASE_DB_URL" -f db/migrations/0003_seed_halls.sql
```

or `supabase db push` against a linked project.

Then verify the access model actually took, rather than assuming it did:

```bash
psql "$SUPABASE_DB_URL" -f db/tests/access_model.sql
```

It asserts three reads succeed and nine writes and private reads are refused,
and prints `access model verified`. This is worth running against the real
project and not just in CI: the anon key ships inside the browser bundle, so
the blast radius of a wrong grant is "anyone can write to your database".

Two keys come out of the project settings, and they are not interchangeable:

| Key | Goes to | Why |
|---|---|---|
| `anon` | Vercel, as `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public by construction. RLS and column grants confine it to reading counts. |
| `service_role` | Render, as `SUPABASE_SERVICE_KEY` | Bypasses RLS entirely. The only thing that writes. Never put this in the web project. |

Anything prefixed `NEXT_PUBLIC_` is compiled into the browser bundle. If the
service role key ever appears in `web/`, rotate it immediately.

## 2. Worker

The worker is a resident process, not a cron job — the counts are only useful
if their timestamps are accurate, and hosted cron schedulers drift by minutes.
See `worker/hallcheck/scheduler.py`.

### Option A: pull the published image (recommended)

`.github/workflows/publish-worker.yml` builds `worker/Dockerfile` on every push
to `main` that touches `worker/`, smoke tests it, and pushes to:

```
ghcr.io/yougijain/hall-check/worker:latest
```

On Render: **New → Web Service → Deploy an existing image**, paste that URL,
and choose an instance with at least 1 GB of memory.

The package is private until you make it public. GitHub → your profile →
Packages → `worker` → Package settings → Change visibility → Public. Leave it
private and Render needs registry credentials instead.

Pulling beats building here: the image carries torch, so a build from source on
a small instance is slow and can exceed the build timeout.

### Option B: build from source

`render.yaml` at the repository root defines the service as a Docker build from
`worker/Dockerfile`. **New → Blueprint**, point it at the repo.

### Environment

Set these on the service. The first two have no defaults and the worker refuses
to start without them, naming both at once.

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_KEY` | **service_role** key |
| `HALLCHECK_MODEL` | `yolo11n.pt` |
| `HALLCHECK_CONF_THRESHOLD` | `0.35` |
| `HALLCHECK_INTERVAL_SECONDS` | `120` |
| `HALLCHECK_CAPTURE_TIMEOUT` | `30` |

`HALLCHECK_CAPTURE_TIMEOUT` must stay below `HALLCHECK_INTERVAL_SECONDS`, and
the worker refuses to start otherwise: a hall that times out would otherwise
consume the whole tick and starve every hall captured after it, which looks
like several dead cameras rather than one.

### Confirming it works

```bash
# From anywhere with the service role key:
python -m hallcheck.cli once
```

prints one line per hall and exits non-zero only if *every* hall failed, so a
single dead camera is distinguishable from nothing working. Expect
`no stream URL configured` on a fresh install — see below.

Roughly one core, ~700 MB resident with the model loaded, four captures every
two minutes.

## 3. Web

Vercel project, **root directory set to `web/`**. Same repository as the
worker, separate deployment target.

```
NEXT_PUBLIC_SUPABASE_URL   = project URL
NEXT_PUBLIC_SUPABASE_ANON_KEY = anon key
```

Without them the site still builds and renders a setup notice, which is why CI
can build it without credentials.

---

## Two things that gate everything

Deploying all three pieces correctly still produces a site that shows
`No recent data` for every hall. That is not a bug in the deployment; it is two
pieces of configuration that cannot be guessed and were deliberately left
unset.

### Stream URLs

`0003_seed_halls.sql` inserts every hall with `stream_url = ''`, and the worker
skips a hall until one is configured. Nothing is captured until you set them:

```sql
update public.halls set stream_url = 'https://…' where hall_id = 'worcester';
```

or per-hall, without touching the database, via `HALLCHECK_STREAM_WORCESTER` on
the worker.

The design assumes UMass publishes a public video stream per dining common.
**Confirm that before counting on any of this** — find the actual page, check
what it serves, and whether the terms permit reading it. If a hall streams
through a watch page rather than a direct `.m3u8`, the worker resolves it with
yt-dlp automatically.

### ROI polygons

The seeded polygons are placeholders: a centred box over the middle of the
frame, marked `roi_version = 'v0-placeholder'` so no count produced under one
can be mistaken for a real measurement.

They must be redrawn against a real frame from each camera before any count
means anything. A polygon over the whole frame counts people eating at tables
and calls it a queue — a different quantity that happens to correlate, which is
exactly enough to be misleading.

Coordinates are normalised to `[0, 1]` against frame width and height, not
pixels, so a change in stream resolution does not silently move the region:

```sql
update public.halls
   set roi_polygon = '[[0.31,0.42],[0.68,0.40],[0.72,0.88],[0.27,0.90]]'::jsonb,
       roi_version = 'v1'
 where hall_id = 'worcester';
```

Bump `roi_version` whenever the shape changes, and `camera_epoch` whenever the
camera physically moves. Neither rewrites history — that is the point. Counts
either side of a change are measurements on different scales, and both columns
are stamped on every row so later queries can tell.

## Order of operations

1. Migrations applied, `access_model.sql` verified.
2. Stream URLs set for at least one hall.
3. Worker deployed; `hallcheck once` returns a count rather than a skip.
4. ROI polygons redrawn against real frames; `roi_version` bumped.
5. Site deployed.
6. Leave it collecting. M2 labelling needs model counts to pair against, and
   the M4 forecast needs weeks of history before it can be trained at all.
