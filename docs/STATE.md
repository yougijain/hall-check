# Live state

What is deployed, what is not, and what the next person needs to know that the
rest of the documentation cannot tell them.

Everything else in `docs/` describes how the system is *designed*. This file
describes what is *true right now*, which is a different thing and goes stale
faster. **Last verified: 2026-10-26.**

Check it against reality before trusting it:

```bash
# worker running? counts climbing?
python -m hallcheck.cli health

# or straight at the database
select count(*), max(ts) from public.counts;

# or on the host itself (see "Where the worker runs")
wsl -d Ubuntu -u root -- docker ps --filter name=hallcheck-worker
```

---

## The one-line summary

The worker has been collecting since **2026-10-26 22:36 UTC**, on a laptop
rather than a server, because YouTube refuses to serve the camera streams to
datacenter IPs. Every count so far is under the guessed ROI, so `counts` proves
the pipeline works end to end; it does not yet measure a queue.

---

## What is live

| Piece | Where | State |
|---|---|---|
| Database | Supabase `buptvnkguezcjgyqtiqf`, us-east-2, PG 17.6 | Migrations 0001-0007 applied. Access model verified as `anon`. Rows arriving every two minutes. |
| Site | https://hall-check.vercel.app | Deployed, env vars set. Reads whatever `counts` holds. |
| Worker image | `ghcr.io/yougijain/hall-check/worker:latest` | `sha256:104902d0…`, revision `45b4d1e`, published 2026-10-26. The first image that can actually count: see "What it took". |
| Worker | A Windows 11 laptop, Docker Engine inside WSL Ubuntu | **Running.** Capture loop every 120 s, four halls. |
| Fly app `hallcheck-worker` | Fly.io, `iad`, personal org | Exists, machine **stopped**. Blocked by YouTube; see "Why not Fly". Holds a copy of the service key as a secret. |

Supabase URL: `https://buptvnkguezcjgyqtiqf.supabase.co`

The `anon` key is public by construction and lives in Vercel's environment
variables. The `service_role` key lives in two places: the laptop (below) and
the Fly app's secrets. Destroying the Fly app removes the second.

## Where the worker runs

On the owner's laptop, as the `hallcheck-worker` container under Docker Engine
inside WSL 2 Ubuntu 26.04. Not Docker Desktop: see "Docker Desktop does not
start" below.

The chain that keeps it up, outermost first:

1. **Task Scheduler**, task `\Hall Check worker keep-alive`, runs at the
   owner's logon: `conhost.exe --headless wsl.exe -d Ubuntu -u root -- sleep infinity`.
   No time limit, keeps running on battery, one instance only.
2. That `sleep` exists only to hold Ubuntu open. WSL shuts a distribution down
   seconds after the last Windows-side process using it exits, and the worker
   goes with it.
3. **systemd** in Ubuntu starts `docker` (enabled).
4. **Docker** starts the container, which has `--restart unless-stopped` and
   log rotation at 3 × 10 MB.

Verified on 2026-10-26 by stopping Ubuntu outright and starting it only through
the task: the container was back in 5 seconds and the next tick landed on
schedule. That is the path a reboot takes.

Secrets: `C:\Users\<owner>\.hallcheck\worker.env`, outside the repo, holding
`SUPABASE_URL` and `SUPABASE_SERVICE_KEY`. Docker read it once when the
container was created and keeps its own copy inside Ubuntu, readable by root
only. Notepad saves it with CRLF line endings; it is passed through
`tr -d '\r'` on the way in, or the key would carry a trailing `\r` and every
write would be refused.

Operating it, from PowerShell or Command Prompt:

```bash
# is it up, and what is it doing
wsl -d Ubuntu -u root -- docker ps --filter name=hallcheck-worker
wsl -d Ubuntu -u root -- docker logs --tail 20 hallcheck-worker

# stop collecting (stays stopped across reboots until started again)
wsl -d Ubuntu -u root -- docker stop hallcheck-worker
wsl -d Ubuntu -u root -- docker start hallcheck-worker

# stop it coming back after logon at all
schtasks /delete /tn "Hall Check worker keep-alive" /f
```

**Updating to a new image does not happen by itself.** `restart` reuses the
image the container was created from. After a publish: `docker pull` the image,
`docker rm -f hallcheck-worker`, and create it again with the same `docker run`
flags (`--name hallcheck-worker --restart unless-stopped --log-opt
max-size=10m --log-opt max-file=3 --env-file <(tr -d '\r' < worker.env)`).

### What interrupts it

