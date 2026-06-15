"""Run one model over an eval set and save predictions (with raw responses).

Resumable: if predictions.jsonl already has a sample's id, it's skipped — so an
interrupted/expensive API run resumes instead of re-paying. Every raw response
is saved, so you can re-score later for free with score.py.

Examples:
    # Verify the harness end-to-end with no API cost:
    python -m unrender.eval.run_baselines --provider perfect --data data/synthetic/test.jsonl --limit 100

    # Real frontier baseline (set keys in .env first; pass the latest model id):
    python -m unrender.eval.run_baselines --provider anthropic --data data/synthetic/test.jsonl --limit 300
    python -m unrender.eval.run_baselines --provider openai --model <latest-gpt-vision> --data data/synthetic/test.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from tqdm import tqdm

from unrender.eval.dataset import load_eval_samples
from unrender.eval.providers import DEFAULT_MODELS, PROVIDERS, STALE_DEFAULT
from unrender.io_utils import read_jsonl, fingerprint_ids
from unrender.eval import providers as _providers
from unrender.eval.metrics import classify_status
from unrender.prompts import EXTRACTION_PROMPT
from unrender.schema.validate import parse_chart_json


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def _is_rate_limit(e: Exception) -> bool:
    s = str(e).lower()
    return any(k in s for k in ("429", "resource_exhausted", "rate limit", "overloaded"))


def _model_revision(model: str, revision=None):
    """Best-effort revision tag so a report records WHICH weights produced it. For
    a local dir (merged model / adapter) a fingerprint of its top-level files'
    (name, size, mtime); for an HF hub id, the explicitly pinned ``revision`` —
    None means UNPINNED, which a base-model control must never be (an unpinned Hub
    HEAD can drift from the exact weights the LoRA was trained on)."""
    p = Path(model)
    if not p.exists():
        return revision
    sig = sorted((f.name, f.stat().st_size, int(f.stat().st_mtime))
                 for f in p.iterdir() if f.is_file())
    return fingerprint_ids([repr(sig)])


def run(provider: str, model: str, data: str, out: str, limit: int, seed: int,
        only_ids=None, gen_config=None, revision=None) -> Path:
    if provider not in PROVIDERS:
        raise SystemExit(f"Unknown provider '{provider}'. Choices: {sorted(PROVIDERS)}")
    fn = PROVIDERS[provider]
    samples = load_eval_samples(data, limit=limit)
    dataset_fp = fingerprint_ids(s.id for s in samples)  # identity of the split actually loaded
    subset_fp = None
    if only_ids is not None:  # fixed stratified subset / decoder-sweep set (A6-style)
        only_ids = set(only_ids)
        subset_fp = fingerprint_ids(only_ids)
        samples = [s for s in samples if s.id in only_ids]
        # STRICT subset-coverage: never silently score fewer charts than requested.
        # A missing id means the subset was built against a different split (the
        # dev300/Modal-test desync), so the reported N would be smaller and no longer
        # stratified — fail loudly instead.
        missing = only_ids - {s.id for s in samples}
        if missing:
            raise SystemExit(
                f"subset-coverage failure: {len(missing)}/{len(only_ids)} requested ids are absent "
                f"from {data} (e.g. {sorted(missing)[:5]}). The subset and the data split do not "
                f"match — refusing to silently score N={len(samples)}.")

    # Decoder config for the hf provider's sweep (repetition_penalty, etc.); other
    # providers ignore it. Set once before the loop so every call uses it.
    _providers.HF_GEN_CONFIG.clear()
    if gen_config:
        _providers.HF_GEN_CONFIG.update(gen_config)
    # Pinned Hub revision for the hf provider (base-model control); empty => default.
    _providers.HF_MODEL_CONFIG.clear()
    if revision:
        _providers.HF_MODEL_CONFIG["revision"] = revision

    out_dir = Path(out) if out else Path("outputs/eval_reports") / f"{provider}__{_slug(model)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.jsonl"

    # Integrity record for this run; also the source of the resume-config guard below.
    meta_new = {
        "provider": provider, "model": model, "model_revision": _model_revision(model, revision),
        "data": data, "limit": limit, "dataset_fp": dataset_fp,
        "gen_config": gen_config or {}, "subset_fp": subset_fp,
        "n_subset": (len(only_ids) if only_ids is not None else None),
    }

    # Resume keeps ok + model_invalid (real model answers) and retries only
    # infra_error rows (429/quota/network) — a transient failure shouldn't be
    # frozen into the benchmark. Rewrite without the infra_error rows to avoid
    # duplicate ids. (Handles old rows with no "status" via classify_status.)
    def _status(r):
        return r.get("status") or classify_status(r.get("error"), r.get("pred"))

    done = set()
    if pred_path.exists():
        # resume-config guard: refuse to append onto predictions written under a
        # different model/decoder/subset/split — mixing incomparable rows silently
        # corrupts the report. Force a fresh --out dir instead.
        meta_old_path = out_dir / "meta.json"
        if meta_old_path.exists():
            old = json.loads(meta_old_path.read_text())
            for k in ("model", "model_revision", "gen_config", "subset_fp", "dataset_fp"):
                if k in old and old.get(k) != meta_new[k]:
                    raise SystemExit(
                        f"resume-config mismatch on '{k}': existing predictions in {out_dir} were "
                        f"written with {k}={old.get(k)!r}, but this run uses {meta_new[k]!r}. "
                        f"Use a fresh --out dir rather than appending incomparable rows.")
        existing = read_jsonl(pred_path)
        keep = [r for r in existing if _status(r) != "infra_error"]
        done = {r["id"] for r in keep}
        if len(keep) != len(existing):
            with open(pred_path, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(r) + "\n" for r in keep)
            print(f"Resuming: kept {len(keep)}, retrying {len(existing) - len(keep)} infra_error.")
        elif done:
            print(f"Resuming: {len(done)} predictions already present, skipping those.")

    (out_dir / "meta.json").write_text(json.dumps(meta_new, indent=2))

    rng = random.Random(seed)
    n_ok = n_err = 0
    with open(pred_path, "a", encoding="utf-8") as f:
        for s in tqdm([x for x in samples if x.id not in done], desc=f"{provider}:{model}"):
            error, raw = None, ""
            _providers.LAST_USAGE.clear()  # observability only; reset before each call
            for attempt in range(6):  # retry transient 429s with exponential backoff
                try:
                    raw = fn(s.image, EXTRACTION_PROMPT, model, gt_json=s.gt_json, rng=rng)
                    error = None
                    break
                except Exception as e:  # one bad sample shouldn't kill the whole run
                    error = f"{type(e).__name__}: {e}"
                    if _is_rate_limit(e) and attempt < 5:
                        time.sleep(min(5 * 2 ** attempt, 60))  # 5,10,20,40,60s
                        continue
                    raw = ""
                    break
            parsed, perrs = parse_chart_json(raw) if raw else (None, ["empty"])
            status = classify_status(error, parsed)
            f.write(json.dumps({
                "id": s.id, "image": s.image, "gt": s.gt_json, "meta": s.meta,
                "raw": raw, "pred": parsed.model_dump() if parsed else None,
                "usage": dict(_providers.LAST_USAGE),
                "status": status, "parse_errors": perrs, "error": error,
            }) + "\n")
            f.flush()
            n_err += int(error is not None)
            n_ok += int(error is None)

    print(f"Wrote {pred_path}  (ok={n_ok}, errors={n_err}, skipped={len(done)})")
    return pred_path


def main():
    from dotenv import load_dotenv

    # override=True so .env wins over a stale/empty key already in the environment
    # (e.g. the harness exports an empty ANTHROPIC_API_KEY since it uses that API).
    load_dotenv(override=True)
    p = argparse.ArgumentParser(description="Run a model over an eval set; save predictions.")
    p.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    p.add_argument("--model", default=None, help="model id (defaults per provider; override frontier ones)")
    p.add_argument("--data", default="data/synthetic/test.jsonl", help="eval set (chat JSONL)")
    p.add_argument("--out", default=None, help="output dir (default outputs/eval_reports/<provider>__<model>)")
    p.add_argument("--limit", type=int, default=0, help="cap number of samples (0 = all) — control API cost")
    p.add_argument("--seed", type=int, default=0, help="seed for the noisy mock provider")
    p.add_argument("--subset", default=None, help="JSON file with an 'ids' list — eval ONLY those samples")
    # hf decoder sweep (item 2): default greedy; these override per-arm.
    p.add_argument("--repetition-penalty", type=float, default=0.0, help="hf: >1.0 penalizes repeats (e.g. 1.1, 1.3)")
    p.add_argument("--max-new-tokens", type=int, default=0, help="hf: token cap (0 => default 4096)")
    p.add_argument("--do-sample", action="store_true", help="hf: sample instead of greedy")
    p.add_argument("--temperature", type=float, default=0.0, help="hf: sampling temperature (implies --do-sample)")
    p.add_argument("--revision", default=None, help="hf: pin the model to an exact Hub revision (base-model control)")
    args = p.parse_args()

    model = args.model or DEFAULT_MODELS[args.provider]
    if args.provider in STALE_DEFAULT and not args.model:
        print(f"⚠  Using placeholder model '{model}' for {args.provider}. "
              f"Pass --model with the latest vision model available to you.")

    only_ids = None
    if args.subset:
        raw_ids = json.loads(Path(args.subset).read_text())["ids"]
        if len(raw_ids) != len(set(raw_ids)):  # a subset with dup ids over-weights charts
            raise SystemExit(f"subset {args.subset} has duplicate ids ({len(raw_ids)} listed, "
                             f"{len(set(raw_ids))} unique) — refusing to score a skewed set.")
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
    run(args.provider, model, args.data, args.out, args.limit, args.seed,
        only_ids=only_ids, gen_config=gen_config or None, revision=args.revision)


if __name__ == "__main__":
    main()
