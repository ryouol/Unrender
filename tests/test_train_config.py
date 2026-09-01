"""CPU-only unit tests for the train-config plumbing (no torch/unsloth import).

These cover the pieces that decide whether a (paid) GPU run is set up correctly:
the numeric-token-loss lever's token selection, the eval/save-step schedule for
best-checkpoint selection, and load_records oversampling vs unweighted-val. The
heavy train() path stays GPU-only; everything here is pure Python so it runs in
`pytest -q` on the Mac.

Run: pytest -q tests/test_train_config.py
"""

import json
import sys
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
    snapshot = tmp_path / "snapshots" / revision
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
    modal_train._production_model_snapshot.cache_clear()
    resolved = modal_train._production_model_snapshot("approved/model", revision, digest)
    assert resolved == str(snapshot.resolve())
    assert calls == [("approved/model", revision)]

    modal_train._production_model_snapshot.cache_clear()
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
