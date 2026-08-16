## What this changes

<!-- and why -->

## Verification

- [ ] `python -m docketlab fixture` — all eight checks unchanged
      (including `paraphrase_caught_by_minhash: 0.0`, which is correct)
- [ ] `python stress.py` — ALL CLEAR
- [ ] New detection behaviour has a seeded fixture case and a `score()` check

## Scaling

<!-- If this touches dedup, clustering, or linkage, say what it does to the
     curve. stress.py measures it. -->

## Notes

<!-- Anything a reviewer should know: thresholds chosen and why, agencies or
     dockets this was tested against, known gaps. -->
