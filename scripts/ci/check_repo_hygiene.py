#!/usr/bin/env python3
"""Repository hygiene gate for S-A-I-L.

Fails when tracked (or staged) files include:
  * AI-agent working folders, private migration material, or archives
  * environment files, keys, databases, dumps, logs, or spreadsheets/exports
  * terms from a private denylist (former branding / identifiers)
  * version strings that disagree with the root VERSION file

The denylist is never committed. It is read from the file named by
SAIL_DENYLIST_FILE (default: .denylist, git-ignored) and/or the
SAIL_DENYLIST environment variable (newline- or comma-separated regexes,
e.g. a CI secret). Matches are reported by path and line only.

Usage:
  check_repo_hygiene.py            # check all tracked files
  check_repo_hygiene.py --staged   # check files staged for commit
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_DIRS = re.compile(
    r"(^|/)(\.hermes|\.claude|\.codex|\.cursor|\.aider[^/]*|\.continue|\.windsurf|"
    r"\.roo|\.cline|\.gemini|\.qwen|\.agents?|\.ai|\.private-migration|local-import|"
    r"uploads|logs|node_modules|\.venv|venv|s-i-l-t)/"
)
FORBIDDEN_FILES = re.compile(
    r"(^|/)(\.env(\.[^/]*)?|[^/]*\.(pem|key|p12|pfx|db|db-[a-z]+|sqlite3?|dump|sql\.gz|"
    r"log|tar|tgz|tar\.[a-z0-9]+|zip|xlsx|xls|csv|bak)|id_(rsa|ed25519|ecdsa)[^/]*|"
    r"\.denylist)$"
)
ALLOWED_FILES = re.compile(r"(^|/)\.env(\.[^/]*)?\.example$")
# Synthetic test fixtures may opt in by living under a fixtures/synthetic dir.
ALLOWED_DATA_DIR = re.compile(r"(^|/)fixtures/synthetic/")

TEXT_LIMIT = 2_000_000


def git_files(staged: bool) -> list[str]:
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"]
    else:
        cmd = ["git", "ls-files", "-z"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def load_denylist() -> list[re.Pattern[str]]:
    raw: list[str] = []
    path = ROOT / os.environ.get("SAIL_DENYLIST_FILE", ".denylist")
    if path.is_file():
        raw += path.read_text().splitlines()
    raw += re.split(r"[\n,]", os.environ.get("SAIL_DENYLIST", ""))
    pats = []
    for line in raw:
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(re.compile(line, re.IGNORECASE))
    return pats


def read_text(path: Path) -> str | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) > TEXT_LIMIT or b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def check_versions(problems: list[str]) -> None:
    vfile = ROOT / "VERSION"
    if not vfile.is_file():
        problems.append("VERSION: missing")
        return
    version = vfile.read_text().strip()
    checks = {
        "pyproject.toml": r'(?m)^version\s*=\s*"([^"]+)"',
        "backend/version.py": r'(?m)^VERSION\s*=\s*"([^"]+)"',
    }
    for rel, pat in checks.items():
        p = ROOT / rel
        if p.is_file():
            m = re.search(pat, p.read_text())
            if not m or m.group(1) != version:
                problems.append(f"{rel}: version does not match VERSION ({version})")
    pkg = ROOT / "frontend/package.json"
    if pkg.is_file() and json.loads(pkg.read_text()).get("version") != version:
        problems.append(f"frontend/package.json: version does not match VERSION ({version})")


def main() -> int:
    staged = "--staged" in sys.argv
    files = git_files(staged)
    denylist = load_denylist()
    problems: list[str] = []

    for rel in files:
        if FORBIDDEN_DIRS.search(rel):
            problems.append(f"{rel}: forbidden folder (agent/private/runtime)")
            continue
        if FORBIDDEN_FILES.search(rel) and not ALLOWED_FILES.search(rel):
            if not ALLOWED_DATA_DIR.search(rel):
                problems.append(f"{rel}: forbidden file type (secret/data/archive)")
                continue
        if not denylist:
            continue
        if any(p.search(rel) for p in denylist):
            problems.append(f"{rel}: path matches private denylist")
        text = read_text(ROOT / rel)
        if text is None:
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in denylist):
                problems.append(f"{rel}:{n}: matches private denylist")

    check_versions(problems)

    if not denylist:
        print("note: no private denylist configured; brand scan skipped", file=sys.stderr)
    if problems:
        print("Repository hygiene check FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"Repository hygiene check passed ({len(files)} files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
