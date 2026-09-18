"""Visibility regressions and generation -> split -> portable consumer checks."""

import json
import random
import shutil
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest

from unrender.data_gen.chart_specs import ChartSpec, random_spec, value_extent
from unrender.data_gen.generate import generate
from unrender.data_gen.provenance import digest, json_bytes, read_split, verify_dataset
from unrender.data_gen.render import _build_figure, render_chart
from unrender.data_gen.split_dataset import split
from unrender.eval.dataset import load_eval_samples
from unrender.train.sft_lora import load_records


def bar(**overrides):
    return replace(
        ChartSpec(
            chart_type="bar",
            title=None,
            x_label=None,
            y_label=None,
            y_unit="USD",
            categories=["a", "b"],
            series_names=[None],
            values=[[4, 6]],
            value_labels_shown=False,
        ),
        **overrides,
    )


@pytest.mark.parametrize("profile", [{}, {"hard": True}, {"v2": True}])
def test_all_profiles_have_visible_identities_and_contained_endpoints(profile):
    families = set()
    for seed in range(1000):
        spec = random_spec(random.Random(seed), **profile)
        spec.to_chart_data()  # semantic target validation applies to every sampled spec
        families.add(spec.chart_type)
        if len(spec.values) == 1:
            assert spec.series_names == [None]
        lo, hi = value_extent(spec.chart_type, spec.values)
        assert spec.y_baseline is None or spec.y_baseline <= lo
        assert spec.y_top is None or spec.y_top >= hi
    assert families == {
        "bar",
        "horizontal_bar",
        "line",
        "multi_line",
        "grouped_bar",
        "stacked_bar",
        "pie",
    }


def test_hidden_series_name_is_rejected_and_unit_only_axes_change_pixels():
    with pytest.raises(ValueError, match="series name must be null"):
        render_chart(bar(series_names=["invisible"]))
    usd, eur = bar(), bar(y_unit="EUR")
    for spec in (usd, eur):
        fig, ax = _build_figure(spec)
        try:
            assert ax.get_ylabel() == spec.y_unit
        finally:
            plt.close(fig)
    assert not np.array_equal(np.asarray(render_chart(usd)), np.asarray(render_chart(eur)))


def test_cumulative_stack_bounds_and_visible_counterfactual():
    spec = bar(chart_type="stacked_bar", series_names=["A", "B"], values=[[4, 6], [10, 12]])
    with pytest.raises(ValueError, match="upper plot bound"):
        render_chart(replace(spec, y_top=13))
    fig, ax = _build_figure(replace(spec, y_top=20))
    try:
        assert ax.get_ylim()[1] >= 18
        assert all(patch.get_y() + patch.get_height() <= ax.get_ylim()[1] for patch in ax.patches)
    finally:
        plt.close(fig)
    changed = replace(spec, values=[[4, 6], [10, 13]])
    assert not np.array_equal(np.asarray(render_chart(spec)), np.asarray(render_chart(changed)))


def test_render_is_independent_of_ambient_styles_without_changing_caller_state():
    reference = np.asarray(render_chart(bar()))
    with plt.rc_context({"axes.labelsize": 32, "figure.dpi": 60, "lines.linewidth": 12}):
        changed = np.asarray(render_chart(bar()))
        assert plt.rcParams["axes.labelsize"] == 32
    assert np.array_equal(reference, changed)


@pytest.mark.parametrize(
    "change",
    [
        {"values": [[-4, -6]], "y_top": -5},
        {"y_baseline": 5},
        {"values": [[float("nan"), 2]]},
        {"chart_type": "stacked_bar", "series_names": ["A", "B"], "values": [[-1, 2], [3, 4]]},
        {"chart_type": "pie"},
        {"chart_type": "multi_line", "series_names": ["hidden without a legend"]},
        {"categories": ["a", "a"]},
    ],
)
def test_invalid_targets_fail_before_rendering(change):
    with pytest.raises(ValueError):
        render_chart(bar(**change))


@pytest.mark.parametrize("chart_type", ["bar", "horizontal_bar", "line"])
def test_negative_ranges_are_visible(chart_type):
    spec = bar(chart_type=chart_type, values=[[-6, -4]], y_baseline=-7, y_top=-3)
    fig, ax = _build_figure(spec)
    try:
        bounds = ax.get_xlim() if chart_type == "horizontal_bar" else ax.get_ylim()
        assert bounds[0] <= -6 and bounds[1] >= -4
    finally:
        plt.close(fig)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("generated")
    generate(8, str(root), workers=1, augment=True, v2=True)
    return root


@pytest.fixture
def dataset(generated, tmp_path):
    root = tmp_path / "dataset"
    shutil.copytree(generated, root)
    return root


def test_portable_pipeline_preserves_evidence_and_rejects_working_directory_shadow(
    dataset, tmp_path, monkeypatch
):
    split(str(dataset), val_size=2, test_size=2)
    moved = tmp_path / "relocated"
    dataset.rename(moved)
    shadow = tmp_path / "unrelated"
    (shadow / "images").mkdir(parents=True)
    row = read_split(moved / "train.jsonl")[0]
    (shadow / row["images"][0]).write_bytes(b"wrong same-named image")
    monkeypatch.chdir(shadow)
    samples = load_eval_samples(str(moved / "train.jsonl"))
    records = load_records(["train.jsonl"], str(moved), 1.0, 0)
    assert len(samples) == len(records) == 4
    assert {s.image for s in samples} == {r["image"] for r in records}
    assert all(Path(s.image).parent == moved / "images" for s in samples)
    for sample in samples:
        receipt = sample.meta["generation"]
        assert receipt["image_sha256"] == digest(Path(sample.image).read_bytes())
        assert receipt["label_sha256"] == digest(sample.gt_json.encode())
        assert sample.meta["visual_review"] == "not_reviewed"


