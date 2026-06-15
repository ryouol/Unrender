"""Run the Phase-3 pipeline on Modal (serverless GPUs, per-second billing).

No box to rent or terminate: `modal run` ships the local `unrender` package to a
container, executes, and stops billing when it returns. Data, the HF model
cache, and training outputs live on one persistent Volume (`unrender-vol`) so
nothing is regenerated or re-downloaded between runs.

The pipeline, in order (from the repo root, .venv active):

    modal run modal_train.py::gen                 # once: v0+v1 data -> Volume (CPU, ~$0.3)
    modal run modal_train.py::smoke               # 30-step train + 5-image eval (~$0.5)
    modal run --detach modal_train.py::train      # the real run (L4, ~$2-4)
    modal run --detach modal_train.py::evaluate   # merged model over the 1000-chart test
    modal volume get unrender-vol outputs ./outputs/modal   # pull predictions/report
    modal volume get unrender-vol runs/qwen3vl4b-lora ./runs/qwen3vl4b-lora  # pull weights

Diagnostics from MODEL_STATUS_REVIEW.md (no retraining; ~$1-3 each on L4):

    # item 1 - base-model controls on a fixed stratified subset (build it locally
    # first: python -m unrender.eval.make_subset). Same prompt + decoder for all.
    # The base MUST be the Unsloth mirror the LoRA was trained on, PINNED to an
    # exact revision so its processor matches the merged model — an unpinned
    # Qwen/ HEAD is a different-processor confound (see PREREGISTRATION.md).
    modal run --detach modal_train.py::evaluate --model unsloth/Qwen3-VL-4B-Instruct --revision 252d592b59b0233b226875a44ac135cfa1d3f755 --subset common300
    UNRENDER_GPU=A100 modal run --detach modal_train.py::evaluate --model unsloth/Qwen3-VL-8B-Instruct --revision <8B-sha> --subset common300  # 8B locked until gate passes
    modal run --detach modal_train.py::evaluate --subset common300   # the LoRA on the same 300
    # item 2 - decoder sweep on the LoRA's invalid+valid charts (greedy vs rep penalty)
    modal run --detach modal_train.py::sweep

`--detach` keeps a run alive after you close the laptop (the tmux equivalent).
Pick the GPU per-invocation with e.g. `UNRENDER_GPU=A100 modal run ...` —
default L4 (24GB, ~$0.80/hr) fits the 4B QLoRA; use A100 for the 8B launch run.
"""

from __future__ import annotations

import os

import modal

app = modal.App("unrender")

VOL = modal.Volume.from_name("unrender-vol", create_if_missing=True)
V = "/vol"  # mount point; paths under it persist across runs

# GPU for train/eval, chosen at `modal run` time via env var (the decorator is
# evaluated locally, so this is the one knob that can't be a function arg).
GPU = os.environ.get("UNRENDER_GPU", "L4")

# Data-gen image pins the EXACT rendering stack from data/synthetic_*/README.md,
# so charts generated on the Volume are byte-identical to the frozen eval recipe
# (the committed test.jsonl ground truth describes these exact pixels).
gen_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("numpy==2.4.6", "matplotlib==3.10.9", "pillow==12.2.0",
                 "pydantic>=2.5", "tqdm>=4.66")
    .add_local_python_source("unrender")
)

# Train/eval image: the pyproject [train] extra + the eval scorer's deps.
# If the unsloth install ever fails to import on a fresh build, swap the base for
# modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11").
train_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("unsloth", "trl>=0.9", "peft>=0.11", "bitsandbytes>=0.43",
                 "transformers>=4.46", "accelerate>=0.34", "datasets>=2.20",
                 "pillow>=10.0", "pydantic>=2.5", "tqdm>=4.66",
                 "rapidfuzz>=3.6", "python-dotenv>=1.0")
    .env({
        "HF_HOME": f"{V}/.hf_cache",     # cache the ~9GB base model on the Volume once
        # Unsloth's auto-compiler code-gens a patched qwen3_vl module that (with
        # current transformers) contains a syntax error and crashes from_pretrained.
        # Disabling it falls back to stock transformers modeling: slightly slower,
        # fully correct. Revisit when unsloth/transformers re-sync.
        "UNSLOTH_COMPILE_DISABLE": "1",
    })
    .add_local_python_source("unrender")
)


# --- helpers shared by the eval/sweep functions (run inside the container) -----


def _resolve_model(model_path: str) -> str:
    """A Volume path (e.g. ``runs/.../merged``) -> ``/vol/...``; an absolute path
    -> as-is; anything else (e.g. ``Qwen/Qwen3-VL-4B-Instruct``) -> an HF hub id
    passed straight to from_pretrained, so base-model controls need no extra
    plumbing — the hf provider downloads/caches it on the Volume like any model."""
    from pathlib import Path
    if model_path.startswith("/"):
        return model_path
    if Path(f"{V}/{model_path}").exists():
        return f"{V}/{model_path}"
    return model_path


