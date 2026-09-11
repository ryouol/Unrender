"""Local operator commands that keep credentials out of shell arguments."""

from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from unrender.product.backup import BackupError, create_backup, restore_backup
from unrender.product.config import Settings
from unrender.product.database import Database
from unrender.product.extractors import build_extractor
from unrender.product.service import ProductError, ProductService
from unrender.product.storage import Storage


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="unrender-admin")
    commands = root.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="provision a controlled-beta account")
    create.add_argument("email")
    create.add_argument("--credits", type=int, default=0)
    invite = commands.add_parser("invite-user", help="create an account with a one-use setup link")
    invite.add_argument("email")
    invite.add_argument("--credits", type=int, default=0)
    invite.add_argument("--destination", required=True, type=Path)
    link = commands.add_parser(
        "account-link", help="issue an operator-verified recovery/setup link"
    )
    link.add_argument("email")
    link.add_argument("--destination", required=True, type=Path)
    grant = commands.add_parser(
        "grant-credits", help="grant extraction credits to an active account"
    )
    grant.add_argument("email")
    grant.add_argument("--credits", type=int, required=True)
    grant.add_argument(
        "--reference", required=True, help="unique grant reference; retry with the same reference"
    )
    backup = commands.add_parser("backup", help="create a coordinated recovery set")
    backup.add_argument("--destination", required=True, type=Path)
    restore = commands.add_parser("restore", help="restore a verified recovery set")
    restore.add_argument("--source", required=True, type=Path)
    restore.add_argument("--target", required=True, type=Path)
    commands.add_parser(
        "check-provider-contract",
        help="resolve the configured Modal function without invoking inference",
    )
    return root


def main() -> None:
    arguments = parser().parse_args()
    settings = Settings.from_env()
    if arguments.command == "backup":
        try:
            created = create_backup(settings, arguments.destination)
        except BackupError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Created coordinated backup at {created}")
        return
    if arguments.command == "restore":
        try:
            restored = restore_backup(arguments.source, arguments.target)
        except BackupError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"Restored verified recovery set to {restored}")
        return
    if arguments.command == "check-provider-contract":
        extractor = build_extractor(settings, Path(__file__).with_name("static"))
        canary = getattr(extractor, "canary_contract", None)
        if not callable(canary):
            raise SystemExit("UNRENDER_EXTRACTOR must be modal for a provider contract canary")
        canary()
        print(
            f"Resolved Modal contract {settings.modal_app_name}/{settings.modal_function_name}; "
            "no inference was invoked"
        )
        return
    if arguments.command not in {"create-user", "grant-credits", "invite-user", "account-link"}:
        raise SystemExit(2)
    password = ""
    if arguments.command == "create-user":
        password = getpass.getpass("Password (12+ characters): ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Passwords did not match")

    static_dir = Path(__file__).with_name("static")
    database = Database(settings.database_path)
    service = ProductService(
        settings=settings,
        database=database,
        storage=Storage(settings),
        extractor=build_extractor(settings, static_dir),
        static_dir=static_dir,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database.initialize()
    try:
        if arguments.command in {"invite-user", "account-link"}:
            descriptor = os.open(arguments.destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "w") as output:

                    def publish(link: str) -> None:
                        output.write(link + "\n")
                        output.flush()
                        os.fsync(output.fileno())

                    if arguments.command == "invite-user":
                        service.invite_user(
                            arguments.email, credits=arguments.credits, publish=publish
                        )
                    else:
                        service.operator_account_link(arguments.email, publish=publish)
            except BaseException:
                arguments.destination.unlink(missing_ok=True)
                raise
            print(
                f"One-use account link saved privately to {arguments.destination}; "
                "expires in 30 minutes"
            )
            return
        if arguments.command == "grant-credits":
            service.grant_credits(
                arguments.email, credits=arguments.credits, reference=arguments.reference
            )
            print("Credit grant applied (retries with the same reference are idempotent)")
            return
        user_id = service.provision_user(arguments.email, password, credits=arguments.credits)
    except (ProductError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Created account {user_id}")
