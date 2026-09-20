"""Local single-process checkpoint receipts, sealed before retention deletes old saves.

The caller owns the run and supplies a verified immutable identity. This module
does not resolve base models, establish that ownership or commit a Modal Volume.
It never unpickles optimizer, scheduler, RNG or training-argument artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path

CONTRACT = "training-checkpoint-v1"
RECEIPT = "checkpoint-receipt.json"
IDENTITY_FIELDS = {
    "base",
    "processor",
    "source_inputs",
    "hyperparameters",
    "runtime",
    "source_code",
}


def canonical(value) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()


def identity_digest(identity: dict) -> str:
    if set(identity) != IDENTITY_FIELDS or any(
        not isinstance(v, dict) or not v for v in identity.values()
    ):
        raise ValueError("checkpoint identity needs all six verified identity components")
    if identity["runtime"].get("world_size") != 1:
        raise ValueError("checkpoint receipts require a declared single-process runtime")
    return hashlib.sha256(canonical(identity)).hexdigest()


def _inventory(directory: Path) -> dict:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("checkpoint must be a regular directory")
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("checkpoint contains a symbolic link")
        if path.is_dir():
            continue
        if path.name == RECEIPT and path.parent == directory:
            continue
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size == 0:
            raise ValueError("checkpoint contains an empty or nonregular file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError("checkpoint file changed before it was opened")
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        current = path.lstat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(
            getattr(before, key) != getattr(after, key)
            or getattr(before, key) != getattr(current, key)
            for key in fields
        ):
            raise ValueError("checkpoint file changed while it was hashed")
        result[path.relative_to(directory).as_posix()] = {
            "bytes": before.st_size,
            "sha256": digest.hexdigest(),
        }
    return result


def _structure(directory: Path, files: dict, model_format: str, fp16: bool) -> int:
    if type(fp16) is not bool:
        raise ValueError("checkpoint precision must be an explicit boolean")
    match = re.fullmatch(r"checkpoint-([1-9][0-9]*)", directory.name)
    if not match:
        raise ValueError("checkpoint directory must identify a positive optimizer step")
    common = {
        "trainer_state.json",
        "training_args.bin",
        "optimizer.pt",
        "scheduler.pt",
        "rng_state.pth",
    }
    formats = {
        "lora": {"adapter_model.safetensors", "adapter_config.json"},
        "full": {"model.safetensors", "config.json"},
    }
    if model_format not in formats:
        raise ValueError("unsupported checkpoint model format")
    required = common | formats[model_format] | ({"scaler.pt"} if fp16 else set())
    if missing := required - set(files):
        raise ValueError(f"incomplete checkpoint; missing {sorted(missing)}")
    state = json.loads((directory / "trainer_state.json").read_bytes())
    step = int(match[1])
    if type(state.get("global_step")) is not int or state["global_step"] != step:
        raise ValueError("trainer state step differs from checkpoint directory")
    if (
        state.get("is_world_process_zero") is not True
        or state.get("is_local_process_zero") is not True
    ):
        raise ValueError("receipt supports only the recorded primary single-process writer")
    return step


def _verify_best(directory: Path, identity: dict, model_format: str, fp16: bool):
    state = json.loads((directory / "trainer_state.json").read_bytes())
    if value := state.get("best_model_checkpoint"):
        best = Path(value)
        if (
            best.resolve().parent != directory.resolve().parent
            or not re.fullmatch(r"checkpoint-([1-9][0-9]*)", best.name)
            or int(best.name.split("-")[-1]) > state["global_step"]
        ):
            raise ValueError("best checkpoint points outside this run or into its future")
        if best.resolve() != directory.resolve():
            _verify_inventory(best, identity, model_format=model_format, fp16=fp16)


def _verify_inventory(directory: Path, identity: dict, *, model_format: str, fp16: bool) -> dict:
    expected = identity_digest(identity)
    if (directory / RECEIPT).is_symlink():
        raise ValueError("checkpoint receipt cannot be a symbolic link")
    try:
        receipt = json.loads((directory / RECEIPT).read_bytes())
    except FileNotFoundError as exc:
        raise ValueError("checkpoint has no completion receipt") from exc
    if (
        receipt.get("contract") != CONTRACT
        or receipt.get("identity_sha256") != expected
        or canonical(receipt.get("identity")) != canonical(identity)
        or receipt.get("model_format") != model_format
        or receipt.get("fp16") is not fp16
    ):
        raise ValueError("checkpoint identity, format or precision changed")
    files = _inventory(directory)
    step = _structure(directory, files, model_format, fp16)
    if receipt.get("files") != files or receipt.get("step") != step:
        raise ValueError("checkpoint artifact inventory changed")
    return receipt


def verify(directory: Path, identity: dict, *, model_format: str, fp16: bool = False) -> dict:
    receipt = _verify_inventory(directory, identity, model_format=model_format, fp16=fp16)
    _verify_best(directory, identity, model_format, fp16)
    return receipt


def seal(directory: Path, identity: dict, *, model_format: str, fp16: bool = False) -> dict:
    identity_hash = identity_digest(identity)
    if (directory / RECEIPT).exists():
        return verify(directory, identity, model_format=model_format, fp16=fp16)
    files = _inventory(directory)
    step = _structure(directory, files, model_format, fp16)
    _verify_best(directory, identity, model_format, fp16)
    # Flush existing bytes before publishing the completion marker. On a Modal
    # Volume the caller must still commit, and prove distributed ownership.
    for name in files:
        with (directory / name).open("rb") as stream:
            os.fsync(stream.fileno())
    if _inventory(directory) != files:
        raise ValueError("checkpoint changed before its receipt was published")
    receipt = {
        "contract": CONTRACT,
        "identity": json.loads(canonical(identity)),
        "identity_sha256": identity_hash,
        "model_format": model_format,
        "fp16": fp16,
        "step": step,
        "files": files,
    }
    temporary = directory.parent / f".receipt-{directory.name}-{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as stream:
            stream.write(canonical(receipt))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, directory / RECEIPT)  # exclusive publication; never replace a receipt
        temporary.unlink()
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    return receipt


def latest(root: Path, identity: dict, *, model_format: str, fp16: bool = False) -> Path | None:
    """No unrecorded rollback: any incomplete/unverified save stops automatic resume."""
    candidates = sorted(root.glob("checkpoint-*"), key=lambda p: p.name)
    checked = []
    for path in candidates:
        receipt = _verify_inventory(path, identity, model_format=model_format, fp16=fp16)
        checked.append((receipt["step"], path))
    if not checked:
        return None
    newest = max(checked)[1]
    # Only the resumed state needs its best weights; older saves may refer to
    # best checkpoints already removed by normal retention.
    _verify_best(newest, identity, model_format, fp16)
    return newest


class SealBeforeRetention:
    """Transformers 5.17 save protocol: seal and commit before any retention.

    Upstream rotation is a module function, not an overridable Trainer method.
    Disable its deletion during the save, restore the real training arguments,
    then seal/persist the complete checkpoint before running retention ourselves.
    """

    checkpoint_identity: dict
    checkpoint_model_format: str

    def _save_checkpoint(self, model, trial):
        import torch
        from transformers.trainer_utils import rotate_checkpoints

        if self.args.world_size != 1 or self.args.push_to_hub:
            raise ValueError("checkpoint receipts require one writer and no automatic Hub push")
        limit = self.args.save_total_limit
        self.args.save_total_limit = None
        try:
            super()._save_checkpoint(model, trial)
        finally:
            self.args.save_total_limit = limit
        root = Path(self._get_output_dir(trial=trial))
        directory = root / f"checkpoint-{self.state.global_step}"
        # Upstream serialized the temporary retention setting. Persist the actual
        # configured args before hashing, so recipe and checkpoint agree.
        torch.save(self.args, directory / "training_args.bin")
        seal(
            directory,
            self.checkpoint_identity,
            model_format=self.checkpoint_model_format,
            fp16=self.args.fp16,
        )
        if commit := getattr(self, "checkpoint_commit", None):
            commit()
        rotate_checkpoints(
            output_dir=str(root),
            save_total_limit=limit,
            best_model_checkpoint=self.state.best_model_checkpoint,
            use_mtime=False,
        )