def _load_subset_ids(name: str):
    """Frozen subset name (e.g. ``common300``) -> the committed id list shipped in
    the package at ``unrender/eval/subsets/<name>.json``."""
    import json
    from pathlib import Path
    import unrender.eval as _ev
    return json.loads((Path(_ev.__file__).parent / "subsets" / f"{name}.json").read_text())["ids"]


def _eval_tag(mp: str, data: str, subset: str, gen_config: dict) -> str:
    """Stable, collision-free output dir name per (model, split, subset, decoder),
    so base/LoRA/8B and each sweep arm land in distinct folders. The plain
    LoRA-merged/no-subset/greedy case reproduces the original ``eval_v1__<run>``
    name, so re-runs still resume the existing predictions."""
    from pathlib import Path
    base = Path(mp.rstrip("/"))
    name = base.parent.name if base.name == "merged" else base.name
    parts = [f"eval_{data}", name]
    if subset:
        parts.append(subset)
    if gen_config.get("repetition_penalty"):
        parts.append(f"rp{gen_config['repetition_penalty']}")
    return "__".join(parts)


@app.function(image=gen_image, volumes={V: VOL}, cpu=8.0, memory=8192, timeout=2 * 3600)
def generate_data(n: int = 5000):
    """Regenerate v0 (easy) + v1 (hard) and split them, exactly per the frozen
    recipes. workers=8 matches the cpu reservation (os.cpu_count() in a container
    reports the host's cores, which would oversubscribe the pool)."""
    from unrender.data_gen.generate import generate
    from unrender.data_gen.split_dataset import split

    for name, seed, hard in (("synthetic_v0", 1234, False), ("synthetic_v1", 5678, True)):
        out = f"{V}/data/{name}"
        generate(n=n, out=out, base_seed=seed, hard=hard, workers=8)
        split(out=out, val_size=500, test_size=1000)
    VOL.commit()


@app.function(image=train_image, volumes={V: VOL}, gpu=GPU, cpu=4.0, memory=32768, timeout=12 * 3600)
def train_model(
    train_files: str = "v1,v0",
    out_name: str = "qwen3vl4b-lora",
    base: str = "Qwen/Qwen3-VL-4B-Instruct",
    labelfree_weight: float = 1.5,
    epochs: float = 2.0,
    max_steps: int = 0,
    batch_size: int = 2,
    grad_accum: int = 4,
    lora_r: int = 16,
):
    from unrender.train.sft_lora import train

    paths = [f"{V}/data/synthetic_{t.strip()}/train.jsonl" for t in train_files.split(",")]
    train(
        train_paths=paths,
        out=f"{V}/runs/{out_name}",
        base=base,
        data_root=V,
        labelfree_weight=labelfree_weight,
        epochs=epochs,
        max_steps=max_steps,
        batch_size=batch_size,
        grad_accum=grad_accum,
        lora_r=lora_r,
    )
    VOL.commit()


@app.function(image=train_image, volumes={V: VOL}, gpu=GPU, cpu=4.0, memory=32768, timeout=20 * 3600)
def eval_model(model_path: str, data: str = "v1", limit: int = 0, out_name: str = "",
               subset: str = "", subset_ids=None, repetition_penalty: float = 0.0,
               max_new_tokens: int = 0, revision: str = ""):
    """Run a model over a test split through the SAME harness as the frontier
    baselines, then print the sliced score report. ``model_path`` is a Volume
    run dir OR an HF hub id (``Qwen/Qwen3-VL-4B-Instruct``) for the base-model
    controls (item 1). ``subset_ids`` (resolved locally by the entrypoint from a
    name like ``common300``) restricts to that frozen id list; ``subset`` is kept
    only to label the output dir. ``repetition_penalty``/``max_new_tokens``
    override decoding (item 2). Resumable: predictions.jsonl persists on the
    Volume, so a re-run skips done ids."""
    import subprocess
    from pathlib import Path

    from unrender.eval.run_baselines import run

    mp = _resolve_model(model_path)
    # ids arrive as an arg (the entrypoint reads the committed JSON on your Mac),
    # so the container never depends on a non-.py file being mounted.
    only_ids = subset_ids or None
    gen_config = {}
    if repetition_penalty:
        gen_config["repetition_penalty"] = repetition_penalty
    if max_new_tokens:
        gen_config["max_new_tokens"] = max_new_tokens

    out_dir = f"{V}/outputs/{out_name or _eval_tag(mp, data, subset, gen_config)}"
    pred = run(
        provider="hf", model=mp,
        data=f"{V}/data/synthetic_{data}/test.jsonl",
        out=out_dir, limit=limit, seed=0,
        only_ids=only_ids, gen_config=gen_config or None, revision=revision or None,
    )
    VOL.commit()
    # score.py prints its report in main(); run it as the CLI so logs show the
    # exact table you'd see locally (cwd=/root is where the package is mounted).
    # Pass --subset so the base report records the SAME subset_fp as the LoRA's
    # subset report (provenance symmetry) and re-asserts coverage.
    score_cmd = ["python", "-m", "unrender.eval.score", "--predictions", str(pred)]
    if subset:
        import unrender.eval as _ev
        score_cmd += ["--subset", str(Path(_ev.__file__).parent / "subsets" / f"{subset}.json")]
    subprocess.run(score_cmd, check=True, cwd="/root")
    VOL.commit()


