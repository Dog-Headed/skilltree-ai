"""Run with all writers stopped; preserve paired SQLite stores and environment."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess


def backup(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    records = []
    for source in sorted((root / 'data').rglob('*')):
        if source.is_file() and source.suffix in {'.sqlite', '.db'}:
            target = destination / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Backup failed integrity check')
            target.chmod(0o600)
            records.append({'path': str(source.relative_to(root)), 'sha256': sha256(target.read_bytes()).hexdigest()})
    shutil.copy2(root / '.env', destination / '.env')
    (destination / '.env').chmod(0o600)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(root), 'archive', '--format=tar.gz', '--output=' + str(destination / 'code.tar.gz'), commit], check=True)
    manifest = {'commit': commit, 'created_at': datetime.now(timezone.utc).isoformat(), 'databases': records}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps({'backup': str(destination), 'commit': commit, 'databases_verified': len(records)}))
    return manifest


if __name__ == '__main__':
    import sys
    backup(sys.argv[1], sys.argv[2])
