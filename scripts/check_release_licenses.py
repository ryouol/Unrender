#!/usr/bin/env python3
"""Validate dependency inventory and fail a public-release gate on unresolved blockers."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)")
DEPENDENCY_NAME = re.compile(r"^([A-Za-z0-9_.-]+)")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def locked_packages() -> dict[str, str]:
    packages: dict[str, str] = {}
    for line in (ROOT / "requirements-app.lock").read_text(encoding="utf-8").splitlines():
        match = PACKAGE.match(line)
        if match:
            packages[normalize(match.group(1))] = match.group(2)
    return packages


def direct_dependencies() -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names: set[str] = set()
    for requirement in project["dependencies"]:
        match = DEPENDENCY_NAME.match(requirement)
        if not match:
            raise RuntimeError(f"Could not parse direct dependency: {requirement}")
        names.add(normalize(match.group(1)))
    return names


def validate() -> list[dict[str, object]]:
    policy = json.loads(
        (ROOT / "release" / "dependency-license-policy.json").read_text(encoding="utf-8")
    )
    sbom = json.loads((ROOT / "release" / "sbom.cdx.json").read_text(encoding="utf-8"))
    locked = locked_packages()
    direct = direct_dependencies()
    policy_direct = {normalize(name) for name in policy["direct_runtime_packages"]}
    if policy_direct != direct:
        missing = sorted(direct - policy_direct)
        extra = sorted(policy_direct - direct)
        raise RuntimeError(f"License policy direct-package drift: missing={missing}, extra={extra}")
    if not direct <= set(locked):
        raise RuntimeError(
            f"Direct dependencies missing from runtime lock: {sorted(direct - set(locked))}"
        )
    sbom_packages = {
        normalize(component["name"]): str(component["version"])
        for component in sbom.get("components", [])
    }
    if sbom_packages != locked:
        raise RuntimeError("CycloneDX inventory does not exactly match requirements-app.lock")
    if "pymupdf" in direct or "pymupdf" in locked or "pymupdf" in sbom_packages:
        raise RuntimeError("PyMuPDF returned to the distributed/runtime dependency graph")
    if "pypdfium2" not in direct or locked.get("pypdfium2") != "5.13.0":
        raise RuntimeError("The reviewed pypdfium2 replacement is missing or drifted")
    replacements = policy.get("replacement_reviews")
    if not isinstance(replacements, list):
        raise RuntimeError("Dependency replacement review is missing")
    pdfium = [
        item for item in replacements if normalize(str(item.get("package", ""))) == "pypdfium2"
    ]
    if (
        len(pdfium) != 1
        or pdfium[0].get("locked_version") != locked["pypdfium2"]
        or pdfium[0].get("status") != "engineering_dependency_gate_passed"
        or "Apache-2.0 OR BSD-3-Clause" not in str(pdfium[0].get("observed_upstream_terms", ""))
    ):
        raise RuntimeError("The pypdfium2 replacement review is incomplete or drifted")
    blockers = policy.get("release_blockers")
    if not isinstance(blockers, list) or blockers:
        raise RuntimeError("The dependency policy unexpectedly retains a release blocker")
    public_blockers = policy.get("non_dependency_release_blockers")
    if not isinstance(public_blockers, list) or not public_blockers:
        raise RuntimeError("Overall owner/counsel release actions must remain explicit")
    if policy.get("dependency_distribution_gate_passed") is not True:
        raise RuntimeError("Dependency distribution gate is not marked complete")
    if policy.get("public_release_allowed") is not False:
        raise RuntimeError(
            "Overall public release must remain blocked pending owner/counsel review"
        )
    return public_blockers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--release",
        action="store_true",
        help="fail unless every public/commercial release blocker is resolved",
    )
    arguments = parser.parse_args()
    try:
        blockers = validate()
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"license-policy validation failed: {exc}", file=sys.stderr)
        return 2
    unresolved = [item for item in blockers if str(item.get("status", "")).startswith("unresolved")]
    if arguments.release and unresolved:
        names = ", ".join(str(item.get("id", "owner/counsel action")) for item in unresolved)
        print(
            f"PUBLIC RELEASE BLOCKED: unresolved non-dependency legal approval: {names}",
            file=sys.stderr,
        )
        return 1
    print(
        "Dependency inventory is internally consistent and the PyMuPDF dependency is absent; "
        "overall public release remains BLOCKED by "
        f"{len(unresolved)} non-dependency owner/counsel decision(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
