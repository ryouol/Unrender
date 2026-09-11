from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_local_launcher_clears_inherited_cloud_destinations(tmp_path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    launcher = scripts / "run_local.sh"
    launcher.write_bytes((ROOT / "scripts" / "run_local.sh").read_bytes())
    executable = tmp_path / ".venv" / "bin" / "unrender-serve"
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/bin/sh\nexec " + shlex.quote(sys.executable) + " - <<'PY'\n"
        "import json, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from unrender.product.config import Settings\n"
        "s = Settings.from_env()\n"
        "print(json.dumps({'environment': s.environment, 'extractor': s.extractor_backend, "
        "'worker': s.worker_enabled, 'data_dir': str(s.data_dir), "
        "'backup_volume': s.backup_volume_name, 'email': s.email_configured, "
        "'billing': s.billing_configured}))\nPY\n"
    )
    executable.chmod(0o700)
    inherited = {k: v for k, v in os.environ.items() if not k.startswith(("UNRENDER_", "STRIPE_"))}
    result = subprocess.run(
        ["sh", str(launcher)],
        env={
            **inherited,
            "UNRENDER_ENV": "production",
            "UNRENDER_EXTRACTOR": "modal",
            "UNRENDER_BACKUP_VOLUME": "production-backup-sentinel",
            "UNRENDER_SMTP_HOST": "smtp.example.com",
            "UNRENDER_SMTP_USERNAME": "production-user",
            "UNRENDER_SMTP_PASSWORD": "test-sentinel",
            "UNRENDER_EMAIL_FROM": "operator@example.com",
            "STRIPE_SECRET_KEY": "sk_live_test_sentinel",
            "STRIPE_WEBHOOK_SECRET": "whsec_test_sentinel",
            "STRIPE_PRICE_ID": "price_test_sentinel",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout) == {
        "environment": "development",
        "extractor": "replay",
        "worker": True,
        "data_dir": str(tmp_path / "outputs" / "local-runtime"),
        "backup_volume": "",
        "email": False,
        "billing": False,
    }


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
