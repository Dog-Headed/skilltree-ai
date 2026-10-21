"""The history adapter must read V2 facts without opening a runtime or migrating."""

import hashlib
import json
import sqlite3

import pytest

from app.v3.legacy import LegacyHistory


@pytest.fixture
def legacy_files(tmp_path):
    business, checkpoint = tmp_path / "old.sqlite", tmp_path / "old-checkpoint.sqlite"
    with sqlite3.connect(business) as connection:
        connection.executescript("""
            CREATE TABLE learning_projects (id TEXT PRIMARY KEY, goal TEXT, created_at TEXT);
            CREATE TABLE project_labels (project_id TEXT PRIMARY KEY, display_name TEXT);
            CREATE TABLE deleted_projects (project_id TEXT PRIMARY KEY, deleted_at TEXT);
            CREATE TABLE knowledge_nodes (
                project_id TEXT, id TEXT, title TEXT, description TEXT, objectives_json TEXT,
                prerequisite_ids_json TEXT, difficulty TEXT, estimated_minutes INTEGER, sort_order INTEGER);
            CREATE TABLE learning_progress (
                project_id TEXT, node_id TEXT, started_at TEXT, completed_at TEXT, completion_assessment_id TEXT);
            CREATE TABLE assessments (
                id TEXT PRIMARY KEY, project_id TEXT, node_id TEXT, round_no INTEGER,
                quiz_json TEXT, answers_json TEXT, evaluation_json TEXT, diagnosis_json TEXT,
                status TEXT, created_at TEXT);
        """)
        connection.executemany("INSERT INTO learning_projects VALUES (?,?,?)", [
            ("old_1", "历史目标", "2026-10-19"), ("old_2", "无存档的业务记录", "2026-10-18"),
            ("deleted", "已删除", "2026-10-20"),
        ])
        connection.execute("INSERT INTO project_labels VALUES (?,?)", ("old_1", "历史名称"))
        connection.execute("INSERT INTO deleted_projects VALUES (?,?)", ("deleted", "2026-10-20"))
        objectives = json.dumps([{"id": "obj1", "description": "理解变量"}])
        connection.executemany("INSERT INTO knowledge_nodes VALUES (?,?,?,?,?,?,?,?,?)", [
            ("old_1", "n1", "变量", "变量基础", objectives, "[]", "beginner", 10, 0),
            ("old_1", "n2", "列表", "列表基础", objectives, '["n1"]', "beginner", 10, 1),
            ("old_2", "n1", "另一项目同名节点", "不能串资料", objectives, "[]", "beginner", 10, 0),
        ])
        connection.execute("INSERT INTO learning_progress VALUES (?,?,?,?,?)",
                           ("old_1", "n1", "start", "finish", "a1"))
        quiz = {"assessment_id": "a1", "node_id": "n1", "questions": [{
            "id": "q1", "type": "short_answer", "objective_id": "obj1", "prompt": "描述变量",
            "options": None, "answer_key": "PRIVATE_ANSWER", "rubric": "PRIVATE_RUBRIC", "max_score": 2.0,
        }]}
        evaluation = {"assessment_id": "a1", "question_results": [{
            "question_id": "q1", "score": 2.0, "error_tags": ["PRIVATE_TAG"],
            "feedback": "PRIVATE_GRADER_FEEDBACK", "evidence": "PRIVATE_EVIDENCE",
        }]}
        connection.execute("INSERT INTO assessments VALUES (?,?,?,?,?,?,?,?,?,?)", (
            "a1", "old_1", "n1", 1, json.dumps(quiz), '{"q1":"STUDENT_PRIVATE_ANSWER"}',
            json.dumps(evaluation), '{"reason":"PRIVATE_DIAGNOSIS","recommended_action":"advance"}',
            "graded", "2026-10-19",
        ))
    with sqlite3.connect(checkpoint) as connection:
        # A blob is intentionally not a LangGraph serialization. It must never be decoded.
        connection.execute("CREATE TABLE checkpoints (thread_id TEXT, checkpoint BLOB)")
        connection.executemany("INSERT INTO checkpoints VALUES (?,?)", [
            ("old_1", b"SECRET_INTERNAL_STATE"), ("checkpoint_only", b"INVALID_PICKLE"),
            ("deleted", b"DELETED_CHECKPOINT"),
        ])
    return business, checkpoint


