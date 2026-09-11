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
    modal run --detach modal_train.py::evaluate \
        --model unsloth/Qwen3-VL-4B-Instruct \
        --revision 252d592b59b0233b226875a44ac135cfa1d3f755 --subset common300
    UNRENDER_GPU=A100 modal run --detach modal_train.py::evaluate \
        --model unsloth/Qwen3-VL-8B-Instruct \
        --revision <8B-sha> --subset common300  # locked until gate passes
    modal run --detach modal_train.py::evaluate --subset common300   # the LoRA on the same 300
    # item 2 - decoder sweep on the LoRA's invalid+valid charts (greedy vs rep penalty)
    modal run --detach modal_train.py::sweep

`--detach` keeps a run alive after you close the laptop (the tmux equivalent).
Pick the GPU per-invocation with e.g. `UNRENDER_GPU=A100 modal run ...` —
default L4 (24GB, ~$0.80/hr) fits the 4B QLoRA; use A100 for the 8B launch run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import shutil
import stat
import tempfile
import uuid
from contextlib import suppress
from pathlib import Path

import modal

app = modal.App("unrender")
production_app = modal.App("unrender-production")

# Production inference is deliberately separate from the mutable research image.
# This contract changes automatically when any reviewed provider/schema source
# changes, rather than relying on an operator to remember a manual version bump.
INFER_PROVIDER_CONTRACT = "unrender-infer-one-v2"
INFER_DIRECT_DEPENDENCIES = {
    "accelerate": "1.12.0",
    "huggingface-hub": "0.36.0",
    "pillow": "12.3.0",
    "pydantic": "2.13.5",
    "torch": "2.9.1",
    "torchvision": "0.24.1",
    "transformers": "4.57.6",
}
_MODEL_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MODEL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _inference_source_digest() -> str:
    root = Path(__file__).resolve().parent
    paths = (
        Path("modal_train.py"),
        Path("unrender/eval/__init__.py"),
        Path("unrender/eval/providers.py"),
        Path("unrender/prompts.py"),
        Path("unrender/schema/chart_schema.py"),
        Path("unrender/schema/json_to_csv.py"),
        Path("unrender/schema/validate.py"),
    )
    digest = hashlib.sha256()
    for relative in paths:
        payload = (root / relative).read_bytes()
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


INFER_SOURCE_SHA256 = _inference_source_digest()

VOL = modal.Volume.from_name("unrender-vol", create_if_missing=True)
V = "/vol"  # mount point; paths under it persist across runs
INFER_VOL = modal.Volume.from_name("unrender-inference-cache", create_if_missing=True)
INFER_V = "/model-cache"

# GPU for train/eval, chosen at `modal run` time via env var (the decorator is
# evaluated locally, so this is the one knob that can't be a function arg).
GPU = os.environ.get("UNRENDER_GPU", "L4")

# Data-gen image pins the EXACT rendering stack from data/synthetic_*/README.md,
# so charts generated on the Volume are byte-identical to the frozen eval recipe
# (the committed test.jsonl ground truth describes these exact pixels).
gen_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "numpy==2.4.6",
        "matplotlib==3.10.9",
        "pillow==12.2.0",
        "pydantic>=2.5",
        "tqdm>=4.66",
    )
    .add_local_python_source("unrender")
)

# Train/eval image: the pyproject [train] extra + the eval scorer's deps.
# If the unsloth install ever fails to import on a fresh build, swap the base for
# modal.Image.from_registry("nvidia/cuda:12.4.1-devel-ubuntu22.04", add_python="3.11").
train_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "unsloth",
        "trl>=0.9",
        "peft>=0.11",
        "bitsandbytes>=0.43",
        "transformers>=4.46",
        "accelerate>=0.34",
        "datasets>=2.20",
        "pillow>=10.0",
        "pydantic>=2.5",
        "tqdm>=4.66",
        "rapidfuzz>=3.6",
        "python-dotenv>=1.0",
    )
    .env(
        {
            "HF_HOME": f"{V}/.hf_cache",  # cache the ~9GB base model on the Volume once
            # Unsloth's auto-compiler code-gens a patched qwen3_vl module that (with
            # current transformers) contains a syntax error and crashes from_pretrained.
            # Disabling it falls back to stock transformers modeling: slightly slower,
            # fully correct. Revisit when unsloth/transformers re-sync.
            "UNSLOTH_COMPILE_DISABLE": "1",
        }
    )
    .add_local_python_source("unrender")
)

# The customer-facing function has a small, exact direct dependency surface.
# Transitive package versions are measured into every canaried release digest;
# the owner still records the resulting Modal image/deployment identity before
# enabling production traffic.
infer_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(*(f"{name}=={version}" for name, version in INFER_DIRECT_DEPENDENCIES.items()))
    .env({"HF_HOME": f"{INFER_V}/huggingface"})
    .add_local_python_source("unrender")
)

# Frontier-API image: just the eval scorer's deps + the Gemini SDK (no torch — a
# Gemini call needs no GPU stack). rapidfuzz pin matches train_image so the score
# is identical to the base/LoRA arms (cell@5_exact doesn't use it, but series_name
# does). add_local_python_source must be the LAST build step.
gemini_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "google-genai",
        "pydantic>=2.5",
        "tqdm>=4.66",
        "rapidfuzz>=3.6",
        "pillow>=10.0",
    )
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


def _snapshot_files(snapshot: Path) -> list[tuple[Path, Path]]:
    """Return (logical path, safe target) pairs without following directory links."""

    root = snapshot.resolve(strict=True)
    repository_cache = root.parents[1].resolve(strict=True)
    files: list[tuple[Path, Path]] = []

    def visit(directory: Path) -> None:
        before = directory.stat(follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            raise ValueError("The model snapshot contains a non-directory path component")
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                logical = Path(entry.path)
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode):
                    target = logical.resolve(strict=True)
                    target_metadata = target.stat(follow_symlinks=False)
                    if stat.S_ISDIR(target_metadata.st_mode):
                        raise ValueError("The model snapshot contains a directory symlink")
                    if not stat.S_ISREG(target_metadata.st_mode):
                        raise ValueError("The model snapshot contains a special-file symlink")
                    if not target.is_relative_to(repository_cache):
                        raise ValueError(
                            "The model snapshot contains a file outside its repository cache"
                        )
                    files.append((logical, target))
                elif stat.S_ISDIR(metadata.st_mode):
                    visit(logical)
                elif stat.S_ISREG(metadata.st_mode):
                    files.append((logical, logical))
                else:
                    raise ValueError("The model snapshot contains a special file")
        after = directory.stat(follow_symlinks=False)
        if (before.st_dev, before.st_ino, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_mtime_ns,
        ):
            raise ValueError("The model snapshot changed while it was inspected")

    visit(root)
    if not files:
        raise ValueError("The resolved model snapshot is empty")
    return sorted(files, key=lambda pair: pair[0].relative_to(root).as_posix())