@pytest.mark.parametrize("damage", ["image", "label", "manifest", "incomplete", "spec", "contract"])
def test_corrupt_generation_cannot_publish_splits(dataset, damage):
    receipt_path = dataset / "generation.json"
    receipt = json.loads(receipt_path.read_text())
    manifest = dataset / "manifest.jsonl"
    entries = [json.loads(line) for line in manifest.read_text().splitlines()]
    if damage in {"image", "label"}:
        (dataset / entries[0][damage]).write_bytes(b"changed")
    elif damage == "incomplete":
        receipt["status"] = "generating"
    elif damage in {"spec", "contract"}:
        if damage == "spec":
            entries[0]["spec"]["values"][0][0] += 10
        else:
            entries[0]["target_contract"] = "historical"
        manifest.write_bytes(b"".join(json_bytes(row) for row in entries))
        receipt["manifest_sha256"] = digest(manifest.read_bytes())
    else:
        manifest.write_bytes(manifest.read_bytes() + b"\n")
    receipt_path.write_bytes(json_bytes(receipt))
    with pytest.raises(ValueError):
        split(str(dataset), val_size=2, test_size=2)
    assert not (dataset / "train.jsonl").exists()
    assert not (dataset / "split.json").exists()


@pytest.mark.parametrize(
    "damage", ["image", "target", "provenance", "membership", "incomplete", "removed_receipt"]
)
def test_loader_rechecks_artifacts_and_semantic_binding(dataset, damage):
    split(str(dataset), val_size=2, test_size=2)
    path = dataset / "train.jsonl"
    rows = read_split(path)
    receipt_path = dataset / "split.json"
    receipt = json.loads(receipt_path.read_text())
    if damage == "image":
        (dataset / rows[0]["images"][0]).write_bytes(b"changed")
    elif damage == "incomplete":
        receipt["status"] = "splitting"
    elif damage == "removed_receipt":
        (dataset / "generation.json").unlink()
    else:
        if damage == "target":
            rows[0]["messages"][1]["content"] = "{}"
        elif damage == "provenance":
            del rows[0]["meta"]["generation"]
        else:
            rows[1] = rows[0]
        path.write_bytes(b"".join(json_bytes(row) for row in rows))
        # Even rehashing a split cannot hide disagreement with generation evidence.
        receipt["files"]["train.jsonl"]["sha256"] = digest(path.read_bytes())
    receipt_path.write_bytes(json_bytes(receipt))
    with pytest.raises((ValueError, FileNotFoundError)):
        load_eval_samples(str(path), limit=1)
    with pytest.raises((ValueError, FileNotFoundError)):
        load_records([str(path)], str(dataset), 1.0, 0)


def test_generation_and_split_never_overwrite_frozen_files(dataset):
    before = {p.relative_to(dataset): p.read_bytes() for p in dataset.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="not empty"):
        generate(8, str(dataset), workers=1)
    assert before == {
        p.relative_to(dataset): p.read_bytes() for p in dataset.rglob("*") if p.is_file()
    }
    split(str(dataset), val_size=2, test_size=2)
    before_split = (dataset / "split.json").read_bytes()
    with pytest.raises(ValueError, match="cannot overwrite"):
        split(str(dataset), val_size=1, test_size=3)
    assert (dataset / "split.json").read_bytes() == before_split


def test_partial_generation_is_rejected(tmp_path, monkeypatch):
    from unrender.data_gen import generate as module

    original = module.render_chart
    count = 0

    def broken(spec):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("injected rendering failure")
        return original(spec)

    monkeypatch.setattr(module, "render_chart", broken)
    with pytest.raises(RuntimeError, match="injected"):
        generate(3, str(tmp_path), workers=1)
    with pytest.raises(ValueError, match="incomplete"):
        verify_dataset(tmp_path)
    assert not (tmp_path / "manifest.jsonl").exists()


def test_worker_count_does_not_change_artifacts(tmp_path):
    first, second = tmp_path / "serial", tmp_path / "parallel"
    for root, workers in ((first, 1), (second, 2)):
        generate(4, str(root), workers=workers, augment=True, hard=True)
    assert (first / "manifest.jsonl").read_bytes() == (second / "manifest.jsonl").read_bytes()
    assert (first / "generation.json").read_bytes() == (second / "generation.json").read_bytes()


@pytest.mark.parametrize(
    "name",
    [
        "synthetic_v0",
        "synthetic_v1",
        "synthetic_v2",
        "../synthetic_visible_x",
        "synthetic_visible_x/child",
    ],
)
def test_cloud_generation_cannot_target_historical_or_outside_directories(name):
    from modal_train import _generation_dir

    with pytest.raises(ValueError, match="new dataset name"):
        _generation_dir(name)
