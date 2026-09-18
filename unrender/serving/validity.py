"""One serving acceptance contract; repairs never earn benchmark validity credit."""

from unrender.eval.metrics import semantic_errors
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import strict_json

CONTRACT = "serving-acceptance-v2"


def assess(
    raw: str, finish_reason: str | None, stream_complete: bool
) -> tuple[dict, ChartData | None]:
    result = {
        "raw_json": False,
        "strict_schema": False,
        "semantic": False,
        "completed": finish_reason == "stop" and stream_complete is True,
        "accepted": False,
    }
    chart = None
    try:
        value = strict_json(raw)
        result["raw_json"] = True
        chart = ChartData.model_validate(value, strict=True)
        result["strict_schema"] = True
        result["semantic"] = not semantic_errors(chart)
    except (ValueError, TypeError):
        pass
    result["accepted"] = all(
        result[k] for k in ("completed", "raw_json", "strict_schema", "semantic")
    )
    return result, chart if result["accepted"] else None