def _open_snapshot_file(repository_cache: Path, target: Path) -> int:
    """Open every path component by descriptor so a swapped directory cannot redirect us."""

    try:
        relative = target.relative_to(repository_cache)
    except ValueError as exc:
        raise ValueError("The model snapshot file escaped its repository cache") from exc
    if not relative.parts:
        raise ValueError("The model snapshot resolved to a directory")
    directory_flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory_descriptor: int | None = None
    try:
        directory_descriptor = os.open(repository_cache, directory_flags)
        for component in relative.parts[:-1]:
            next_descriptor = os.open(
                component,
                directory_flags,
                dir_fd=directory_descriptor,
            )
            os.close(directory_descriptor)
            directory_descriptor = next_descriptor
        return os.open(relative.parts[-1], file_flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ValueError("The model snapshot path changed before it was opened") from exc
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)


def _copy_snapshot_and_digest(snapshot: Path, destination: Path | None = None) -> str:
    root = snapshot.resolve(strict=True)
    repository_cache = root.parents[1].resolve(strict=True)
    digest = hashlib.sha256()
    for logical, target in _snapshot_files(root):
        relative = logical.relative_to(root)
        logical_before = logical.lstat()
        if target.stat(follow_symlinks=False).st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError("The model snapshot contains a group/world-writable file")
        descriptor = _open_snapshot_file(repository_cache, target)
        output = None
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("The model snapshot contains a non-regular file")
            if (before.st_dev, before.st_ino) != (
                target.stat(follow_symlinks=False).st_dev,
                target.stat(follow_symlinks=False).st_ino,
            ):
                raise ValueError("The model snapshot file changed before it was opened")
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(before.st_size).encode("ascii"))
            digest.update(b"\0")
            if destination is not None:
                output_path = destination / relative
                output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                output = output_path.open("xb")
            while chunk := os.read(descriptor, 8 * 1024 * 1024):
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
            after = os.fstat(descriptor)
            logical_after = logical.lstat()
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
            ) or (logical_before.st_dev, logical_before.st_ino, logical_before.st_mtime_ns) != (
                logical_after.st_dev,
                logical_after.st_ino,
                logical_after.st_mtime_ns,
            ):
                raise ValueError("The model snapshot file changed while it was copied")
            if output is not None:
                output.flush()
                os.fsync(output.fileno())
                os.chmod(output.name, 0o400)
        finally:
            if output is not None:
                output.close()
            os.close(descriptor)
    return digest.hexdigest()


def _snapshot_digest(snapshot: Path) -> str:
    """Hash every safely opened snapshot file and reject path races/special files."""

    return _copy_snapshot_and_digest(snapshot)


def _verify_materialization(snapshot: Path, expected_digest: str) -> None:
    root_metadata = snapshot.lstat()
    if stat.S_ISLNK(root_metadata.st_mode) or not stat.S_ISDIR(root_metadata.st_mode):
        raise ValueError("The verified model materialization root is unsafe")
    if root_metadata.st_mode & 0o222:
        raise ValueError("The verified model materialization root is writable")
    for path in snapshot.rglob("*"):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not (
            stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)
        ):
            raise ValueError("The verified model materialization contains an unsafe path")
        if metadata.st_mode & 0o222:
            raise ValueError("The verified model materialization is writable")
    actual = _snapshot_digest(snapshot)
    if not hmac.compare_digest(actual, expected_digest):
        raise ValueError("The verified model materialization drifted from its content address")


def _production_model_snapshot(model_path: str, revision: str, expected_digest: str) -> str:
    """Materialize one verified Hub commit into a private read-only content address."""

    if model_path == "modal-volume/unrender-inference-cache":
        if not _DIGEST.fullmatch(expected_digest.casefold()) or revision != expected_digest:
            raise ValueError("Modal releases require an exact SHA-256 revision and matching digest")
        snapshot = Path(INFER_V) / "releases" / expected_digest
        _verify_materialization(snapshot, expected_digest)
        return str(snapshot)
    if not _MODEL_REPOSITORY.fullmatch(model_path):
        raise ValueError("Production inference requires an owner/model Hub repository")
    if not _MODEL_COMMIT.fullmatch(revision.casefold()):
        raise ValueError("Production inference requires a full 40-character Hub commit")
    if not _DIGEST.fullmatch(expected_digest.casefold()):
        raise ValueError("Production inference requires a 64-character model-manifest digest")

    from huggingface_hub import snapshot_download

    snapshot = Path(snapshot_download(repo_id=model_path, revision=revision)).resolve(strict=True)
    if snapshot.name.casefold() != revision.casefold():
        raise ValueError("The Hub client did not resolve the requested immutable commit")
    approved_digest = expected_digest.casefold()
    repository_cache = snapshot.parents[1].resolve(strict=True)
    materializations = repository_cache.parent / "unrender-verified-models"
    materializations.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(materializations, 0o700)
    destination = materializations / approved_digest
    if destination.exists():
        _verify_materialization(destination, approved_digest)
        return str(destination)

    temporary = Path(
        tempfile.mkdtemp(prefix=f".{approved_digest}.{uuid.uuid4().hex}.", dir=materializations)
    )
    try:
        actual_digest = _copy_snapshot_and_digest(snapshot, temporary)
        if not hmac.compare_digest(actual_digest, approved_digest):
            raise ValueError("The resolved model files do not match the approved manifest")
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()), reverse=True
        ):
            os.chmod(directory, 0o500)
        os.chmod(temporary, 0o700)
        try:
            os.rename(temporary, destination)
        except OSError:
            if not destination.exists():
                raise
            os.chmod(temporary, 0o700)
            shutil.rmtree(temporary)
        os.chmod(destination, 0o500)
        _verify_materialization(destination, approved_digest)
        return str(destination)
    except Exception:
        if temporary.exists():
            for path in temporary.rglob("*"):
                with suppress(OSError):
                    os.chmod(path, 0o700 if path.is_dir() else 0o600)
            os.chmod(temporary, 0o700)
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def _provider_release_digest(
    *,
    runtime_versions: dict[str, str],
    model_path: str,
    revision: str,
    model_digest: str,
    prompt_sha256: str,
) -> str:
    manifest = {
        "contract": INFER_PROVIDER_CONTRACT,
        "source_sha256": INFER_SOURCE_SHA256,
        "prompt_sha256": prompt_sha256,
        "packages": dict(sorted(runtime_versions.items())),
        "model": {
            "repository": model_path,
            "revision": revision.casefold(),
            "manifest_sha256": model_digest.casefold(),
        },
    }
    return hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_subset_ids(name: str):
    """Frozen subset name (e.g. ``common300``) -> the committed id list shipped in
    the package at ``unrender/eval/subsets/<name>.json``."""
    import json
    from pathlib import Path

    import unrender.eval as _ev

    return json.loads((Path(_ev.__file__).parent / "subsets" / f"{name}.json").read_text())["ids"]


