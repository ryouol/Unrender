"""Render the owned reference demo with legible text and source/table order aligned.

This is a synthetic product walkthrough fixture, not model inference evidence.
The original historical model benchmark artifacts are not modified.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "unrender/product/static/demo"


def build():
    path = ROOT / "budget-quarter-result.json"
    payload = json.loads(path.read_text())
    chart = payload["result"]
    chart["y_axis"]["unit"] = "USD millions"
    points = chart["series"][0]["points"]
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 16}):
        fig, ax = plt.subplots(figsize=(10, 10), dpi=160)
        fig.subplots_adjust(left=0.22, right=0.92, top=0.86, bottom=0.10)
        fig.suptitle(chart["title"], x=0.22, y=0.95, ha="left", fontsize=26, weight="bold")
        fig.text(
            0.22,
            0.903,
            "Synthetic reference data · values in USD millions",
            fontsize=13,
            color="#536273",
        )
        bars = ax.barh(
            [p["x"] for p in points],
            [p["y"] for p in points],
            height=0.62,
            color="#3261c6",
            label="Budget",
        )
        ax.invert_yaxis()
        ax.bar_label(bars, labels=[f"{p['y']:.1f}" for p in points], padding=7, fontsize=14)
        ax.set_xlim(0, 11.2)
        ax.set_xlabel("Budget (USD millions)", labelpad=14)
        ax.set_ylabel("Quarter", labelpad=12)
        ax.set_axisbelow(True)
        ax.xaxis.grid(True, color="#e5e9f0")
        ax.tick_params(length=0, pad=8)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.legend(loc="lower right", frameon=False, fontsize=12)
        image = io.BytesIO()
        fig.savefig(image, format="png", facecolor="white")
        plt.close(fig)
    Image.open(image).convert("RGB").save(ROOT / "budget-quarter.webp", lossless=True)
    payload["model_version"] = "reference-fixture/budget-quarter-v2"
    payload["source"] = "Owned synthetic walkthrough; rendered by analysis/build_demo_fixture.py"
    payload["raw"] = json.dumps(chart, ensure_ascii=False, separators=(",", ":"))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    build()
