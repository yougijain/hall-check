# Measurement protocol (M2)

How Hall Check's accuracy numbers are produced, written down before the numbers
are, so the procedure cannot be adjusted to flatter the result.

## What is being measured

For a given instant and hall: how far the detector's count of the queue region
differs from a person's count of the same region at the same instant.

Not "how accurate is YOLO". Not "how long is the wait". The error of this
pipeline — this model, this threshold, this polygon, this camera — against a
human looking at the same stream.

## Target

**150 to 250 paired labels**, spanning:

| Dimension | Values |
|---|---|
| Meal | breakfast, lunch, dinner |
| Lighting | daylight, dark |
| Hall | Worcester, Franklin, Hampshire, Berkshire |

At least 10 labels per stratum. Below that, a stratum's MAE is an anecdote; the
report shows it with a ⚠ rather than hiding it, because a hidden thin stratum
is indistinguishable from good coverage.

## Procedure

```bash
cd worker
python -m hallcheck.cli label worcester -n 10
```

Each round:

1. The tool captures a frame and runs the detector. **It says nothing about
   the result.**
2. It asks for your count of the people inside the queue region.
3. You answer.
4. Only then does it show both numbers and the error, and write the row.

### The ordering is the protocol

The human count is recorded before the model count is revealed. This is not a
nicety.

Counting people in a crowded frame is genuinely hard. The honest answer is
often "somewhere around twenty", and a labeller who has already seen `23` will
write `23`. Every label collected that way drags MAE toward zero, and the
published figure becomes a measurement of the labeller's suggestibility rather
than the detector's accuracy. Nothing downstream can detect it, and no amount
of care afterwards can repair it.

So the ordering is enforced in code rather than left to discipline:
`run_label_session` obtains the model count into a local, calls the prompt, and
only writes or prints anything about the model afterwards.
`tests/test_labeling.py::test_the_model_count_is_not_revealed_before_the_human_answers`
fails the build if that order is disturbed.

### Counting rules

- Count people whose **feet** are inside the queue region. Same rule the
  detector uses, so the two are measuring the same thing.
- Count people, not trays, bags or reflections.
- If someone is half-occluded but clearly a person, count them. The detector
  will often miss them; that miss is the thing being measured.
- If you genuinely cannot tell, note it in the free-text field. Do not guess
  silently.
- Count the frame as it was when you started. If you spend forty seconds
  counting, you are counting the room at the start of those forty seconds.

### Conditions

`lighting` is what you can see, not what the clock says. A dining hall at 5pm
in December is dark; the same clock time in June is not.

`meal` is suggested from the time of day and confirmed by you. Service hours
shift on weekends and during breaks.

## What gets reported

```bash
python -m hallcheck.cli evaluate
```

MAE, signed bias and RMSE, overall and broken out by hall, lighting and meal,
each with its n and a bootstrap confidence interval for MAE.

### Why MAE and not MAPE

Counts go to zero between meals. MAPE divides by the true value: a single
off-by-two at a true count of 1 contributes 200% and swamps the mean, and at a
true count of 0 it is undefined.

MAE is also in the unit the decision gets made in. "The line is about eight
people longer than the model says" is actionable. "The model is 40% off" is
not.

### Why bias is reported next to MAE

They describe different failures. MAE 6 with bias 0 is a noisy detector. MAE 6
with bias −6 is a detector that systematically misses half the queue. The
second is fixable — a different model, a different threshold, a redrawn polygon
— and the first mostly is not. A report showing MAE alone cannot tell them
apart.

Bias is **model minus human**. Positive means the detector over-counts.

### Why there is a confidence interval

A point estimate from 180 labels invites being read as exact. Resampling the
labels with replacement and taking percentiles of the resulting MAEs shows how
much of the number is the detector and how much is which afternoons happened to
get labelled. The bootstrap is seeded, so the interval does not move between
runs of the same data.

### Why every table is stratified

Occlusion is worst exactly when the count matters most. At peak, people stand
behind each other, the detector sees the front of the line and loses the back,
and the error is both larger and one-sided. A single MAE averaged across the
day hides this behind the quiet hours, when the detector is nearly perfect and
nobody needs it.

The expected shape, which the report should make visible: near-zero bias at
breakfast, strongly negative bias at lunch, worse again in the dark.

## When the number may be quoted

`hallcheck evaluate` exits non-zero while any coverage gap remains, and prints
the gaps above the table. The headline MAE is quotable only when:

- there are at least 150 paired labels, **and**
- every meal, lighting condition and active hall has at least 10.

Until then the report is still useful — it shows where the labelling has to go
next — but the overall figure carries an explicit "not yet reportable".

## Known limitations

- **One annotator.** There is no second labeller and therefore no inter-rater
  agreement. The human count is treated as ground truth; at high occupancy it
  is also an estimate, and the true error is larger than reported.
- **The human and the detector are not looking at the identical frame.** The
  browser and ffmpeg both pull the live edge of the same HLS stream, but they
  can be a few seconds apart. At peak, a few seconds is people.
- **Labels are not sampled at random.** They are collected when the labeller is
  free, which correlates with the labeller's own schedule. The stratification
  targets are what stop this from becoming a lunchtime-only dataset; they do
  not make the sample random.
