"""Original file retention and location metadata beside immutable SourceDocuments."""
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4

SCHEMA = '''CREATE TABLE IF NOT EXISTS source_files(
 project_id TEXT NOT NULL, source_id TEXT NOT NULL, source_version INTEGER NOT NULL,
 relative_path TEXT NOT NULL, metadata_json TEXT NOT NULL,
 PRIMARY KEY(project_id,source_id,source_version),
 FOREIGN KEY(project_id,source_id,source_version) REFERENCES source_documents(project_id,source_id,source_version))'''


def retain(root, data, parsed):
    relative = Path('original-files') / (parsed['original_sha256'] + '.' + parsed['format'])
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix('.' + uuid4().hex + '.tmp')
        temporary.write_bytes(data)
        temporary.replace(path)
    if sha256(path.read_bytes()).hexdigest() != parsed['original_sha256']:
        raise ValueError('Original file integrity mismatch')
    return {'relative_path': relative.as_posix(), 'metadata': {k: v for k, v in parsed.items() if k != 'content'}}


def save_link(conn, document, record):
    if record is None:
        return
    conn.execute(SCHEMA)
    conn.execute('INSERT OR IGNORE INTO source_files VALUES (?,?,?,?,?)',
                 (document['project_id'], document['source_id'], document['source_version'],
                  record['relative_path'], json.dumps(record['metadata'], ensure_ascii=False)))


def file_link(repo, pid, sid, version):
    if not repo.conn.execute("SELECT 1 FROM sqlite_master WHERE name='source_files'").fetchone():
        return None
    row = repo.conn.execute('SELECT * FROM source_files WHERE project_id=? AND source_id=? AND source_version=?',
                            (pid, sid, version)).fetchone()
    return {**dict(row), 'metadata': json.loads(row['metadata_json'])} if row else None


def original_path(repo, record):
    path = (repo.paths.root / record['relative_path']).resolve()
    if not path.is_relative_to((repo.paths.root / 'original-files').resolve()) or not path.is_file():
        raise KeyError('Original missing')
    if sha256(path.read_bytes()).hexdigest() != record['metadata']['original_sha256']:
        raise ValueError('Original file integrity mismatch')
    return path
