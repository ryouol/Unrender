"""Build the frozen, owned synthetic pilot fixtures; performs no inference."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from unrender.data_gen.chart_specs import ChartSpec
from unrender.data_gen.render import render_chart

DESTINATION = Path(__file__).resolve().parents[1] / "release" / "launch-eval-v1"


def main() -> None:
    cases = [
        (
            "labelled-bar",
            ChartSpec(
                chart_type="bar",
                title="Pilot orders by location",
                x_label="Location",
                y_label="Orders",
                y_unit=None,
                categories=["Harbor", "Cedar", "Meadow", "Ridge"],
                series_names=["Orders"],
                values=[[14, 28, 21, 35]],
                value_labels_shown=True,
                dpi=160,
            ),
        ),
        (
            "unlabelled-line",
            ChartSpec(
                chart_type="line",
                title="Pilot processing time",
                x_label="Batch",
                y_label="Time",
                y_unit="ms",
                categories=["A", "B", "C", "D", "E"],
                series_names=["Time"],
                values=[[2.5, 4.0, 3.0, 5.5, 4.5]],
                decimals=1,
                dpi=160,
            ),
        ),
        (
            "unlabelled-grouped-bar",
            ChartSpec(
                chart_type="grouped_bar",
                title="Pilot planned and completed units",
                x_label="Phase",
                y_label="Units",
                y_unit=None,
                categories=["Design", "Build", "Review"],
                series_names=["Planned", "Completed"],
                values=[[12, 18, 24], [9, 12, 15]],
                dpi=160,
            ),
        ),
    ]
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DESTINATION.parent) as temporary:
        staged = Path(temporary) / DESTINATION.name
        staged.mkdir()
        build(cases, staged)
        if DESTINATION.exists():
            existing = {path.name: path.read_bytes() for path in DESTINATION.iterdir()}
            generated = {path.name: path.read_bytes() for path in staged.iterdir()}
            if existing != generated:
                raise SystemExit("Frozen fixtures differ; use a new version instead of overwriting")
        else:
            staged.rename(DESTINATION)


def build(cases: list[tuple[str, ChartSpec]], destination: Path) -> None:
    records = []
    for name, spec in cases:
        source = destination / f"{name}.png"
        image = render_chart(spec)
        image.save(source)
        records.append(
            {
                "id": name,
                "image": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "width": image.width,
                "height": image.height,
                "labels_shown": spec.value_labels_shown,
                "ground_truth": spec.to_chart_data().model_dump(),
            }
        )
    manifest = {
        "version": "launch-eval-v1",
        "scope": "Three owned synthetic operational fixtures; not a customer benchmark",
        "limitation": "Uses the research training renderer; renderer-independent inputs untested",
        "relative_tolerance": 0.05,
        "cases": records,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
