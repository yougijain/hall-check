# Live state

What is deployed, what is not, and what the next person needs to know that the
rest of the documentation cannot tell them.

Everything else in `docs/` describes how the system is *designed*. This file
describes what is *true right now*, which is a different thing and goes stale
faster. **Last verified: 2026-10-28.**

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
datacenter IPs. Since **2026-10-28 01:14 UTC** three of the four cameras count
inside regions drawn against real frames (`v1`), with the detector at 1280 px.
Hampshire South's image is too hazy to measure and stays on the guess. Nothing
is labelled yet, so how wrong the v1 counts are is not known.

---

## What is live

| Piece | Where | State |
|---|---|---|
| Database | Supabase `buptvnkguezcjgyqtiqf`, us-east-2, PG 17.6 | Migrations 0001-0007 applied. Access model verified as `anon`. Rows arriving every two minutes. |
| Site | https://hall-check.vercel.app | Deployed, env vars set. Reads whatever `counts` holds. |
| Worker image | `ghcr.io/yougijain/hall-check/worker:latest` | `sha256:d5a08b2a…`, revision `e535c06`, published 2026-10-27. Inference at 1280 px. |
| Worker | A Windows 11 laptop, Docker Engine inside WSL Ubuntu | **Running** that image since 2026-10-28 01:13 UTC. Capture loop every 120 s, four halls. Collects only while the laptop is awake: see "What interrupts it". |
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
tick simply never fired.

It is the dominant failure, not an edge case. By 03:26 UTC on 2026-10-28, 416
of the 866 two-minute slots since the worker started were filled - under half.
The big holes are the laptop asleep: 00:30-02:50 and 04:16-16:06 UTC on
2026-10-27, the second of which also made a scheduled noon frame capture miss
by six minutes. This laptop's power plan sleeps after 3 minutes idle on
battery and never on mains, so plugged in on a desk is the only state in which
it collects reliably. Look for gaps with:

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
| `hampshire_south` | yes | `RprORF_ggOA` | Image hazy enough that detection barely works; still on the v0 region. See below. |
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

## The ROI polygons

Three cameras carry `roi_version = 'v1'`, drawn on 2026-10-27 against 24 frames
of the dinner rush - six rounds, six minutes apart, 17:30-18:01 local - by
plotting every foot-point the 1280 px detector found and drawing around where
people stood still. Coordinates are fractions of the frame; a person is inside
if the bottom-centre of their box, their feet, is.

| Hall | Version | Polygon | Frame | What it covers |
|---|---|---|---|---|
| `berkshire` | v1 | `[[0.79,0.02],[1.00,0.02],[1.00,0.16],[0.905,0.27],[0.855,0.40],[0.82,0.30]]` | 5.0% | The lane behind the stanchion belt on the right, up toward the serving shelves. The first single frame suggested the open floor on the other side of the belt; over thirty minutes that turned out to be a walkway. |
| `worcester_north` | v1 | `[[0.74,0.26],[0.83,0.26],[0.83,0.40],[0.93,0.44],[0.93,0.52],[0.79,0.52]]` | 2.7% | The floor in front of the bright serving counter on the right, short of the tables. People there are only detected at 1280 px. |
| `worcester_south` | v1 | `[[0.12,0.50],[0.50,0.33],[0.56,0.34],[0.56,0.43],[0.42,0.50],[0.17,0.56]]` | 4.6% | The walkway along the GREENS self-serve counter. There is no managed line here; this counts people standing at the counter. Stops above the first tables. |
| `hampshire_south` | v0-geometry-prior | `[[0.30,0.35],[0.70,0.35],[0.95,1.00],[0.05,1.00]]` | 42% | Unchanged. The image is hazy - a dirty or fogged cover - and the detector finds 1-2 people in a room of dozens at either input size. No polygon fixes that; the camera needs attention, or the hall deactivating. |

**What v0 was.** A trapezoid over the bottom of the frame, chosen sight unseen
on the assumption that the counter is in the near field. On all four cameras
the near field is dining tables, so v0 mostly counted people eating: over the
same dinner frames, Worcester South had 9-14 people per frame inside v0 and
0-4 inside v1. The v0 counts are pipeline output, not queue measurements.

**Known weak spots in v1.**
- Worcester South's lower edge sits at the counter base so the nearest diners
  stay out. Someone standing back from the counter is missed, and staff behind
  it whose feet are hidden can be counted.
- Berkshire's queue side of the belt is read from where people stood still
  across six frames, not from knowing the room.
- All of it rests on one dinner. If lunch lines form elsewhere, that is a v2.

**Rollback.** Set the three rows back to the v0 polygon above with
`roi_version = 'v0-geometry-prior'`, and recreate the worker on image
`sha256:104902d0…`. Counts already written keep the stamps they were written
with.

