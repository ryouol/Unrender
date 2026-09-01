from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_sbom_matches_lock_and_pymupdf_is_replaced_without_overclaiming_release() -> None:
    validation = subprocess.run(
        [sys.executable, "scripts/check_release_licenses.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert validation.returncode == 0, validation.stderr
    release = subprocess.run(
        [sys.executable, "scripts/check_release_licenses.py", "--release"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert release.returncode == 1
    assert "PUBLIC RELEASE BLOCKED" in release.stderr
    assert "non-dependency legal approval" in release.stderr
    assert "PyMuPDF" not in release.stderr

    policy = json.loads(
        (ROOT / "release" / "dependency-license-policy.json").read_text(encoding="utf-8")
    )
    assert policy["public_release_allowed"] is False
    assert policy["dependency_distribution_gate_passed"] is True
    assert policy["release_blockers"] == []
    assert policy["non_dependency_release_blockers"][0]["status"] == (
        "unresolved_owner_counsel_action"
    )
    sbom = json.loads((ROOT / "release" / "sbom.cdx.json").read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    names = {component["name"] for component in sbom["components"]}
    assert "pymupdf" not in names
    assert "pypdfium2" in names

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert "THIRD_PARTY_NOTICES.md" in project["license-files"]
