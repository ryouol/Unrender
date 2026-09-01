"""Local operator commands that keep credentials out of shell arguments."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

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
    return root


def main() -> None:
    arguments = parser().parse_args()
    if arguments.command != "create-user":  # argparse currently makes this unreachable
        raise SystemExit(2)
    password = getpass.getpass("Password (12+ characters): ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords did not match")

    settings = Settings.from_env()
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
        user_id = service.provision_user(arguments.email, password, credits=arguments.credits)
    except ProductError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Created account {user_id}")
