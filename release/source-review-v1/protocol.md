# Source and numeric-recoverability review

Inspect the source image, exact target and both actual processor rasters for every
chart. Mark eligible only when all target metadata is visible, source values and
units are correct, category/series associations are unambiguous, and the numeric
precision required by the target is supported at both budgets. Check blur, glyph
contrast, clipping, line/leader association, logarithmic scales, multipliers and
rounding. This protocol uses the current cell scorer's tolerance:
absolute error <= max(0.05 * abs(target), 0.000001). It does not require exact
transcription of unprinted trailing digits. For unlabeled charts, quantify the
plausible reading interval in notes; its uncertainty must fit inside that
tolerance for every value. Do not approve unsupported subpixel precision. A pie
without printed values does not identify an absolute total.

No font-size cutoff or native bounding-box result is automatic approval. Record
uncertain examples as pending; use stress or unreadable for unsuitable examples
and explain why. Do not remove them from the packet. No bulk approval is provided.
Record the reviewer's identity and timezone-aware time for each eligible row.

This is source review, not a benchmark eligibility rate, proof of independent
review, GPU parity or approval of the training collator. Final evaluation needs
independent annotation/recoverability review, frozen scope and a separate holdout.
