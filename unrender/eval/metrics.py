"""Versioned chart evaluation: exact identities, semantic cells, and full tables.

The primary metric is exact-numeric cell F1 at a declared value tolerance.
Missing and extra cells both count. Unlabeled pie proportions are a separate
proxy. Numeric recovery without units is diagnostic, never table correctness.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from decimal import Decimal, DecimalException, localcontext

from unrender.schema.chart_schema import CHART_TYPES, ChartData, x_key

METRIC_VERSION = "chart-table-v2"
_GROUPED_KEY_RE = re.compile(r"[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_NUMBER_KEY_RE = re.compile(r"[-+]?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?")
_MONTH_ABBREV = {
    m: m[:3]
    for m in (
        "january",
        "february",
        "march",
        "april",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    )
}
_MONTH_ABBREV["sept"] = "sep"
_MONTH_ABBREV["may"] = "may"
_MONTH_ABBREV.update({value: value for value in list(_MONTH_ABBREV.values())})


def _norm(value) -> str:
    """Only declared equivalent spellings; no fuzzy dates or category matches.

    Unambiguous numeric keys use Decimal equality (no float rounding). Leading
    zero identifiers and ambiguous date formats remain distinct.
    """
    if value is None:
        return ""
    text = " ".join(x_key(value).strip().split())
    if _GROUPED_KEY_RE.fullmatch(text):
        text = text.replace(",", "")
    if _NUMBER_KEY_RE.fullmatch(text):
        try:
            number = Decimal(text)
            if number == 0:
                return "0"
            with localcontext() as context:
                context.prec = max(28, len(number.as_tuple().digits))
                normalized = number.normalize()
            # Avoid expanding adversarial exponents into enormous strings.
            if -100 <= normalized.adjusted() <= 100:
                return format(normalized, "f")
            return str(normalized)
        except DecimalException:
            return text
    return " ".join(_MONTH_ABBREV.get(word.casefold(), word) for word in text.split())


def _unit(value: str | None) -> str:
    # SI prefixes are case-sensitive: m and M must never be equated.
    return " ".join((value or "").strip().split())


def semantic_errors(chart: ChartData) -> list[str]:
    """Structural semantics not guaranteed by the permissive wire schema."""
    errors = []
    if chart.chart_type not in CHART_TYPES:
        errors.append("unsupported_chart_type")
    if not chart.series:
        errors.append("empty_series")
    names = [_norm(series.name) for series in chart.series]
    if len(names) > 1 and (not all(names) or len(set(names)) != len(names)):
        errors.append("ambiguous_series_names")
    for series in chart.series:
        if not series.points:
            errors.append("empty_points")
        keys = [_norm(point.x) for point in series.points]
        if not all(keys) or len(set(keys)) != len(keys):
            errors.append("ambiguous_point_keys")
        if any(
            not math.isfinite(point.y)
            or (isinstance(point.x, (int, float)) and not math.isfinite(point.x))
            for point in series.points
        ):
            errors.append("nonfinite_value")
    if chart.chart_type == "pie" and any(
        any(point.y < 0 for point in series.points) or sum(p.y for p in series.points) <= 0
        for series in chart.series
    ):
        errors.append("invalid_pie_values")
    return sorted(set(errors))


def _unique_matches(truth, predicted) -> dict[int, int]:
    """Ambiguous keys never match, even if one duplicated value looks correct."""
    gt_counts, pred_counts = Counter(truth), Counter(predicted)
    index = {key: i for i, key in enumerate(predicted) if pred_counts[key] == 1}
    return {i: index[key] for i, key in enumerate(truth) if gt_counts[key] == 1 and key in index}


def _value_correct(pred_y: float, gt_y: float, tol: float) -> bool:
    # Zero has no relative scale. Do not accept 5 merely because another cell is 100.
    return abs(pred_y - gt_y) <= max(tol * abs(gt_y), 1e-6)


def classify_status(error, pred) -> str:
    if error:
        return "infra_error"
    return "model_invalid" if pred is None else "ok"


def score_sample(
    pred: ChartData | None, gt: ChartData, tol: float = 0.05, labels_shown: bool | None = None
) -> dict:
    if not math.isfinite(tol) or not 0 <= tol <= 1:
        raise ValueError("tolerance must be finite and between zero and one")
    if errors := semantic_errors(gt):
        raise ValueError(f"invalid ground truth: {', '.join(errors)}")
    proxy = gt.chart_type == "pie" and labels_shown is False
    n_gt = sum(len(series.points) for series in gt.series)
    n_pred = sum(len(series.points) for series in pred.series) if pred else 0
    result = {
        "schema_valid": int(pred is not None),
        "semantic_valid": int(pred is not None and not semantic_errors(pred)),
        "chart_type_correct": 0,
        "title_total": int(bool(gt.title)),
        "title_hit": 0,
        "x_label_total": int(bool(gt.x_axis.label)),
        "x_label_hit": 0,
        "y_label_total": int(bool(gt.y_axis.label)),
        "y_label_hit": 0,
        "units_correct": 0,
        "series_name_f1": 0.0,
        "n_gt_points": n_gt,
        "n_pred_points": n_pred,
        "n_correct_points": 0,
        "n_numeric_correct": 0,
        "n_proxy_points": n_gt if proxy else 0,
        "n_pred_proxy_points": n_pred if proxy else 0,
        "n_proxy_correct": 0,
        "is_proxy": proxy,
        "chart_exact": 0,
        "table_within_tolerance": 0,
        "abs_errors": [],
        "rel_errors": [],
    }
    if pred is None:
        return result

    type_ok = pred.chart_type == gt.chart_type
    units_ok = all(
        _unit(getattr(pred, axis).unit) == _unit(getattr(gt, axis).unit)
        for axis in ("x_axis", "y_axis")
    )
    series_map = _unique_matches(
        [_norm(s.name) for s in gt.series], [_norm(s.name) for s in pred.series]
    )
    n_numeric, n_correct, n_exact = 0, 0, 0
    for gi, pi in series_map.items():
        gs, ps = gt.series[gi], pred.series[pi]
        point_map = _unique_matches(
            [_norm(p.x) for p in gs.points], [_norm(p.x) for p in ps.points]
        )
        gt_total = sum(p.y for p in gs.points)
        pred_total = sum(p.y for p in ps.points)
        valid_pie = (
            gt_total > 0
            and pred_total > 0
            and all(p.y >= 0 and math.isfinite(p.y) for p in gs.points + ps.points)
        )
        for gpi, ppi in point_map.items():
            gy, py = gs.points[gpi].y, ps.points[ppi].y
            if not math.isfinite(py):
                continue
            if proxy:
                if not valid_pie:
                    continue
                gy, py = gy / gt_total, py / pred_total
            result["abs_errors"].append(abs(py - gy))
            result["rel_errors"].append(abs(py - gy) / max(abs(gy), 1e-9))
            hit = _value_correct(py, gy, tol)
            n_numeric += int(hit)
            n_correct += int(hit and type_ok and units_ok)
            n_exact += int(py == gy)

    labels_ok = _norm(pred.x_axis.label) == _norm(gt.x_axis.label) and _norm(
        pred.y_axis.label
    ) == _norm(gt.y_axis.label)
    shape_ok = len(series_map) == len(gt.series) == len(pred.series) and n_pred == n_gt
    full = (
        result["semantic_valid"] and shape_ok and labels_ok and units_ok and type_ok and not proxy
    )
    result.update(
        {
            "chart_type_correct": int(type_ok),
            "units_correct": int(units_ok),
            "title_hit": int(bool(gt.title) and _norm(pred.title) == _norm(gt.title)),
            "x_label_hit": int(
                bool(gt.x_axis.label) and _norm(pred.x_axis.label) == _norm(gt.x_axis.label)
            ),
            "y_label_hit": int(
                bool(gt.y_axis.label) and _norm(pred.y_axis.label) == _norm(gt.y_axis.label)
            ),
            "series_name_f1": 2 * len(series_map) / (len(gt.series) + len(pred.series)),
            "n_correct_points": n_correct,
            "n_numeric_correct": n_numeric,
            "n_proxy_correct": n_correct if proxy else 0,
            "table_within_tolerance": int(full and n_correct == n_gt),
            "chart_exact": int(full and n_exact == n_gt and _norm(pred.title) == _norm(gt.title)),
        }
    )
    return result


def aggregate(samples: list[dict]) -> dict:
    n = len(samples)
    if not n:
        return {"n": 0, "metric_version": METRIC_VERSION}

    def ratio(num, den):
        return num / den if den else 0.0

    def total(key):
        return sum(sample[key] for sample in samples)

    exact = [s for s in samples if not s["is_proxy"]]
    ng = sum(s["n_gt_points"] for s in exact)
    np = sum(s["n_pred_points"] for s in exact)
    nc = sum(s["n_correct_points"] for s in exact)
    proxy_gt, proxy_pred, proxy_correct = (
        total(k) for k in ("n_proxy_points", "n_pred_proxy_points", "n_proxy_correct")
    )
    abs_errors = [e for s in samples for e in s["abs_errors"]]
    rel_errors = [e for s in samples for e in s["rel_errors"]]
    return {
        "metric_version": METRIC_VERSION,
        "n": n,
        "schema_valid_rate": ratio(total("schema_valid"), n),
        "semantic_valid_rate": ratio(total("semantic_valid"), n),
        "chart_type_acc": ratio(total("chart_type_correct"), n),
        "cell_accuracy": ratio(total("n_correct_points"), total("n_gt_points")),
        "cell_accuracy_exact": ratio(nc, ng),
        "cell_precision": ratio(nc, np),
        "cell_recall": ratio(nc, ng),
        "cell_f1": ratio(2 * nc, ng + np),
        "macro_cell_f1": ratio(
            sum(
                ratio(2 * s["n_correct_points"], s["n_gt_points"] + s["n_pred_points"])
                for s in exact
            ),
            len(exact),
        ),
        "numeric_recall": ratio(sum(s["n_numeric_correct"] for s in exact), ng),
        "pie_proportion_accuracy": ratio(proxy_correct, proxy_gt),
        "pie_proportion_precision": ratio(proxy_correct, proxy_pred),
        "pie_proportion_f1": ratio(2 * proxy_correct, proxy_gt + proxy_pred),
        "chart_exact_rate": ratio(total("chart_exact"), len(exact)),
        "table_within_tolerance_rate": ratio(total("table_within_tolerance"), len(exact)),
        "exact_chart_count": len(exact),
        "title_acc": ratio(total("title_hit"), total("title_total")),
        "x_label_acc": ratio(total("x_label_hit"), total("x_label_total")),
        "y_label_acc": ratio(total("y_label_hit"), total("y_label_total")),
        "units_acc": ratio(total("units_correct"), n),
        "series_name_f1": ratio(total("series_name_f1"), n),
        "mae": statistics.mean(abs_errors) if abs_errors else None,
        "median_rel_err": statistics.median(rel_errors) if rel_errors else None,
        "matched_value_count": len(abs_errors),
        "total_points": total("n_gt_points"),
        "predicted_points": total("n_pred_points"),
        "exact_points": ng,
        "proxy_points": proxy_gt,
    }
