"""Replay one verified generated image and retain every augmentation stage.

Requires the exact recorded generator source and rendering environment. This is
a diagnostic development tool, not an eligibility or legibility classifier.
"""

from __future__ import annotations

import argparse
import io
import json
import random
from dataclasses import asdict
from pathlib import Path

from unrender.data_gen.augment import _OPS
from unrender.data_gen.chart_specs import random_spec
from unrender.data_gen.generate import _cap_long_side
from unrender.data_gen.provenance import digest, json_bytes, recipe, verify_dataset
from unrender.data_gen.render import render_chart


class TracedRandom(random.Random):
    def __init__(self, seed):
        super().__init__(seed)
        self.draws = []

    def uniform(self, a, b):
        value = super().uniform(a, b)
        self.draws.append({"method": "uniform", "range": [a, b], "value": value})
        return value

    def randint(self, a, b):
        value = super().randint(a, b)
        self.draws.append({"method": "randint", "range": [a, b], "value": value})
        return value


def replay(root: Path, chart_id: str, out: Path) -> dict:
    generation, rows = verify_dataset(root)
    parameters = generation["recipe"]["parameters"]
    if recipe(**parameters) != generation["recipe"]:
        raise ValueError("replay requires the recorded generator sources and environment")
    row = next((row for row in rows if row["id"] == chart_id), None)
    if row is None:
        raise ValueError("chart ID is absent from the verified bundle")
    if out.exists() and any(out.iterdir()):
        raise ValueError("output must be a fresh directory")
    rng = TracedRandom(parameters["base_seed"] + int(chart_id))
    spec = random_spec(rng, hard=parameters["hard"], v2=parameters["v2"])
    if json_bytes(asdict(spec)) != json_bytes(row["spec"]):
        raise ValueError("replayed specification differs from recorded specification")
    image = render_chart(spec)
    out.mkdir(parents=True, exist_ok=True)
    report = {
        "contract": "augmentation-replay-v1",
        "recipe_sha256": generation["recipe_sha256"],
        "id": chart_id,
        "source_image_sha256": row["image_sha256"],
        "auditor_sha256": digest(Path(__file__).read_bytes()),
        "stages": [],
        "limits": "Development diagnostics only; no independent human readability approval.",
    }

    def save(name, draws):
        path = out / f"{len(report['stages']):02d}-{name}.png"
        image.save(path)
        report["stages"].append(
            {
                "name": name,
                "image": path.name,
                "sha256": digest(path.read_bytes()),
                "size": list(image.size),
                "parameter_draws": draws,
            }
        )

    save("native", [])
    selected = parameters["augment"] and rng.random() < parameters["augmentation_fraction"]
    report["augmentation_selected"] = selected
    if selected:
        for probability, operation in _OPS:
            if rng.random() < probability:
                rng.draws.clear()
                image = operation(image, rng)
                save(operation.__name__.strip("_<>") or "operation", list(rng.draws))
    image = _cap_long_side(image, parameters["max_side"])
    save("final", [])
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    if digest(buffer.getvalue()) != row["image_sha256"]:
        raise ValueError("replayed final raster does not equal the recorded image")
    report["final_image_matches_recorded_bytes"] = True
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    replay(args.dataset, args.id, args.out)


if __name__ == "__main__":
    main()
