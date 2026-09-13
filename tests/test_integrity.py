"""Integrity guards for the eval harness — the safeguards that would have caught
the dev300/Modal-test split desync (subset coverage, fingerprints, no-clobber,
resume-config, deterministic splitting, duplicate ids, output-tag uniqueness).

All hermetic: mock 'perfect' provider, tmp dirs, no API/GPU/network.
"""

import json
import random
from pathlib import Path

import pytest

from unrender.io_utils import fingerprint_ids
from unrender.schema.chart_schema import ChartData, Point, Series, canonical_json


def _gt():
    return ChartData(chart_type="bar", series=[Series(name="S", points=[
        Point(x="a", y=1.0), Point(x="b", y=2.0)])])


def _chat_row(i, labels_shown=True):
    return {
        "images": [f"data/x/{i:07d}.png"],
        "messages": [{"role": "user", "content": "P"},
                     {"role": "assistant", "content": canonical_json(_gt())}],
        "meta": {"labels_shown": labels_shown, "chart_type": "bar", "augmented": False},
    }


def _write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r) + "\n" for r in rows))


def _make_dataset(path, n):
    _write_jsonl(path, [_chat_row(i) for i in range(1, n + 1)])


# --- fingerprints ------------------------------------------------------------

def test_fingerprint_order_independent_content_sensitive_and_dedup():
    assert fingerprint_ids(["a", "b", "c"]) == fingerprint_ids(["c", "a", "b"])  # order-independent
    assert fingerprint_ids(["a", "b"]) != fingerprint_ids(["a", "c"])            # content-sensitive
    assert fingerprint_ids(["a", "a", "b"]) == fingerprint_ids(["a", "b"])  # dedup
    fp = fingerprint_ids(["a"])
    assert isinstance(fp, str) and len(fp) == 16


# --- run() coverage + provenance --------------------------------------------

def test_run_coverage_guard_raises_on_missing_id(tmp_path):
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"
    _make_dataset(data, 2)
    with pytest.raises(SystemExit, match="coverage"):
        run("perfect", "mock", str(data), str(tmp_path / "o"), 0, 0,
            only_ids={"0000001", "ZZZZZZZ"})


def test_run_records_fingerprints_and_pinned_revision(tmp_path):
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"
    _make_dataset(data, 3)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0, only_ids={"0000001", "0000002"})
    meta = json.loads((out / "meta.json").read_text())
    assert meta["subset_fp"] and meta["dataset_fp"] and meta["n_subset"] == 2
    # an explicit Hub revision is recorded (the base-control fix); None would be unpinned
    out2 = tmp_path / "o2"
    run("perfect", "Some/HubModel", str(data), str(out2), 0, 0, revision="abc123")
    assert json.loads((out2 / "meta.json").read_text())["model_revision"] == "abc123"


def test_hf_hub_model_requires_pinned_revision(tmp_path):
    """A Hub-id base control must be revision-pinned — an unpinned HEAD can drift
    from the merged model's processor (a base-vs-LoRA confound, audit finding I).
    A local model dir is exempt (fingerprinted by content)."""
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"
    _make_dataset(data, 2)
    # Hub id (not a local path) without --revision -> refuse before any model load.
    with pytest.raises(SystemExit, match="revision"):
        run("hf", "Qwen/Qwen3-VL-4B-Instruct", str(data), str(tmp_path / "o"), 0, 0)
    # Passing an explicit revision clears the guard (it then proceeds to load, which
    # needs torch — so we only assert the guard itself no longer raises SystemExit).
    try:
        run(
            "hf", "Qwen/Qwen3-VL-4B-Instruct", str(data), str(tmp_path / "o2"),
            0, 0, revision="deadbeef",
        )
    except SystemExit as e:
        assert "revision" not in str(e)
    except Exception:
        pass  # any non-SystemExit (e.g. missing torch) means the guard passed


def test_resume_config_mismatch_raises(tmp_path):
    from unrender.eval.run_baselines import run
    data = tmp_path / "test.jsonl"
    _make_dataset(data, 2)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0)                       # greedy
    with pytest.raises(SystemExit, match="resume-config"):                  # different decoder
        run("perfect", "mock", str(data), str(out), 0, 0,
            gen_config={"repetition_penalty": 1.1})


# --- score() coverage, no-clobber, duplicate rows ---------------------------

def test_score_subset_does_not_clobber_full_report(tmp_path):
    from unrender.eval.run_baselines import run
    from unrender.eval.score import score
    data = tmp_path / "test.jsonl"
    _make_dataset(data, 3)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0)
    pred = str(out / "predictions.jsonl")

    score(pred)                                   # full -> report.json
    full = (out / "report.json").read_text()
    score(pred, only_ids={"0000001", "0000002"})  # subset must NOT touch report.json
    assert (out / "report.json").read_text() == full
    assert any(p.name.startswith("report.subset-") for p in out.iterdir())


