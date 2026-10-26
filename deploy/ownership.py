"""Durable ownership at the authenticated reverse-proxy boundary."""
import sqlite3
from pathlib import Path


class Ownership:
    def __init__(self, database):
        self.database = Path(database).resolve()

    def owned(self, account):
        if not self.database.is_file():
            return set()
        with sqlite3.connect(self.database.as_uri() + '?mode=ro', uri=True) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='project_owners'").fetchone():
                return set()
            return {r[0] for r in conn.execute('SELECT project_id FROM project_owners WHERE account=?', (account,))}

    def claim(self, project_id, account):
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database, timeout=5) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS project_owners (project_id TEXT PRIMARY KEY, account TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT account FROM project_owners WHERE project_id=?', (project_id,)).fetchone()
            if row:
                return row[0] == account
            conn.execute('INSERT INTO project_owners(project_id,account) VALUES (?,?)', (project_id, account))
        return True
