"""Run the reserved scheduler comparison with an explicit bounded GPU budget."""

from pathlib import Path

import modal
from modal_serving_case import data_volume, image, model_volume, results_volume

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("unrender-serving-final-quality")
final_image = image.add_local_file(
    ROOT / "scripts/modal_serving_case.py", "/root/modal_serving_case.py"
).add_local_file(ROOT / "scripts/serving_final_driver.py", "/root/serving_final_driver.py")


@app.function(
    image=final_image,
    gpu="H100",
    cpu=8,
    memory=65536,
    volumes={"/models": model_volume, "/research": data_volume, "/results": results_volume},
    timeout=2160,
    retries=0,
    max_containers=1,
    scaledown_window=2,
)
def quality(after_only: bool = False, budget_seconds: int = 1200):
    import os
    import subprocess
    import time

    if not 300 <= budget_seconds <= 2100:
        raise ValueError("budget_seconds must be between 300 and 2100")
    limit = min(budget_seconds, 480) if after_only else budget_seconds
    run_id = time.strftime(
        "final-after-%Y%m%d-%H%M%S" if after_only else "final-%Y%m%d-%H%M%S", time.gmtime()
    )
    out = Path("/results") / run_id
    out.mkdir()
    try:
        subprocess.run(
            ["python", "/root/serving_final_driver.py", str(out)],
            check=True,
            timeout=limit - 30,
            env={
                **os.environ,
                "UNRENDER_FINAL_AFTER_ONLY": "1" if after_only else "0",
                "UNRENDER_FINAL_BUDGET_SECONDS": str(limit - 80),
            },
        )
    finally:
        results_volume.commit()
    return {"run": run_id, "summary": (out / "progress.json").read_text()}


@app.local_entrypoint()
def main(after_only: bool = False, budget_seconds: int = 1200):
    if not 300 <= budget_seconds <= 2100:
        raise ValueError("budget_seconds must be between 300 and 2100")
    print(quality.remote(after_only, budget_seconds))
