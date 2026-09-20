# Unrender — Literature Landscape & Research Edge

**Date**: 2026-06-15 · `/research-lit` (sources: arXiv API + web; anti-hallucination via `verify_papers.py`)
**Question**: strongest research edge for a small VLM doing chart-image→JSON that beats frontier VLMs on *exact numeric measurement*.

## Verification status
`verify_papers.py` verdict = **WARN**: 11 verified (10 arXiv + DePlot via S2); 8 returned `verify_pending` (transient API failure — real, well-known papers, not promoted to verified per protocol; ChartOCR additionally web-confirmed: Microsoft, WACV 2021, IEEE Xplore). Retry verification next session to upgrade the pending rows.

## Literature table

| Paper | Year/Venue | Method | Key result | Relevance to Unrender | Verify |
|---|---|---|---|---|---|
| **OneChart** (2404.09987) | 2024, ACM MM Oral | image→table VLM **+ auxiliary numeric token + extra decoder + self-eval confidence** | 0.2B model beats DePlot/ChartVLM/ChartAst; **+19–29% on charts WITHOUT printed numbers** | ⭐ closest precedent: small model, numeric reliability, label-free focus, confidence head | ✅ arxiv |
| **ChartOCR** (WACV 2021) | 2021, IEEE | keypoint detection (bars/line pts/plot-area corners) **+ axis calibration (tick pixel↔value) → compute values** | accurate values via deterministic pixel→value | ⭐ the geometry-supervision blueprint — but CV pipeline, per-type, hand-labeled | … pending (web ✓) |
| **LineFormer** (2305.01837) | 2023 | line-chart extraction as **instance segmentation** | SOTA line data extraction | geometry-as-target; line-only, mask supervision | ✅ arxiv |
| **ChartDETR** (2308.07743) | 2023 | DETR multi-shape detection of chart elements | unified element detection | geometry target in one detector (still detection, not values) | ✅ arxiv |
| **Chart-RCNN** (2211.14362) | 2022 | line extraction from camera images + synthetic train | robust to photos | synthetic-data + geometry; degradation robustness | ✅ arxiv |
| **DePlot** | 2023, ACL | image→table "derendering", then LLM reasons over table | strong chart QA via table intermediate | the **compact-table-target** idea Unrender uses | ✅ s2 |
| **MatCha** (2212.09662) | 2023, ACL | Pix2Struct + **chart-derendering & math pretraining** | +~20% on PlotQA/ChartQA | derendering pretraining as a numeric-skill prior | ✅ arxiv |
| **ChartT5** (2305.18641) | 2023 | plot-table cross-modal pretrain: **Masked Value Prediction** | +8% ChartQA | value-prediction objective ≈ a numeric aux head | ✅ arxiv |
| **ChartX & ChartVLM** (2402.12185) | 2024 | benchmark + model **separating perception from reasoning** | versatile chart foundation model | perception/reasoning split mirrors geometry→table split | ✅ arxiv |
| **Self-Ensembling VLMs** (2605.27298) | 2026 | sample N tables, **per-cell median + convergence + uncertainty**; new **WB-ChartExtract** (7× denser than ChartQA) | +23% rel. on hard charts | ⭐ cheap test-time reliability boost + a hard real-world-ish benchmark + uncertainty | ✅ arxiv |
| **TOON vs JSON** (2603.03306) | 2026 | **constrained-decoding** of compact object notation vs JSON | compact target + grammar decode | kills invalid-JSON/repetition loops (Unrender's 28 failures) | ✅ arxiv |
| UniChart / ChartAssistant / ChartGemma | 2023–24 | instruction-tuned chart VLMs, chart-to-table pretrain | strong chart QA/summarization | the text-target lineage Unrender's LoRA sits in | … pending |
| Donut / Pix2Struct | 2022–23 | OCR-free image→structured-text; screenshot-parsing pretrain | doc/UI parsing | the image→structured-JSON paradigm + pixel-token pretraining | … pending |
| PlotQA / ChartQA | 2020/2022 | synthetic+real chart QA benchmarks | standard evals | baselines / eval lineage (note: ChartQA is *easy* vs WB-ChartExtract) | …/✅ |

## The three camps (and where the gap is)

1. **VLM chart→table (text target)** — DePlot, MatCha, UniChart, ChartAst, ChartVLM, ChartGemma, and *Unrender's current 4B LoRA*. Learns schema/type reliably; **guesses** pixel→value, so it's weak on exact numeric — worst exactly where values aren't printed. Self-Ensembling (2026) shows even SOTA VLMs lag badly on dense/styled charts — the gap is real and unsolved.
2. **CV geometry/keypoint** — ChartOCR, Chart-RCNN, ChartDETR, LineFormer. **Computes** values from detected geometry + axis calibration (tick pixel↔value), so numerically precise — but task-specific detectors per chart type, brittle to style, needs explicit axis OCR, not one unified model, and limited by hand-labeled geometry.
3. **Numeric-reliable VLM (bridge)** — **OneChart**: keeps the unified VLM but adds an auxiliary numeric token + decoder + self-eval. Big gains on label-free charts at 0.2B. **But it still trains image→table text** with only a scalar aux token — it does *not* use dense, exact geometry supervision, because public chart datasets don't have exact geometry.

## ⭐ Unrender's edge (the unfair advantage)

**The synthetic renderer knows the exact geometry of unlimited charts — nobody else's training data does.** That makes feasible a single small VLM trained with *renderer-derived privileged geometry* and a *deterministic* value decode — fusing camp 2's "compute, don't guess" precision with camp 1's unified model, at camp-1 scale:

```
image → chart_type
      → plot bbox                         (renderer-exact)
      → axis scale + tick (pixel,value) pairs   ← the calibration frontier models never get
      → per-mark geometry (bar tops / point xy / wedge angles)
      → deterministic pixel→value transform
      → compact table  → ChartData JSON
```

This is **Learning Using Privileged Information** applied to charts: geometry is supervised at train time (free from the renderer), absent at test time. Frontier VLMs and even OneChart *guess* values from pixels; Unrender would *compute* them from predicted marks calibrated against predicted ticks — and uniquely has exact geometry labels to supervise every step.

**Concrete tactics to borrow:** OneChart's aux-numeric-token + self-eval confidence; ChartOCR/LineFormer's geometry intermediate (but renderer-supervised, folded into one VLM); DePlot/MatCha's compact-table target + derendering pretraining; Self-Ensembling's per-cell-median test-time reliability + WB-ChartExtract as an external hard test; constrained/compact decoding to eliminate the invalid-JSON loops.

**Open risks to pressure-test next** (for `/research-review`): (a) does predicting ticks+geometry actually beat directly predicting values, or does error in the calibration step compound? (b) the synthetic→real transfer gap (WB-ChartExtract / real charts); (c) can a 4B model emit calibrated geometry reliably, or does it need the aux-decoder trick; (d) is deterministic decode robust to mild geometry mispredictions.
