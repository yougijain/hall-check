-- 0006_hampshire_cameras_and_blue_wall.sql
--
-- Two more corrections to the seeded roster, on the same evidence as 0005:
-- the cameras UMass actually publishes.
--
--   * Hampshire has TWO cameras, north and south, not one. Split, exactly as
--     Worcester was in 0005 and for the same reasons - separate queues, so
--     separate ROI, camera_epoch and count series.
--   * Blue Wall publishes a camera at its entrance. It is retail rather than a
--     dining common, so it is seeded INACTIVE: the row exists and its stream
--     can be configured, but the site filters on `active` and the worker skips
--     it, so nothing changes until someone deliberately turns it on.
--
-- Note what is NOT here: stream URLs. Those are deployment configuration, not
-- schema. A URL committed to a migration is wrong the moment a stream is
-- restarted and its id changes, and it would differ per environment. Every
-- hall is seeded with an empty stream_url and set per deployment, either with
-- an UPDATE or via HALLCHECK_STREAM_<HALL_ID>. See docs/deploy.md.

insert into public.halls (hall_id, name, stream_url, roi_polygon, roi_version, opens_at, closes_at)
values
    ('hampshire_north', 'Hampshire Commons North', '',
     '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00'),
    ('hampshire_south', 'Hampshire Commons South', '',
     '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00')
on conflict (hall_id) do nothing;

-- Carry any history onto the north camera before retiring the single row, for
-- the same reason as 0005: a migration that silently drops rows when run
-- against a database that has them is a trap, even when none exist today.
update public.counts set hall_id = 'hampshire_north' where hall_id = 'hampshire';
update public.labels set hall_id = 'hampshire_north' where hall_id = 'hampshire';

delete from public.halls where hall_id = 'hampshire';

-- Blue Wall: recorded, not enabled. Retail rather than a dining common, and
-- outside what the project describes - but it is busy and queue-driven, so it
-- is the obvious next candidate and the row is here ready for it.
insert into public.halls (hall_id, name, stream_url, roi_polygon, roi_version, opens_at, closes_at, active)
values
    ('blue_wall', 'Blue Wall', '',
     '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '22:00', false)
on conflict (hall_id) do nothing;
