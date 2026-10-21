"""Small process-owned preparation lock; the OS releases it on hard exit.

The marker in SQLite records unfinished work, not ownership. An HTTP timeout
or elapsed lease alone must never authorize a second live Graph executor.
"""
from contextlib import contextmanager
from hashlib import sha256
import os
from threading import Lock, RLock, local

from .repository import ConflictError
from .storage import V3Paths

_locks={}
_guard=Lock()
_ownership=local()


class ExecutionActiveError(ConflictError):
    pass


def _path(paths,project_id):
    return paths.root/'execution-locks'/(sha256(project_id.encode()).hexdigest()+'.lock')


def _try_lock(handle):
    handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        return True
    except (BlockingIOError,PermissionError,OSError):return False


def _unlock(handle):
    handle.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
    else:
        import fcntl
        fcntl.flock(handle.fileno(),fcntl.LOCK_UN)


@contextmanager
def project_execution(project_id,paths=V3Paths()):
    path=_path(paths,project_id)
    with _guard:lock=_locks.setdefault(str(path),RLock())
    with lock:
        owned=getattr(_ownership,'paths',set())
        if str(path) in owned:
            yield
            return
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a+b') as handle:
            if path.stat().st_size==0:handle.write(b'\0');handle.flush()
            if not _try_lock(handle):raise ExecutionActiveError('Project execution is active')
            _ownership.paths=owned | {str(path)}
            try:yield
            finally:
                _ownership.paths=owned
                _unlock(handle)


def execution_is_active(paths,project_id):
    """Read-only ownership probe; never creates files, touches SQL or runs Graph."""
    try:
        with _path(paths,project_id).open('r+b') as handle:
            if not _try_lock(handle):return True
            _unlock(handle)
    except FileNotFoundError:return False
    except PermissionError:return True
    return False