@app.function(image=train_image, volumes={V: VOL}, gpu=GPU, cpu=4.0, memory=32768, timeout=20 * 3600)
def sweep_model(
    model_path: str = "runs/qwen3vl4b-lora/merged",
    lora_pred_dir: str = "outputs/eval_v1__qwen3vl4b-lora",
    data: str = "v1",
    n_valid: int = 200,
    penalties: str = "1.1,1.3",
):
    """Decoder sweep WITHOUT retraining (item 2). Subset = every model_invalid id
    from the full LoRA eval + ``n_valid`` random ok ids (seeded). The greedy
    control is read FOR FREE from the existing predictions (those ids are invalid
    precisely because greedy looped); only the repetition_penalty arms generate,
    and the ~8GB model loads once for all of them. Per the review's rule: adopt an
    arm only if invalid drops below 1% AND cell@5% on the previously-valid charts
    falls by no more than 1 point."""
    import random
    from pathlib import Path

    from unrender.io_utils import read_jsonl
    from unrender.eval.run_baselines import run
    from unrender.eval.score import score_rows, row_status

    mp = _resolve_model(model_path)
    full = read_jsonl(Path(f"{V}/{lora_pred_dir}/predictions.jsonl"))
    invalid_ids = [r["id"] for r in full if row_status(r) == "model_invalid"]
    ok_ids = [r["id"] for r in full if row_status(r) == "ok"]
    random.Random(0).shuffle(ok_ids)
    valid_ids = set(ok_ids[:n_valid])
    subset_ids = set(invalid_ids) | valid_ids
    print(f"[sweep] subset: {len(invalid_ids)} invalid + {len(valid_ids)} valid = {len(subset_ids)} charts")

    def _summarize(rows, arm):
        a = score_rows(rows, 0.05, only_ids=subset_ids)
        av = score_rows(rows, 0.05, only_ids=valid_ids)
        n = a["metrics"]["n"]
        return {"arm": arm, "invalid": a["n_model_invalid"], "n": n,
                "invalid_pct": (a["n_model_invalid"] / n * 100) if n else 0.0,
                "cell": a["metrics"]["cell_accuracy"] * 100,
                "valid_cell": av["metrics"]["cell_accuracy"] * 100}

    results = [_summarize(full, "greedy")]  # control — no generation
    valid_floor = results[0]["valid_cell"]

    data_path = f"{V}/data/synthetic_{data}/test.jsonl"
    for rp in [float(x) for x in penalties.split(",") if x.strip()]:
        pred = run(provider="hf", model=mp, data=data_path,
                   out=f"{V}/outputs/sweep_{data}__rp{rp}", limit=0, seed=0,
                   only_ids=subset_ids, gen_config={"repetition_penalty": rp})
        VOL.commit()
        results.append(_summarize(read_jsonl(Path(pred)), f"rep{rp}"))

    print(f"\n=== decoder sweep  (subset N={len(subset_ids)}, greedy valid-cell floor={valid_floor:.1f}%) ===")
    print(f"{'arm':<10}{'invalid':>9}{'invalid%':>10}{'cell@5%':>10}{'valid-cell':>12}  verdict")
    for r in results:
        ok = r["invalid_pct"] < 1.0 and (valid_floor - r["valid_cell"]) <= 1.0
        verdict = "" if r["arm"] == "greedy" else ("ADOPT" if ok else "reject")
        print(f"{r['arm']:<10}{r['invalid']:>9}{r['invalid_pct']:>9.1f}%{r['cell']:>9.1f}%{r['valid_cell']:>11.1f}%  {verdict}")


