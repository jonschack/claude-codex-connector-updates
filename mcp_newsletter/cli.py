from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from .emailer import EmailConfigError, send_daily_report
from .gitops import bootstrap_github, check_prereqs, commit_and_push
from .updater import run_update
from .utils import today_iso


def _root(value: str) -> Path:
    return Path(value).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily MCP write-capability tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    update = sub.add_parser("update", help="collect, diff, and render daily tracker outputs")
    update.add_argument("--root", default=".", type=_root)
    update.add_argument("--date", default=today_iso())
    update.add_argument("--skip-network", action="store_true")
    update.add_argument("--max-details", type=int, default=200)

    check = sub.add_parser("check", help="verify git/GitHub prerequisites")
    check.add_argument("--root", default=".", type=_root)

    bootstrap = sub.add_parser("bootstrap-github", help="create/configure the public GitHub repository using gh")
    bootstrap.add_argument("--root", default=".", type=_root)
    bootstrap.add_argument("--repo-name", default="mcp-newsletter")
    bootstrap.add_argument("--visibility", choices=["public", "private"], default="public")

    publish = sub.add_parser("publish", help="commit generated changes and push to origin/main")
    publish.add_argument("--root", default=".", type=_root)
    publish.add_argument("--date", default=today_iso())

    daily = sub.add_parser("daily", help="run update, tests, publish, and email")
    daily.add_argument("--root", default=".", type=_root)
    daily.add_argument("--date", default=today_iso())
    daily.add_argument("--max-details", type=int, default=200)
    daily.add_argument("--email-to", default=None, help="recipient address; defaults to MCP_NEWSLETTER_EMAIL_TO")
    daily.add_argument("--skip-email", action="store_true")

    email = sub.add_parser("email", help="email the report for a given date")
    email.add_argument("--root", default=".", type=_root)
    email.add_argument("--date", default=today_iso())
    email.add_argument("--to", default=None)

    args = parser.parse_args(argv)

    if args.command == "update":
        result = run_update(args.root, run_date=args.date, skip_network=args.skip_network, max_details=args.max_details)
        print(result["status"])
        return 0
    if args.command == "check":
        ok, issues = check_prereqs(args.root)
        if ok:
            print("All prerequisites satisfied.")
            return 0
        for issue in issues:
            print(f"- {issue}")
        return 1
    if args.command == "bootstrap-github":
        try:
            print(bootstrap_github(args.root, repo_name=args.repo_name, visibility=args.visibility))
            return 0
        except RuntimeError as exc:
            print(f"Bootstrap failed: {exc}")
            return 1
    if args.command == "publish":
        try:
            print(commit_and_push(args.root, run_date=args.date))
            return 0
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"Publish failed: {exc}")
            return 1
    if args.command == "daily":
        result = run_update(args.root, run_date=args.date, max_details=args.max_details)
        print(result["status"])
        tests = subprocess.run([sys.executable, "-m", "unittest"], cwd=str(args.root), text=True)
        if tests.returncode != 0:
            return tests.returncode
        try:
            print(commit_and_push(args.root, run_date=args.date))
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(f"Publish skipped: {exc}")
        if not args.skip_email:
            try:
                print(send_daily_report(args.root, run_date=args.date, to_addr=args.email_to))
            except EmailConfigError as exc:
                print(f"Email skipped: {exc}")
        return 0
    if args.command == "email":
        try:
            print(send_daily_report(args.root, run_date=args.date, to_addr=args.to))
            return 0
        except EmailConfigError as exc:
            print(f"Email failed: {exc}")
            return 1
    return 2