def _parse_eval_specs(spec: str):
    """ "real_v0,common300,v2:300" -> ordered eval descriptors for the post-train
    chain. Forms: "common300" (the frozen v1 subset), "real_v0" (a real set dir),
    "v0"/"v1"/"v2" (a synthetic test split); an optional ":N" caps the row count
    (e.g. "v2:300"). Pure string parsing -> unit-testable."""
    out = []
    for part in (s.strip() for s in spec.split(",") if s.strip()):
        name, _, lim = part.partition(":")
        d = {"limit": int(lim) if lim else 0}
        if name == "common300":
            d.update(data="v1", subset="common300")
        else:
            d.update(data=name, subset="")
        out.append(d)
    return out


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

    for name, seed, hard in (
        ("synthetic_v0", 1234, False),
        ("synthetic_v1", 5678, True),
    ):
        out = f"{V}/data/{name}"
        generate(n=n, out=out, base_seed=seed, hard=hard, workers=8)
        split(out=out, val_size=500, test_size=1000)
    VOL.commit()


@app.function(image=gen_image, volumes={V: VOL}, cpu=8.0, memory=8192, timeout=4 * 3600)
def generate_data_v2(n: int = 20000, seed: int = 9012):
    """synthetic_v2 (FRONTIER_PLAN P1): magnitudes to 1e9, real-world axis formats,
    continuous year x-axes, themes; 20k charts by default (data scale is the moat
    and CPU is cheap). Rows bake EXTRACTION_PROMPT (v1) for now — switch to the V2
    prompt only when ALL compared arms are re-run on it (comparability rule)."""
    from pathlib import Path

    from unrender.data_gen.generate import generate
    from unrender.data_gen.split_dataset import split

    out = f"{V}/data/synthetic_v2"
    # Completion sentinel: removed FIRST so an interrupted regen can't be mistaken
    # for a finished one, written LAST so its presence proves the whole
    # gen+split+commit ran. This is how a detached run (immune to the client/
    # session dying) is verified afterwards — the recurring local-upload failure
    # mode was session teardown, and server-side --detach + this sentinel sidesteps
    # it entirely (no 6GB upload).
    ready = Path(out) / "READY.json"
    ready.unlink(missing_ok=True)
    generate(n=n, out=out, base_seed=seed, hard=False, v2=True, workers=8)
    split(out=out, val_size=500, test_size=1000)
    n_img = len(list((Path(out) / "images").glob("*.png")))
    import json as _json

    ready.write_text(_json.dumps({"n": n, "seed": seed, "images": n_img, "v2_fixed": True}))
    VOL.commit()
    print(f"gen_v2 DONE: {n_img} images + splits + READY.json committed to {out}")


@app.function(image=gen_image, volumes={V: VOL}, cpu=8.0, memory=8192, timeout=2 * 3600)
def gen_geometry_data(train_files: str = "v1,v0"):
    """Build the geometry-supervision training targets (train.geom.jsonl) from the
    existing train splits on the Volume — CPU, ~$0.3. Regenerates each chart's spec
    from its seed, captures exact renderer geometry, writes the compact geometry
    target (verified against the stored GT). Run once before the geometry train."""
    from unrender.train.geometry_data import build_geometry_split

    seeds = {"v0": 1234, "v1": 5678}
    for t in (s.strip() for s in train_files.split(",")):
        build_geometry_split(
            f"{V}/data/synthetic_{t}/train.jsonl",
            f"{V}/data/synthetic_{t}/train.geom.jsonl",
            base_seed=seeds[t],
            hard=(t == "v1"),
        )
    VOL.commit()


