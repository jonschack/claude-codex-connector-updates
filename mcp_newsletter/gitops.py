from __future__ import annotations

import datetime as dt
from pathlib import Path
import shutil
import subprocess
from typing import List, Tuple


def run(cmd: List[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def check_prereqs(root: Path) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    if shutil.which("git") is None:
        issues.append("git is not installed")
    if shutil.which("gh") is None:
        issues.append("gh is not installed")
    else:
        result = run(["gh", "auth", "status"], root, check=False)
        if result.returncode != 0:
            issues.append("gh is installed but not authenticated")
    if not (root / ".git").exists():
        issues.append("workspace is not initialized as a git repository")
    else:
        remote = run(["git", "remote", "get-url", "origin"], root, check=False)
        if remote.returncode != 0:
            issues.append("git remote origin is not configured")
    return not issues, issues


def bootstrap_github(root: Path, repo_name: str = "mcp-newsletter", visibility: str = "public") -> str:
    if shutil.which("gh") is None:
        raise RuntimeError("gh is not installed; install and authenticate GitHub CLI first")
    if not (root / ".git").exists():
        run(["git", "init", "-b", "main"], root)
    auth = run(["gh", "auth", "status"], root, check=False)
    if auth.returncode != 0:
        raise RuntimeError("gh is not authenticated; run `gh auth login` first")
    remote = run(["git", "remote", "get-url", "origin"], root, check=False)
    if remote.returncode == 0:
        return "origin already configured"
    visibility_flag = "--public" if visibility == "public" else "--private"
    created = run(["gh", "repo", "create", repo_name, visibility_flag, "--source=.", "--remote=origin", "--push"], root)
    return created.stdout


def commit_and_push(root: Path, run_date: str = "") -> str:
    if not (root / ".git").exists():
        raise RuntimeError("workspace is not initialized as a git repository")
    status = run(["git", "status", "--porcelain"], root)
    if not status.stdout.strip():
        return "No material changes to commit."
    run(["git", "add", "README.md", "data", "reports", "docs", "mcp_newsletter", "scripts", "tests", ".gitignore"], root)
    status_after_add = run(["git", "status", "--porcelain"], root)
    if not status_after_add.stdout.strip():
        return "No tracked/generated changes to commit after staging."
    run_date = run_date or dt.date.today().isoformat()
    run(["git", "commit", "-m", f"Update MCP write capability snapshot {run_date}"], root)
    remote = run(["git", "remote", "get-url", "origin"], root, check=False)
    if remote.returncode != 0:
        return "Committed locally; origin remote is not configured, so push was skipped."
    run(["git", "push", "origin", "main"], root)
    return "Committed and pushed to origin/main."