def fingerprint(paths):
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def test_legacy_read_is_schema_and_byte_preserving_and_never_runs_runtime(legacy_files, monkeypatch):
    business, checkpoint = legacy_files
    before = fingerprint(legacy_files)
    with sqlite3.connect(business) as connection:
        before_schema = connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
    def no_runtime(*args, **kwargs):
        pytest.fail("A read-only legacy history cannot initialize a repository, Graph, or model")
    monkeypatch.setattr("app.db.repository.LearningRepository.__init__", no_runtime)
    monkeypatch.setattr("app.graph.build_graph", no_runtime)
    history = LegacyHistory(business, checkpoint)
    assert len(history.list_projects()) == 3
    for _ in range(3):
        item = history.get_project("old_1")
        assert item["read_only"] and item["version"] == "v2" and item["allowed_actions"] == []
        assert item["page_state"] == "legacy_readonly"
        assert item["display_name"] == "历史名称" and item["completed_count"] == 1
        assert item["availability"] == "business_and_checkpoint"
    assert fingerprint(legacy_files) == before
    with sqlite3.connect(business) as connection:
        assert connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall() == before_schema


def test_private_quiz_rubric_feedback_state_and_student_answers_are_not_public(legacy_files):
    item = LegacyHistory(*legacy_files).get_project("old_1")
    text = json.dumps(item)
    assert "PRIVATE" not in text and "SECRET_INTERNAL_STATE" not in text
    assert "answer_key" not in text and "rubric" not in text and "evidence" not in text
    assert item["results"][0]["quiz"]["questions"][0]["prompt"] == "描述变量"
    assert item["results"][0]["feedback"] == {
        "total_score": 2.0, "max_score": 2.0,
        "question_scores": [{"question_id": "q1", "score": 2.0, "max_score": 2.0}],
    }


def test_business_only_and_checkpoint_only_are_explicitly_read_only(legacy_files):
    history = LegacyHistory(*legacy_files)
    business = history.get_project("old_2")
    assert business["availability"] == "business_only" and "Checkpoint" in business["notice"]
    assert business["nodes"][0]["title"] == "另一项目同名节点"
    checkpoint = history.get_project("checkpoint_only")
    assert checkpoint["availability"] == "checkpoint_only"
    assert checkpoint["nodes"] == checkpoint["results"] == checkpoint["allowed_actions"] == []
    assert checkpoint["total_count"] == 0 and history.contains("checkpoint_only")


def test_deleted_checkpoint_cannot_resurrect_history_and_unknown_ids_are_safe(legacy_files):
    history = LegacyHistory(*legacy_files)
    assert {item["project_id"] for item in history.list_projects()} == {"old_1", "old_2", "checkpoint_only"}
    assert not history.contains("deleted")
    for project_id in ("deleted", "missing", "old_1' OR 1=1--"):
        with pytest.raises(KeyError):
            history.get_project(project_id)


def test_missing_paths_never_create_database_or_parent_directory(tmp_path):
    business = tmp_path / "never-created" / "business.sqlite"
    checkpoint = tmp_path / "never-created" / "checkpoint.sqlite"
    history = LegacyHistory(business, checkpoint)
    assert history.list_projects() == [] and not history.contains("missing")
    with pytest.raises(KeyError):
        history.get_project("missing")
    assert not business.parent.exists()


def test_older_business_schema_without_labels_or_tombstones_is_not_migrated(legacy_files):
    business, checkpoint = legacy_files
    with sqlite3.connect(business) as connection:
        connection.executescript("DROP TABLE project_labels; DROP TABLE deleted_projects;")
    before = fingerprint(legacy_files)
    history = LegacyHistory(business, checkpoint)
    assert history.get_project("old_1")["display_name"] is None
    assert fingerprint(legacy_files) == before
    with sqlite3.connect(business) as connection:
        assert "project_labels" not in history._tables(connection)
        assert "deleted_projects" not in history._tables(connection)


@pytest.mark.parametrize("damage", ["mismatched_identity", "invalid_score", "invalid_json"])
def test_invalid_old_evaluation_cannot_be_published_as_valid_score(legacy_files, damage):
    business, _ = legacy_files
    with sqlite3.connect(business) as connection:
        evaluation = json.loads(connection.execute("SELECT evaluation_json FROM assessments").fetchone()[0])
        if damage == "mismatched_identity":
            evaluation["assessment_id"] = "another_assessment"
        elif damage == "invalid_score":
            evaluation["question_results"][0]["score"] = 3.0
        connection.execute("UPDATE assessments SET evaluation_json = ?",
                           ("{broken" if damage == "invalid_json" else json.dumps(evaluation),))
    item = LegacyHistory(*legacy_files).get_project("old_1")
    assert item["results"][0]["feedback"] is None
    assert item["results"][0]["quiz"] is not None


def test_connection_itself_rejects_accidental_writes(legacy_files):
    before = fingerprint(legacy_files)
    with LegacyHistory._open(legacy_files[0]) as connection:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO learning_projects VALUES ('bad','write','now')")
    assert fingerprint(legacy_files) == before
