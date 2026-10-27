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

Then verify the access model and the ROI polygons actually took, rather than
assuming they did:

```bash
psql "$SUPABASE_DB_URL" -f db/tests/access_model.sql
psql "$SUPABASE_DB_URL" -f db/tests/roi_sanity.sql
```

`access_model.sql` asserts three reads succeed and nine writes and private
reads are refused, and prints `access model verified`. `roi_sanity.sql` checks
every polygon against the rules the worker enforces at load and prints what
each hall ships with. Both are worth running against the real project and not
just in CI: the anon key ships inside the browser bundle, so the blast radius
of a wrong grant is "anyone can write to your database".

Two keys come out of the project settings, and they are not interchangeable:

| Key | Goes to | Why |
|---|---|---|
| `anon` | Vercel, as `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Public by construction. RLS and column grants confine it to reading counts. |
| `service_role` | The worker's host only, as `SUPABASE_SERVICE_KEY` | Bypasses RLS entirely. The only thing that writes. Never put this in the web project. |

Anything prefixed `NEXT_PUBLIC_` is compiled into the browser bundle. If the
service role key ever appears in `web/`, rotate it immediately.

## 2. Worker

The worker is a resident process, not a cron job — the counts are only useful
if their timestamps are accurate, and hosted cron schedulers drift by minutes.
See `worker/hallcheck/scheduler.py`.

Every host below runs the same image. **Pick on network first and cost
second:** the cameras are YouTube live streams, and YouTube refuses them to
datacenter IPs with "Sign in to confirm you're not a bot". Fly was tried on
2026-10-23 and blocked on all four halls; Render is a datacenter too and has
not been tried. What runs today is a laptop - see [STATE.md](STATE.md).

| Host | Instance | Rough cost | Notes |
|---|---|---|---|
| **A machine on a home or campus network** | anything with ~1 GB free | electricity | [Option D](#option-d-a-machine-on-a-residential-network). The only host that has produced a count. |
| Fly.io | `shared-cpu-1x`, 1 GB | ~$5-7/mo | `fly.toml` at the repo root. **Blocked by YouTube.** |
| Render | `standard`, 2 GB | ~$25/mo | `render.yaml`. Its 512 MB `starter` does not fit. Datacenter IP; expect the same block. |

Whatever the host, it is one container and two environment variables, and the
only test that counts is `hallcheck once` passing from that host - more than
once. A single success from a datacenter IP proved nothing on Fly.

The workload is four halls (five when `hampshire_north` returns), one frame
each every two minutes, YOLO11n at roughly 50-100 ms a frame — about six
minutes of CPU a day. The instance is sized by torch's resident footprint, not
by compute, which is why
`worker/Dockerfile` installs the CPU-only torch wheel: PyPI's default wheel for
linux x86_64 is the CUDA build and vendors over a gigabyte of NVIDIA runtime
onto a machine with no GPU. CI asserts it stays that way.

### Option A: pull the published image (recommended)

`.github/workflows/publish-worker.yml` builds `worker/Dockerfile` on every push
to `main` that touches `worker/`, smoke tests it, and pushes to:

```
ghcr.io/yougijain/hall-check/worker:latest
```

On Render: **New → Background Worker → Deploy an existing image**, paste that
URL, and choose an instance with **at least 1 GB of memory** — Render's
`standard`, not `starter`.

A Background Worker, not a Web Service. `worker/Dockerfile` runs
`hallcheck.cli run`, which is a scheduler loop: it binds no port and the image
declares no `EXPOSE`. Render waits for a Web Service to open one and kills the
service when it never does, so the wrong service type fails with "no open ports
detected" on a container that is working correctly.

Measured on 2026-10-26: 376-447 MiB resident with the model loaded and after real
inferences. On a 512 MB instance that leaves nothing for a frame in flight or
a load-time spike, and the container OOMs, which reads as a broken image
rather than an undersized box. 1 GB is enough; it is what `fly.toml` asks for.

The package is private until you make it public. GitHub → your profile →
Packages → `worker` → Package settings → Change visibility → Public. Leave it
private and Render needs registry credentials instead.

Pulling beats building here: the image carries torch, so a build from source on
a small instance is slow and can exceed the build timeout.

### Option B: Fly.io

**YouTube blocks Fly's IPs.** Kept because the configuration is correct and
would be the cheapest option for a stream source that is not YouTube. See
STATE.md, "Why not Fly", before trying it again.

`fly.toml` at the repository root pulls the published image onto a 1 GB
`shared-cpu-1x` machine. It declares no service, because the worker binds no
port — declaring one would make Fly health-check a port that never opens and
cycle the machine.

```bash
fly apps create hallcheck-worker
fly secrets set --app hallcheck-worker --stage SUPABASE_URL=https://<project>.supabase.co
fly secrets set --app hallcheck-worker --stage SUPABASE_SERVICE_KEY=<service_role key>
fly deploy --ha=false
```

Not `fly launch`: it scans the directory, finds `worker/Dockerfile` and tries
to scaffold over a `fly.toml` that is already right. `--ha=false` because the
default creates two machines, and two workers would both capture and
double-write every slot. A new Fly organization also refuses to deploy until a
card is on file.

Put the key last on the `fly secrets set` line. A key copied with a trailing
newline submits the command when pasted, and anything after it is lost.

Secrets go through `fly secrets`, never into `fly.toml` — the file is in git
and the service role key bypasses row level security.

`swap_size_mb` under `[[vm]]` did not take effect (`SwapTotal: 0` on the
machine). Memory never needed it.

Verify the same way as anywhere else:

```bash
fly ssh console -C "python -m hallcheck.cli once"
```

### Option C: build from source

`render.yaml` at the repository root defines the service as a Docker build from
`worker/Dockerfile`. **New → Blueprint**, point it at the repo.

Slower than pulling: the build compiles a torch-sized image on the host's
builder, work the publish workflow has already done and smoke tested. Set
**Root Directory** to `worker` so the Docker build context matches what the
Dockerfile's `COPY` lines expect.

### Option D: a machine on a residential network

What runs today: Docker Engine inside WSL 2 Ubuntu on a Windows laptop. Not
Docker Desktop, which would not start on that machine - see STATE.md. On a
Linux box or a Raspberry Pi 4/5 with 4 GB, skip step 1 and the keep-alive.

1. `wsl --install -d Ubuntu`, then pick a Linux username and password.
2. Inside Ubuntu, as root: `apt-get install -y docker.io`, then
   `systemctl enable --now docker`.
3. Put the two secrets in a file **outside the repo**, one `KEY=value` per
   line. If it was written on Windows, strip the CRLFs on the way in or the
   key carries a trailing `\r`:

   ```bash
   docker run --rm --env-file <(tr -d '\r' < worker.env) \
     ghcr.io/yougijain/hall-check/worker:latest python -m hallcheck.cli once
   ```

   Four lines with a count and a latency each, exit 0. Read it before going
   further.
4. Start the loop, same image and file:

   ```bash
   docker run -d --name hallcheck-worker --restart unless-stopped \
     --log-opt max-size=10m --log-opt max-file=3 \
     --env-file <(tr -d '\r' < worker.env) \
     ghcr.io/yougijain/hall-check/worker:latest
   ```

5. **On WSL, keep Ubuntu running.** WSL stops a distribution seconds after the
   last Windows process using it exits, taking Docker and the worker with it.
   A Task Scheduler task at logon running
   `conhost.exe --headless wsl.exe -d Ubuntu -u root -- sleep infinity`, with
   no execution time limit (the default kills tasks after 72 hours), holds it
   open. systemd starts Docker; Docker starts the container.

`--restart` reuses the image the container was created from, so a new publish
needs `docker pull`, `docker rm -f hallcheck-worker` and step 4 again.

A laptop collects nothing while asleep, and the task waits for a logon after a
reboot. Both leave gaps in `counts`; an always-on machine does not.

### Environment

Set the first two on the service. They have no defaults and the worker refuses
to start without them, naming both at once. The rest carry the defaults below
in `worker/hallcheck/config.py`, so a deployment that wants them does not need
to set them — `render.yaml` states them explicitly because a blueprint is a
record of intent, not because the worker requires it.

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Project URL |
| `SUPABASE_SERVICE_KEY` | **service_role** key |
| `HALLCHECK_MODEL` | `yolo11n.pt` |
| `HALLCHECK_CONF_THRESHOLD` | `0.35` |
| `HALLCHECK_IMGSZ` | `1280` |
| `HALLCHECK_INTERVAL_SECONDS` | `120` |
| `HALLCHECK_CAPTURE_TIMEOUT` | `30` |

`HALLCHECK_CAPTURE_TIMEOUT` must stay below `HALLCHECK_INTERVAL_SECONDS`, and
the worker refuses to start otherwise: a hall that times out would otherwise
consume the whole tick and starve every hall captured after it, which looks
like several dead cameras rather than one.

### Confirming it works

```bash
# On the host that will capture - not a laptop standing in for a server:
python -m hallcheck.cli once
```

prints one line per hall and exits non-zero only if *every* hall failed, so a
single dead camera is distinguishable from nothing working. Expect
`no stream URL configured` on a fresh install — see below.

Where it fails says what is wrong:

| Failure | Meaning |
|---|---|
| `could not resolve stream URL …: Sign in to confirm you're not a bot` | YouTube is blocking this host's IP. Change hosts; retrying does not help. |
| `could not resolve stream URL …: Requested format is not available` | The format selector matches nothing the stream offers. Fixed once in `capture.py`; check `FORMAT_SELECTOR` against `yt-dlp --list-formats`. |
| `inference failed: …` | The frame was captured; the model could not run. An image problem - the publish workflow's detection step should have caught it. |

