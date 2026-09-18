"""Offline CPU fault experiment for the checkpoint protocol, without downloaded weights.

Uses torch 2.14.0 / transformers 5.17.0 / accelerate 1.15.0 in a separate environment.
This is a tiny random GPT-2 Trainer probe, not Qwen, CUDA or Modal parity.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import random
import shutil
import signal
import subprocess
import sys
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def worker(out: Path, mode: str, resume: str, checked: bool):
    import numpy as np
    import torch
    from transformers import (
        GPT2Config,
        GPT2LMHeadModel,
        Trainer,
        TrainerCallback,
        TrainingArguments,
        set_seed,
    )

    for package, version in {
        "torch": "2.14.0",
        "transformers": "5.17.0",
        "accelerate": "1.15.0",
    }.items():
        if importlib.metadata.version(package).split("+")[0] != version:
            raise ValueError(f"requires {package}=={version}")
    torch.set_num_threads(1)
    set_seed(123)

    def normalized(value):
        if isinstance(value, torch.Tensor):
            tensor = value.detach().cpu().contiguous()
            return {
                "dtype": str(tensor.dtype),
                "shape": list(tensor.shape),
                "sha256": sha(tensor.reshape(-1).view(torch.uint8).numpy().tobytes()),
            }
        if isinstance(value, np.ndarray):
            return {
                "dtype": str(value.dtype),
                "shape": list(value.shape),
                "sha256": sha(value.tobytes()),
            }
        if isinstance(value, dict):
            return {str(key): normalized(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalized(item) for item in value]
        return value

    def state_hash(value):
        return sha(json.dumps(normalized(value), sort_keys=True, allow_nan=False).encode())

    class Data(torch.utils.data.Dataset):
        def __len__(self):
            return 32

        def __getitem__(self, index):
            tokens = torch.randint(1, 32, (12,), generator=torch.Generator().manual_seed(index))
            return {"input_ids": tokens, "labels": tokens.clone()}

    class Crash(TrainerCallback):
        def on_save(self, args, state, control, **kwargs):
            if mode == "kill_complete" and state.global_step == 4:
                os.kill(os.getpid(), signal.SIGKILL)

    from unrender.train.checkpoints import SealBeforeRetention, verify

    trainer_base = (
        type("CheckedTrainer", (SealBeforeRetention, Trainer), {}) if checked else Trainer
    )

    class ProbeTrainer(trainer_base):
        def _save_rng_state(self, output_dir):
            if mode == "kill_partial" and self.state.global_step == 4:
                os.kill(os.getpid(), signal.SIGKILL)
            super()._save_rng_state(output_dir)

    config = GPT2Config(
        vocab_size=32,
        n_positions=16,
        n_embd=16,
        n_layer=1,
        n_head=2,
        resid_pdrop=0.2,
        embd_pdrop=0.2,
        attn_pdrop=0.2,
        use_cache=False,
        bos_token_id=1,
        eos_token_id=1,
        pad_token_id=0,
    )
    config._attn_implementation = "eager"
    model = GPT2LMHeadModel(config)
    learning_rate = 0.002 if mode == "changed_lr" else 0.001
    args = TrainingArguments(
        output_dir=str(out),
        use_cpu=True,
        full_determinism=True,
        seed=123,
        data_seed=456,
        max_steps=8,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=2,
        learning_rate=learning_rate,
        warmup_steps=1,
        optim="adamw_torch",
        save_steps=4,
        save_total_limit=1 if checked else 3,
        logging_steps=1,
        disable_tqdm=True,
        report_to=[],
        dataloader_num_workers=0,
    )
    trainer = ProbeTrainer(model=model, args=args, train_dataset=Data(), callbacks=[Crash()])
    if checked:
        settings = args.to_dict()
        for name in ("output_dir", "logging_dir", "run_name"):
            settings.pop(name, None)
        repo = Path(__file__).resolve().parents[1]
        identity = {
            "base": {
                "config": config.to_dict(),
                "initial_weights_sha256": state_hash(model.state_dict()),
            },
            "processor": {"kind": "pretokenized synthetic integers"},
            "source_inputs": {"sha256": state_hash([Data()[i] for i in range(len(Data()))])},
            "hyperparameters": settings,
            "runtime": {
                "world_size": args.world_size,
                "python": platform.python_version(),
                "packages": {
                    name: importlib.metadata.version(name)
                    for name in ("torch", "transformers", "accelerate")
                },
            },
            "source_code": {
                name: sha((repo / name).read_bytes())
                for name in ("analysis/audit_training_resume.py", "unrender/train/checkpoints.py")
            },
        }
        trainer.checkpoint_identity = identity
        trainer.checkpoint_model_format = "full"
        if resume:
            verify(Path(resume), identity, model_format="full")
    trainer.train(resume_from_checkpoint=resume or None)

    result = {
        "global_step": trainer.state.global_step,
        "learning_rate_argument": learning_rate,
        "model_sha256": state_hash(model.state_dict()),
        "optimizer_sha256": state_hash(trainer.optimizer.state_dict()),
        "scheduler_sha256": state_hash(trainer.lr_scheduler.state_dict()),
        "rng_sha256": state_hash(
            {
                "torch": torch.get_rng_state(),
                "numpy": np.random.get_state(),
                "python": random.getstate(),
            }
        ),
        "losses": [
            {"step": row["step"], "loss": row["loss"]}
            for row in trainer.state.log_history
            if "loss" in row
        ],
    }
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")


def audit(out: Path):
    if out.exists():
        raise ValueError("audit output must be a new directory")
    out.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[1]
    report = {
        "contract": "training-resume-fault-audit-v1",
        "device": "cpu",
        "downloaded_weights": False,
        "python": platform.python_version(),
        "system": platform.system(),
        "machine": platform.machine(),
        "packages": dict(
            sorted((d.metadata["Name"], d.version) for d in importlib.metadata.distributions())
        ),
        "auditor_sha256": sha(Path(__file__).read_bytes()),
        "processes": {},
        "limits": "Random tiny GPT-2 / stock Trainer; not Qwen, Unsloth, CUDA or Modal parity.",
    }

    def run(name, mode="normal", resume="", checked=False):
        directory = out / name
        log = out / f"{name}.log"
        command = [
            sys.executable,
            "-m",
            "analysis.audit_training_resume",
            "--out",
            str(directory),
            "--worker",
            mode,
            "--resume",
            str(resume),
        ]
        if checked:
            command.append("--checked")
        with log.open("w") as stream:
            completed = subprocess.run(
                command,
                cwd=repo,
                stdout=stream,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "HF_HUB_OFFLINE": "1",
                    "TRANSFORMERS_OFFLINE": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                timeout=60,
            )
        report["processes"][name] = {
            "returncode": completed.returncode,
            "log_sha256": sha(log.read_bytes()),
        }
        print(f"{name}: exit {completed.returncode}", flush=True)
        return completed.returncode

    if run("continuous") != 0 or run("killed_complete", "kill_complete") != -signal.SIGKILL:
        raise RuntimeError("continuous or complete-checkpoint crash probe failed")
    checkpoint = out / "killed_complete/checkpoint-4"
    if run("resumed", resume=checkpoint) != 0:
        raise RuntimeError("complete checkpoint did not resume")
    run("changed_lr", "changed_lr", checkpoint)
    if run("killed_partial", "kill_partial") != -signal.SIGKILL:
        raise RuntimeError("partial-checkpoint crash probe failed")
    partial = out / "killed_partial/checkpoint-4"
    run("partial_resume", resume=partial)

    run("checked_continuous", checked=True)
    run("checked_killed_complete", "kill_complete", checked=True)
    checked_checkpoint = out / "checked_killed_complete/checkpoint-4"
    run("checked_resumed", resume=checked_checkpoint, checked=True)
    run("checked_changed_lr", "changed_lr", checked_checkpoint, checked=True)
    run("checked_killed_partial", "kill_partial", checked=True)
    run("checked_partial_resume", resume=out / "checked_killed_partial/checkpoint-4", checked=True)

    before = json.loads((out / "continuous/result.json").read_bytes())
    after = json.loads((out / "resumed/result.json").read_bytes())
    report["complete_resume_equal"] = {
        key: before[key] == after[key]
        for key in (
            "model_sha256",
            "optimizer_sha256",
            "scheduler_sha256",
            "rng_sha256",
            "losses",
            "global_step",
        )
    }
    checked_before = json.loads((out / "checked_continuous/result.json").read_bytes())
    checked_after = json.loads((out / "checked_resumed/result.json").read_bytes())
    report["verified_guard"] = {
        "complete_resume_equal": {
            key: checked_before[key] == checked_after[key]
            for key in report["complete_resume_equal"]
        },
        "changed_lr_rejected": report["processes"]["checked_changed_lr"]["returncode"] != 0,
        "partial_resume_rejected": report["processes"]["checked_partial_resume"]["returncode"] != 0,
        "receipt_before_complete_kill": (checked_checkpoint / "checkpoint-receipt.json").is_file(),
        "retained_checkpoint_has_receipt": (
            out / "checked_continuous/checkpoint-8/checkpoint-receipt.json"
        ).is_file(),
        "older_checkpoint_rotated": not (out / "checked_continuous/checkpoint-4").exists(),
        "verifier_sha256": sha((repo / "unrender/train/checkpoints.py").read_bytes()),
    }
    report["changed_lr_accepted"] = report["processes"]["changed_lr"]["returncode"] == 0
    report["partial_resume_accepted"] = report["processes"]["partial_resume"]["returncode"] == 0
    report["checkpoint_files"] = {
        "complete": sorted(p.name for p in checkpoint.iterdir()),
        "partial": sorted(p.name for p in partial.iterdir()),
    }
    from unrender.train.checkpoints import latest

    fixture = out / "selector-fixture/checkpoints"
    fixture.mkdir(parents=True)
    shutil.copytree(checked_checkpoint, fixture / "checkpoint-4")
    (fixture / "checkpoint-8").mkdir()
    saved_identity = json.loads((checked_checkpoint / "checkpoint-receipt.json").read_bytes())[
        "identity"
    ]
    rejected = False
    try:
        latest(fixture, saved_identity, model_format="full")
    except ValueError:
        rejected = True
    report["project_selector"] = {
        "source_sha256": sha((repo / "unrender/train/checkpoints.py").read_bytes()),
        "rejects_incomplete_newest": rejected,
    }
    guard = report["verified_guard"]
    required = [
        "changed_lr_rejected",
        "partial_resume_rejected",
        "receipt_before_complete_kill",
        "retained_checkpoint_has_receipt",
        "older_checkpoint_rotated",
    ]
    if not (
        rejected
        and all(guard["complete_resume_equal"].values())
        and all(guard[key] for key in required)
    ):
        raise AssertionError("checkpoint regression")
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "complete_resume_equal",
                    "changed_lr_accepted",
                    "partial_resume_accepted",
                    "project_selector",
                )
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--worker", choices=["normal", "kill_complete", "kill_partial", "changed_lr"]
    )
    parser.add_argument("--resume", default="")
    parser.add_argument("--checked", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.out, args.worker, args.resume, args.checked)
    else:
        audit(args.out)


if __name__ == "__main__":
    main()