@app.function(image=train_image, volumes={V: VOL}, cpu=8.0, memory=8192, timeout=3600)
def preflight(
    train_files: str = "v2,v1,v0",
    val_files: str = "v2,v1,v0",
    batch_size: int = 2,
    grad_accum: int = 4,
    epochs: float = 1.0,
    labelfree_weight: float = 1.5,
    verify_all: str = "",
):
    """$0.02 insurance before a multi-hour train: verify ON THE VOLUME that
    (1) every split file exists and parses, (2) every referenced image exists,
    (3) images decode (ALL of `verify_all`'s sets — they went through
    tar/upload/untar — plus a sample of the rest), (4) the longest targets fit
    the 4096-token budget with room for image tokens, and (5) print the step/
    time/cost estimate for the planned run. Fails loudly on any problem."""
    import json
    from pathlib import Path

    from PIL import Image

    def rows_of(tag, fname):
        p = Path(f"{V}/data/synthetic_{tag}/{fname}")
        assert p.exists(), f"MISSING split: {p}"
        return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]

    def img_path(r):
        p = r["images"][0]
        return p if Path(p).exists() else f"{V}/{p}"

    tags = [t.strip() for t in train_files.split(",")]
    n_records = 0
    longest = []  # (len, target_text)
    for tag in tags:
        rows = rows_of(tag, "train.jsonl")
        missing = [img_path(r) for r in rows if not Path(img_path(r)).exists()]
        assert not missing, f"{tag}: {len(missing)} missing images, e.g. {missing[:3]}"
        lf = sum(1 for r in rows if not (r.get("meta") or {}).get("labels_shown", True))
        n_records += len(rows) + int(lf * (labelfree_weight - 1.0))
        for r in rows:
            t = r["messages"][1]["content"]
            longest.append((len(t), t))
        longest = sorted(longest, key=lambda x: -x[0])[:30]
        # decode check, PARALLEL (a serial 20k-image pass over the Volume ran
        # >30min and died to a client blip): full pass for `verify_all` sets,
        # a spread sample for the rest. Full-set verification of fresh data
        # should happen LOCALLY before upload; here it's transfer insurance.
        import multiprocessing.dummy as mpd  # threads: PIL verify is I/O-bound here

        check = rows if tag in verify_all.split(",") else rows[:: max(1, len(rows) // 200)]

        def _verify(r):
            try:
                with Image.open(img_path(r)) as im:
                    im.verify()
                return None
            except Exception as e:  # noqa: BLE001
                return (img_path(r), str(e))

        with mpd.Pool(16) as pool:
            bad = [b for b in pool.map(_verify, check) if b]
        assert not bad, f"{tag}: {len(bad)} corrupt images, e.g. {bad[:3]}"
        print(f"  {tag}: {len(rows)} rows, images ok ({len(check)} decoded), label-free {lf}")
    for tag in (t.strip() for t in val_files.split(",") if t.strip()):
        assert Path(f"{V}/data/synthetic_{tag}/val.jsonl").exists(), f"MISSING val for {tag}"

    # Token budget: prompt + longest target must leave headroom for image tokens
    # under sft_lora's max_seq_length=4096. Use the merged fair model's processor
    # from the Volume (no network).
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(
        f"{V}/runs/qwen3vl4b-table-fair/merged", trust_remote_code=True
    )
    prompt_len = len(tok(rows_of(tags[0], "train.jsonl")[0]["messages"][0]["content"]).input_ids)
    worst = max(len(tok(t).input_ids) for _, t in longest)
    budget = 4096 - prompt_len - worst
    print(
        f"  token budget: prompt={prompt_len} + worst_target={worst} "
        f"-> {budget} left for image tokens"
    )
    assert budget >= 900, (
        f"longest target leaves only {budget} tokens for the image — raise max_seq_length"
    )

    steps = int(n_records / (batch_size * grad_accum) * epochs)
    for gpu, sps, rate in (("L4", 11.0, 0.80), ("A100", 3.7, 2.10)):
        h = steps * sps / 3600
        print(f"  estimate {gpu}: ~{steps} steps ≈ {h:.1f}h train ≈ ${h * rate:.0f} (+evals)")
    print(f"PREFLIGHT PASS: ~{n_records} records, ~{steps} steps")
    return {"records": n_records, "steps": steps}


@app.function(image=train_image, volumes={V: VOL}, cpu=2.0, memory=4096, timeout=1800)
def fetch_real_data(dirname: str = "real_v0"):
    """Source the REAL-chart transfer eval INSIDE Modal — the dev sandbox has no
    egress, but a Modal container does. Downloads each curated FRED/OWID chart PNG
    plus its OFFICIAL data CSV, reads ground truth straight from the CSV (never
    estimated off the pixels), and writes images + a test.jsonl (with /vol-absolute
    image paths) to {V}/data/<dirname>/. Then eval with `--data <dirname>`. CPU/~free.
    See data/real_v0/README.md."""
    import json
    import urllib.request
    from pathlib import Path

    from unrender.data_gen.split_dataset import _row
    from unrender.eval.build_real_set import label_to_chartdata

    # OWID only: FRED is unreachable from Modal egress (DNS fails / datacenter IPs
    # time out). The local tool (unrender.eval.fetch_real_set) still does FRED for a
    # machine that can reach it; here we use OWID, which resolves and serves cleanly.
    from unrender.eval.fetch_real_set import (
        _OWID_COUNTRY,
        _OWID_HI,
        _OWID_LO,
        OWID,
        _is_png,
        _owid_urls,
        make_line_label,
        parse_owid_csv,
    )
    from unrender.schema.chart_schema import canonical_json

    root = Path(f"{V}/data/{dirname}")
    imgs = root / "images"
    imgs.mkdir(parents=True, exist_ok=True)

    def get(url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (unrender real-set)"})
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.read()

    def add(out_id, png_url, csv_url, parse, title, ylab, yunit, sname, source, rows):
        png = get(png_url)
        if not _is_png(png):  # bad slug/param => an HTML error page; never write a fake chart
            print(f"  ! {out_id}: non-PNG ({len(png)}B) from {png_url} — skip")
            return
        pts = parse(get(csv_url).decode("utf-8", "replace"))
        if len(pts) < 3:
            print(f"  ! {out_id}: only {len(pts)} points — skip ({csv_url})")
            return
        label = make_line_label(out_id, title, ylab, yunit, sname, pts, source)
        gt = label_to_chartdata(label, out_id)  # validate; fail loud on a bad value
        (imgs / f"{out_id}.png").write_bytes(png)
        meta = {"labels_shown": False, "chart_type": "line", "augmented": False, "source": source}
        rows.append(_row(f"{root}/images/{out_id}.png", canonical_json(gt), meta))
        print(f"  ✓ {out_id}: {len(pts)} pts  ({title})")

    rows = []
    print(f"OWID ({len(OWID)}):")
    for out_id, slug, title, ylab, yunit in OWID:
        png_url, csv_url = _owid_urls(slug)
        src = (
            f"Our World in Data: {slug} (ourworldindata.org/grapher/{slug}), "
            f"{_OWID_COUNTRY} {_OWID_LO}–{_OWID_HI}"
        )
        try:
            add(out_id, png_url, csv_url, parse_owid_csv, title, ylab, yunit, title, src, rows)
        except Exception as e:  # noqa: BLE001 — one bad source shouldn't abort the batch
            print(f"  ! {out_id}: {type(e).__name__}: {e}")

    (root / "test.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    VOL.commit()
    print(f"\nfetched {len(rows)}/{len(OWID)} real charts -> {root}/test.jsonl")
    return len(rows)


@app.function(
    image=gemini_image,
    volumes={V: VOL},
    secrets=[modal.Secret.from_name("gemini-real")],
    cpu=2.0,
    memory=8192,
    timeout=2 * 3600,
)
def eval_gemini(model: str = "gemini-3.1-pro-preview", dirname: str = "real_v0"):
    """Frontier (Gemini) baseline on a set, run INSIDE Modal because the dev sandbox
    has no egress (Modal containers do). Reads GOOGLE_API_KEY from the 'gemini-real'
    secret; SAME EXTRACTION_PROMPT + table decoder + cell@5_exact metric as the
    base/LoRA arms, so the number is directly comparable. Results -> Volume."""
    import subprocess

    from unrender.eval.run_baselines import run
    from unrender.prompts import EXTRACTION_PROMPT

    out_dir = f"{V}/outputs/eval_{dirname}__gemini"
    pred = run(
        provider="gemini",
        model=model,
        data=f"{V}/data/{dirname}/test.jsonl",
        out=out_dir,
        limit=0,
        seed=0,
        prompt=EXTRACTION_PROMPT,
    )
    VOL.commit()
    try:
        subprocess.run(
            ["python", "-m", "unrender.eval.score", "--predictions", str(pred)],
            check=True,
            cwd="/root",
        )
    except Exception as e:  # noqa: BLE001 — predictions are committed; re-score locally
        print(f"⚠ in-container scoring failed ({e}); predictions ARE saved — re-score locally.")
    VOL.commit()


@production_app.function(
    image=infer_image,
    volumes={INFER_V: INFER_VOL},
    secrets=(
        [modal.Secret.from_name(os.environ["UNRENDER_HF_SECRET"])]
        if os.environ.get("UNRENDER_HF_SECRET")
        else []
    ),
    gpu=GPU,
    cpu=4.0,
    memory=32768,
    timeout=240,
    max_containers=1,
    scaledown_window=2,
    retries=0,
)
def infer_one(image_bytes: bytes, model_path: str, revision: str, model_digest: str):
    """Production boundary: exact Hub commit + verified weights + source release."""
    import importlib.metadata
    import tempfile
    import time

    from unrender.eval import providers as _providers
    from unrender.eval.providers import hf_vlm_provider
    from unrender.prompts import EXTRACTION_PROMPT
    from unrender.schema.json_to_csv import chart_to_csv
    from unrender.schema.validate import parse_chart_json

    started = time.perf_counter()
    timings = {}
    succeeded = False
    try:
        runtime_packages = set(INFER_DIRECT_DEPENDENCIES) | {"numpy", "safetensors", "tokenizers"}
        runtime_versions = {
            package: importlib.metadata.version(package) for package in sorted(runtime_packages)
        }
        for package, expected in INFER_DIRECT_DEPENDENCIES.items():
            if runtime_versions[package] != expected:
                raise RuntimeError(f"Inference dependency drift: {package}")
        verification_started = time.perf_counter()
        snapshot = _production_model_snapshot(model_path, revision, model_digest)
        timings["snapshot_verification_seconds"] = time.perf_counter() - verification_started
        provider_release = _provider_release_digest(
            runtime_versions=runtime_versions,
            model_path=model_path,
            revision=revision,
            model_digest=model_digest,
            prompt_sha256=hashlib.sha256(EXTRACTION_PROMPT.encode("utf-8")).hexdigest(),
        )

        _providers.HF_GEN_CONFIG.clear()  # greedy — identical to the eval default
        _providers.HF_MODEL_CONFIG.clear()

        with tempfile.NamedTemporaryFile(suffix=".png") as f:
            f.write(image_bytes)
            f.flush()
            raw = hf_vlm_provider(f.name, EXTRACTION_PROMPT, snapshot, timings=timings)
        pred, errs = parse_chart_json(raw)
        result = {
            "raw": raw,
            "json": pred.model_dump() if pred else None,
            "csv": chart_to_csv(pred) if pred else None,
            "parse_errors": errs,
            "provider_release": provider_release,
        }
        succeeded = True
        return result
    finally:
        with suppress(OSError, ValueError):
            print(
                json.dumps(
                    {
                        "event": "inference_timings",
                        "succeeded": succeeded,
                        "total_seconds": time.perf_counter() - started,
                        "stages": timings,
                    }
                ),
                flush=True,
            )


@app.function(image=train_image, volumes={V: VOL}, gpu=GPU, cpu=4.0, memory=32768, timeout=1200)
def research_infer_one(
    image_bytes: bytes,
    model_path: str = "runs/qwen3vl4b-table-fair/merged",
    revision: str = "",
):
    """Explicit research-only inference for mutable Volume paths and comparisons."""

    import tempfile

    from unrender.eval import providers as _providers
    from unrender.eval.providers import hf_vlm_provider
    from unrender.prompts import EXTRACTION_PROMPT
    from unrender.schema.json_to_csv import chart_to_csv
    from unrender.schema.validate import parse_chart_json

    _providers.HF_GEN_CONFIG.clear()
    _providers.HF_MODEL_CONFIG.clear()
    if revision:
        _providers.HF_MODEL_CONFIG["revision"] = revision
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(image_bytes)
        f.flush()
        raw = hf_vlm_provider(f.name, EXTRACTION_PROMPT, _resolve_model(model_path))
    pred, errs = parse_chart_json(raw)
    return {
        "raw": raw,
        "json": pred.model_dump() if pred else None,
        "csv": chart_to_csv(pred) if pred else None,
        "parse_errors": errs,
        "provider_release": "research-unattested",
    }


@app.function(
    image=train_image,
    volumes={V: VOL},
    secrets=[modal.Secret.from_name("hf-token")],
    cpu=4.0,
    memory=8192,
    timeout=3600,
)
def publish_hf(
    repo_id: str, model_path: str = "runs/qwen3vl4b-table-fair/merged", private: bool = False
):
    """Push the merged fine-tune from the Volume to the Hugging Face Hub so anyone can
    `from_pretrained` it. CPU-only (uploads the folder; no model load). Needs an
    `hf-token` Modal secret carrying HF_TOKEN. NOT run by default — publishing makes
    the weights public and is the owner's call (see the `publish` entrypoint)."""
    import os
    from pathlib import Path

    from huggingface_hub import HfApi

    src = _resolve_model(model_path)
    if not Path(src).exists():
        raise SystemExit(f"no merged model at {src} on the Volume — train it first")
    api = HfApi(token=os.environ["HF_TOKEN"])
    api.create_repo(repo_id, private=private, exist_ok=True)
    api.upload_folder(
        repo_id=repo_id,
        folder_path=src,
        commit_message="Unrender chart->data LoRA (Qwen3-VL-4B, merged 16bit)",
    )
    print(f"published {src} -> https://huggingface.co/{repo_id}")


@app.function(
    image=train_image,
    volumes={V: VOL},
    gpu=GPU,
    cpu=4.0,
    memory=32768,
    timeout=24 * 3600,  # train (~4k steps on the v2 mix) + the chained evals
)
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
    geometry: bool = False,
    hbar_weight: float = 1.0,
    numeric_loss_weight: float = 1.0,
    val_files: str = "",
    val_size: int = 256,
    n_evals: int = 5,
    type_weights: str = "",
    eval_after: str = "",
    common300_ids=None,
):
    from unrender.train.sft_lora import train

    # geometry=True trains on the geometry-program targets (run gen_geom first);
    # sft_lora is target-agnostic (feeds messages[].content straight through), so
    # only the filename changes. hbar_weight oversamples horizontal_bar;
    # numeric_loss_weight up-weights digit-token loss (the precision levers).
    fname = "train.geom.jsonl" if geometry else "train.jsonl"
    paths = [f"{V}/data/synthetic_{t.strip()}/{fname}" for t in train_files.split(",")]
    # val_files (e.g. "v1,v0") enables best-checkpoint selection on eval_loss — the
    # fairness fix for the table arms. "" disables it (smoke, or a deliberate
    # final-ckpt run). val mirrors the train fname (val.jsonl / val.geom.jsonl), so
    # geometry+val would need a val.geom.jsonl (gen_geom only builds train.geom.jsonl)
    # — table arms use the committed val.jsonl that's already on the Volume.
    val_fname = fname.replace("train", "val", 1)
    val_paths = (
        [f"{V}/data/synthetic_{t.strip()}/{val_fname}" for t in val_files.split(",") if t.strip()]
        if val_files
        else None
    )
    train(
        train_paths=paths,
        val_paths=val_paths,
        val_size=val_size,
        n_evals=n_evals,
        out=f"{V}/runs/{out_name}",
        base=base,
        data_root=V,
        labelfree_weight=labelfree_weight,
        hbar_weight=hbar_weight,
        type_weights=type_weights,
        numeric_loss_weight=numeric_loss_weight,
        epochs=epochs,
        max_steps=max_steps,
        batch_size=batch_size,
        grad_accum=grad_accum,
        lora_r=lora_r,
    )
    VOL.commit()

    # One-shot chain (eval_after="real_v0,common300,v2:300"): run the evals in
    # THIS container right after the merge commits — no human needed between
    # train and results. Each eval is resumable and failure-isolated: a crash
    # here never loses the trained model (committed above), and the remaining
    # evals still run.
    for spec in _parse_eval_specs(eval_after):
        ids = common300_ids if spec["subset"] == "common300" else None
        print(f"\n=== chained eval: {spec} ===")
        try:
            _eval_impl(
                model_path=f"runs/{out_name}/merged",
                data=spec["data"],
                limit=spec["limit"],
                subset=spec["subset"],
                subset_ids=ids,
            )
        except Exception as e:  # noqa: BLE001
            print(
                f"⚠ chained eval {spec} failed ({e}) — model + earlier evals are safe; "
                f"re-run standalone: modal run --detach modal_train.py::evaluate "
                f"--model runs/{out_name}/merged --data {spec['data']}"
                + (f" --subset {spec['subset']}" if spec["subset"] else "")
                + (f" --limit {spec['limit']}" if spec["limit"] else "")
            )
    VOL.commit()


def _eval_impl(
    model_path: str,
    data: str = "v1",
    limit: int = 0,
    out_name: str = "",
    subset: str = "",
    subset_ids=None,
    repetition_penalty: float = 0.0,
    max_new_tokens: int = 0,
    revision: str = "",
    decode: str = "table",
):
    """The eval body, as a plain function so BOTH the standalone eval_model
    function AND the post-train chain inside train_model can run it (same
    container, same GPU — the one-shot flow). Resumable: predictions.jsonl
    persists on the Volume, so a re-run skips done ids."""
    import subprocess
    from pathlib import Path

    from unrender.eval.run_baselines import run
    from unrender.prompts import EXTRACTION_PROMPT, GEOMETRY_PROMPT

    prompt = GEOMETRY_PROMPT if decode == "geometry" else EXTRACTION_PROMPT
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
    # "v0"/"v1" -> the synthetic splits; "real_*" -> a hand-labeled real-chart set
    # (data/real_v0, uploaded to the Volume) for the transfer eval. See data/real_v0/README.md.
    data_sub = data if data.startswith("real") else f"synthetic_{data}"
    pred = run(
        provider="hf",
        model=mp,
        data=f"{V}/data/{data_sub}/test.jsonl",
        out=out_dir,
        limit=limit,
        seed=0,
        only_ids=only_ids,
        gen_config=gen_config or None,
        revision=revision or None,
        prompt=prompt,
    )
    VOL.commit()
    # score.py prints its report in main(); run it as the CLI so logs show the
    # exact table you'd see locally (cwd=/root is where the package is mounted).
    # Pass --subset so the base report records the SAME subset_fp as the LoRA's
    # subset report (provenance symmetry) and re-asserts coverage.
    score_cmd = ["python", "-m", "unrender.eval.score", "--predictions", str(pred)]
    if subset:
        # Write the RESOLVED ids to a container-local file rather than relying on
        # the packaged subset JSON being shipped to Modal — add_local_python_source
        # does NOT ship non-.py data, which is why the first base run produced
        # predictions+meta but no report (the score subprocess couldn't find
        # common300.json and raised). only_ids was passed from the entrypoint.
        import json as _json

        if only_ids:
            subset_file = f"{out_dir}/subset_ids.json"
            Path(subset_file).write_text(_json.dumps({"ids": sorted(str(i) for i in only_ids)}))
            score_cmd += ["--subset", subset_file]
    if decode != "table":
        score_cmd += ["--decode", decode]
    # Non-fatal: predictions are already committed above; a scoring hiccup must not
    # lose the run — log loudly and let the report be regenerated locally for free.
    try:
        subprocess.run(score_cmd, check=True, cwd="/root")
    except Exception as e:  # noqa: BLE001
        print(
            f"⚠ in-container scoring failed ({e}). Predictions ARE committed; "
            f"re-score locally: python -m unrender.eval.score --predictions <pulled> "
            f"--subset unrender/eval/subsets/{subset or '<name>'}.json"
            + (f" --decode {decode}" if decode != "table" else "")
        )
    VOL.commit()


@app.function(
    image=train_image,
    volumes={V: VOL},
    gpu=GPU,
    cpu=4.0,
    memory=32768,
    timeout=20 * 3600,
)
def eval_model(
    model_path: str,
    data: str = "v1",
    limit: int = 0,
    out_name: str = "",
    subset: str = "",
    subset_ids=None,
    repetition_penalty: float = 0.0,
    max_new_tokens: int = 0,
    revision: str = "",
    decode: str = "table",
):
    """Run a model over a test split through the SAME harness as the frontier
    baselines, then print the sliced score report. ``model_path`` is a Volume
    run dir OR an HF hub id (``Qwen/Qwen3-VL-4B-Instruct``) for the base-model
    controls (item 1). ``subset_ids`` (resolved locally by the entrypoint from a
    name like ``common300``) restricts to that frozen id list; ``subset`` is kept
    only to label the output dir. See _eval_impl for the body."""
    _eval_impl(
        model_path=model_path,
        data=data,
        limit=limit,
        out_name=out_name,
        subset=subset,
        subset_ids=subset_ids,
        repetition_penalty=repetition_penalty,
        max_new_tokens=max_new_tokens,
        revision=revision,
        decode=decode,
    )


@app.function(
    image=train_image,
    volumes={V: VOL},
    gpu=GPU,
    cpu=4.0,
    memory=32768,
    timeout=20 * 3600,
)
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

    from unrender.eval.run_baselines import run
    from unrender.eval.score import row_status, score_rows
    from unrender.io_utils import read_jsonl

    mp = _resolve_model(model_path)
    full = read_jsonl(Path(f"{V}/{lora_pred_dir}/predictions.jsonl"))
    invalid_ids = [r["id"] for r in full if row_status(r) == "model_invalid"]
    ok_ids = [r["id"] for r in full if row_status(r) == "ok"]
    random.Random(0).shuffle(ok_ids)
    valid_ids = set(ok_ids[:n_valid])
    subset_ids = set(invalid_ids) | valid_ids
    print(
        f"[sweep] subset: {len(invalid_ids)} invalid + {len(valid_ids)} valid "
        f"= {len(subset_ids)} charts"
    )

    def _summarize(rows, arm):
        a = score_rows(rows, 0.05, only_ids=subset_ids)
        av = score_rows(rows, 0.05, only_ids=valid_ids)
        n = a["metrics"]["n"]
        return {
            "arm": arm,
            "invalid": a["n_model_invalid"],
            "n": n,
            "invalid_pct": (a["n_model_invalid"] / n * 100) if n else 0.0,
            "cell": a["metrics"]["cell_accuracy"] * 100,
            "valid_cell": av["metrics"]["cell_accuracy"] * 100,
        }

    results = [_summarize(full, "greedy")]  # control — no generation
    valid_floor = results[0]["valid_cell"]

    data_path = f"{V}/data/synthetic_{data}/test.jsonl"
    for rp in [float(x) for x in penalties.split(",") if x.strip()]:
        pred = run(
            provider="hf",
            model=mp,
            data=data_path,
            out=f"{V}/outputs/sweep_{data}__rp{rp}",
            limit=0,
            seed=0,
            only_ids=subset_ids,
            gen_config={"repetition_penalty": rp},
        )
        VOL.commit()
        results.append(_summarize(read_jsonl(Path(pred)), f"rep{rp}"))

    print(
        f"\n=== decoder sweep  (subset N={len(subset_ids)}, "
        f"greedy valid-cell floor={valid_floor:.1f}%) ==="
    )
    print(f"{'arm':<10}{'invalid':>9}{'invalid%':>10}{'cell@5%':>10}{'valid-cell':>12}  verdict")
    for r in results:
        ok = r["invalid_pct"] < 1.0 and (valid_floor - r["valid_cell"]) <= 1.0
        verdict = "" if r["arm"] == "greedy" else ("ADOPT" if ok else "reject")
        print(
            f"{r['arm']:<10}{r['invalid']:>9}{r['invalid_pct']:>9.1f}%"
            f"{r['cell']:>9.1f}%{r['valid_cell']:>11.1f}%  {verdict}"
        )


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
        (
            "AutoProcessor",
            lambda: AutoProcessor.from_pretrained(mp, trust_remote_code=True),
        ),
        (
            "AutoModel",
            lambda: AutoModelForImageTextToText.from_pretrained(
                mp, torch_dtype="auto", device_map="auto", trust_remote_code=True
            ),
        ),
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
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": img_path},
                {"type": "text", "text": "Extract the data as JSON."},
            ],
        }
    ]
    text = proc.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = proc(
        text=[text], images=[Image.open(img_path).convert("RGB")], return_tensors="pt"
    ).to(net.device)
    with torch.no_grad():
        out = net.generate(**inputs, max_new_tokens=64, do_sample=False)
    print(
        "[probe] generate: OK ->",
        proc.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)[:200],
    )


