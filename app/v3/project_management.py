"""Display labels and durable deletion receipts, written only by explicit commands.

These additive UI tables are created by the first management write. Querying an
older store never initializes tables or changes its version or business facts.
"""
from langgraph.checkpoint.sqlite import SqliteSaver

from .repository import ConflictError, now
from .runtime_storage import learning_checkpoint_path
import sqlite3


def _exists(repo):
    return bool(repo.conn.execute("SELECT 1 FROM sqlite_master WHERE name='web_project_metadata' AND type='table'").fetchone())


def metadata(repo, pid):
    if not _exists(repo):return {}
    row=repo.conn.execute('SELECT display_name,deleted_at FROM web_project_metadata WHERE project_id=?',(pid,)).fetchone()
    return dict(row) if row else {}


def require_visible(repo,pid):
    if metadata(repo,pid).get('deleted_at') or not repo.get_project(pid):raise KeyError(pid)


def _setup(repo):
    repo.conn.execute('CREATE TABLE IF NOT EXISTS web_project_metadata (project_id TEXT PRIMARY KEY, display_name TEXT, deleted_at TEXT)')


def rename(repo,pid,name):
    require_visible(repo,pid)
    with repo.transaction():
        _setup(repo)
        repo.conn.execute('INSERT INTO web_project_metadata(project_id,display_name) VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET display_name=excluded.display_name',(pid,name))


def delete(repo,pid):
    """Commit tombstone and all project facts atomically, then clear checkpoints.

If the process dies before cleanup, repeating DELETE safely finishes cleanup.
The receipt prevents an old creation request from resurrecting the project.
"""
    deleted=metadata(repo,pid).get('deleted_at')
    if not deleted:
        require_visible(repo,pid)
        for table in ('learning_execution','preparation_execution'):
            if repo.conn.execute(f'SELECT 1 FROM {table} WHERE project_id=?',(pid,)).fetchone():
                raise ConflictError('Recover the interrupted operation before deleting')
        with repo.transaction():
            repo.conn.execute('PRAGMA defer_foreign_keys=ON')
            _setup(repo)
            repo.conn.execute('INSERT INTO web_project_metadata(project_id,deleted_at) VALUES (?,?) ON CONFLICT(project_id) DO UPDATE SET deleted_at=excluded.deleted_at',(pid,now()))
            tables=[r[0] for r in repo.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            # Names originate from SQLite schema, never request input.
            for table in tables:
                if table=='web_project_metadata':continue
                quoted='"'+table.replace('"','""')+'"'
                if any(r[1]=='project_id' for r in repo.conn.execute(f'PRAGMA table_info({quoted})')):
                    repo.conn.execute(f'DELETE FROM {quoted} WHERE project_id=?',(pid,))
            repo.conn.execute('UPDATE learning_projects SET derived_from_project_id=NULL WHERE derived_from_project_id=?',(pid,))
            repo.conn.execute('DELETE FROM learning_projects WHERE id=?',(pid,))
    for path in (repo.paths.checkpoints,learning_checkpoint_path(repo.paths)):
        with sqlite3.connect(path) as conn:
            SqliteSaver(conn).delete_thread(pid)

