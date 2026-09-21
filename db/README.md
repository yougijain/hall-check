# Database

Supabase Postgres. Migrations are plain SQL, applied in filename order, and
never edited once merged — a change is a new file.

## Applying

```bash
# Supabase CLI against a linked project
supabase db push

# or directly
psql "$SUPABASE_DB_URL" -f db/migrations/0001_init.sql
```

## Files

| File | Contents |
|---|---|
| `0001_init.sql` | `halls`, `counts`, `labels`, indexes, `updated_at` trigger |
| `0002_rls_and_read_views.sql` | Row level security, `halls_public` and `hall_latest` views |
| `0003_seed_halls.sql` | The four dining commons, with placeholder ROIs |
| `0004_harden_function_search_path.sql` | Pins `search_path` on the `updated_at` trigger function |
| `0005_reconcile_halls_with_live_streams.sql` | Splits Worcester into its two cameras; deactivates Franklin, which has none |

## Access model

Two keys, two very different privileges.

The **anon key** ships inside the web bundle and is public by construction. It
gets `select` on `halls` and `counts` and nothing else — no insert, no update,
no delete, and no access to `labels`. Every policy in `0002` is a `for select`
policy, so there is no write path to close.

The **service role key** belongs to the worker, lives only in the worker's
environment, and bypasses RLS. It is the only thing that writes.

If the anon key leaks, the damage is that someone can read counts that are
already published on the site. That is the intended blast radius.

## Two columns to respect

`roi_version` and `camera_epoch` are stamped on every count. A count is
comparable to another count only when both match. Any query that aggregates
across a change in either — a forecast feature, a drift baseline, a weekly
average — is comparing measurements taken on different scales and will produce
a confident wrong answer.

When a camera moves: bump `halls.camera_epoch`. When an ROI is redrawn: bump
`halls.roi_version`. Neither operation touches history, which is the point.