# --- local entrypoints (what you `modal run`) ---------------------------------


@app.local_entrypoint()
def probe(model: str = "runs/smoke/merged"):
    probe_model.remote(model_path=model)


@app.local_entrypoint()
def gen(n: int = 5000):
    generate_data.remote(n=n)


@app.local_entrypoint()
def check(
    train_files: str = "v2,v1,v0",
    val_files: str = "v2,v1,v0",
    epochs: float = 1.0,
    verify_all: str = "v2",
):
    """Pre-train preflight (CPU, ~$0.02): data integrity + token budget + cost
    estimate for the one-shot. Run this, read PASS, then launch ::train.
    `verify_all` sets get EVERY image decoded (default v2 — the freshest set);
    others are sampled. Pass verify_all="" for the fast sampled-only pass."""
    print(
        preflight.remote(
            train_files=train_files, val_files=val_files, epochs=epochs, verify_all=verify_all
        )
    )


@app.local_entrypoint()
def gen_v2(n: int = 20000, seed: int = 9012):
    """Regenerate synthetic_v2 ON the Volume (CPU, ~$1-2, ~5-8 min). Use with
    `modal run --detach` — .spawn() returns immediately and the work runs
    server-side, so it CANNOT be killed by the client/session dying (the failure
    mode that killed the 6GB upload three times). Verify afterward: a committed
    data/synthetic_v2/READY.json means it finished. Then (GATED, GPU):
        modal run --detach modal_train.py::train --train-files v2,v1,v0 --out-name qwen3vl4b-v2
    """
    call = generate_data_v2.spawn(n=n, seed=seed)
    print(
        f"submitted gen_v2 (FunctionCall {call.object_id}); returns now — use --detach. "
        f"Done when data/synthetic_v2/READY.json exists on the Volume."
    )


