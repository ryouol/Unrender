"""Run one model over an eval set and save predictions (with raw responses).

The durable schedule precedes provider dispatch. Resume preserves completed and
uncertain attempts without retrying them; only never-dispatched inputs can run.
Raw responses and failures remain available for offline scoring.

CPU harness smoke test (no API cost):
    python -m unrender.eval.run_baselines --provider perfect \
        --data data/synthetic/test.jsonl --limit 100

Real providers require an explicit model identity and incur external charges.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import threading
import time
from pathlib import Path

from tqdm import tqdm

from unrender.eval import providers as _providers
from unrender.eval.dataset import load_eval_samples
from unrender.eval.ledger import RUN_CONTRACT, RunLedger, atomic_text, run_owner, schedule_hash
from unrender.eval.metrics import classify_status, semantic_errors
from unrender.eval.providers import DEFAULT_MODELS, PROVIDERS, STALE_DEFAULT
from unrender.io_utils import fingerprint_ids
from unrender.prompts import EXTRACTION_PROMPT
from unrender.schema.chart_schema import ChartData
from unrender.schema.validate import PARSER_VERSION, parse_chart_json, strict_json


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_revision(model: str, revision=None):
    """Fingerprint local model bytes recursively; never call mtimes content hashes."""
    root = Path(model)
    if not root.exists():
        return revision
    if not root.is_dir():
        raise SystemExit("local model must be a directory")
    paths = list(root.rglob("*"))
    if any(path.is_symlink() and path.is_dir() for path in paths):
        raise SystemExit("local model contains an untracked directory symlink")
    files = sorted(path for path in paths if path.is_file())
    if not files:
        raise SystemExit("local model directory is empty")
    manifest = [(path.relative_to(root).as_posix(), _file_sha256(path)) for path in files]
    return hashlib.sha256(json.dumps(manifest).encode()).hexdigest()


_RUN_LOCK = threading.Lock()  # Providers share mutable decoder/cache state in this process.


def run(
    provider: str,
    model: str,
    data: str,
    out: str,
    limit: int,
    seed: int,
    only_ids=None,
    gen_config=None,
    revision=None,
    prompt: str = EXTRACTION_PROMPT,
) -> Path:
    if not _RUN_LOCK.acquire(blocking=False):
        raise SystemExit("another evaluation is active in this process")
    try:
        return _run(provider, model, data, out, limit, seed, only_ids, gen_config, revision, prompt)
    finally:
        _RUN_LOCK.release()


def _run(provider, model, data, out, limit, seed, only_ids, gen_config, revision, prompt):
    if provider not in PROVIDERS:
        raise SystemExit(f"Unknown provider '{provider}'. Choices: {sorted(PROVIDERS)}")
    if limit < 0:
        raise SystemExit("limit must be nonnegative")
    if (
        provider == "hf"
        and not Path(model).exists()
        and not re.fullmatch(r"[0-9a-f]{40}", revision or "")
    ):
        raise SystemExit("unpinned hf model: pass --revision <40-character commit-sha>")
    samples = load_eval_samples(data, limit=limit)
    dataset_fp = fingerprint_ids(s.id for s in samples)
    if len({sample.id for sample in samples}) != len(samples):
        raise SystemExit("duplicate input ids; each scheduled chart needs a unique identity")
    subset_fp = None
    if only_ids is not None:
        requested = list(only_ids)
        if not requested or len(set(requested)) != len(requested):
            raise SystemExit("subset must contain unique, nonempty ids")
        only_ids = set(requested)
        subset_fp = fingerprint_ids(only_ids)
        samples = [sample for sample in samples if sample.id in only_ids]
        if missing := only_ids - {sample.id for sample in samples}:
            raise SystemExit(f"subset-coverage failure: {len(missing)} requested ids are absent")
    if not samples:
        raise SystemExit("evaluation schedule is empty")
    schedule = []
    for sample in samples:
        try:
            gt = ChartData.model_validate(strict_json(sample.gt_json), strict=True)
            if errors := semantic_errors(gt):
                raise ValueError(", ".join(errors))
        except ValueError as exc:
            raise SystemExit(f"invalid ground truth for {sample.id}: {exc}") from exc
        image = Path(sample.image)
        try:
            image_sha256 = _file_sha256(image)
        except OSError:
            image_sha256 = None
        schedule.append(
            {
                "id": sample.id,
                "image": sample.image,
                "image_sha256": image_sha256,
                "gt": sample.gt_json,
                "meta": sample.meta,
            }
        )
    root = Path(__file__).resolve().parents[2]
    source_files = [
        "unrender/eval/run_baselines.py",
        "unrender/eval/ledger.py",
        "unrender/eval/providers.py",
        "unrender/eval/dataset.py",
        "unrender/eval/metrics.py",
        "unrender/io_utils.py",
        "unrender/prompts.py",
        "unrender/schema/validate.py",
        "unrender/schema/chart_schema.py",
    ]
    metadata = {
        "run_contract": RUN_CONTRACT,
        "provider": provider,
        "seed": seed,
        "dataset_sha256": _file_sha256(Path(data)),
        "attempt_policy": "durable_dispatch_no_automatic_retry_v1",
        "sdk_retry_policy": "not_attested",
        "durability_scope": "POSIX local filesystem fsync and host-local writer lock; "
        "remote-volume persistence and distributed ownership not attested",
        "seed_policy": "per_input_python_rng_only; GPU sampling seed not attested",
        "model": model,
        "model_revision": _model_revision(model, revision),
        "data": data,
        "limit": limit,
        "dataset_fp": dataset_fp,
        "gen_config": gen_config or {},
        "subset_fp": subset_fp,
        "n_subset": len(only_ids) if only_ids is not None else None,
        "n_scheduled": len(schedule),
        "schedule_sha256": schedule_hash(schedule),
        "prompt_fp": fingerprint_ids([prompt]),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "parser_version": PARSER_VERSION,
        "source_sha256": {name: _file_sha256(root / name) for name in source_files},
    }
    directory = Path(out) if out else Path("outputs/eval_reports") / f"{provider}__{_slug(model)}"
    with run_owner(directory):
        ledger = RunLedger(directory, metadata, schedule)
        try:
            atomic_text(directory / "meta.json", json.dumps(metadata, indent=2))
            ledger.recover()
            # Publish all scheduled rows before any inference. Readers use the
            # live ledger for fresh outcomes if a hard crash leaves this snapshot stale.
            ledger.export()
            _providers.HF_GEN_CONFIG.clear()
            _providers.HF_GEN_CONFIG.update(gen_config or {})
            _providers.HF_MODEL_CONFIG.clear()
            if revision:
                _providers.HF_MODEL_CONFIG["revision"] = revision
            if provider == "hf":
                _providers._HF_CACHE.clear()  # never reuse weights from a previous recipe
            for sample in tqdm(ledger.pending(), desc=f"{provider}:{model}"):
                error, raw = None, ""
                generation = {"finish_reason": "unrecorded"}
                if provider in {"perfect", "noisy"}:
                    generation["finish_reason"] = "not_applicable_reference"
                if provider not in {"perfect", "noisy"}:
                    try:
                        if sample["image_sha256"] is None or (
                            _file_sha256(Path(sample["image"])) != sample["image_sha256"]
                        ):
                            raise ValueError("input image missing or changed")
                    except (OSError, ValueError):
                        ledger.complete(
                            sample["id"],
                            {
                                "raw": "",
                                "pred": None,
                                "usage": {},
                                "status": "infra_error",
                                "parse_errors": [],
                                "error": "input_image_unavailable_or_changed",
                                "generation": generation,
                            },
                            dispatched=False,
                        )
                        continue
                _providers.LAST_USAGE.clear()
                ledger.dispatch(sample["id"])
                started = time.perf_counter()
                try:
                    input_seed = int.from_bytes(
                        hashlib.sha256(json.dumps([seed, sample["id"]]).encode()).digest(), "big"
                    )
                    kwargs = {"timings": generation} if provider == "hf" else {}
                    raw = PROVIDERS[provider](
                        sample["image"],
                        prompt,
                        model,
                        gt_json=sample["gt"],
                        rng=random.Random(input_seed),
                        **kwargs,
                    )
                    if not isinstance(raw, str):
                        raise TypeError("provider must return raw text")
                except Exception as exc:
                    # Errors may embed credentials/customer data. Keep a safe type,
                    # never a complete SDK response or another invocation.
                    error, raw = f"provider_call_failed:{type(exc).__name__}", ""
                parsed, diagnostics = parse_chart_json(raw) if raw else (None, ["empty_output"])
                ledger.complete(
                    sample["id"],
                    {
                        "raw": raw,
                        "pred": parsed.model_dump() if parsed else None,
                        "usage": dict(_providers.LAST_USAGE),
                        "generation": generation,
                        "status": classify_status(error, parsed),
                        "parse_errors": diagnostics,
                        "error": error,
                        "provider_roundtrip_seconds": time.perf_counter() - started,
                    },
                )
        finally:
            # KeyboardInterrupt/SystemExit get a portable full-schedule snapshot;
            # SIGKILL still leaves the committed SQLite ledger authoritative.
            try:
                ledger.export()
            finally:
                ledger.close()
    print(f"Wrote {directory / 'predictions.jsonl'}; durable schedule: {directory / 'run.sqlite3'}")
    return directory / "predictions.jsonl"


def main():
    from dotenv import load_dotenv

    # override=True so .env wins over a stale/empty key already in the environment
    # (e.g. the harness exports an empty ANTHROPIC_API_KEY since it uses that API).
    load_dotenv(override=True)
    p = argparse.ArgumentParser(description="Run a model over an eval set; save predictions.")
    p.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    p.add_argument(
        "--model", default=None, help="model id (defaults per provider; override frontier ones)"
    )
    p.add_argument("--data", default="data/synthetic/test.jsonl", help="eval set (chat JSONL)")
    p.add_argument(
        "--out", default=None, help="output dir (default outputs/eval_reports/<provider>__<model>)"
    )
    p.add_argument(
        "--limit", type=int, default=0, help="cap number of samples (0 = all) — control API cost"
    )
    p.add_argument("--seed", type=int, default=0, help="seed for the noisy mock provider")
    p.add_argument(
        "--subset", default=None, help="JSON file with an 'ids' list — eval ONLY those samples"
    )
    # hf decoder sweep (item 2): default greedy; these override per-arm.
    p.add_argument(
        "--repetition-penalty",
        type=float,
        default=0.0,
        help="hf: >1.0 penalizes repeats (e.g. 1.1, 1.3)",
    )
    p.add_argument(
        "--max-new-tokens", type=int, default=0, help="hf: token cap (0 => default 4096)"
    )
    p.add_argument("--do-sample", action="store_true", help="hf: sample instead of greedy")
    p.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="hf: sampling temperature (implies --do-sample)",
    )
    p.add_argument(
        "--revision",
        default=None,
        help="hf: pin the model to an exact Hub revision (base-model control)",
    )
    args = p.parse_args()

    model = args.model or DEFAULT_MODELS[args.provider]
    if args.provider in STALE_DEFAULT and not args.model:
        print(
            f"⚠  Using placeholder model '{model}' for {args.provider}. "
            f"Pass --model with the latest vision model available to you."
        )

    only_ids = None
    if args.subset:
        raw_ids = json.loads(Path(args.subset).read_text())["ids"]
        if len(raw_ids) != len(set(raw_ids)):  # a subset with dup ids over-weights charts
            raise SystemExit(
                f"subset {args.subset} has duplicate ids ({len(raw_ids)} listed, "
                f"{len(set(raw_ids))} unique) — refusing to score a skewed set."
            )
        only_ids = raw_ids
    gen_config = {}
    if args.repetition_penalty:
        gen_config["repetition_penalty"] = args.repetition_penalty
    if args.max_new_tokens:
        gen_config["max_new_tokens"] = args.max_new_tokens
    if args.temperature:
        gen_config["temperature"], gen_config["do_sample"] = args.temperature, True
    if args.do_sample:
        gen_config["do_sample"] = True
    run(
        args.provider,
        model,
        args.data,
        args.out,
        args.limit,
        args.seed,
        only_ids=only_ids,
        gen_config=gen_config or None,
        revision=args.revision,
    )


if __name__ == "__main__":
    main()