def test_score_coverage_guard_raises_on_missing_id(tmp_path):
    from unrender.eval.run_baselines import run
    from unrender.eval.score import score
    data = tmp_path / "test.jsonl"
    _make_dataset(data, 2)
    out = tmp_path / "o"
    run("perfect", "mock", str(data), str(out), 0, 0)
    with pytest.raises(SystemExit, match="coverage"):
        score(str(out / "predictions.jsonl"), out=str(tmp_path / "x.json"),
              only_ids={"0000001", "NOPE"})


def test_score_duplicate_rows_raise(tmp_path):
    from unrender.eval.score import score
    pred = tmp_path / "predictions.jsonl"
    row = {"id": "0000001", "gt": canonical_json(_gt()), "raw": "{}", "status": "ok"}
    pred.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(SystemExit, match="duplicate"):
        score(str(pred))


# --- deterministic splitting -------------------------------------------------

def _make_manifest(d, order):
    d = Path(d)
    (d / "labels").mkdir(parents=True, exist_ok=True)
    entries = []
    for i in order:
        stem = f"{i:07d}"
        (d / "labels" / f"{stem}.json").write_text(canonical_json(_gt()))
        entries.append({"id": stem, "image": f"data/img/{stem}.png",
                        "label": str(d / "labels" / f"{stem}.json"),
                        "chart_type": "bar", "labels_shown": True, "augmented": False})
    _write_jsonl(d / "manifest.jsonl", entries)


def test_split_membership_independent_of_manifest_order(tmp_path):
    from unrender.data_gen.split_dataset import split
    order = list(range(1, 21))
    shuffled = order[:]
    random.Random(99).shuffle(shuffled)
    _make_manifest(tmp_path / "a", order)       # ascending manifest
    _make_manifest(tmp_path / "b", shuffled)    # same ids, different write-order
    split(str(tmp_path / "a"), val_size=4, test_size=6, seed=7)
    split(str(tmp_path / "b"), val_size=4, test_size=6, seed=7)

    def ids(p):
        return {Path(json.loads(line)["images"][0]).stem
                for line in Path(p).read_text().splitlines() if line.strip()}
    for name in ("train", "val", "test"):
        assert ids(tmp_path / "a" / f"{name}.jsonl") == ids(tmp_path / "b" / f"{name}.jsonl")


# --- table-level leakage (data-table dedup across splits) -------------------

def _table_sigs_by_id(path):
    """id -> data_table_signature for a chat-format split file."""
    from unrender.io_utils import read_jsonl
    from unrender.schema.chart_schema import ChartData, data_table_signature
    out = {}
    for r in read_jsonl(path):
        rid = Path(r["images"][0]).stem
        out[rid] = data_table_signature(ChartData.model_validate_json(r["messages"][1]["content"]))
    return out


def test_data_table_signature_ignores_cosmetics_keeps_values():
    from unrender.schema.chart_schema import Axis, ChartData, Point, Series, data_table_signature
    base = ChartData(chart_type="bar", title="A", x_axis=Axis(label="X"),
                     series=[Series(name="S", points=[Point(x="a", y=1.0), Point(x="b", y=2.0)])])
    cosmetic = base.model_copy(deep=True)
    cosmetic.title = "totally different title"
    valued = base.model_copy(deep=True)
    valued.series[0].points[1].y = 2.5
    assert data_table_signature(base) == data_table_signature(cosmetic)  # cosmetics ignored
    assert data_table_signature(base) != data_table_signature(valued)    # value change detected


def test_common300_no_data_table_leak_into_train():
    """The base-vs-LoRA subset (common300) must share NO underlying data table with
    the TRAIN split — id-level disjointness isn't enough if a train chart was
    re-rendered into test (audit finding G). Reads the committed Modal split
    artifacts; skips if they aren't present."""
    root = Path(__file__).resolve().parent.parent
    train_p = root / "outputs/modal/data_v1/train.jsonl"
    test_p = root / "outputs/modal/data_v1/test.jsonl"
    sub_p = root / "unrender/eval/subsets/common300.json"
    if not (train_p.exists() and test_p.exists() and sub_p.exists()):
        pytest.skip("committed Modal split artifacts not present")
    common = set(json.loads(sub_p.read_text())["ids"])
    test_sigs = _table_sigs_by_id(test_p)
    common_sigs = {test_sigs[i] for i in common if i in test_sigs}
    train_sigs = set(_table_sigs_by_id(train_p).values())
    leaked = common_sigs & train_sigs
    assert not leaked, (
        f"{len(leaked)} common300 data tables also appear in TRAIN (memorization leak)"
    )