@app.local_entrypoint()
def gen_geom(train_files: str = "v1,v0"):
    """Build geometry-supervision targets on the Volume (CPU, ~$0.3). Run once
    before `train ... --geometry`."""
    gen_geometry_data.remote(train_files=train_files)


@app.local_entrypoint()
def smoke():
    """End-to-end insurance before spending real hours: 30 train steps WITH the
    val/best-checkpoint path on (val-size 64 so it's cheap), save + merge, then
    eval 5 images through the hf provider (proves the merged = best-checkpoint
    model loads back). Exercising val here means the first time the eval +
    load_best_model_at_end code runs is NOT the multi-hour paid run. Total ~$0.5,
    mostly the one-time base-model download."""
    train_model.remote(
        train_files="v1", out_name="smoke", max_steps=30, val_files="v1", val_size=64
    )
    eval_model.remote(model_path="runs/smoke/merged", data="v1", limit=5)


@app.local_entrypoint()
def fetch_real(dirname: str = "real_v0"):
    """Build the real-chart transfer eval on the Volume (FRED/OWID downloaded inside
    Modal, GT read from the official CSVs). Blocking — CPU, ~free, ~1-2 min. Then:
        modal run modal_train.py::evaluate --model runs/qwen3vl4b-lora/merged --data real_v0
    """
    n = fetch_real_data.remote(dirname)
    print(f"done: {n} real charts on the Volume at data/{dirname}/ (eval with --data {dirname})")


