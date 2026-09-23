-- roi_sanity.sql
--
-- Every polygon in public.halls, checked against the rules worker/hallcheck/
-- roi.py enforces at load time.
--
-- The worker validates its own ROI, but it does so per hall, at startup, in
-- production - so a bad polygon is a hall that stops reporting while the
-- others carry on, which is the sort of thing nobody notices for a week. The
-- same rules asserted here fail a build instead.
--
-- Inactive halls are included on purpose. A row is seeded inactive because it
-- is not wanted yet, not because its contents may be wrong, and the moment
-- someone flips `active` the polygon is live.

\set ON_ERROR_STOP on

-- Shoelace, matching Roi.area. Vertex order comes from WITH ORDINALITY rather
-- than row_number() over an unordered window, which is not guaranteed to
-- follow the array.
create or replace function pg_temp.roi_area(polygon jsonb) returns double precision
language sql immutable as $$
    with v as (
        select (e.value->>0)::double precision as x,
               (e.value->>1)::double precision as y,
               e.ord                           as i,
               count(*) over ()                as n
          from jsonb_array_elements(polygon) with ordinality as e(value, ord)
    )
    select abs(sum(a.x * b.y - b.x * a.y)) / 2.0
      from v a
      join v b on b.i = (a.i % a.n) + 1;
$$;

do $$
declare
    offender text;
begin
    -- Roi.__post_init__: at least three vertices.
    select string_agg(hall_id, ', ') into offender
      from public.halls
     where jsonb_array_length(roi_polygon) < 3;
    if offender is not null then
        raise exception 'ROI: fewer than 3 vertices for: %', offender;
    end if;

    -- Roi.__post_init__: normalised coordinates, not pixels.
    select string_agg(distinct h.hall_id, ', ') into offender
      from public.halls h,
           lateral jsonb_array_elements(h.roi_polygon) as e(value)
     where (e.value->>0)::double precision not between 0 and 1
        or (e.value->>1)::double precision not between 0 and 1;
    if offender is not null then
        raise exception 'ROI: vertex outside the normalised frame for: %', offender;
    end if;

    -- Roi.MIN_ROI_AREA. A polygon this small counts nobody, forever.
    select string_agg(hall_id, ', ') into offender
      from public.halls
     where pg_temp.roi_area(roi_polygon) < 1e-4;
    if offender is not null then
        raise exception 'ROI: degenerate polygon for: %', offender;
    end if;

    -- Not a rule the worker enforces, because it is a judgement rather than a
    -- correctness bound: roi.py notes that a region covering 0.9 of the frame
    -- "is not a queue region, it is the whole room with extra steps". A
    -- polygon that large is a placeholder someone forgot, so it fails here.
    select string_agg(hall_id, ', ') into offender
      from public.halls
     where pg_temp.roi_area(roi_polygon) > 0.9;
    if offender is not null then
        raise exception 'ROI: polygon covers most of the frame for: %', offender;
    end if;

    -- Every count carries its roi_version so history stays interpretable. An
    -- empty one makes that column useless for the row it describes.
    select string_agg(hall_id, ', ') into offender
      from public.halls
     where roi_version is null or btrim(roi_version) = '';
    if offender is not null then
        raise exception 'ROI: blank roi_version for: %', offender;
    end if;

    raise notice 'ROI sanity: all % halls pass', (select count(*) from public.halls);
end;
$$;

-- Printed so a CI log shows what shipped, not just that it passed.
select hall_id,
       roi_version,
       round(pg_temp.roi_area(roi_polygon)::numeric, 4) as frame_fraction,
       jsonb_array_length(roi_polygon)                  as vertices,
       active
  from public.halls
 order by hall_id;