@app.function(image=train_image, volumes={V: VOL}, gpu=GPU, cpu=4.0, memory=32768, timeout=1800)
def probe_model(model_path: str):
    """Load a saved model the exact way hf_vlm_provider does, one piece at a
    time, with full tracebacks — for debugging broken exports without burning a
    full eval run."""
    import traceback

    from transformers import AutoModelForImageTextToText, AutoProcessor

    mp = model_path if model_path.startswith("/") else f"{V}/{model_path}"
    proc = net = None
    for name, fn in (
        ("AutoProcessor", lambda: AutoProcessor.from_pretrained(mp, trust_remote_code=True)),
        ("AutoModel", lambda: AutoModelForImageTextToText.from_pretrained(
            mp, torch_dtype="auto", device_map="auto", trust_remote_code=True)),
    ):
        try:
            obj = fn()
            print(f"[probe] {name}: OK ({type(obj).__name__})")
            proc, net = (obj, net) if name == "AutoProcessor" else (proc, obj)
        except Exception:
            print(f"[probe] {name}: FAILED")
            traceback.print_exc()
            return
    # One real generation against a volume image, exactly like the provider.
    import glob

    import torch
    from PIL import Image

    img_path = sorted(glob.glob(f"{V}/data/synthetic_v1/images/*.png"))[0]
    messages = [{"role": "user", "content": [
        {"type": "image", "image": img_path}, {"type": "text", "text": "Extract the data as JSON."}]}]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = proc(text=[text], images=[Image.open(img_path).convert("RGB")], return_tensors="pt").to(net.device)
    with torch.no_grad():
        out = net.generate(**inputs, max_new_tokens=64, do_sample=False)
    print("[probe] generate: OK ->", proc.decode(out[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True)[:200])


# --- local entrypoints (what you `modal run`) ---------------------------------


@app.local_entrypoint()
def probe(model: str = "runs/smoke/merged"):
    probe_model.remote(model_path=model)

@app.local_entrypoint()
def gen(n: int = 5000):
    generate_data.remote(n=n)


@app.local_entrypoint()
def smoke():
    """End-to-end insurance before spending real hours: 30 train steps, save +
    merge, then eval 5 images through the hf provider (proves the merged model
    loads back). Total ~$0.5, mostly the one-time base-model download."""
    train_model.remote(train_files="v1", out_name="smoke", max_steps=30)
    eval_model.remote(model_path="runs/smoke/merged", data="v1", limit=5)


@app.local_entrypoint()
def train(
    train_files: str = "v1,v0",
    out_name: str = "qwen3vl4b-lora",
    base: str = "Qwen/Qwen3-VL-4B-Instruct",
    labelfree_weight: float = 1.5,
    epochs: float = 2.0,
    max_steps: int = 0,
    batch_size: int = 2,
    grad_accum: int = 4,
    lora_r: int = 16,
):
    train_model.remote(
        train_files=train_files, out_name=out_name, base=base,
        labelfree_weight=labelfree_weight, epochs=epochs, max_steps=max_steps,
        batch_size=batch_size, grad_accum=grad_accum, lora_r=lora_r,
    )


@app.local_entrypoint()
def evaluate(model: str = "runs/qwen3vl4b-lora/merged", data: str = "v1", limit: int = 0,
             subset: str = "", repetition_penalty: float = 0.0, max_new_tokens: int = 0,
             revision: str = ""):
    """Eval one model. Examples (item 1 base-model controls on the frozen subset):
        modal run modal_train.py::evaluate --model unsloth/Qwen3-VL-4B-Instruct --revision 252d592b59b0233b226875a44ac135cfa1d3f755 --subset common300
        modal run modal_train.py::evaluate --subset common300   # the LoRA on the same 300 (apples-to-apples)

    `--revision` pins a Hub base to an exact commit; the base control must use the
    Unsloth mirror + matching revision (PREREGISTRATION.md), not an unpinned HEAD.
    """
    # Resolve the frozen id list LOCALLY (the repo has it) and pass it as an arg,
    # so the container needs no data-file mount.
    ids = _load_subset_ids(subset) if subset else None
    eval_model.remote(model_path=model, data=data, limit=limit, subset=subset, subset_ids=ids,
                      repetition_penalty=repetition_penalty, max_new_tokens=max_new_tokens,
                      revision=revision)


@app.local_entrypoint()
def sweep(model: str = "runs/qwen3vl4b-lora/merged",
          lora_pred_dir: str = "outputs/eval_v1__qwen3vl4b-lora",
          data: str = "v1", n_valid: int = 200, penalties: str = "1.1,1.3"):
    """Decoder sweep on the LoRA (item 2): greedy control (free) vs repetition
    penalties, on the invalid+valid subset. One model load, prints an ADOPT table.
        modal run --detach modal_train.py::sweep
    """
    sweep_model.remote(model_path=model, lora_pred_dir=lora_pred_dir, data=data,
                       n_valid=n_valid, penalties=penalties)
