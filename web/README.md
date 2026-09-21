# Hall Check web

The public site. Next.js on Vercel, reading Supabase directly with the anon
key.

```bash
cd web
npm install
cp .env.example .env.local    # NEXT_PUBLIC_SUPABASE_URL + ANON key
npm run dev
```

Without those variables the app still builds and runs; it renders a setup
notice instead of hall data, which keeps CI from needing database credentials.

## Deploying

Vercel project with **root directory set to `web/`**. Same repository as the
worker, separate deployment target — the worker runs on Render from
`worker/Dockerfile`, and the only thing the two share is the schema.

Two environment variables, both public by design:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | **anon** key |

The service role key must never be set here. It bypasses row level security,
and anything prefixed `NEXT_PUBLIC_` is compiled into the browser bundle.

## Two rules the UI is built around

**Never show a number that has stopped being true.** The worker dies at 12:05
with a count of 3, a student opens the page at 12:40, sees "3 people", and
walks into a queue out the door. Past fifteen minutes the count is withheld and
the page says it does not know, with the age of the last reading so a dead
camera does not read as a broken site. `lib/freshness.ts`.

**A closed hall says "Closed", not "0".** Zero is technically true and
completely useless — it reads as "no queue, go now". `lib/hours.ts`, in
`America/New_York` rather than the server's timezone, so a student checking
over break sees Amherst's hours.

## Structure

| Path | What it is |
|---|---|
| `app/page.tsx` | All halls, current count each |
| `app/[hallId]/page.tsx` | One hall, today's curve, provenance |
| `app/privacy/page.tsx` | The privacy rule in full |
| `components/` | Card, chart, privacy banner |
| `lib/freshness.ts` | When a count stops being worth showing |
| `lib/hours.ts` | Service hours and campus-local time |
| `lib/chart.ts` | Chart geometry, as pure functions |
| `lib/data.ts` | Every read the site makes |

Pages are statically generated and revalidated every 60 seconds. Captures land
every two minutes, so a cached page is at most half an interval behind and the
database is not queried once per visitor.

## The chart

Hand-rolled SVG, no charting dependency. The geometry is pure functions in
`lib/chart.ts` with unit tests, and the component only renders what they
return.

It breaks the line wherever the worker missed several captures in a row rather
than interpolating across the hole. An outage drawn as a smooth curve is
indistinguishable from measured data, which is the one thing a chart of
measurements must not do — so a gap looks like a gap, and the caption says so.

## Tests

```bash
npm test         # 80 unit tests
npm run lint
npm run typecheck
npm run build
```

`lib/` tests cover the logic that decides what the reader sees: staleness
thresholds, service hours across a daylight saving transition, and chart
geometry including gap splitting and axis rounding.

`components/HallCard.test.tsx` renders the card to static markup and asserts
the four states it can be in — fresh, slightly behind, too old to show, and
closed. That is where the "0 people at a closed hall" regression would surface.

No browser and no database: `renderToStaticMarkup` on Node, and the data layer
is not involved.