Every frame used to draw these was deleted after review; none is in the repo.

**Labels can now be collected, against v1.** A label carries the
`roi_version` it was taken under, so redrawing a region later voids the labels
for that hall - which is the reason this came first.

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

**Memory, measured.** 376-447 MiB resident at 640 px on 2026-10-26, and
473-497 MiB at 1280 px on 2026-10-28, with the model loaded and after real inferences,
out of 7.5 GiB visible to WSL. The earlier estimate of ~700 MB was
conservative. 1 GB is enough; the ONNX Runtime fallback is not needed.

**The detector still misses most people.** 1280 px finds roughly three times
what 640 did, and that is still a fraction of the people visible in a busy
frame. How large a fraction, and whether it is stable enough to be useful, is
exactly what the labels will measure.

**Drift and forecast do not fully separate series.** `drift.check_hall` keeps
only the latest `camera_epoch` and ignores `roi_version` and `model_version`,
so about a day after 2026-10-28 01:14 UTC, the last 24 hours (v1, 1280 px) will
be compared against a baseline that is v0 at 640 px, and every switched camera
will read as drifting. `features.Reading.scale` is `(camera_epoch,
roi_version)` without `model_version`, so Hampshire South's 640 and 1280 rows -
both v0 - look like one series to the forecast. Neither check is scheduled yet,
so nothing is wrong today. Fix both before scheduling drift. Bumping
`camera_epoch` instead would be wrong: it means the camera physically moved.

**Vercel previews every PR.** Linking the project means `vercel[bot]` comments
a preview URL on every pull request. Harmless, occasionally noisy.

## What is measured

Counts, every two minutes, four halls, in three series that must not be mixed:

| Slots (UTC) | `model_version` | `roi_version` | Halls |
|---|---|---|---|
| 2026-10-26 22:36 - 2026-10-28 01:12 | `yolo11n.pt@conf0.35` (640 px) | `v0-geometry-prior` | all four |
| 2026-10-28 01:14 onward | `yolo11n.pt@conf0.35@imgsz1280` | `v1` | berkshire, worcester_north, worcester_south |
| 2026-10-28 01:14 onward | `yolo11n.pt@conf0.35@imgsz1280` | `v0-geometry-prior` | hampshire_south |

The switch: the old worker was stopped at 01:13:20 so no tick could count the
new regions with the old detector, the three polygons went in in one
transaction, `db/tests/roi_sanity.sql` passed against the live database, and
the worker was recreated on the 1280 px image at 01:13:57. The last old slot is
01:12 and the first new one 01:14; none was lost or overwritten.

Why 1280: the streams are 1280×720 and the detector had been shrinking them to
640, where the people at the far counters are too small to find. On one frame
per camera, 640 found 7, 5, 0 and 4 people where 1280 found 21, 2, 6 and 15.

| Report | State |
|---|---|
| Accuracy (MAE, bias) | No labels. `hallcheck evaluate` exits non-zero until coverage is met: 10+ per meal, 10+ per lighting, 10+ per hall, 150+ total - marginals, not the full cross. Labels can start now, against v1. |
| Forecast | The usable series starts at the switch, 2026-10-28. About two weeks before a time split means anything: around 2026-11-11, later by whatever the laptop sleeps through. |
| Drift | No baseline. Needs about 15 days of the new series, so around 2026-11-12 at the earliest - and the series fix under "Known gotchas" first. The incident log in the runbook is empty because the check has never run, which is no evidence the thresholds are right. |

## The order that matters

1. ~~**Deploy the worker.**~~ Done 2026-10-26, on the laptop.
2. ~~**Watch 24 hours.**~~ Done; it showed the laptop sleeps more than it
   collects. See "What interrupts it".
3. ~~**Draw real ROIs, bump to `v1`.**~~ Done 2026-10-28 for three cameras,
   with the detector moved to 1280 px at the same moment.
4. **Schedule `hallcheck health`.** An alarm nobody runs catches nothing.
5. **Collect labels**, then publish accuracy.

Also open:
- **The host.** At under half coverage the laptop is a stopgap. An always-on
  machine at home or on campus removes the sleep and logon gaps; until then,
  plugged in and awake is the only state in which it collects.
- **Hampshire South.** Clean or fix the camera, or deactivate the hall rather
  than publish a number that is mostly haze.
- **Drift and forecast series.** Separate by `roi_version` and
  `model_version` before scheduling drift.
- **The Fly app.** Destroy it if it is not coming back; it holds a copy of the
  service key.

Steps 2 and 4 are hours. Step 5 is weeks of elapsed time, and the forecast and
drift evaluations are gated on history that only accrues while the worker
runs. Every day it is not running pushes those out day for day, and that clock
cannot be made up later.
