# Unrender Research Review Follow-up

Tighten the recommendation into an implementable plan for this repository.

Two corrections and constraints:

1. `max_new_tokens` is already 4,096. The invalid cases mostly hallucinate
   200-300 repeated categories until the cap, so simply increasing output
   length is wrong.
2. Several 36-40 point images are genuinely near-illegible at roughly 400x280,
   so density collapse cannot be assigned to capacity without a
   readability-controlled slice.

Please provide:

1. Exact E0 decoding variants and parameters worth testing without training.
2. The minimum three 4B training runs, including validation/checkpoint metric
   and whether numeric-token loss weighting is preferable to a compact target
   representation.
3. A precise gate for unlocking 8B.
4. The smallest base-model and human-readability controls.

Keep the entire package under $25 GPU spend and rank each run by information
value. Challenge your previous assumptions where appropriate.
