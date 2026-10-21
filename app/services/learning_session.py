"""SQLite 存档的连接生命周期，以及新建、恢复输入、重试失败的入口。"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from app.db import repository
from app.graph import CHECKPOINT_DB_PATH, build_graph


def result_from_snapshot(snapshot) -> dict[str, Any]:
    result = dict(snapshot.values)
    if snapshot.interrupts:
        result["__interrupt__"] = snapshot.interrupts
    return result


@dataclass
class LearningSession:
    graph: Any
    project_id: str
    learning_db_path: Path
    checkpoint_db_path: Path

    @property
    def config(self):
        return {"configurable": {"thread_id": self.project_id}, "recursion_limit": 30}

    def snapshot(self):
        with repository.LearningRepository(self.learning_db_path) as repo:
            if repo.is_project_deleted(self.project_id):
                raise ValueError("这个学习项目已删除，不能继续恢复或重试。")
        return self.graph.get_state(self.config)

    def restore(self):
        snapshot = self.snapshot()
        saved_project = snapshot.values.get("project_id")
        if saved_project and saved_project != self.project_id:
            raise ValueError("存档的 project_id 与当前 thread_id 不一致")
        saved_path = snapshot.values.get("learning_db_path")
        if saved_path and Path(saved_path).resolve() != self.learning_db_path:
            raise ValueError(f"该项目的业务库是 {saved_path}，请使用同一个数据库恢复。")
        return result_from_snapshot(snapshot)

    def start(self, goal: str):
        if self.snapshot().values:
            raise ValueError("项目已有存档，请恢复或重试，不能重新从 START 启动。")
        with repository.LearningRepository(self.learning_db_path) as repo:
            if repo.get_project(self.project_id) is not None:
                raise ValueError("业务项目存在，但找不到对应 Checkpoint，不能重新规划覆盖；请恢复原存档或新建项目。")
        if not isinstance(goal, str) or not goal.strip():
            raise ValueError("学习目标必须是非空字符串")
        return self.graph.invoke(
            {
                "project_id": self.project_id,
                "learning_db_path": str(self.learning_db_path),
                "goal": goal,
                "lesson_mode": "normal",
            },
            config=self.config,
            # 本节点的 Checkpoint 提交完成后，才允许下一节点产生业务副作用。
            durability="sync",
        )

    def resume(self, payload: dict):
        self.restore()
        if not self.snapshot().interrupts:
            raise ValueError("当前没有等待用户输入；执行失败请使用 retry。")
        return self.graph.invoke(Command(resume=payload), config=self.config, durability="sync")

    def retry(self):
        self.restore()
        snapshot = self.snapshot()
        if snapshot.interrupts:
            raise ValueError("当前正在等待用户输入，请使用 resume，不能重试执行。")
        if not snapshot.next:
            raise ValueError("当前没有未完成的执行节点。")
        return self.graph.invoke(None, config=self.config, durability="sync")


@contextmanager
def open_learning_session(
    project_id: str,
    *,
    checkpoint_db_path: str | Path = CHECKPOINT_DB_PATH,
    learning_db_path: str | Path | None = None,
):
    if not isinstance(project_id, str) or not project_id.strip():
        raise ValueError("project_id 必须是非空字符串")
    checkpoint_path = Path(checkpoint_db_path).resolve()
    business_path = Path(learning_db_path or repository.DEFAULT_DB_PATH).resolve()
    if checkpoint_path == business_path:
        raise ValueError("Checkpoint 和业务事实必须使用两个独立数据库。")
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(checkpoint_path, check_same_thread=False)
    try:
        # Saver 自动创建和维护自己的表；连接覆盖所有 Graph 操作的生命周期。
        graph = build_graph(checkpointer=SqliteSaver(conn))
        yield LearningSession(graph, project_id, business_path, checkpoint_path)
    finally:
        conn.close()
