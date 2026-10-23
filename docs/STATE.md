# Live state

What is deployed, what is not, and what the next person needs to know that the
rest of the documentation cannot tell them.

Everything else in `docs/` describes how the system is *designed*. This file
describes what is *true right now*, which is a different thing and goes stale
faster. **Last verified: 2026-10-23.**

Check it against reality before trusting it:

```bash
# worker running? counts climbing?
python -m hallcheck.cli health

# or straight at the database
select count(*), max(ts) from public.counts;
```

---

## The one-line summary

Every component is built, tested and deployed except the worker, which has
never run. There are zero rows in `counts`. Nothing in this project has ever
measured anything.

---

## What is live

| Piece | Where | State |
|---|---|---|
| Database | Supabase `buptvnkguezcjgyqtiqf`, us-east-2, PG 17.6 | Migrations 0001-0007 applied. Access model verified as `anon`. |
| Site | https://hall-check.vercel.app | Deployed, env vars set, renders "No readings yet" because there are no readings. |
| Worker image | `ghcr.io/yougijain/hall-check/worker:latest` | Published, public, smoke tested. 748 MiB compressed. |
| Worker | — | **Never deployed. This is the blocker.** |

Supabase URL: `https://buptvnkguezcjgyqtiqf.supabase.co`

The `anon` key is public by construction and lives in Vercel's environment
variables. The `service_role` key is in nobody's environment yet, because the
worker has nowhere to run; get it from Supabase → Settings → API when you
deploy, and put it only in the worker's host.

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
demonstrate the pipeline works; they are not measurements of a queue.

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
project. A running worker writes every two minutes and prevents it. If you stop
the worker for a term break, expect the pause and restore it before blaming
anything else.

**A residential IP does not test a datacenter IP.** `yt-dlp -g` from a laptop
proves nothing about whether YouTube will serve a Fly machine; that is exactly
the distinction it blocks on. The only real test is `hallcheck once` from the
host that will do the capturing. If all four halls fail at `resolve_stream_url`
there, the answer is a different host or a proxy, not a retry.

**The worker ignores opening hours.** `pipeline.run_tick` captures every active
hall on every tick regardless of the clock. `opens_at` and `closes_at` are
presentation - the site uses them to say "Closed" instead of a number. So a
healthy hall produces readings at 3am, and six hours of silence means broken
rather than shut. `hallcheck health` relies on this.

**Memory is unverified.** `fly.toml` asks for 1 GB plus 512 MB swap. That was
sized from image size, not from a measurement of resident footprint - the image
is 748 MiB compressed, 2.3 GB on disk, and nobody has watched it run. If it
OOM-loops, the fix is ONNX Runtime instead of torch (a fraction of the
footprint for a model this small), not a bigger instance.

**Vercel previews every PR.** Linking the project means `vercel[bot]` comments
a preview URL on every pull request. Harmless, occasionally noisy.

## What is measured

Nothing.

| Report | State |
|---|---|
| Accuracy (MAE, bias) | No labels. `hallcheck evaluate` exits non-zero until coverage is met: 10+ per meal, 10+ per lighting, 10+ per hall, 150+ total - marginals, not the full cross. |
| Forecast | No history. Needs about two weeks before a time split means anything. |
| Drift | No baseline. Needs about 15 days. The incident log in the runbook is empty because the check has never run, which is no evidence the thresholds are right. |

## The order that matters

1. **Deploy the worker.** Nothing below is possible until `counts` is filling.
2. **Watch 24 hours.** Memory, gaps, `hallcheck health`.
3. **Draw real ROIs, bump to `v1`.** Before any labelling.
4. **Schedule `hallcheck health`.** An alarm nobody runs catches nothing.
5. **Collect labels**, then publish accuracy.

Steps 1, 2 and 4 are hours. Step 5 is weeks of elapsed time, and the forecast
and drift evaluations are gated on history that only accrues while the worker
runs. Every day it is not running pushes those out day for day, and that clock
cannot be made up later.
