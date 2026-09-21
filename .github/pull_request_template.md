## What changed

<!-- One paragraph. What this does, not how. -->

## Why

<!-- The problem it solves, or the milestone it moves. Link the issue if there is one. -->

## How it was verified

<!-- Commands run and what they returned. "Tests pass" is not verification; paste the result. -->

- [ ] `make -C worker test` passes
- [ ] `make -C worker lint` passes
- [ ] Web build passes (`npm run build` in `web/`), if the web app changed

## Privacy check

Hall Check stores counts, never frames.

- [ ] No code path in this change writes, caches, uploads, or logs image data
- [ ] Any new frame handling releases the buffer in the same call that acquires it

## Schema and compatibility

- [ ] No migration, **or** migration is additive and the running worker tolerates it
- [ ] `roi_version` / `camera_epoch` semantics unchanged, **or** the change is described above

## Notes for the reviewer

<!-- Known gaps, follow-ups, anything deliberately left out of scope. -->