# --- geometry-supervision plumbing ------------------------------------------

def test_geometry_data_builder_and_decode_scoring(tmp_path):
    """End-to-end geometry arm: build geometry-target training rows from a seeded
    split, then score a 'perfect' geometry prediction file via --decode geometry.
    Both must round-trip to high cell@5_exact (the train target == what the eval
    decodes)."""
    import random as _random

    from unrender.data_gen.chart_specs import random_spec
    from unrender.data_gen.geometry import capture_geometry
    from unrender.data_gen.geometry_target import to_target
    from unrender.eval.score import score
    from unrender.prompts import GEOMETRY_PROMPT
    from unrender.train.geometry_data import build_geometry_split

    # 1. a small seeded source split (chat format, table-JSON targets)
    src = tmp_path / "train.jsonl"
    specs = {}
    with open(src, "w") as f:
        for i in range(4):
            spec = random_spec(_random.Random(5678 + i), hard=True)
            specs[i] = spec
            f.write(json.dumps({
                "images": [f"data/x/{i:07d}.png"],
                "messages": [{"role": "user", "content": "P"},
                             {"role": "assistant",
                              "content": canonical_json(spec.to_chart_data())}],
                "meta": {"labels_shown": spec.value_labels_shown, "chart_type": spec.chart_type},
            }) + "\n")

    # 2. build geometry-target rows; every row must carry GEOMETRY_PROMPT
    out = tmp_path / "train.geom.jsonl"
    res = build_geometry_split(str(src), str(out), base_seed=5678, hard=True)
    assert res["n_ok"] == 4 and res["n_mismatch"] == 0
    grows = [json.loads(line) for line in out.read_text().splitlines()]
    assert all(r["messages"][0]["content"] == GEOMETRY_PROMPT for r in grows)

    # 3. a 'perfect' geometry prediction file (raw = the captured target) scored
    #    via --decode geometry must recover values within tolerance.
    preds = tmp_path / "predictions.jsonl"
    with open(preds, "w") as f:
        for i, spec in specs.items():
            f.write(json.dumps({
                "id": f"{i:07d}", "gt": canonical_json(spec.to_chart_data()),
                "raw": to_target(capture_geometry(spec)),
                "status": "ok", "meta": {"labels_shown": spec.value_labels_shown},
            }) + "\n")
    rep = score(str(preds), out=str(tmp_path / "r.json"), decode="geometry")
    assert rep["tracks"]["0.05"]["metrics"]["cell_accuracy_exact"] >= 0.9


# --- precision levers (numeric-token loss + oversampling) -------------------

def test_numeric_token_ids_and_copies():
    """The precision-lever helpers (pure-Python, testable off the GPU box):
    digit-bearing tokens are detected for loss up-weighting, and the fractional
    oversample multiplier produces the right integer copy counts."""
    from unrender.train.sft_lora import _copies, _numeric_token_ids

    toks = ["the", "0.", "314", "abc", "Ġ5", "!", "100", "x"]  # ids 0..7

    class _FakeTok:
        def __len__(self):
            return len(toks)
        def convert_ids_to_tokens(self, i):
            return toks[i]

    assert _numeric_token_ids(_FakeTok()) == {1, 2, 4, 6}  # '0.', '314', 'Ġ5', '100'

    rng = random.Random(0)
    assert all(_copies(1.0, rng) == 1 for _ in range(30))   # no oversample
    assert all(_copies(3.0, rng) == 3 for _ in range(30))   # integer oversample
    vals = [_copies(1.5, rng) for _ in range(4000)]         # fractional -> mix of 1 and 2
    assert set(vals) == {1, 2}
    assert abs(sum(vals) / len(vals) - 1.5) < 0.08          # averages to the multiplier


# --- output-tag uniqueness (Modal) ------------------------------------------

def test_eval_tag_unique_per_config_and_preserves_resume_name():
    pytest.importorskip("modal")
    from modal_train import _eval_tag
    merged = "/vol/runs/qwen3vl4b-lora/merged"
    tags = {
        _eval_tag(merged, "v1", "", {}),                                    # LoRA full greedy
        _eval_tag(merged, "v1", "common300", {}),                           # LoRA subset
        _eval_tag("unsloth/Qwen3-VL-4B-Instruct", "v1", "common300", {}),   # base subset
        _eval_tag(merged, "v1", "common300", {"repetition_penalty": 1.1}),  # decoder arm
    }
    assert len(tags) == 4                                       # every config distinct
    assert _eval_tag(merged, "v1", "", {}) == "eval_v1__qwen3vl4b-lora"  # original name preserved