@app.local_entrypoint()
def gemini_real(model: str = "gemini-3.1-pro-preview", dirname: str = "real_v0"):
    """Run the Gemini frontier baseline on the real-chart set (inside Modal).
        modal run modal_train.py::gemini_real
    Then pull/score: outputs/eval_<dirname>__gemini on the Volume."""
    eval_gemini.remote(model, dirname)
    print(f"gemini done -> outputs/eval_{dirname}__gemini on the Volume")


@app.local_entrypoint()
def infer(image: str, model: str = "runs/qwen3vl4b-table-fair/merged", revision: str = ""):
    """Extract the data from ONE chart image with the fine-tuned model:
        modal run modal_train.py::infer --image path/to/chart.png
    Prints the ChartData JSON + CSV. Defaults to the best model (table-fair); pass
    --model unsloth/Qwen3-VL-4B-Instruct --revision <sha> to try the base."""
    import json as _json
    from pathlib import Path

    p = Path(image)
    if not p.is_file():
        egs = sorted(Path("data/real_v0/images").glob("*.png"))[:3]
        hint = ("\n  try: " + "  ".join(str(e) for e in egs)) if egs else ""
        raise SystemExit(f"no image at {image!r} — pass --image <path to a real chart PNG>.{hint}")
    out = research_infer_one.remote(p.read_bytes(), model, revision)
    if out["json"]:
        print("\n=== JSON ===\n" + _json.dumps(out["json"], indent=2, ensure_ascii=False))
        print("\n=== CSV ===\n" + (out["csv"] or ""))
    else:
        print(f"\n⚠ unparseable output ({out['parse_errors']}). Raw:\n{out['raw'][:2000]}")


