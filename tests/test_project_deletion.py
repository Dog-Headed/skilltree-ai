"""单条 V2 删除只操作临时数据库：业务、Checkpoint、重启及并发行为。"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from app.db.repository import LearningRepository
from app.main import create_app
from app.services.learning_session import LearningSession, open_learning_session


@pytest.fixture
def web(tmp_path):
    paths = {"learning_db_path": tmp_path / "learning.sqlite",
             "checkpoint_db_path": tmp_path / "checkpoints.sqlite"}
    return TestClient(create_app(**paths), raise_server_exceptions=False), paths


def create(client, goal="删除验收 Python 项目"):
    payload = {"goal": goal, "request_id": str(uuid4())}
    response = client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json(), payload


def remove(client, project_id, **kwargs):
    return client.request("DELETE", "/projects/" + project_id,
                          json={"confirm_project_id": project_id}, **kwargs)


def checkpoint_counts(paths, project_id):
    with sqlite3.connect(paths["checkpoint_db_path"]) as conn:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table} WHERE thread_id = ?",
                                    (project_id,)).fetchone()[0]
                for table in ("checkpoints", "writes")}


def test_delete_cascades_business_and_checkpoint_and_preserves_other_project(web, monkeypatch):
    client, paths = web
    first, _ = create(client)
    second, _ = create(client, "保留的另一项目")
    pid = first["project_id"]
    quiz = client.post(f"/projects/{pid}/resume", json={
        "pending_input_id": first["pending_input_id"], "action": "start_quiz",
    }).json()
    assert quiz["quiz"]
    before_other_checkpoints = checkpoint_counts(paths, second["project_id"])
    assert checkpoint_counts(paths, pid)["checkpoints"] > 0
    monkeypatch.setattr(LearningSession, "snapshot", lambda *args: pytest.fail("删除不运行 Graph 或模型"))
    result = remove(client, pid)
    assert result.status_code == 200 and result.json() == {"project_id": pid, "deleted": True}
    assert checkpoint_counts(paths, pid) == {"checkpoints": 0, "writes": 0}
    assert checkpoint_counts(paths, second["project_id"]) == before_other_checkpoints
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.is_project_deleted(pid)
        assert repo.get_project(pid) is None
        for table in ("knowledge_nodes", "learning_progress", "assessments"):
            assert repo.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (pid,)).fetchone()[0] == 0
        assert repo.get_project(second["project_id"])
        assert repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_restart_repeat_delete_and_replayed_inputs_cannot_restore_or_replan(web, monkeypatch):
    client, paths = web
    project, payload = create(client)
    pid = project["project_id"]
    assert remove(client, pid).status_code == 200
    restarted = TestClient(create_app(**paths))
    monkeypatch.setattr("app.graph.build_graph", lambda *args, **kwargs: pytest.fail("删除后的输入不能运行模型"))
    monkeypatch.setattr(LearningSession, "snapshot", lambda *args: pytest.fail("删除后不能读取 Graph"))
    assert restarted.get("/projects").json() == []
    assert restarted.get(f"/projects/{pid}").status_code == 404
    assert restarted.post("/projects", json=payload).status_code == 409
    assert restarted.post(f"/projects/{pid}/resume", json={
        "pending_input_id": project["pending_input_id"], "action": "start_quiz",
    }).status_code == 404
    assert restarted.post(f"/projects/{pid}/retry", json={"retry_token": "old-token"}).status_code == 404
    assert remove(restarted, pid).status_code == 200
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.deleted_project_ids() == {pid}


@pytest.mark.parametrize("operation", ["restore", "resume", "retry", "start"])
def test_deleted_id_is_also_blocked_in_cli_session(web, operation):
    client, paths = web
    project, _ = create(client)
    pid = project["project_id"]
    assert remove(client, pid).status_code == 200
    args = {"restore": (), "resume": ({"action": "start_quiz"},), "retry": (), "start": ("新目标",)}
    with open_learning_session(pid, **paths) as session:
        with pytest.raises(ValueError, match="已删除"):
            getattr(session, operation)(*args[operation])
    assert checkpoint_counts(paths, pid) == {"checkpoints": 0, "writes": 0}


def test_confirmation_required_and_cross_project_mismatch_changes_nothing(web):
    client, paths = web
    first, _ = create(client)
    second, _ = create(client)
    pid = first["project_id"]
    assert client.request("DELETE", f"/projects/{pid}").status_code == 422
    mismatch = client.request("DELETE", f"/projects/{pid}", json={"confirm_project_id": second["project_id"]})
    assert mismatch.status_code == 422 and mismatch.json()["error"]["code"] == "delete_confirmation_mismatch"
    assert client.get(f"/projects/{pid}").json() == first
    assert client.get(f"/projects/{second['project_id']}").json() == second
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.deleted_project_ids() == set()


def test_running_project_rejects_delete_then_can_delete_when_finished(web, monkeypatch):
    client, _ = web
    project, _ = create(client)
    pid = project["project_id"]
    entered, finish = Event(), Event()

    def tutor(*args):
        entered.set()
        assert finish.wait(10)
        return "完成本次追问。"

    monkeypatch.setattr("app.agents.tutor.generate_tutor_content", tutor)
    with ThreadPoolExecutor(2) as pool:
        running = pool.submit(client.post, f"/projects/{pid}/resume", json={
            "pending_input_id": project["pending_input_id"], "action": "ask", "message": "测试追问",
        })
        assert entered.wait(5)
        try:
            refused = remove(client, pid)
            assert refused.status_code == 409 and refused.json()["error"]["code"] == "project_busy"
            assert client.get(f"/projects/{pid}").json()["page_state"] == "running"
        finally:
            finish.set()
        assert running.result().status_code == 200
    assert remove(client, pid).status_code == 200


def test_checkpoint_cleanup_failure_cannot_resurrect_and_retry_finishes_cleanup(web, monkeypatch):
    client, paths = web
    project, _ = create(client)
    pid = project["project_id"]
    original = SqliteSaver.delete_thread
    monkeypatch.setattr(SqliteSaver, "delete_thread", lambda *args: (_ for _ in ()).throw(OSError("injected failure")))
    assert remove(client, pid).status_code == 500
    assert checkpoint_counts(paths, pid)["checkpoints"] > 0
    restarted = TestClient(create_app(**paths))
    assert restarted.get("/projects").json() == []
    assert restarted.get(f"/projects/{pid}").status_code == 404
    with open_learning_session(pid, **paths) as session, pytest.raises(ValueError, match="已删除"):
        session.restore()
    monkeypatch.setattr(SqliteSaver, "delete_thread", original)
    assert remove(restarted, pid).status_code == 200
    assert checkpoint_counts(paths, pid) == {"checkpoints": 0, "writes": 0}


def test_orphan_checkpoint_and_orphan_business_can_be_deleted(web):
    client, paths = web
    checkpoint_only, _ = create(client)
    business_only, _ = create(client)
    with LearningRepository(paths["learning_db_path"]) as repo:
        with repo.conn:
            repo.conn.execute("DELETE FROM learning_projects WHERE id = ?", (checkpoint_only["project_id"],))
    with SqliteSaver.from_conn_string(str(paths["checkpoint_db_path"])) as saver:
        saver.delete_thread(business_only["project_id"])
    for project in (checkpoint_only, business_only):
        assert remove(client, project["project_id"]).status_code == 200
        assert checkpoint_counts(paths, project["project_id"]) == {"checkpoints": 0, "writes": 0}
    assert client.get("/projects").json() == []


def test_unknown_project_and_cross_origin_cannot_delete(web):
    client, paths = web
    assert remove(client, "unknown").status_code == 404
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert not repo.is_project_deleted("unknown")
    project, _ = create(client)
    assert remove(client, project["project_id"], headers={"Origin": "https://other.example"}).status_code == 403
    assert client.get("/projects/" + project["project_id"]).json() == project