Measured: 1-3 s per hall once a stream URL is resolved and cached, 376-447 MiB
resident with the model loaded.

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

Every hall is seeded with `stream_url = ''`, and the worker skips a hall until
one is configured. Nothing is captured until you set them:

```sql
update public.halls set stream_url = 'https://…' where hall_id = 'worcester_north';
```

or without touching the database, via `HALLCHECK_STREAM_<HALL_ID>` on the
worker — `HALLCHECK_STREAM_WORCESTER_NORTH` and so on.

The cameras UMass actually publishes are at
[umassdining.com/livestream](https://www.umassdining.com/livestream), and the
roster does not match the obvious guess:

| hall_id | Camera | Active |
|---|---|---|
| `worcester_north` | Worcester Commons, north | yes |
| `worcester_south` | Worcester Commons, south | yes |
| `hampshire_north` | Hampshire Commons, north | yes as seeded; deactivated in the live project 2026-10-23 when its stream died |
| `hampshire_south` | Hampshire Commons, south | yes |
| `berkshire` | Berkshire Commons | yes |
| `blue_wall` | Blue Wall entrance | **no** — retail, recorded not enabled |
| `franklin` | **None published** | **no** |

Both Worcester and Hampshire have two cameras, Franklin has none, and Blue Wall
is retail rather than a dining common — which is what `0005` and `0006` are
for. Blue Wall's row exists and its stream can be set, but it stays
`active = false` until someone deliberately enables it:

```sql
update public.halls set active = true where hall_id = 'blue_wall';
```

Harvest and Roots also stream and are not seeded at all.

If a camera streams through a watch page rather than a direct `.m3u8`, the
worker resolves it with yt-dlp automatically, so the watch URL is a fine value
for `stream_url`. Check what the page actually serves, and that the terms
permit reading it.

### ROI polygons

Every hall ships with `roi_version = 'v0-geometry-prior'` and the same
polygon, set by `0007`:

```
[[0.30, 0.35], [0.70, 0.35], [0.95, 1.00], [0.05, 1.00]]
```

**Nobody has looked at these frames.** It is not a queue region, it is a guess
about where a queue sits given how a dining hall camera is mounted — a
trapezoid because a camera angled down at a floor sees a fixed-width corridor
as narrow far away and wide up close, reaching the bottom edge because the
near field is where the counter is, and stopping at `y = 0.35` because above
that a person is small enough that the detector is unreliable on them and the
band is mostly people walking through to somewhere else.

It covers 0.42 of the frame, which is wide, deliberately. The two failure
modes are not symmetric: too wide inflates the count but keeps it monotone in
occupancy, while too tight returns zeros that read as a quiet hall.

The `v0-` prefix is load-bearing. It means *not drawn against a frame*, and a
count stamped `v0-geometry-prior` is not a measurement of a queue — it is the
worker proving it can see, on a region chosen sight-unseen. Every camera has
the same polygon for the same reason: numbers that differed per hall would
read as though someone had drawn them.

So the regions still must be redrawn against a real frame before any count
means anything. A polygon over the whole frame counts people eating at tables
and calls it a queue — a different quantity that happens to correlate, which is
exactly enough to be misleading.

Coordinates are normalised to `[0, 1]` against frame width and height, not
pixels, so a change in stream resolution does not silently move the region:

```sql
update public.halls
   set roi_polygon = '[[0.31,0.42],[0.68,0.40],[0.72,0.88],[0.27,0.90]]'::jsonb,
       roi_version = 'v1'
 where hall_id = 'worcester_north';
```

Bump `roi_version` whenever the shape changes, and `camera_epoch` whenever the
camera physically moves. Neither rewrites history — that is the point. Counts
either side of a change are measurements on different scales, and both columns
are stamped on every row so later queries can tell.

## Order of operations

1. Migrations applied, `access_model.sql` and `roi_sanity.sql` verified.
2. Stream URLs set for at least one hall.
3. Worker deployed; `hallcheck once` returns a count rather than a skip.
4. ROI polygons redrawn against real frames; `roi_version` bumped off the
   `v0-` prefix. Until this is done the counts are a demonstration, not data.

`db/tests/roi_sanity.sql` checks every polygon against the rules the worker
enforces at load, and runs in CI. Run it after any hand-written `UPDATE`.
5. Site deployed.
6. Leave it collecting. M2 labelling needs model counts to pair against, and
   the M4 forecast needs weeks of history before it can be trained at all.
