"""CPU-only unit tests for the train-config plumbing (no torch/unsloth import).

These cover the pieces that decide whether a (paid) GPU run is set up correctly:
the numeric-token-loss lever's token selection, the eval/save-step schedule for
best-checkpoint selection, and load_records oversampling vs unweighted-val. The
heavy train() path stays GPU-only; everything here is pure Python so it runs in
`pytest -q` on the Mac.

Run: pytest -q tests/test_train_config.py
"""

import ast
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from unrender.train.sft_lora import _eval_save_steps, _numeric_token_ids, load_records


class _FakeTok:
    """Minimal stand-in for a HF tokenizer: just len + id->token."""

    def __init__(self, toks):
        self._t = toks

    def __len__(self):
        return len(self._t)

    def convert_ids_to_tokens(self, i):
        return self._t[i]


def test_numeric_token_ids_selects_only_digit_bearing_tokens():
    toks = ["<pad>", "abc", "0", "3.14", "value", "x2", ".", ","]
    ids = _numeric_token_ids(_FakeTok(toks))
    assert ids == {2, 3, 5}  # "0", "3.14", "x2" — the digit-bearing ones
    # non-digit tokens (incl. the lone "." and ",") are excluded
    assert all(not any(c.isdigit() for c in toks[i]) for i in range(len(toks)) if i not in ids)


def test_numeric_token_ids_tolerates_non_string_tokens():
    """Some tokenizers return None for unused/added-token slots — must not crash."""
    ids = _numeric_token_ids(_FakeTok(["7", None, "ok"]))
    assert ids == {0}


def test_eval_save_steps_targets_n_evals():
    assert _eval_save_steps(2000, 5) == 400  # ~5 evals over the run
    assert _eval_save_steps(900, 3) == 300
    # save_steps == eval_steps, so it divides itself — load_best_model_at_end is happy
    es = _eval_save_steps(2000, 5)
    assert es % es == 0


def test_eval_save_steps_floor_and_cap():
    assert _eval_save_steps(0, 5) == 10  # degenerate (max_steps unknown)
    assert _eval_save_steps(30, 5) == 10  # floored at 10
    assert _eval_save_steps(7, 5) == 7  # never larger than the run -> one eval fires
    assert _eval_save_steps(2000, 0) >= 10  # n_evals=0 must not divide-by-zero


def _row(img, labels_shown, ctype="bar"):
    return {
        "images": [img],
        "messages": [
            {"role": "user", "content": "P"},
            {"role": "assistant", "content": "{}"},
        ],
        "meta": {"labels_shown": labels_shown, "chart_type": ctype},
    }


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_load_records_val_is_unweighted(tmp_path):
    """Val load (weight 1.0) must be the natural distribution — one copy per row,
    so best-checkpoint selection isn't biased toward the oversampled slices."""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n")  # exists -> _resolve_image returns it as-is
    p = tmp_path / "val.jsonl"
    _write(p, [_row(str(img), labels_shown=False), _row(str(img), labels_shown=True)])
    recs = load_records([str(p)], data_root=str(tmp_path), labelfree_weight=1.0, seed=0)
    assert len(recs) == 2
    assert {r["user"] for r in recs} == {"P"}


def test_load_records_oversamples_label_free(tmp_path):
    """Train load duplicates label-free rows by the (integer) weight — the
    label-free skill the model must learn."""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n")
    p = tmp_path / "train.jsonl"
    _write(p, [_row(str(img), labels_shown=False)] * 4)  # all label-free
    recs = load_records([str(p)], data_root=str(tmp_path), labelfree_weight=2.0, seed=0)
    assert len(recs) == 8  # each label-free row appears 2x at weight 2.0


def test_load_records_hbar_weight_composes(tmp_path):
    """A label-free horizontal_bar gets BOTH multipliers (label-free x hbar)."""
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n")
    p = tmp_path / "train.jsonl"
    _write(p, [_row(str(img), labels_shown=False, ctype="horizontal_bar")])
    recs = load_records(
        [str(p)], data_root=str(tmp_path), labelfree_weight=2.0, seed=0, hbar_weight=3.0
    )
    assert len(recs) == 6  # 2 (label-free) * 3 (hbar)


def test_latest_checkpoint(tmp_path):
    from unrender.train.sft_lora import _latest_checkpoint

    assert _latest_checkpoint(str(tmp_path / "nope")) is None  # fresh run
    root = tmp_path / "run" / "checkpoints"
    root.mkdir(parents=True)
    assert _latest_checkpoint(str(tmp_path / "run")) is None  # dir but no ckpts
    for n in (449, 898, 1347):
        (root / f"checkpoint-{n}").mkdir()
    (root / "checkpoint-tmp").mkdir()  # non-numeric ignored
    got = _latest_checkpoint(str(tmp_path / "run"))
    assert got and got.endswith("checkpoint-1347")  # numeric max, not lexical