@app.local_entrypoint()
def publish(repo_id: str, model: str = "runs/qwen3vl4b-table-fair/merged", private: bool = False):
    """Publish the merged fine-tune to the Hugging Face Hub (makes it public + usable
    via `from_pretrained`). Needs an `hf-token` Modal secret (HF_TOKEN=hf_...):
        modal run modal_train.py::publish --repo-id <your-user>/unrender-qwen3vl4b-4b
    NOT part of any automated flow — run it yourself when you want to publish."""
    publish_hf.remote(repo_id=repo_id, model_path=model, private=private)


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
    geometry: bool = False,
    hbar_weight: float = 1.0,
    numeric_loss_weight: float = 1.0,
    val_files: str = "v1,v0",
    n_evals: int = 5,
    type_weights: str = "",
    eval_after: str = "",
):
    """Defaults to the FAIR protocol: `--val-files v1,v0` selects the best
    checkpoint on val eval_loss (set `--val-files ""` for a final-ckpt run).

    THE ONE-SHOT (P2, refine-logs/FRONTIER_PLAN.md — train on v2 then auto-eval
    real_v0 + common300 + 300 v2-test rows in the same container, ~$11-13 total):
        UNRENDER_GPU=A100 modal run --detach modal_train.py::train \\
            --train-files v2,v1,v0 --val-files v2,v1,v0 --epochs 1.0 \\
            --out-name qwen3vl4b-v2 --eval-after real_v0,common300,v2:300
    Crash-safe: a relaunch of the SAME command resumes from the latest
    checkpoint (sft_lora._latest_checkpoint) and finished evals resume too.

    The numeric-loss-on-table pivot (refine-logs/NUMERIC_TABLE_PLAN.md):
        modal run --detach modal_train.py::train \
            --out-name qwen3vl4b-table-fair --numeric-loss-weight 1
        modal run --detach modal_train.py::train \
            --out-name qwen3vl4b-table-numloss --numeric-loss-weight 3

    `--geometry` trains the geometry-supervision arm on train.geom.jsonl (run
    `gen_geom` first; geometry+val needs a val.geom.jsonl). Precision levers:
    `--numeric-loss-weight 3` up-weights digit-token loss; `--hbar-weight 3`
    oversamples horizontal_bar (the worst Stage-A slice).

    Uses .spawn() (fire-and-forget): the client returns immediately so a dropped
    laptop/SSH/stream can't tear down a multi-hour run. ALWAYS invoke with
    `modal run --detach ...` so the app persists after this returns; results land
    on the Volume regardless of the client. Logs: `modal app logs <id>`."""
    call = train_model.spawn(
        train_files=train_files,
        out_name=out_name,
        base=base,
        labelfree_weight=labelfree_weight,
        epochs=epochs,
        max_steps=max_steps,
        batch_size=batch_size,
        grad_accum=grad_accum,
        lora_r=lora_r,
        geometry=geometry,
        hbar_weight=hbar_weight,
        numeric_loss_weight=numeric_loss_weight,
        val_files=val_files,
        n_evals=n_evals,
        type_weights=type_weights,
        eval_after=eval_after,
        # resolve the frozen id list LOCALLY (the repo ships it; the container doesn't)
        common300_ids=_load_subset_ids("common300") if "common300" in eval_after else None,
    )
    print(
        f"submitted train '{out_name}' (FunctionCall {call.object_id}); "
        "returns now — use --detach. "
        f"Pull when done: modal volume get unrender-vol runs/{out_name} ./runs/{out_name}"
        + (f"\nchained evals after training: {eval_after}" if eval_after else "")
    )


@app.local_entrypoint()
def evaluate(
    model: str = "runs/qwen3vl4b-table-fair/merged",
    data: str = "v1",
    limit: int = 0,
    subset: str = "",
    repetition_penalty: float = 0.0,
    max_new_tokens: int = 0,
    revision: str = "",
    decode: str = "table",
):
    """Eval one model. Examples (item 1 base-model controls on the frozen subset):
        modal run modal_train.py::evaluate --model unsloth/Qwen3-VL-4B-Instruct \
            --revision 252d592b59b0233b226875a44ac135cfa1d3f755 --subset common300
        modal run modal_train.py::evaluate --subset common300
            # LoRA on the same 300 (apples-to-apples)

    `--revision` pins a Hub base to an exact commit; the base control must use the
    Unsloth mirror + matching revision (PREREGISTRATION.md), not an unpinned HEAD.
    `--decode geometry` evals the geometry arm (geometry prompt + deterministic decode).

    Uses .spawn() — returns immediately; ALWAYS run with `modal run --detach ...` so
    the long eval survives a dropped client (the base run nearly lost its report to a
    local network blip). Results persist on the Volume; logs via `modal app logs <id>`.
    """
    # Resolve the frozen id list LOCALLY (the repo has it) and pass it as an arg,
    # so the container needs no data-file mount.
    ids = _load_subset_ids(subset) if subset else None
    call = eval_model.spawn(
        model_path=model,
        data=data,
        limit=limit,
        subset=subset,
        subset_ids=ids,
        repetition_penalty=repetition_penalty,
        max_new_tokens=max_new_tokens,
        revision=revision,
        decode=decode,
    )
    print(
        f"submitted eval (FunctionCall {call.object_id}); returns now — use --detach. "
        f"Results -> Volume outputs/; pull: modal volume get unrender-vol outputs ./outputs/modal"
    )


@app.local_entrypoint()
def sweep(
    model: str = "runs/qwen3vl4b-lora/merged",
    lora_pred_dir: str = "outputs/eval_v1__qwen3vl4b-lora",
    data: str = "v1",
    n_valid: int = 200,
    penalties: str = "1.1,1.3",
):
    """Decoder sweep on the LoRA (item 2): greedy control (free) vs repetition
    penalties, on the invalid+valid subset. One model load, prints an ADOPT table.
        modal run --detach modal_train.py::sweep
    Uses .spawn() — run with --detach; read the ADOPT table in `modal app logs <id>`.
    """
    call = sweep_model.spawn(
        model_path=model,
        lora_pred_dir=lora_pred_dir,
        data=data,
        n_valid=n_valid,
        penalties=penalties,
    )
    print(
        f"submitted sweep (FunctionCall {call.object_id}); returns now — use --detach. "
        f"ADOPT table prints in: modal app logs {call.object_id}"
    )