**Sleep.** A sleeping laptop collects nothing, and the worker cannot catch up a
missed slot. Lid closed, low battery, Windows deciding to sleep: each is a gap
in `counts`. This already happened within the first half hour: Windows entered
Modern Standby from 23:01:22 to 23:03:50 UTC on 2026-10-26, cut networking
while in it ("Connectivity state in standby: Disconnected, Reason: Policy
Setting"), and the 23:02 slot is empty. The worker logged nothing about it; the
tick simply never fired. Set the laptop never to sleep while plugged in if the
history matters more than the battery, and look for gaps with:

```sql
select g from generate_series((select min(ts) from public.counts),
                              (select max(ts) from public.counts),
                              interval '2 minutes') g
 where g not in (select ts from public.counts);
```

**Not logging in.** The task runs at logon, not at boot. After a restart the
worker is down until the owner signs in.

**Restart inside a slot overwrites it.** The loop captures immediately on
start and stamps the reading with the current two-minute slot, and writes
upsert on `(hall_id, ts)`. Restart at 22:55 and the 22:54 slot is captured
again and replaced: on 2026-10-26 Berkshire's 22:54 reading went from 8 to 4
this way. Nothing is lost or duplicated, but one reading is swapped for a
slightly later one. It matters only if restarts become frequent.

**The network is a campus network, not a home one.** Egress was
`128.119.202.94` on one run and `128.119.202.113` three days later - UMass
Amherst's range. YouTube serves it today. It is also subject to campus network
policy, and it changes when the laptop moves. If YouTube starts asking this
host to sign in too, the same error as Fly's will show up in the logs.

## Why not Fly

`fly.toml` is still correct and the app exists; YouTube is the problem.

On 2026-10-23, deployed from the then-current image, every hall failed at
`resolve_stream_url`. Two separate failures were stacked:

1. **"Requested format is not available."** The worker asked yt-dlp for
   `best`, the best single stream with both video and audio. YouTube's live
   cameras offer none: every rendition is video-only or audio-only. A real bug,
   on any host. Fixed in #16.
2. **"Sign in to confirm you're not a bot."** With the format fixed, all four
   halls failed here instead. That is the datacenter-IP block.

The sequence is the instructive part. One diagnostic `yt-dlp --list-formats`
from a fresh Fly machine between the two runs *succeeded*, listed eight
formats, and was taken as evidence that Fly was not blocked. About ten
minutes later the redeployed worker machine was. One success from one IP is not a clean
bill of health; treat any datacenter host as blocked until a `hallcheck once`
from that exact host has passed more than once.

The Fly machine is stopped, not destroyed: it costs only rootfs storage. Its
secrets include the service key, which is a reason to `fly apps destroy
hallcheck-worker` if Fly will not be used again.

Also learned there: **swap was never on.** `fly.toml` sets `swap_size_mb = 512`
under `[[vm]]`; the running machine reported `SwapTotal: 0`. The config
validates, so nothing flags it. The key probably belongs at the top level.
Moot while memory sits where it does, below.

## What it took to get one count

Three things were broken, each hidden behind the one before it. Worth knowing
because every check that existed passed on all three.

| Symptom | Cause | Fix |
|---|---|---|
| `Requested format is not available` | `format: "best"` matches nothing on YouTube live | #16: `bv*[height<=?720]/bv*`, tested against real yt-dlp |
| `Sign in to confirm you're not a bot` | Fly's datacenter IP | Moved to a residential-type network |
| `operator torchvision::nms does not exist` | torch from the CPU index, torchvision from PyPI; the pair does not load | #17: both from the CPU index, and the publish workflow now runs a real detection |

The third had passed the image's smoke tests since the image existed: they
loaded the model but never ran it. It now runs one detection on a frame with
people in it. A blank frame would not have caught it, because non-max
suppression only runs on candidate boxes.

### Docker Desktop does not start on this laptop

Every socket file Docker Desktop creates under `%LOCALAPPDATA%` becomes
undeletable once its process exits ("error 1920: the file cannot be accessed
by the system"), and Desktop refuses to start while one exists. Moving the
folders aside gets one start further, which then leaves new undeletable files
for the next. Smart App Control is on in enforce mode and is the likely cause
- it also blocked a scikit-learn DLL in a local virtualenv the same week - but
that is not proven. It is why the worker runs on Docker Engine inside WSL,
which does not involve any of those files. Two dead sockets are parked in
`%LOCALAPPDATA%\Docker\run.stale-20261023`, harmless and, for now,
undeletable.

## The halls, and why four

| Hall | Active | Video id | Note |
|---|---|---|---|
| `berkshire` | yes | `AoceCqa6MWw` | |
| `hampshire_south` | yes | `RprORF_ggOA` | |
| `worcester_north` | yes | `7wHgOpwHz8k` | |
| `worcester_south` | yes | `89KPOnjHEC4` | |
| `hampshire_north` | **no** | `TWC87AgKJHA` | Stream stopped playing, found 2026-10-23. Deactivated rather than deleted. |
| `blue_wall` | no | `9qoJFLMyfuc` | Retail, not a dining common. Recorded, never enabled. |
| `franklin` | no | — | Publishes no camera at all. |

All four live halls open 07:00 and close 21:00, `camera_epoch = 1`.

**On `hampshire_north`:** the ids above were collected on 2026-09-23. One of
five was dead a month later. That rate is the reason `hallcheck health` exists,
and the reason it needs to run on a schedule rather than when someone
remembers. To bring the hall back: find the current stream on
umassdining.com/livestream, `update public.halls set stream_url = ...,
active = true where hall_id = 'hampshire_north'`.

## The ROI polygons are a guess

Every hall carries this, stamped `roi_version = 'v0-geometry-prior'`:

```
[[0.30, 0.35], [0.70, 0.35], [0.95, 1.00], [0.05, 1.00]]
```

**Nobody has ever seen these frames.** It is a trapezoid derived from how a
dining hall camera is typically mounted - narrower at the top because a camera
angled down sees a fixed-width corridor as narrow far away, reaching the bottom
edge because the near field is where the counter is, stopping at `y = 0.35`
because above that the detector is unreliable and the band is mostly people
walking through. It covers 0.42 of the frame, deliberately wide: an ROI that is
too large inflates the count but keeps it monotone in occupancy, while one that
is too tight returns zeros that read as a quiet hall.

The `v0-` prefix means *not drawn against a frame*. Counts produced under it
demonstrate the pipeline works; they are not measurements of a queue. Every
row in `counts` as of this writing carries it.

Every hall has the identical polygon on purpose. There is no evidence on which
to make them differ, and numbers that varied per hall would read as though
someone had drawn them.

**Draw the real regions before collecting labels.** Labels carry a
`roi_version`. Collect against the prior, then redraw, and every label is void
because it measured a different region. This is the sequencing mistake that
costs a week.

## Known gotchas

**The database auto-pauses.** Free-tier Supabase suspends a project after about
a week without traffic. This happened - the project sat paused from roughly
early October until 2026-10-23, and every query in that window failed with a
connection timeout that looks like a network fault rather than a suspended
project. A running worker writes every two minutes and prevents it. If the
worker stops for longer than a few days - term break, a laptop left asleep -
expect the pause and restore it before blaming anything else.

**A residential IP does not test a datacenter IP.** `yt-dlp -g` from a laptop
proves nothing about whether YouTube will serve a datacenter machine; that is
exactly the distinction it blocks on. The only real test is `hallcheck once`
from the host that will do the capturing - and, per "Why not Fly", more than
once.

**The worker ignores opening hours.** `pipeline.run_tick` captures every active
hall on every tick regardless of the clock. `opens_at` and `closes_at` are
presentation - the site uses them to say "Closed" instead of a number. So a
healthy hall produces readings at 3am, and six hours of silence means broken
rather than shut. `hallcheck health` relies on this.

**Memory, measured.** 376-447 MiB resident across two readings on 2026-10-26,
with the model loaded and after real inferences, out of 7.5 GiB visible to WSL. The earlier estimate of
~700 MB was conservative. The 1 GB Fly sizing would have fit; the ONNX Runtime
fallback is not needed.

**Vercel previews every PR.** Linking the project means `vercel[bot]` comments
a preview URL on every pull request. Harmless, occasionally noisy.

## What is measured

Counts, from 2026-10-26 22:36 UTC, every two minutes, four halls, all under
`v0-geometry-prior`. Nothing derived from them yet.

| Report | State |
|---|---|
| Accuracy (MAE, bias) | No labels. `hallcheck evaluate` exits non-zero until coverage is met: 10+ per meal, 10+ per lighting, 10+ per hall, 150+ total - marginals, not the full cross. Labels wait on real ROIs. |
| Forecast | History started 2026-10-26. About two weeks before a time split means anything: around 2026-11-09, less whatever the laptop sleeps through. |
| Drift | No baseline. Needs about 15 days: around 2026-11-10 at the earliest. The incident log in the runbook is empty because the check has never run, which is no evidence the thresholds are right. |

## The order that matters

1. ~~**Deploy the worker.**~~ Done 2026-10-26, on the laptop.
2. **Watch 24 hours.** Gaps (sleep), restarts, `hallcheck health`. In progress.
3. **Draw real ROIs, bump to `v1`.** Before any labelling.
4. **Schedule `hallcheck health`.** An alarm nobody runs catches nothing.
5. **Collect labels**, then publish accuracy.

Also open, not on the critical path: decide whether the laptop is the host or
a stopgap (an always-on machine at home or on campus removes the sleep and
logon gaps), and destroy the Fly app if it is not coming back.

Steps 2 and 4 are hours. Step 5 is weeks of elapsed time, and the forecast and
drift evaluations are gated on history that only accrues while the worker
runs. Every day it is not running pushes those out day for day, and that clock
cannot be made up later.
