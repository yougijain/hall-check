-- 0003_seed_halls.sql
--
-- The four UMass Amherst dining commons.
--
-- ROI polygons are placeholders: a centred box covering the middle of the
-- frame. They MUST be redrawn against a real frame from each camera before the
-- counts mean anything, and roi_version bumped when they are. A polygon over
-- the whole frame counts people eating at tables and calls it a queue.
--
-- Stream URLs are set per deployment rather than committed, so this seed
-- inserts an empty string and the worker skips a hall until one is configured.

insert into public.halls (hall_id, name, stream_url, roi_polygon, roi_version, opens_at, closes_at)
values
    ('worcester',  'Worcester Commons',  '', '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00'),
    ('franklin',   'Franklin Commons',   '', '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '20:00'),
    ('hampshire',  'Hampshire Commons',  '', '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00'),
    ('berkshire',  'Berkshire Commons',  '', '[[0.25,0.30],[0.75,0.30],[0.75,0.90],[0.25,0.90]]'::jsonb, 'v0-placeholder', '07:00', '21:00')
on conflict (hall_id) do nothing;
