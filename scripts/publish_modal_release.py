"""Privately freeze the saved fine-tune; no Hub credential or GPU required.

Run from the repository: modal run scripts/publish_modal_release.py --digest <sha256>
The digest must come from a separately inspected source snapshot.
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
app = modal.App("unrender-release-publisher")
source_volume = modal.Volume.from_name("unrender-vol")
release_volume = modal.Volume.from_name("unrender-inference-cache", create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.11")
    .add_local_file(ROOT / "modal_train.py", "/root/modal_train.py")
    .add_local_python_source("unrender")
)


@app.function(
    image=image,
    volumes={"/source": source_volume, "/releases-volume": release_volume},
    cpu=1.0,
    memory=512,
    timeout=300,
    max_containers=1,
    retries=0,
)
def publish(digest: str):
    import hmac
    import os
    import re
    import shutil
    import tempfile

    from modal_train import _copy_snapshot_and_digest, _verify_materialization

    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected an inspected SHA-256 digest")
    source = Path("/source/runs/qwen3vl4b-table-fair/merged")
    if source.is_symlink():
        raise ValueError("The release source cannot be a symlink")
    root = Path("/releases-volume/releases")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = root / digest
    if target.exists():
        _verify_materialization(target, digest)
    else:
        temporary = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
        try:
            actual = _copy_snapshot_and_digest(source, temporary)
            if not hmac.compare_digest(actual, digest):
                raise ValueError("Source changed since inspection; release refused")
            for directory in sorted((p for p in temporary.rglob("*") if p.is_dir()), reverse=True):
                directory.chmod(0o500)
            temporary.chmod(0o500)
            _verify_materialization(temporary, digest)
            os.rename(temporary, target)
        finally:
            if temporary.exists():
                temporary.chmod(0o700)
                for path in temporary.rglob("*"):
                    path.chmod(0o700 if path.is_dir() else 0o600)
                shutil.rmtree(temporary)
    release_volume.commit()
    return {
        "model": "modal-volume/unrender-inference-cache",
        "revision": digest,
        "digest": digest,
        "status": "private_release_verified",
    }


@app.local_entrypoint()
def main(digest: str):
    import json

    print(json.dumps(publish.remote(digest), sort_keys=True))
