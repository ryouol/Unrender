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
from pathlib import Path

from tqdm import tqdm

from unrender.eval.dataset import load_eval_samples
from unrender.eval.providers import DEFAULT_MODELS, PROVIDERS, STALE_DEFAULT
from unrender.io_utils import read_jsonl
from unrender.prompts import EXTRACTION_PROMPT
from unrender.schema.validate import parse_chart_json


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")


def run(provider: str, model: str, data: str, out: str, limit: int, seed: int) -> Path:
    if provider not in PROVIDERS:
        raise SystemExit(f"Unknown provider '{provider}'. Choices: {sorted(PROVIDERS)}")
    fn = PROVIDERS[provider]
    samples = load_eval_samples(data, limit=limit)

    out_dir = Path(out) if out else Path("outputs/eval_reports") / f"{provider}__{_slug(model)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / "predictions.jsonl"

    # Resume only over SUCCESSFUL attempts; rows that recorded a transport error
    # are dropped so they get retried (a rate-limit on Monday shouldn't be frozen
    # into the benchmark forever). Rewrite the file without them to avoid dupe ids.
    done = set()
    if pred_path.exists():
        existing = read_jsonl(pred_path)
        keep = [r for r in existing if not r.get("error")]
        done = {r["id"] for r in keep}
        if len(keep) != len(existing):
            with open(pred_path, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(r) + "\n" for r in keep)
            print(f"Resuming: kept {len(keep)} ok, retrying {len(existing) - len(keep)} failed.")
        elif done:
            print(f"Resuming: {len(done)} predictions already present, skipping those.")

    (out_dir / "meta.json").write_text(json.dumps({"provider": provider, "model": model, "data": data}, indent=2))

    rng = random.Random(seed)
    n_ok = n_err = 0
    with open(pred_path, "a", encoding="utf-8") as f:
        for s in tqdm([x for x in samples if x.id not in done], desc=f"{provider}:{model}"):
            error = None
            try:
                raw = fn(s.image, EXTRACTION_PROMPT, model, gt_json=s.gt_json, rng=rng)
            except Exception as e:  # one bad sample shouldn't kill the whole run
                raw, error = "", f"{type(e).__name__}: {e}"
            parsed, perrs = parse_chart_json(raw) if raw else (None, ["empty"])
            f.write(json.dumps({
                "id": s.id, "image": s.image, "gt": s.gt_json, "meta": s.meta,
                "raw": raw, "pred": parsed.model_dump() if parsed else None,
                "parse_errors": perrs, "error": error,
            }) + "\n")
            f.flush()
            n_err += int(error is not None)
            n_ok += int(error is None)

    print(f"Wrote {pred_path}  (ok={n_ok}, errors={n_err}, skipped={len(done)})")
    return pred_path


def main():
    p = argparse.ArgumentParser(description="Run a model over an eval set; save predictions.")
    p.add_argument("--provider", required=True, choices=sorted(PROVIDERS))
    p.add_argument("--model", default=None, help="model id (defaults per provider; override frontier ones)")
    p.add_argument("--data", default="data/synthetic/test.jsonl", help="eval set (chat JSONL)")
    p.add_argument("--out", default=None, help="output dir (default outputs/eval_reports/<provider>__<model>)")
    p.add_argument("--limit", type=int, default=0, help="cap number of samples (0 = all) — control API cost")
    p.add_argument("--seed", type=int, default=0, help="seed for the noisy mock provider")
    args = p.parse_args()

    model = args.model or DEFAULT_MODELS[args.provider]
    if args.provider in STALE_DEFAULT and not args.model:
        print(f"⚠  Using placeholder model '{model}' for {args.provider}. "
              f"Pass --model with the latest vision model available to you.")
    run(args.provider, model, args.data, args.out, args.limit, args.seed)


if __name__ == "__main__":
    main()
