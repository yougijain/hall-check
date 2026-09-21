-- 0002_rls_and_read_views.sql
--
-- The site talks to Postgres directly with Supabase's anon key, which ships in
-- the browser bundle. Treat it as public. Everything the anon role can reach
-- has to be something we are content to publish, and every write has to be
-- closed off.
--
-- Writes belong to the worker, which holds the service role key and bypasses
-- RLS entirely. No policy below grants insert, update or delete to anyone.

alter table public.halls  enable row level security;
alter table public.counts enable row level security;
alter table public.labels enable row level security;

-- ---------------------------------------------------------------------------
-- Table privileges
-- ---------------------------------------------------------------------------
-- RLS decides which ROWS a role may see. It does not decide whether the role
-- may touch the table at all - that is a grant, and without one the policies
-- below never get evaluated.
--
-- A Supabase project bootstraps with broad grants to anon and authenticated
-- already in place, so a schema that omits this section appears to work while
-- depending on a privilege it never asked for. Stating it here means the
-- access model travels with the migrations and can be tested against a stock
-- Postgres, which is what CI does.

grant usage on schema public to anon, authenticated;

revoke all on public.halls  from anon, authenticated;
revoke all on public.counts from anon, authenticated;
revoke all on public.labels from anon, authenticated;

-- Counts in full: an integer about a room, plus the provenance that lets
-- anyone check our accuracy claims against our own published history.
grant select on public.counts to anon, authenticated;

-- Halls by column, not by table. `stream_url` and `roi_polygon` are
-- deliberately excluded: the streams are already public, but re-serving their
-- URLs from our origin points other people's traffic at the university's
-- endpoint in our name, and the polygon is operational detail the site has no
-- use for. A column grant enforces that; a view over a fully granted table
-- would only hide it from people who do not look.
grant select (hall_id, name, camera_epoch, roi_version, opens_at, closes_at, active)
    on public.halls to anon, authenticated;

-- `labels` gets nothing. No grant, no policy, no access.

-- ---------------------------------------------------------------------------
-- halls: public, minus the stream URL
-- ---------------------------------------------------------------------------
-- The streams are already public, but republishing the URLs from our own
-- origin invites traffic onto the university's endpoint in our name. The site
-- does not need them, so the anon role reads a view that omits them.

drop policy if exists halls_read_active on public.halls;
create policy halls_read_active
    on public.halls for select
    to anon, authenticated
    using (active);

create or replace view public.halls_public
with (security_invoker = true) as
    select hall_id, name, camera_epoch, roi_version, opens_at, closes_at
    from public.halls
    where active;

comment on view public.halls_public is
    'Hall list for the site. Deliberately omits stream_url and roi_polygon.';

-- ---------------------------------------------------------------------------
-- counts: public in full
-- ---------------------------------------------------------------------------
-- A count is an integer about a room. There is nothing here to withhold, and
-- publishing the model version and thresholds alongside it is what lets anyone
-- check our accuracy claims against our own history.

drop policy if exists counts_read_all on public.counts;
create policy counts_read_all
    on public.counts for select
    to anon, authenticated
    using (true);

-- ---------------------------------------------------------------------------
-- labels: private
-- ---------------------------------------------------------------------------
-- Free-text notes are written for whoever is doing the labelling, in the
-- shorthand of someone talking to themselves. They are not written to be read
-- by strangers, so no policy exists and the anon role sees an empty table.
-- Published accuracy numbers come from the evaluation report, not from here.

-- ---------------------------------------------------------------------------
-- Read surfaces for the site
-- ---------------------------------------------------------------------------

-- Latest reading per hall. distinct on is the cheap form of this in Postgres
-- and rides the (hall_id, ts desc) index.
create or replace view public.hall_latest
with (security_invoker = true) as
    select distinct on (c.hall_id)
        c.hall_id,
        h.name,
        c.ts,
        c.count,
        c.model_version,
        c.roi_version,
        c.camera_epoch,
        h.opens_at,
        h.closes_at
    from public.counts c
    join public.halls h using (hall_id)
    where h.active
    order by c.hall_id, c.ts desc;

comment on view public.hall_latest is
    'Most recent count per active hall. The site should treat a stale ts as unknown, not as current.';

-- Views are separate objects and need their own grants. Both are declared
-- security_invoker, so the querying role's own privileges and the policies
-- above still apply through them - the view is a convenience, not a way around
-- the access model.
grant select on public.halls_public to anon, authenticated;
grant select on public.hall_latest to anon, authenticated;
