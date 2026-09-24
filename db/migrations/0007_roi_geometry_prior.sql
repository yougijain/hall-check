-- 0007_roi_geometry_prior.sql
--
-- Replaces the seeded placeholder box with a polygon derived from camera
-- geometry, so the worker measures something defensible while the real
-- regions are still undrawn.
--
-- READ THIS BEFORE TRUSTING A COUNT PRODUCED UNDER IT.
--
-- Nobody has looked at these frames. The polygon is not a queue region; it is
-- a prior over where a queue is likely to be given how a dining hall camera is
-- mounted. It stays on the `v0-` prefix for exactly that reason - `v0-` means
-- "not drawn against a frame" everywhere else in this project, and a count
-- stamped `v0-geometry-prior` is still not a measurement of a queue. Drawing
-- the real regions is unchanged work; see docs/deploy.md.
--
-- What the shape encodes, and why it beats the centred box it replaces:
--
--   * It is a trapezoid, not a rectangle. A camera angled down at a floor
--     sees a fixed-width corridor as narrow at the top and wide at the
--     bottom. A rectangle in image space is a floor region that flares out
--     with distance, which is the opposite of what a queue does.
--
--   * It reaches the bottom of the frame. The near field is where the counter
--     is, and a person close enough to be clipped by the bottom edge is
--     almost always at it. The old box stopped at 0.90 and dropped them.
--
--   * It excludes the top third. Past roughly y = 0.35 a person is small
--     enough that YOLO11n at conf 0.35 is unreliable on them anyway, and that
--     band is where the far wall and the people merely walking through live.
--     Cutting it removes noise without removing much signal.
--
-- The area is 0.42 of the frame, which is wide for a queue region and is
-- deliberate. The two failure modes are not symmetric: an ROI that is too
-- wide inflates the count but keeps it monotone in occupancy, while one that
-- is too tight returns zeros that read as a quiet hall. Absent a frame to
-- check against, bias toward inclusion.
--
-- Every camera gets the same polygon. There is no evidence on which to make
-- them differ, and numbers that differ per hall would read as though someone
-- had drawn them. Identical polygons across every row are the honest signal
-- that nobody has.

update public.halls
   set roi_polygon = '[[0.30,0.35],[0.70,0.35],[0.95,1.00],[0.05,1.00]]'::jsonb,
       roi_version = 'v0-geometry-prior'
 -- Scoped to rows still on the seeded placeholder. Re-applying is a no-op,
 -- and a region someone has actually drawn is never overwritten by a guess.
 where roi_version = 'v0-placeholder';
