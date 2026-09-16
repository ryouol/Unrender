"""Isolated, one-GPU, no-retry serving case study; never deploys the product."""

import subprocess
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "606408af6c0f59959867458cf026ebe0e4f9ef65"
BASELINE_SOURCE = ROOT / "outputs/serving-inputs/production_providers.py"
if modal.is_local():
    BASELINE_SOURCE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_SOURCE.write_bytes(
        subprocess.check_output(
            ["git", "show", BASELINE_COMMIT + ":unrender/eval/providers.py"], cwd=ROOT
        )
    )
app = modal.App("unrender-serving-case-study")
model_volume = modal.Volume.from_name("unrender-inference-cache")
data_volume = modal.Volume.from_name("unrender-vol")
results_volume = modal.Volume.from_name("unrender-serving-results", create_if_missing=True)
image = (
    modal.Image.from_registry("vllm/vllm-openai:v0.11.0")
    .entrypoint([])
    .run_commands("ln -sf /usr/bin/python3 /usr/local/bin/python", "python --version")
    .pip_install(
        "transformers==4.57.6",
        "pillow==12.3.0",
        "pydantic==2.13.5",
        "rapidfuzz==3.14.1",
        "httpx==0.28.1",
    )
    .add_local_python_source("unrender")
    .add_local_dir(ROOT / "unrender/eval/subsets", "/root/unrender/eval/subsets")
    .add_local_file(ROOT / "scripts/serving_case_driver.py", "/root/serving_case_driver.py")
    .add_local_file(BASELINE_SOURCE, "/root/production_providers.py")
)


@app.function(
    image=image,
    gpu="H100",
    cpu=8,
    memory=65536,
    volumes={"/models": model_volume, "/research": data_volume, "/results": results_volume},
    timeout=3000,
    max_containers=1,
    retries=0,
    scaledown_window=2,
)
def experiment():
    import subprocess
    import time

    run_id = time.strftime("case-%Y%m%d-%H%M%S", time.gmtime())
    out = Path("/results") / run_id
    out.mkdir()
    try:
        subprocess.run(
            ["python", "/root/serving_case_driver.py", str(out)], check=True, timeout=2850
        )
    finally:
        results_volume.commit()
    return {"run": run_id, "summary": (out / "progress.json").read_text()}


@app.local_entrypoint()
def main():
    print(experiment.remote())
