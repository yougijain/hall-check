-- 0005_reconcile_halls_with_live_streams.sql
--
-- Brings the seeded halls in line with the cameras UMass actually publishes.
--
-- 0003 seeded four dining commons with one camera each, from the project
-- brief. The published livestream roster does not match that:
--
--   * Worcester has TWO cameras, North and South.
--   * Franklin has none.
--   * Berkshire and Hampshire have one each, as assumed.
--
-- Worcester's two cameras become two rows rather than a new cameras table.
-- Each camera needs its own ROI polygon, its own camera_epoch and its own
-- count series, which is exactly what a `halls` row already provides - and a
-- student choosing which door to walk to genuinely wants both numbers, so
-- they are not an implementation detail to be summed away. A cameras table
-- would be the right shape if several halls had several cameras; while only
-- one does, it is generality bought on speculation.
--
-- Franklin stays as a row with active = false rather than being deleted. The
-- site filters on active and the worker skips it, so it disappears from both;
-- keeping the row records that it was considered and why it is absent, which
-- a deletion would not.
--
-- A fresh database runs 0003 and then this file, so it briefly creates a
-- 'worcester' row only to retire it here. That is the cost of never editing a
-- merged migration, and it is cheaper than the alternative.

-- Worcester's two cameras. ROI polygons are placeholders on the same terms as
-- 0003: they must be redrawn per camera against a real frame before any count
-- from them means anything.
insert into public.halls (hall_id, name, stream_url, roi_polygon, roi_version, opens_at, closes_at)
values
    ('worcester_north', 'Worcester Commons North', '',
     '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00'),
    ('worcester_south', 'Worcester Commons South', '',
     '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00')
on conflict (hall_id) do nothing;

-- Carry any history from the single-camera row onto the north camera before
-- retiring it. There is none today, but a migration that silently drops rows
-- when run against a database that does have them is a trap.
update public.counts set hall_id = 'worcester_north' where hall_id = 'worcester';
update public.labels set hall_id = 'worcester_north' where hall_id = 'worcester';

delete from public.halls where hall_id = 'worcester';

-- Franklin publishes no camera, so there is nothing to measure. Left in place,
-- inactive, rather than deleted.
update public.halls set active = false where hall_id = 'franklin';
