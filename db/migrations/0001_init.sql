-- 0001_init.sql
--
-- Core schema for Hall Check.
--
-- Three tables. `halls` is configuration, `counts` is the time series the
-- product is built on, and `labels` is the ground truth that says whether the
-- time series is any good.
--
-- Two columns carry interpretive weight and appear on every reading path:
--   * roi_version   - which queue polygon produced this count
--   * camera_epoch  - which physical camera placement produced it
-- A count is only comparable to another count that shares both.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- halls
-- ---------------------------------------------------------------------------

create table if not exists public.halls (
    hall_id      text primary key
                 check (hall_id ~ '^[a-z][a-z0-9_]{1,30}$'),
    name         text        not null,
    stream_url   text        not null,

    -- GeoJSON-style ring of [x, y] pairs in NORMALISED frame coordinates,
    -- each in [0, 1]. Normalised rather than pixels so a change in stream
    -- resolution does not silently move the queue region.
    roi_polygon  jsonb       not null,

    -- Bumped by hand whenever the camera is moved, re-aimed or refocused.
    -- Counts either side of a bump measure different things.
    camera_epoch integer     not null default 1 check (camera_epoch >= 1),

    -- Identifies the polygon itself, so redrawing an ROI does not rewrite the
    -- meaning of counts already collected under the old one.
    roi_version  text        not null default 'v1',

    -- Local service hours, used by the site to show "closed" instead of "0"
    -- and by the forecast to compute minutes-until-close.
    opens_at     time,
    closes_at    time,

    active       boolean     not null default true,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

comment on column public.halls.roi_polygon is
    'Normalised [[x,y],...] ring bounding the queue region. Values in [0,1].';
comment on column public.halls.camera_epoch is
    'Increment when the camera physically moves. Counts across epochs are not comparable.';

-- ---------------------------------------------------------------------------
-- counts
-- ---------------------------------------------------------------------------

create table if not exists public.counts (
    id            bigint generated always as identity primary key,
    hall_id       text        not null references public.halls (hall_id) on delete cascade,
    ts            timestamptz not null,

    -- People detected inside the ROI. Never negative; zero is a real reading
    -- (the hall is open and empty) and is distinct from a missing row (the
    -- capture failed), which is why failures insert nothing at all.
    count         integer     not null check (count >= 0),

    model_version   text      not null,
    conf_threshold  real      not null check (conf_threshold > 0 and conf_threshold < 1),
    roi_version     text      not null,
    camera_epoch    integer   not null default 1,

    -- Wall-clock cost of capture + inference. Cheap to store, and the first
    -- thing worth looking at when the scheduler starts falling behind.
    latency_ms    integer     check (latency_ms >= 0),

    created_at    timestamptz not null default now(),

    -- One reading per hall per instant. Makes the writer idempotent under
    -- retries: a replayed capture upserts rather than double-counting.
    unique (hall_id, ts)
);

-- The two queries the product actually makes: "latest for this hall" and
-- "this hall over this window", both newest-first.
create index if not exists counts_hall_ts_desc_idx
    on public.counts (hall_id, ts desc);

-- Drift and forecasting scan a whole window across halls.
create index if not exists counts_ts_idx
    on public.counts (ts desc);

-- ---------------------------------------------------------------------------
-- labels
-- ---------------------------------------------------------------------------

-- Postgres has no `create type if not exists`, and a migration that cannot be
-- replayed is a migration that breaks the next redeploy. CI applies this file
-- twice for exactly this reason.
do $$
begin
    if not exists (select 1 from pg_type where typname = 'meal_period') then
        create type public.meal_period as enum ('breakfast', 'lunch', 'dinner', 'closed');
    end if;
    if not exists (select 1 from pg_type where typname = 'lighting_condition') then
        create type public.lighting_condition as enum ('daylight', 'dark');
    end if;
end
$$;

create table if not exists public.labels (
    id           bigint generated always as identity primary key,
    hall_id      text        not null references public.halls (hall_id) on delete cascade,
    ts           timestamptz not null,

    -- Counted by a person watching the stream. Recorded BEFORE model_count is
    -- revealed; see docs/measurement-protocol.md.
    human_count  integer     not null check (human_count >= 0),

    -- The model's count for the same instant. Nullable so a label can be
    -- captured while the worker is down and paired up afterwards.
    model_count  integer     check (model_count >= 0),

    meal         public.meal_period        not null,
    lighting     public.lighting_condition not null,

    model_version  text,
    conf_threshold real,
    roi_version    text,
    camera_epoch   integer,

    notes        text,
    created_at   timestamptz not null default now(),

    unique (hall_id, ts)
);

-- Accuracy is reported per hall and per lighting condition, so those are the
-- groupings the evaluation query filters on.
create index if not exists labels_hall_lighting_idx
    on public.labels (hall_id, lighting);
create index if not exists labels_ts_idx
    on public.labels (ts desc);

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- ---------------------------------------------------------------------------

create or replace function public.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists halls_touch_updated_at on public.halls;
create trigger halls_touch_updated_at
    before update on public.halls
    for each row execute function public.touch_updated_at();