def test_parse_eval_specs():
    import modal_train

    specs = modal_train._parse_eval_specs("real_v0,common300,v2:300")
    assert specs == [
        {"limit": 0, "data": "real_v0", "subset": ""},
        {"limit": 0, "data": "v1", "subset": "common300"},
        {"limit": 300, "data": "v2", "subset": ""},
    ]
    assert modal_train._parse_eval_specs("") == []  # chain off by default
    assert modal_train._parse_eval_specs(" v1 , ") == [{"limit": 0, "data": "v1", "subset": ""}]


def test_production_model_resolution_uses_only_verified_hub_snapshot(tmp_path, monkeypatch):
    import modal_train

    revision = "1" * 40
    snapshot = tmp_path / "repository" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text('{"model_type":"test"}', encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(b"immutable-weights")
    digest = modal_train._snapshot_digest(snapshot)
    calls = []

    def snapshot_download(*, repo_id, revision):
        calls.append((repo_id, revision))
        return str(snapshot)

    fake_hub = ModuleType("huggingface_hub")
    fake_hub.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)
    resolved = modal_train._production_model_snapshot("approved/model", revision, digest)
    resolved_path = Path(resolved)
    assert resolved_path != snapshot.resolve()
    assert resolved_path.name == digest
    assert (resolved_path / "model.safetensors").read_bytes() == b"immutable-weights"
    assert not ((resolved_path / "model.safetensors").stat().st_mode & 0o222)
    assert calls == [("approved/model", revision)]

    (snapshot / "model.safetensors").write_bytes(b"source-mutated-after-materialization")
    cached = modal_train._production_model_snapshot("approved/model", revision, digest)
    assert cached == resolved
    assert (resolved_path / "model.safetensors").read_bytes() == b"immutable-weights"

    cached_weights = resolved_path / "model.safetensors"
    cached_weights.chmod(0o600)
    cached_weights.write_bytes(b"post-cache-tampering")
    cached_weights.chmod(0o400)
    with pytest.raises(ValueError, match="drifted from its content address"):
        modal_train._production_model_snapshot("approved/model", revision, digest)

    cached_weights.chmod(0o600)
    cached_weights.write_bytes(b"immutable-weights")
    cached_weights.chmod(0o400)
    original_materialization = resolved_path.with_name(f"{digest}-original")
    resolved_path.chmod(0o700)
    resolved_path.rename(original_materialization)
    resolved_path.symlink_to(original_materialization, target_is_directory=True)
    with pytest.raises(ValueError, match="root is unsafe"):
        modal_train._production_model_snapshot("approved/model", revision, digest)
    resolved_path.unlink()
    original_materialization.rename(resolved_path)
    resolved_path.chmod(0o500)

    with pytest.raises(ValueError, match="approved manifest"):
        modal_train._production_model_snapshot("approved/model", revision, "a" * 64)
    with pytest.raises(ValueError, match="owner/model"):
        modal_train._production_model_snapshot("/vol/mutable-model", revision, digest)


def test_provider_release_covers_source_runtime_and_model_identity():
    import modal_train

    assert modal_train.INFER_V != modal_train.V
    base = {
        "runtime_versions": {"torch": "2.9.1", "transformers": "4.57.6"},
        "model_path": "approved/model",
        "revision": "1" * 40,
        "model_digest": "2" * 64,
        "prompt_sha256": "3" * 64,
    }
    release = modal_train._provider_release_digest(**base)
    assert len(release) == 64
    assert release != modal_train._provider_release_digest(**{**base, "model_digest": "4" * 64})


def test_production_modal_deployment_exports_exact_infer_one_contract():
    import modal_train

    tree = ast.parse(Path(modal_train.__file__).read_text(encoding="utf-8"))
    function = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "infer_one"
    )
    assert any(
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and isinstance(decorator.func.value, ast.Name)
        and decorator.func.value.id == "production_app"
        and decorator.func.attr == "function"
        for decorator in function.decorator_list
    )


def test_model_snapshot_rejects_external_links_and_writable_files(tmp_path):
    import modal_train

    revision = "1" * 40
    snapshot = tmp_path / "repository" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    (snapshot / "weights.bin").symlink_to(outside)
    with pytest.raises(ValueError, match="outside its repository cache"):
        modal_train._snapshot_digest(snapshot)

    (snapshot / "weights.bin").unlink()
    local = snapshot / "weights.bin"
    local.write_bytes(b"weights")
    local.chmod(0o664)
    with pytest.raises(ValueError, match="group/world-writable"):
        modal_train._snapshot_digest(snapshot)


