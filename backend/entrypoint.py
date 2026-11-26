"""Fail-fast container startup; application imports never run migrations."""
import os
import subprocess
import sys

from backend.config import get_settings
from backend.runtime import prepare_runtime


def main(argv=None):
    prepare_runtime()
    if get_settings().run_migrations_on_start:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
        subprocess.run([sys.executable, "-m", "backend.seed", "--admin-only"], check=True)
    command = list(argv if argv is not None else sys.argv[1:])
    if not command:
        command = ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", os.getenv("PORT", "8000"), "--workers", "1"]
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
