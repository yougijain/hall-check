-- Executable form of the access model in db/README.md.
--
-- The anon key ships inside the web bundle and is public by construction.
-- Everything it can reach is published; everything else has to be refused.
-- CI runs this against a freshly migrated database, so a grant added for
-- convenience and forgotten shows up as a failed build rather than as data
-- somebody else notices first.

\set ON_ERROR_STOP on

-- A statement that must be refused. Anything other than a privilege error -
-- including success - fails the run.
create or replace function pg_temp.assert_denied(statement text) returns void
language plpgsql as $$
begin
    execute statement;
    raise exception 'SECURITY: expected permission denied, but this succeeded: %', statement;
exception
    when insufficient_privilege then
        raise notice 'denied as expected: %', statement;
end;
$$;

-- Something for the read assertions to find.
insert into public.counts (hall_id, ts, count, model_version, conf_threshold, roi_version)
values ('worcester', now(), 12, 'test', 0.35, 'v0-placeholder')
on conflict (hall_id, ts) do nothing;

insert into public.labels (hall_id, ts, human_count, model_count, meal, lighting)
values ('worcester', now(), 14, 12, 'lunch', 'daylight')
on conflict (hall_id, ts) do nothing;

set role anon;

-- ---------------------------------------------------------------------------
-- What anon MUST be able to read. The site is broken without these.
-- ---------------------------------------------------------------------------
select count(*) as counts_readable        from public.counts;
select count(*) as hall_latest_readable   from public.hall_latest;
select count(*) as halls_public_readable  from public.halls_public;

-- ---------------------------------------------------------------------------
-- What anon MUST NOT be able to do.
-- ---------------------------------------------------------------------------

-- No writes anywhere. The service role key is the only writer.
select pg_temp.assert_denied($$insert into public.counts (hall_id, ts, count, model_version, conf_threshold, roi_version) values ('worcester', now() + interval '1 hour', 999, 'x', 0.5, 'v')$$);
select pg_temp.assert_denied($$update public.counts set count = 0$$);
select pg_temp.assert_denied($$delete from public.counts$$);
select pg_temp.assert_denied($$insert into public.halls (hall_id, name, stream_url, roi_polygon) values ('fake', 'Fake', 'x', '[[0,0],[1,0],[1,1]]'::jsonb)$$);
select pg_temp.assert_denied($$update public.halls set camera_epoch = 99$$);

-- Labels are private: free-text notes written by one person for themselves.
select pg_temp.assert_denied($$select * from public.labels$$);
select pg_temp.assert_denied($$insert into public.labels (hall_id, ts, human_count, meal, lighting) values ('worcester', now() + interval '2 hours', 1, 'lunch', 'dark')$$);

-- Stream URLs and ROI polygons are withheld by column grant, not by a view
-- that merely omits them. Selecting them directly has to fail.
select pg_temp.assert_denied($$select stream_url from public.halls$$);
select pg_temp.assert_denied($$select roi_polygon from public.halls$$);

reset role;

\echo 'access model verified'
