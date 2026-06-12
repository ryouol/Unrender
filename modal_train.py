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


@app.function(image=train_image, volumes={V: VOL}, gpu=GPU, cpu=4.0, memory=32768, timeout=8 * 3600)
def eval_model(model_path: str, data: str = "v1", limit: int = 0, out_name: str = ""):
    """Run the merged model over a frozen test split through the SAME harness as
    the frontier baselines, then print the sliced score report. Resumable: the
    predictions.jsonl persists on the Volume, so a re-run skips finished ids."""
    import subprocess
    from pathlib import Path

    from unrender.eval.run_baselines import run

    mp = model_path if model_path.startswith("/") else f"{V}/{model_path}"
    out_dir = f"{V}/outputs/{out_name or 'eval_' + data + '__' + Path(mp).parent.name}"
    pred = run(
        provider="hf", model=mp,
        data=f"{V}/data/synthetic_{data}/test.jsonl",
        out=out_dir, limit=limit, seed=0,
    )
    VOL.commit()
    # score.py prints its report in main(); run it as the CLI so logs show the
    # exact table you'd see locally (cwd=/root is where the package is mounted).
    subprocess.run(
        ["python", "-m", "unrender.eval.score", "--predictions", str(pred)],
        check=True, cwd="/root",
    )
    VOL.commit()


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
def evaluate(model: str = "runs/qwen3vl4b-lora/merged", data: str = "v1", limit: int = 0):
    eval_model.remote(model_path=model, data=data, limit=limit)
