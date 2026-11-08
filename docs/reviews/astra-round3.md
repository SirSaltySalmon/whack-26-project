# Astra review, round 3

Reviewed `cae12e5...d9d6223`. Reproduced each case with the branch's Python functions and synthetic inputs.

## [P1] A fixed orange border can suppress the low-health event

`brain/learner/validate.py:80` and `brain/learner/validate.py:108`

Use a 100 × 10 crop with a fixed 20-column orange border (OpenCV hue 15), a red bar (hue 9) and black elsewhere. Set saturation and value to 255 for both colours. At full health the red fill spans 30 columns. At 80% it spans 24. Ask for a red reader.

The named red range ends at 9, but the resulting mask includes hues 176 through 16 across zero. It counts the orange border. Calibration returns `full_at=0.525`, and the two training reads, 95.2% and 83.8%, both pass the 15-point tolerance. At 10% health, three red columns remain and the reader reports **43.8%**. The 25% alert cannot fire. Keep the named hue constraint when building the final mask, and exercise the alert threshold with a fixed-colour border.

## [P2] Unrelated number detections defeat a repeatable bar

`brain/learner/regions.py:160`

In four 100 × 100 gameplay frames, report health once per frame. The first two are bars at `[0,0,10,10]`. The last two are numbers reading 90, one at `[40,40,50,50]` and one at `[80,80,90,90]`.

The bars have identical boxes. Neither number overlaps another sighting. The kind vote ties, numbers win, and `agree` returns an empty list. Compare spatially agreeing groups of each kind before breaking ties on precision.

## [P2] Whitespace counts as evidence of visible digits

`brain/learner/regions.py:119` and `brain/learner/regions.py:125`

Use two health sightings at the same box. Set the first to `kind="bar"` and the second to `kind="number", text_seen=" "`. Both have `fraction_seen=1.0`. The whitespace votes for a number and prevents the second sighting from backing a bar. The number wins the tie, then fails the two-frame minimum. The result is empty. Use the same digit-presence check for voting and group membership.

## [P2] A one-pixel overshoot loses a visible edge target

`brain/perception/coords.py:80`

On a 1280 × 720 screenshot, pass `[1270,100,1281,112]` to both box converters. The learner clips it to the visible 10 × 12 rectangle. The pointing converter raises `ValueError` because the normalized right edge is 1000.78125. The player gets a failed lookup for an otherwise visible target. Clip a small overshoot before conversion and continue rejecting boxes with no visible area.