def test_model_snapshot_rejects_directory_links_and_parent_swaps(tmp_path, monkeypatch):
    import modal_train

    revision = "1" * 40
    snapshot = tmp_path / "repository" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    external = tmp_path / "external-directory"
    external.mkdir()
    (external / "weights.bin").write_bytes(b"outside")
    (snapshot / "linked").symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="directory symlink"):
        modal_train._snapshot_digest(snapshot)

    (snapshot / "linked").unlink()
    model_dir = snapshot / "model"
    model_dir.mkdir()
    (model_dir / "weights.bin").write_bytes(b"approved")
    original_snapshot_files = modal_train._snapshot_files

    def swap_parent(path):
        files = original_snapshot_files(path)
        model_dir.rename(snapshot / "model-original")
        model_dir.symlink_to(external, target_is_directory=True)
        return files

    monkeypatch.setattr(modal_train, "_snapshot_files", swap_parent)
    with pytest.raises(ValueError, match="changed before it was opened"):
        modal_train._snapshot_digest(snapshot)


def test_model_snapshot_detects_owner_mutation_during_descriptor_copy(tmp_path, monkeypatch):
    import modal_train

    revision = "1" * 40
    snapshot = tmp_path / "repository" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    weights = snapshot / "weights.bin"
    weights.write_bytes(b"approved-weights")
    original_read = modal_train.os.read
    changed = False

    def mutate_after_read(descriptor, amount):
        nonlocal changed
        chunk = original_read(descriptor, amount)
        if chunk and not changed:
            changed = True
            weights.write_bytes(b"tampered-weights")
        return chunk

    monkeypatch.setattr(modal_train.os, "read", mutate_after_read)
    with pytest.raises(ValueError, match="changed while it was copied"):
        modal_train._snapshot_digest(snapshot)


def test_parse_type_weights():
    from unrender.train.sft_lora import _parse_type_weights

    assert _parse_type_weights("multi_line:1.5,stacked_bar:2") == {
        "multi_line": 1.5,
        "stacked_bar": 2.0,
    }
    assert _parse_type_weights("") == {} and _parse_type_weights(None) == {}


def test_load_records_type_weights(tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n")
    p = tmp_path / "train.jsonl"
    _write(
        p,
        [
            _row(str(img), labels_shown=True, ctype="multi_line"),
            _row(str(img), labels_shown=True, ctype="bar"),
        ],
    )
    recs = load_records(
        [str(p)],
        data_root=str(tmp_path),
        labelfree_weight=1.0,
        seed=0,
        type_weights={"multi_line": 3.0},
    )
    assert len(recs) == 4  # multi_line x3 + bar x1


def test_private_modal_release_is_content_verified(tmp_path, monkeypatch):
    import modal_train

    monkeypatch.setattr(modal_train, "INFER_V", str(tmp_path))
    temporary = tmp_path / "releases" / "temporary"
    temporary.mkdir(parents=True)
    model = temporary / "config.json"
    model.write_text('{"model_type":"qwen3_vl"}')
    digest = modal_train._snapshot_digest(temporary)
    model.chmod(0o400)
    temporary.chmod(0o500)
    target = temporary.rename(temporary.parent / digest)
    try:
        assert modal_train._production_model_snapshot(
            "modal-volume/unrender-inference-cache", digest, digest
        ) == str(target)
        with pytest.raises(ValueError, match="matching digest"):
            modal_train._production_model_snapshot(
                "modal-volume/unrender-inference-cache", "a" * 64, digest
            )
        model = target / "config.json"
        model.chmod(0o600)
        model.write_text("tampered")
        model.chmod(0o400)
        with pytest.raises(ValueError, match="drifted"):
            modal_train._production_model_snapshot(
                "modal-volume/unrender-inference-cache", digest, digest
            )
    finally:
        target.chmod(0o700)
        (target / "config.json").chmod(0o600)


def test_production_settings_require_exact_modal_release_digest(tmp_path):
    from dataclasses import replace

    from unrender.product.config import Settings

    digest = "a" * 64
    settings = Settings(
        data_dir=tmp_path,
        environment="production",
        base_url="https://example.com",
        extractor_backend="modal",
        allow_registration=False,
        seed_demo_account=False,
        modal_model_path="modal-volume/unrender-inference-cache",
        modal_model_revision=digest,
        modal_model_digest=digest,
        modal_provider_release="b" * 64,
    )
    settings.validate()
    for revision in ["latest", "a" * 40, "c" * 64, "../escape"]:
        with pytest.raises(ValueError, match="matching SHA-256"):
            replace(settings, modal_model_revision=revision).validate()


def test_render_origin_uses_platform_url_with_explicit_override(monkeypatch):
    from unrender.product.config import Settings

    monkeypatch.delenv("UNRENDER_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://assigned-service.onrender.com/")
    assert Settings.from_env().base_url == "https://assigned-service.onrender.com"
    monkeypatch.setenv("UNRENDER_BASE_URL", "https://custom.example/")
    assert Settings.from_env().base_url == "https://custom.example"
