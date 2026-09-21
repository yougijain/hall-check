# Privacy

## The rule

Hall Check stores counts, never frames.

## What that means concretely

A frame enters the process as a byte buffer, is decoded in memory, is passed to
a person detector, and is dereferenced before the enclosing function returns.
What survives is a single integer and the metadata needed to interpret it: which
hall, which timestamp, which model version, which confidence threshold, which
ROI version.

No frame is written to disk. No frame is uploaded to object storage. No frame is
attached to a log line, an error report, or a crash dump. No frame is sent to a
third-party service. The repository contains no code that would do any of these
things, and no configuration flag that turns any of them on.

## What is stored

| Table | Contents |
|---|---|
| `counts` | hall id, timestamp, integer count, model version, confidence threshold, ROI version |
| `labels` | hall id, timestamp, a human count, the model count, meal, lighting, free-text note |
| `halls` | hall id, display name, public stream URL, ROI polygon, camera epoch |

None of these identify a person. A count of 23 is not reversible into 23 people.

## What is not stored

Images. Video. Crops. Thumbnails. Embeddings. Bounding boxes. Tracks. Re-identification
features. Face data of any kind. Timestamps tied to any individual.

Bounding boxes deserve their own line, because they are the tempting exception.
A box is a position, and a sequence of positions is a trajectory, and a
trajectory through a public space is behavioural data about a person who did not
consent to being measured. Hall Check reduces the detector's output to a scalar
inside the same function that produced the boxes.

## Source material

The streams are published publicly by the university. Hall Check reads them the
same way any browser would and adds nothing to what is already public — it
subtracts, turning video into a number.

## How the rule is enforced

Three layers, because a policy nobody checks is a wish:

1. **Design.** `capture.grab_frame` yields a buffer inside a context manager
   that zeroes and releases it on exit. `detect.count_people` returns an `int`.
   There is no return path for pixels.
2. **Tests.** `worker/tests/test_privacy.py` asserts that no module under
   `hallcheck/` calls an image-writing API (`cv2.imwrite`, `PIL.Image.save`,
   `ultralytics` `save=`/`save_txt=`/`save_crop=`, or a binary `open(...)` write)
   and that the detector's public return type carries no array.
3. **Review.** Every pull request carries a privacy checkbox that has to be
   ticked by a human who read the diff.

If you find a path that violates this, it is a bug of the highest severity in
this repository. Open an issue.

## Retention

Counts are kept indefinitely; they are the history the forecast is trained on
and they contain nothing to expire. There is nothing else to retain.
