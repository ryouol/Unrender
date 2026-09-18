"""Content-address an isolated serving experiment and launch its exact configuration."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from unrender.prompts import EXTRACTION_PROMPT
from unrender.schema.chart_schema import ChartData


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Use a materialized, read-only snapshot, not symlinks")
        if path.is_file():
            with path.open("rb") as handle:
                files[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    handle, "sha256"
                ).hexdigest()
    if not files or "config.json" not in files:
        raise ValueError("Model snapshot is missing config.json")
    return files


def model_name(manifest: dict) -> str:
    return "unrender-" + digest(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    )


def command(manifest: dict, snapshot: Path) -> list[str]:
    return [
        "vllm",
        "serve",
        str(snapshot.resolve()),
        "--host",
        "127.0.0.1",
        "--port",
        "8001",
        "--served-model-name",
        model_name(manifest),
        "--dtype",
        manifest["dtype"],
        "--max-model-len",
        str(manifest["max_model_len"]),
        "--max-num-seqs",
        str(manifest["max_num_seqs"]),
        "--max-num-batched-tokens",
        str(manifest["max_num_batched_tokens"]),
        "--gpu-memory-utilization",
        str(manifest["gpu_memory_utilization"]),
        "--enable-prefix-caching" if manifest["prefix_caching"] else "--no-enable-prefix-caching",
        "--limit-mm-per-prompt",
        '{"image":1}',
        "--seed",
        "0",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "manifest", "launch"])
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--vllm-version", help="Exact version selected for the GPU canary")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--dtype", choices=["bfloat16", "float16"], default="bfloat16")
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--max-num-seqs", type=int, default=4)
    parser.add_argument("--max-num-batched-tokens", type=int, default=8192)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.8)
    parser.add_argument("--prefix-caching", action="store_true")
    args = parser.parse_args()
    if args.action == "preflight":
        gpu = shutil.which("nvidia-smi")
        evidence = {
            "platform": platform.platform(),
            "architecture": platform.machine(),
            "candidate_vllm": args.vllm_version,
            "gpu_available": bool(gpu),
            "status": "requires_gpu_canary" if gpu else "blocked_no_nvidia_host",
        }
        if gpu:
            result = subprocess.run(
                [gpu, "--query-gpu=name,uuid,driver_version,memory.total", "--format=csv"],
                capture_output=True,
                text=True,
                check=False,
            )
            evidence.update(gpu_probe=result.stdout, gpu_probe_exit=result.returncode)
        print(json.dumps(evidence, indent=2))
        return
    if args.snapshot is None or args.manifest is None:
        parser.error("--snapshot and --manifest are required")
    if args.action == "manifest":
        if not args.vllm_version:
            parser.error("--vllm-version is required; validate this exact runtime on the GPU")
        if (
            min(args.max_model_len, args.max_num_seqs, args.max_num_batched_tokens) <= 0
            or not 0 < args.gpu_memory_utilization <= 0.9
        ):
            parser.error("Positive scheduler limits and memory utilization <= 0.9 required")
        config = json.loads((args.snapshot / "config.json").read_text())
        if config.get("quantization_config") or (args.snapshot / "adapter_config.json").exists():
            parser.error(
                "Baseline requires merged higher-precision weights; "
                "adapter/quantization is a separate gate"
            )
        manifest = {
            "format": 1,
            "vllm": args.vllm_version,
            "files": inventory(args.snapshot),
            "architectures": config.get("architectures"),
            "dtype": args.dtype,
            "max_model_len": args.max_model_len,
            "max_num_seqs": args.max_num_seqs,
            "max_num_batched_tokens": args.max_num_batched_tokens,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "prefix_caching": args.prefix_caching,
            "prompt_sha256": digest(EXTRACTION_PROMPT.encode()),
            "schema_sha256": digest(
                json.dumps(ChartData.model_json_schema(), sort_keys=True).encode()
            ),
        }
        with args.manifest.open("x") as handle:
            json.dump(manifest, handle, indent=2)
        print(model_name(manifest))
        return
    manifest = json.loads(args.manifest.read_text())
    if importlib.metadata.version("vllm") != manifest["vllm"]:
        raise SystemExit("Runtime release mismatch")
    if inventory(args.snapshot) != manifest["files"]:
        raise SystemExit("Snapshot content mismatch")
    if manifest["prompt_sha256"] != digest(EXTRACTION_PROMPT.encode()):
        raise SystemExit("Prompt mismatch")
    if manifest["schema_sha256"] != digest(
        json.dumps(ChartData.model_json_schema(), sort_keys=True).encode()
    ):
        raise SystemExit("Schema mismatch")
    if not os.environ.get("VLLM_API_KEY"):
        raise SystemExit("Set VLLM_API_KEY through your secret manager")
    argv = command(manifest, args.snapshot)
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()
