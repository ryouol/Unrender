"""Bounded cold/warm check of the production provider; invokes paid L4 inference."""

import json
from pathlib import Path

import modal

import modal_train as provider

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("unrender-provider-fix-canary")
image = provider.infer_image.add_local_file(ROOT / "modal_train.py", "/root/modal_train.py")


@app.function(
    image=image,
    volumes={provider.INFER_V: provider.INFER_VOL},
    gpu="L4",
    cpu=4,
    memory=32768,
    timeout=300,
    retries=0,
    max_containers=1,
    scaledown_window=2,
)
def check(image_bytes: bytes, revision: str):
    import time

    from modal_train import infer_one

    results = []
    for phase in ("cold", "warm"):
        started = time.perf_counter()
        result = infer_one.local(
            image_bytes, "modal-volume/unrender-inference-cache", revision, revision
        )
        results.append({"phase": phase, "elapsed_seconds": time.perf_counter() - started, **result})
    return results


@app.local_entrypoint()
def main(image_path: str, output: str, revision: str):
    results = check.remote(Path(image_path).read_bytes(), revision)
    Path(output).write_text(json.dumps(results, indent=2))
    print(
        json.dumps(
            [
                {
                    "phase": r["phase"],
                    "seconds": r["elapsed_seconds"],
                    "valid": r["json"] is not None,
                    "release": r["provider_release"],
                }
                for r in results
            ],
            indent=2,
        )
    )
