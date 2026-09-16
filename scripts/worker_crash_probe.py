"""Kill a real worker process against an isolated database and a blocked fake provider."""

import argparse
import io
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--child", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.source))
    from PIL import Image

    from unrender.product.config import Settings
    from unrender.product.database import Database
    from unrender.product.extractors import ReplayExtractor
    from unrender.product.service import ProductService, WorkerClaim
    from unrender.product.storage import Storage

    temporary = tempfile.TemporaryDirectory() if args.data is None else None
    data = args.data or Path(temporary.name)
    static = args.source / "unrender/product/static"
    settings = Settings(
        data_dir=data,
        environment="test",
        worker_enabled=False,
        seed_demo_account=False,
        initial_credits=2,
        worker_lease_seconds=10,
        worker_heartbeat_seconds=1,
    )
    service = ProductService(
        settings=settings,
        database=Database(settings.database_path),
        storage=Storage(settings),
        extractor=ReplayExtractor(static),
        static_dir=static,
    )
    service.initialize()
    signal_path = data / "provider-entered"
    if args.child:

        class BlockingProvider:
            def extract(self, image_bytes):
                signal_path.write_text("one provider attempt entered")
                time.sleep(120)
                raise RuntimeError("Probe should have killed the worker")

        service.extractor = BlockingProvider()
        service.process_one("crash-probe")
        return
    session = service.register("crash-probe@example.com", "isolated probe password")
    user = service.session_user(session["session"])
    user_id = user["id"]
    buffer = io.BytesIO()
    Image.new("RGB", (128, 128), "blue").save(buffer, format="PNG")

    def job():
        upload = service.prepare_upload(
            user_id=user_id, filename="probe.png", content=buffer.getvalue()
        )
        return service.create_job(user_id=user_id, upload_id=upload["id"], page_index=0, crop=None)

    queued = job()
    service.cancel(user_id=user_id, job_id=queued["id"])
    running = job()
    process = subprocess.Popen(
        [
            sys.executable,
            __file__,
            "--source",
            str(args.source),
            "--out",
            str(args.out),
            "--data",
            str(data),
            "--child",
        ]
    )
    try:
        deadline = time.monotonic() + 15
        while not signal_path.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        if not signal_path.exists():
            raise RuntimeError("Worker did not dispatch")
        with service.database.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (running["id"],)).fetchone()
        stale = WorkerClaim(
            job_id=row["id"],
            user_id=row["user_id"],
            attempt=row["attempt"],
            generation=row["lease_generation"],
            token=row["lease_token"],
            owner=row["worker_owner"],
            row=row,
        )
        killed = time.monotonic()
        process.kill()
        process.wait(timeout=5)
        recovered = 0
        while time.monotonic() - killed < 15 and not recovered:
            recovered += service.recover_interrupted_jobs()
            time.sleep(0.1)
        recovery_s = time.monotonic() - killed
        stale_commit = service._finish_failed_claim(stale, "stale_probe", "must not publish")
        redispatched = service.process_one("replacement")
        with service.database.connect() as conn:
            attempts = conn.execute("SELECT COUNT(*) FROM provider_attempts").fetchone()[0]
            queued_attempts = conn.execute(
                "SELECT COUNT(*) FROM provider_attempts WHERE job_id=?", (queued["id"],)
            ).fetchone()[0]
        result = {
            "scope": "Real worker SIGKILL, isolated DB, fake blocked provider; no GPU",
            "source_commit": subprocess.check_output(
                ["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True
            ).strip(),
            "worker_exit": process.returncode,
            "recovery_s": recovery_s,
            "recovered": recovered,
            "provider_attempts": attempts,
            "queued_cancel_provider_attempts": queued_attempts,
            "stale_terminal_write_accepted": stale_commit,
            "redispatched": redispatched,
            "status": service.get_job(user_id=user_id, job_id=running["id"])["status"],
            "credits": service.account(user_id)["credits"],
        }
        assert recovered == 1 and attempts == 1 and queued_attempts == 0
        assert not stale_commit and not redispatched and result["status"] == "failed"
        assert result["credits"] == 1
        args.out.write_text(json.dumps(result, indent=2))
        print(json.dumps(result))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    main()
