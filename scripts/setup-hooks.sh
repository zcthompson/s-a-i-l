#!/bin/sh
# Enable the repository's git hooks (commit-msg + pre-commit).
set -e
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath .githooks
chmod +x .githooks/* scripts/ci/*.py
echo "Hooks enabled from .githooks/."
[ -f .denylist ] || echo "Optional: create a git-ignored .denylist (one regex per line) for brand scanning."
