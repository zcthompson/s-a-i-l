#!/usr/bin/env python3
"""Reject co-author trailers and agent attribution in commit messages.

Repository policy (AGENTS.md): no Co-authored-by trailers or other
agent/co-author attribution. The configured Git author identity is kept.

Usage:
  check_commit_messages.py --file MSGFILE   # commit-msg hook
  check_commit_messages.py RANGE            # e.g. origin/main..HEAD (CI)
"""

from __future__ import annotations

import re
import subprocess
import sys

BANNED = [
    re.compile(r"^\s*co-?authored-?by\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*(signed-off|assisted|generated)-by\s*:.*\b(claude|codex|gpt|copilot|"
               r"hermes|qwen|gemini|cursor|aider|bot)\b", re.IGNORECASE | re.MULTILINE),
    re.compile(r"generated (with|by) \[?(claude|codex|chatgpt|copilot|hermes|qwen|gemini|cursor|aider)",
               re.IGNORECASE),
    re.compile(r"noreply@(anthropic|openai)\.com", re.IGNORECASE),
    re.compile(r"🤖"),
]


def violations(message: str) -> list[str]:
    body = "\n".join(line for line in message.splitlines() if not line.startswith("#"))
    return [p.pattern for p in BANNED if p.search(body)]


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--file":
        with open(argv[1], encoding="utf-8") as fh:
            bad = violations(fh.read())
        if bad:
            print("Commit rejected: co-author / agent attribution is not allowed "
                  "(see AGENTS.md). Remove the trailer and retry.", file=sys.stderr)
            return 1
        return 0

    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    shas = subprocess.run(["git", "rev-list", argv[0]], capture_output=True, text=True,
                          check=True).stdout.split()
    failed = []
    for sha in shas:
        msg = subprocess.run(["git", "log", "-1", "--format=%B", sha], capture_output=True,
                             text=True, check=True).stdout
        if violations(msg):
            failed.append(sha[:12])
    if failed:
        print("Commits with co-author / agent attribution (not allowed, see AGENTS.md):",
              file=sys.stderr)
        for sha in failed:
            print(f"  - {sha}", file=sys.stderr)
        return 1
    print(f"Commit message check passed ({len(shas)} commits).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
