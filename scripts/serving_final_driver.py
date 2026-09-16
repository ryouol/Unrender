"""Reserved common300 quality comparison, on a separate isolated H100 allocation."""

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import serving_case_driver as case

from unrender.serving.release import command

AFTER_ONLY = os.getenv("UNRENDER_FINAL_AFTER_ONLY") == "1"
case.LIMIT = 450 if AFTER_ONLY else 1120
case.PROGRESS["after_only"] = AFTER_ONLY
case.PROGRESS["scope"] = "common300 scheduler quality comparison; separate H100 from load tests"
case.PROGRESS["case_start_epoch"] = time.time()


def main():
    os.environ["UNRENDER_VLLM_API_KEY"] = uuid.uuid4().hex
    os.environ["VLLM_API_KEY"] = os.environ["UNRENDER_VLLM_API_KEY"]
    os.environ["UNRENDER_CASE_REQUEST_TIMEOUT"] = "600"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["VLLM_USAGE_STATS_DISABLED"] = "1"
    case.shell(["nvidia-smi", "-q"], "gpu.txt")
    case.shell(["python", "-m", "pip", "freeze"], "packages.txt")
    case.shell(
        [
            "python",
            "-m",
            "unrender.serving.release",
            "manifest",
            "--snapshot",
            str(case.SNAPSHOT),
            "--manifest",
            str(case.MANIFEST),
            "--dtype",
            "bfloat16",
            "--max-num-seqs",
            "1",
            "--gpu-memory-utilization",
            "0.70",
        ],
        "manifest-name.txt",
        180,
    )
    rows = [
        json.loads(line)
        for line in Path("/research/data/synthetic_v1/test.jsonl").read_text().splitlines()
    ]
    for row in rows:
        row["images"] = [
            str(Path("/research/data/synthetic_v1/images") / Path(row["images"][0]).name)
        ]
    data = case.OUT / "common300-source.jsonl"
    data.write_text("\n".join(json.dumps(row) for row in rows))
    manifest = json.loads(case.MANIFEST.read_text())
    release_digest = hashlib.sha256()
    for name in sorted(manifest["files"]):
        path = case.SNAPSHOT / name
        release_digest.update(name.encode() + b"\0" + str(path.stat().st_size).encode() + b"\0")
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                release_digest.update(chunk)
    case.PROGRESS["verified_production_model_digest"] = release_digest.hexdigest()
    if release_digest.hexdigest() != case.SNAPSHOT.name:
        raise ValueError("Published model digest mismatch")
    case.PROGRESS["intervention"] = {
        "max_num_seqs": [1, 16],
        "frozen_before_final": True,
        "quality_gate": "loss <= 1 percentage point; no failures; full 300",
    }
    case.save()
    if not AFTER_ONLY:
        case.start_server(command(manifest, case.SNAPSHOT), "vllm-before")
        case.bench("final-before", "vllm", data, concurrency=16, final=True)
        case.stop_server()
    manifest["max_num_seqs"] = 16
    case.MANIFEST = case.OUT / "manifest-after.json"
    case.MANIFEST.write_text(json.dumps(manifest, indent=2))
    case.start_server(command(manifest, case.SNAPSHOT), "vllm-after")
    case.bench("final-after", "vllm", data, concurrency=16, final=True)
    case.PROGRESS["status"] = "complete"
    case.save()


try:
    main()
except Exception as exc:
    case.PROGRESS["status"] = "failed"
    case.PROGRESS["failures"].append({"type": type(exc).__name__, "message": str(exc)})
    case.save()
    raise
finally:
    case.stop_server()
