"""Scoring logic: compare a predicted ChartData against ground truth.

The same function scores every model identically — that's what makes the
benchmark fair and reproducible. The headline metric is **cell accuracy**: the
fraction of ground-truth data points the model recovered within tolerance
(default 5% relative error, the ChartQA convention). `chart_exact_rate` (every
point in a chart correct) is the strict companion.

Matching is robust to ordering and minor label noise:
  - series are aligned by fuzzy name (multi-series) or by index,
  - points within a series are aligned by fuzzy x-label match (threshold 85),
  - a point counts correct iff its x aligns AND |pred-gt|/|gt| <= tol.
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, List, Optional

from rapidfuzz import fuzz

from unrender.schema.chart_schema import ChartData, Point, Series, x_key

_X_MATCH_THRESHOLD = 85   # fuzzy ratio to consider two x-labels the same point
_NAME_ALIGN_THRESHOLD = 55  # looser, for pairing predicted series to GT series
_NAME_F1_THRESHOLD = 85   # stricter, for counting a series name as correct
_LABEL_MATCH_THRESHOLD = 90  # title / axis label correctness


def _norm(v) -> str:
    """Normalize a label/x value to a comparable string (case/space-folded)."""
    if v is None:
        return ""
    return " ".join(x_key(v).strip().lower().split())


def _value_correct(pred_y: float, gt_y: float, tol: float, scale: float) -> bool:
    """Within `tol` relative error, with an absolute fallback for gt≈0."""
    if abs(gt_y) <= 1e-9:
        return abs(pred_y) <= max(tol * scale, 1e-6)
    return abs(pred_y - gt_y) / abs(gt_y) <= tol


def _best_matches(gt_keys: List[str], pred_keys: List[str], threshold: float) -> Dict[int, int]:
    """Global greedy assignment: map gt index -> pred index by fuzzy key match.

    Considers ALL candidate pairs scoring >= threshold and assigns the
    highest-scoring first (each gt/pred used once). This avoids the order-
    dependence of per-gt greedy matching — e.g. "north"~"south" (ratio 60) can't
    steal the "south" prediction away from the real "south" (ratio 100). Empty
    keys (unnamed series) never match by key. Ties break deterministically.
    """
    cands = []
    for gi, gk in enumerate(gt_keys):
        if not gk:
            continue
        for pi, pk in enumerate(pred_keys):
            if not pk:
                continue
            sc = fuzz.ratio(gk, pk)
            if sc >= threshold:
                cands.append((sc, gi, pi))
    cands.sort(key=lambda c: (-c[0], c[1], c[2]))
    matched, used = {}, set()
    for _sc, gi, pi in cands:
        if gi not in matched and pi not in used:
            matched[gi] = pi
            used.add(pi)
    return matched


def _align_series(pred: List[Series], gt: List[Series]) -> List:
    """Pair each GT series with a predicted series (or None).

    Single-series charts pair directly. For multi-series, fuzzy-match by name
    (best pairs first), then assign any still-unmatched GT series to leftover
    predictions by position — so reordering is tolerated even when the model
    omits some (or all) series names; index order is only the fallback.
    """
    if not pred:
        return [(g, None) for g in gt]
    if len(gt) == 1:
        return [(gt[0], pred[0])]

    matched = _best_matches([_norm(s.name) for s in gt], [_norm(s.name) for s in pred], _NAME_ALIGN_THRESHOLD)
    leftover = [pi for pi in range(len(pred)) if pi not in set(matched.values())]
    pairs, ri = [], 0
    for gi, g in enumerate(gt):
        if gi in matched:
            pairs.append((g, pred[matched[gi]]))
        elif ri < len(leftover):
            pairs.append((g, pred[leftover[ri]]))  # positional fallback
            ri += 1
        else:
            pairs.append((g, None))
    return pairs


def _align_points(pred_pts: List[Point], gt_pts: List[Point]) -> List:
    """Pair each GT point with the best fuzzy-x-matching predicted point.

    No positional fallback — an unmatched GT point is a genuine miss.
    """
    matched = _best_matches([_norm(p.x) for p in gt_pts], [_norm(p.x) for p in pred_pts], _X_MATCH_THRESHOLD)
    return [(gp, pred_pts[matched[gi]] if gi in matched else None) for gi, gp in enumerate(gt_pts)]


def _label_hit(pred: Optional[str], gt: Optional[str]) -> bool:
    return fuzz.ratio(_norm(pred), _norm(gt)) >= _LABEL_MATCH_THRESHOLD


def _series_name_f1(pred: List[Series], gt: List[Series]) -> float:
    gt_names = [_norm(s.name) for s in gt if s.name]
    pred_names = [_norm(s.name) for s in pred if s.name]
    if not gt_names and not pred_names:
        return 1.0
    if not gt_names or not pred_names:
        return 0.0
    used, tp = set(), 0
    for g in gt_names:
        for j, p in enumerate(pred_names):
            if j not in used and fuzz.ratio(g, p) >= _NAME_F1_THRESHOLD:
                used.add(j)
                tp += 1
                break
    prec, rec = tp / len(pred_names), tp / len(gt_names)
    return 2 * prec * rec / (prec + rec) if prec + rec else 0.0


def classify_status(error, pred) -> str:
    """Three-way status for a prediction row (A1):
      infra_error  — the call raised (429/quota/network); model never answered.
      model_invalid — model answered but output couldn't be parsed/validated.
      ok           — usable prediction.
    Scoring excludes infra_error from N; model_invalid counts as a miss.
    """
    if error:
        return "infra_error"
    if pred is None:
        return "model_invalid"
    return "ok"


def score_sample(pred: Optional[ChartData], gt: ChartData, tol: float = 0.05,
                 labels_shown: Optional[bool] = None) -> Dict:
    """Score one prediction. Returns raw counts so aggregate() can pool them.

    Pie special case (A3): when a pie's values are NOT printed (labels_shown is
    False), the absolute slice values are unrecoverable from geometry — only the
    proportions are. So for label-free pies we normalize BOTH gt and prediction
    to shares-of-total before the tolerance check, scoring the model on the
    proportions it can actually read.
    """
    n_gt = sum(len(s.points) for s in gt.series)
    has_title, has_x, has_y = int(bool(gt.title)), int(bool(gt.x_axis.label)), int(bool(gt.y_axis.label))

    if pred is None:  # unparseable output — total miss
        return {
            "schema_valid": 0, "chart_type_correct": 0,
            "title_total": has_title, "title_hit": 0,
            "x_label_total": has_x, "x_label_hit": 0,
            "y_label_total": has_y, "y_label_hit": 0,
            "series_name_f1": 0.0,
            "n_gt_points": n_gt, "n_correct_points": 0, "chart_exact": 0,
            "abs_errors": [], "rel_errors": [],
        }

    pie_prop = gt.chart_type == "pie" and labels_shown is False
    n_correct, abs_e, rel_e = 0, [], []
    for g_series, p_series in _align_series(pred.series, gt.series):
        if p_series is None:
            continue
        # Scale the gt≈0 absolute tolerance to THIS series' magnitude, not the
        # whole chart's — otherwise a true 0 beside a huge value in another
        # series would accept an arbitrarily large prediction.
        series_scale = max([abs(p.y) for p in g_series.points] + [1e-9])
        gt_total = sum(abs(p.y) for p in g_series.points) or 1.0
        pred_total = sum(abs(p.y) for p in p_series.points if math.isfinite(p.y)) or 1.0
        for gp, pp in _align_points(p_series.points, g_series.points):
            if pp is None or not math.isfinite(pp.y):
                continue  # NaN/Infinity counts as a miss, never poisons error stats
            if pie_prop:  # compare shares of total, with a fixed [0,1] scale
                gy, py, scale = abs(gp.y) / gt_total, abs(pp.y) / pred_total, 1.0
            else:
                gy, py, scale = gp.y, pp.y, series_scale
            abs_e.append(abs(py - gy))
            rel_e.append(abs(py - gy) / max(abs(gy), 1e-9))
            if _value_correct(py, gy, tol, scale):
                n_correct += 1

    ct_ok = _norm(pred.chart_type) == _norm(gt.chart_type)
    return {
        "schema_valid": 1, "chart_type_correct": int(ct_ok),
        "title_total": has_title, "title_hit": int(has_title and _label_hit(pred.title, gt.title)),
        "x_label_total": has_x, "x_label_hit": int(has_x and _label_hit(pred.x_axis.label, gt.x_axis.label)),
        "y_label_total": has_y, "y_label_hit": int(has_y and _label_hit(pred.y_axis.label, gt.y_axis.label)),
        "series_name_f1": _series_name_f1(pred.series, gt.series),
        "n_gt_points": n_gt, "n_correct_points": n_correct,
        "chart_exact": int(ct_ok and n_gt > 0 and n_correct == n_gt),
        "abs_errors": abs_e, "rel_errors": rel_e,
    }


def aggregate(samples: List[Dict]) -> Dict:
    """Pool per-sample scores into headline metrics."""
    n = len(samples)
    if n == 0:
        return {"n": 0}

    def rate(num, den):
        return num / den if den else 0.0

    total_pts = sum(s["n_gt_points"] for s in samples)
    correct_pts = sum(s["n_correct_points"] for s in samples)
    all_abs = [e for s in samples for e in s["abs_errors"]]
    all_rel = [e for s in samples for e in s["rel_errors"]]

    return {
        "n": n,
        "schema_valid_rate": rate(sum(s["schema_valid"] for s in samples), n),
        "chart_type_acc": rate(sum(s["chart_type_correct"] for s in samples), n),
        "cell_accuracy": rate(correct_pts, total_pts),          # <- headline
        "chart_exact_rate": rate(sum(s["chart_exact"] for s in samples), n),
        "title_acc": rate(sum(s["title_hit"] for s in samples), sum(s["title_total"] for s in samples)),
        "x_label_acc": rate(sum(s["x_label_hit"] for s in samples), sum(s["x_label_total"] for s in samples)),
        "y_label_acc": rate(sum(s["y_label_hit"] for s in samples), sum(s["y_label_total"] for s in samples)),
        "series_name_f1": rate(sum(s["series_name_f1"] for s in samples), n),
        "mae": statistics.mean(all_abs) if all_abs else 0.0,
        "median_rel_err": statistics.median(all_rel) if all_rel else 0.0,
        "total_points": total_pts,
    }
