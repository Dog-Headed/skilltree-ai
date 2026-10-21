"""删除单个 V2 项目；持久化删除标记隔离跨库清理故障，不执行 Graph。"""

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def has_checkpoint(checkpoint_db_path: Path, project_id: str) -> bool:
    if not checkpoint_db_path.exists():
        return False
    with sqlite3.connect(checkpoint_db_path) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'checkpoints'").fetchone():
            return False
        return conn.execute(
            "SELECT 1 FROM checkpoints WHERE thread_id = ? LIMIT 1", (project_id,)
        ).fetchone() is not None


def delete_project_record(repo, checkpoint_db_path: Path, project_id: str) -> bool:
    """未知项目返回 False；重复删除会再次尝试清理，不恢复项目或调用模型。"""
    if not (repo.is_project_deleted(project_id) or repo.get_project(project_id)
            or has_checkpoint(checkpoint_db_path, project_id)):
        return False
    # 必须先提交标记。即使进程在下方退出，旧 Checkpoint 也不能重新进入列表或执行。
    repo.delete_project(project_id)
    if checkpoint_db_path.exists():
        with SqliteSaver.from_conn_string(str(checkpoint_db_path)) as saver:
            saver.delete_thread(project_id)
    return True
