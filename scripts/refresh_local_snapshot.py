"""Refresh the ignored local beta snapshot from a consistent running SQLite backup."""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='sail')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = root / 'local-import'
    destination.mkdir(mode=0o700, exist_ok=True)
    remote = f'/tmp/sail-export-{uuid.uuid4().hex}.sqlite'
    target = destination / 'sail-beta-export.db'
    with tempfile.TemporaryDirectory(prefix='.refresh-', dir=destination) as temporary:
        staged = Path(temporary) / 'snapshot.db'
        try:
            code = ('import sqlite3; '
                    'src=sqlite3.connect("file:/data/sail.db?mode=ro",uri=True); '
                    f'dst=sqlite3.connect({remote!r}); '
                    'src.backup(dst); dst.close(); src.close()')
            subprocess.run(['docker', 'exec', args.container, 'python', '-c', code], check=True)
            subprocess.run(['docker', 'cp', f'{args.container}:{remote}', str(staged)], check=True)
            staged.chmod(0o600)
            env = {**os.environ, 'SAIL_DATABASE_URL': f'sqlite:///{staged}', 'DATABASE_URL': f'sqlite:///{staged}'}
            for command in (['upgrade', 'head'], ['check']):
                subprocess.run([sys.executable, '-m', 'alembic', *command], cwd=root, env=env, check=True)
            with sqlite3.connect(staged) as db:
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Snapshot integrity check failed')
                revision = db.execute('SELECT version_num FROM alembic_version').fetchone()[0]
                fk_count = len(db.execute('PRAGMA foreign_key_check').fetchall())
            manifest = {'refreshed_at': datetime.now(UTC).isoformat(), 'schema_revision': revision,
                        'foreign_key_violations': fk_count,
                        'note': 'Full local snapshot; configure target environment secrets separately.'}
            manifest['code_commit'] = subprocess.check_output(
                ['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
            manifest['code_dirty'] = bool(subprocess.check_output(
                ['git', 'status', '--porcelain'], cwd=root, text=True).strip())
            if target.exists():
                previous = destination / 'sail-beta-export.previous.db'
                shutil.copyfile(target, previous)
                previous.chmod(0o600)
            os.replace(staged, target)
            metadata = destination / 'snapshot-manifest.json'
            metadata.write_text(json.dumps(manifest, indent=2) + '\n')
            metadata.chmod(0o600)
            print(f'Updated local snapshot at schema {revision}; foreign-key violations: {fk_count}')
        finally:
            subprocess.run(['docker', 'exec', args.container, 'python', '-c',
                            f'import pathlib; pathlib.Path({remote!r}).unlink(missing_ok=True)'], check=False)


if __name__ == '__main__':
    main()
