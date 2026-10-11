import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from app.services.learning_session import open_learning_session
from app.db.repository import LearningRepository


WORKER = Path(__file__).parent / "support" / "checkpoint_worker.py"


def run_worker(tmp_path, phase, *, project_id="recovery_project", boundary="none", expected_exit=0):
    # 子进程从项目目录以外启动，避免用相对路径误建另一套数据库。
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(WORKER), phase, str(tmp_path), project_id, boundary],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == expected_exit, result.stderr + result.stdout
    return json.loads(result.stdout.strip().splitlines()[-1])


def call_names(tmp_path):
    return [json.loads(line)["name"] for line in (tmp_path / "model_calls.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("entry_point", ["begin_immediate_crash", "interactive_immediate_crash"])
def test_slow_checkpoint_and_immediate_quiz_commit_exit_keep_original_id(tmp_path, entry_point):
    crashed = run_worker(tmp_path, entry_point, expected_exit=3)
    assert crashed["crash_point"] == "quiz_business_commit"
    assert crashed["prepare_checkpoint_started"] is True
    assert crashed["prepare_checkpoint_committed"] is True
    committed_id = crashed["assessment_id"]
    with LearningRepository(tmp_path / "learning.sqlite") as repo:
        original = repo.get_assessment(committed_id)
        assert original["quiz"] is not None
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1

    # 新进程首先只读取存档；生成节点尚未返回，但准备节点的 ID 必须已可靠保存。
    restored = run_worker(tmp_path, "inspect")
    assert restored["next"] == ["assessment_generate"]
    assert restored["interrupts"] == []
    assert restored["state"]["assessment_id"] == committed_id
    assert call_names(tmp_path) == ["planner", "tutor", "quiz"]
    recovered = run_worker(tmp_path, "retry", boundary="quiz")
    assert recovered["next"] == ["wait_answer"]
    assert recovered["state"]["assessment_id"] == committed_id
    assert recovered["state"]["quiz"] == original["quiz"]
    assert call_names(tmp_path) == ["planner", "tutor", "quiz"]
    with LearningRepository(tmp_path / "learning.sqlite") as repo:
        assert repo.get_assessment(committed_id) == original
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1


def test_async_control_starts_quiz_before_prepared_id_checkpoint_commits(tmp_path):
    # 对照验证故障注入确实覆盖旧漏洞，而不是等图退出后才杀进程。
    crashed = run_worker(tmp_path, "async_immediate_crash", expected_exit=3)
    assert crashed["prepare_checkpoint_started"] is True
    assert crashed["prepare_checkpoint_committed"] is False
    with LearningRepository(tmp_path / "learning.sqlite") as repo:
        assert repo.get_assessment(crashed["assessment_id"])["quiz"] is not None
    restored = run_worker(tmp_path, "inspect")
    assert restored["next"] == ["assessment_prepare"]
    assert restored["state"].get("assessment_id") != crashed["assessment_id"]
    recovered = run_worker(tmp_path, "retry_async_control")
    assert recovered["state"]["assessment_id"] != crashed["assessment_id"]
    with LearningRepository(tmp_path / "learning.sqlite") as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 2


def test_wait_answer_survives_process_exit_and_resume_grades_original_quiz(tmp_path):
    first = run_worker(tmp_path, "begin")
    assert (tmp_path / "checkpoints.sqlite").is_file()
    assert first["project_id"] == first["thread_id"] == "recovery_project"
    assert first["next"] == ["wait_answer"]
    assert first["interrupts"][0]["type"] == "wait_answer"

    restored = run_worker(tmp_path, "inspect")
    assert restored["state"]["current_node_id"] == first["state"]["current_node_id"]
    assert restored["state"]["assessment_id"] == first["state"]["assessment_id"]
    assert restored["state"]["quiz"] == first["state"]["quiz"]
    assert restored["interrupts"] == first["interrupts"]
    assert call_names(tmp_path) == ["planner", "tutor", "quiz"]
    assert "answer_key" not in str(restored["interrupts"][0]["quiz"])
    assert "rubric" not in str(restored["interrupts"][0]["quiz"])

    finished = run_worker(tmp_path, "submit")
    assert finished["next"] == ["wait_learning"]
    assert finished["state"]["last_assessment_id"] == first["state"]["assessment_id"]
    assert finished["state"]["assessment_id"] is None
    assert finished["state"]["current_node_id"] == "node_1"
    assert finished["state"]["branch_result"].startswith("advance")
    assert finished["assessment"]["status"] == "graded"
    assert finished["assessment"]["quiz"] == first["state"]["quiz"]
    assert finished["assessment"]["answers"] == {q["id"]: q["answer_key"] for q in first["state"]["quiz"]["questions"]}
    assert finished["assessment"]["evaluation"]["assessment_id"] == first["state"]["assessment_id"]
    assert finished["assessment"]["diagnosis"]["recommended_action"] == "advance"
    assert finished["state"]["quiz"] == finished["state"]["answers"] == finished["state"]["evaluation"] == finished["state"]["diagnosis"] == {}
    assert finished["progress"]["completion_assessment_id"] == first["state"]["assessment_id"]
    assert call_names(tmp_path) == ["planner", "tutor", "quiz", "grade", "diagnosis", "tutor"]
    assert run_worker(tmp_path, "inspect")["state"] == finished["state"]


@pytest.mark.parametrize("boundary, failed_node", [
    ("quiz", "assessment_generate"), ("evaluation", "assessment_grade"),
    ("diagnosis", "diagnosis"), ("completion", "advance"),
])
def test_business_commit_before_checkpoint_is_reused_on_retry(tmp_path, boundary, failed_node):
    if boundary == "quiz":
        failed = run_worker(tmp_path, "begin_crash", boundary=boundary, expected_exit=2)
    else:
        run_worker(tmp_path, "begin")
        failed = run_worker(tmp_path, "submit_crash", boundary=boundary, expected_exit=2)
    assert failed["next"] == [failed_node]
    assert failed["interrupts"] == []
    field = "evaluation" if boundary == "evaluation" else boundary
    if boundary != "completion":
        assert failed["assessment"][field] is not None
    names_before_retry = call_names(tmp_path)

    recovered = run_worker(tmp_path, "retry", boundary=boundary)
    assert (recovered["state"].get("assessment_id") or recovered["state"].get("last_assessment_id")) == failed["state"]["assessment_id"]
    assert recovered["assessment"]["quiz"] == failed["assessment"]["quiz"]
    if boundary == "quiz":
        assert recovered["next"] == ["wait_answer"]
        assert recovered["state"]["quiz"] == failed["assessment"]["quiz"]
        assert call_names(tmp_path) == names_before_retry
    else:
        assert recovered["next"] == ["wait_learning"]
        assert recovered["state"]["current_node_id"] == "node_1"
        assert recovered["state"]["rounds_by_node"] == {"node_0": 1}
        assert recovered["assessment"]["evaluation"] == failed["assessment"]["evaluation"]
        if boundary == "evaluation":
            assert call_names(tmp_path) == names_before_retry + ["diagnosis", "tutor"]
        else:
            assert call_names(tmp_path) == names_before_retry + ["tutor"]
            assert recovered["assessment"]["diagnosis"] == failed["assessment"]["diagnosis"]
        if boundary == "completion":
            assert recovered["progress"] == failed["progress"]
    with sqlite3.connect(tmp_path / "learning.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM assessments").fetchone()[0] == 1


def test_session_distinguishes_new_waiting_and_failed_execution(tmp_path):
    kwargs = {"checkpoint_db_path": tmp_path / "checkpoints.sqlite", "learning_db_path": tmp_path / "learning.sqlite"}
    with open_learning_session("session_guards", **kwargs) as session:
        assert session.snapshot().values == {}
        assert session.snapshot().next == ()
        with pytest.raises(ValueError, match="没有等待用户输入"):
            session.resume({"action": "start_quiz"})
        with pytest.raises(ValueError, match="没有未完成"):
            session.retry()
        session.start("学习 Python")
        with pytest.raises(ValueError, match="不能重新从 START"):
            session.start("重新规划")
        with pytest.raises(ValueError, match="等待用户输入"):
            session.retry()
        session.resume({"action": "start_quiz"})
        quiz = session.restore()["quiz"]
    with open_learning_session("session_guards", **kwargs) as session:
        assert session.restore()["quiz"] == quiz
        assert session.snapshot().next == ("wait_answer",)


def test_projects_have_separate_persistent_threads(tmp_path):
    kwargs = {"checkpoint_db_path": tmp_path / "checkpoints.sqlite", "learning_db_path": tmp_path / "learning.sqlite"}
    with open_learning_session("project_a", **kwargs) as session:
        session.start("项目 A")
        session.resume({"action": "start_quiz"})
        first_quiz = session.restore()["quiz"]
    with open_learning_session("project_b", **kwargs) as session:
        assert session.snapshot().values == {}
        session.start("项目 B")
        assert "quiz" not in session.restore()
    with open_learning_session("project_a", **kwargs) as session:
        assert session.restore()["quiz"] == first_quiz
        assert session.snapshot().next == ("wait_answer",)


def test_partial_answers_survive_restart_without_fixing_incomplete_submission(tmp_path, answers_for_quiz):
    kwargs = {"checkpoint_db_path": tmp_path / "checkpoints.sqlite", "learning_db_path": tmp_path / "learning.sqlite"}
    with open_learning_session("partial_answer_project", **kwargs) as session:
        session.start("学习 Python")
        result = session.resume({"action": "start_quiz"})
        assessment_id = result["assessment_id"]
        answers = answers_for_quiz(result["quiz"])
        result = session.resume({"action": "submit_answer", "answers": {"q1": answers["q1"]}})
        assert result["answers"] == {"q1": answers["q1"]}
        assert session.snapshot().next == ("wait_answer",)
    with LearningRepository(kwargs["learning_db_path"]) as repo:
        assert repo.get_assessment(assessment_id)["answers"] is None
    with open_learning_session("partial_answer_project", **kwargs) as session:
        assert session.restore()["answers"] == {"q1": answers["q1"]}
        assert session.restore()["assessment_id"] == assessment_id
        result = session.resume({
            "action": "submit_answer", "answers": {key: value for key, value in answers.items() if key != "q1"}
        })
        assert result["answers"] == {}
        with LearningRepository(kwargs["learning_db_path"]) as repo:
            assert repo.get_assessment(assessment_id)["answers"] == answers
        assert result["last_assessment_id"] == assessment_id
        assert result["score_summary"] == {}
        assert session.snapshot().next == ("wait_learning",)


def test_teaching_wait_and_conversation_survive_process_exit(tmp_path):
    first = run_worker(tmp_path, "begin_learning")
    assert first["next"] == ["wait_learning"]
    assert first["state"]["lesson"]
    assert first["state"]["tutor_messages"]
    restored = run_worker(tmp_path, "inspect")
    assert restored["state"] == first["state"]
    assert restored["interrupts"] == first["interrupts"]
    assert call_names(tmp_path) == ["planner", "tutor"]
    answered = run_worker(tmp_path, "ask")
    assert answered["next"] == ["wait_learning"]
    assert answered["state"]["current_node_id"] == first["state"]["current_node_id"]
    assert len(answered["state"]["tutor_messages"]) == 3
    assert call_names(tmp_path) == ["planner", "tutor", "tutor"]
    assert run_worker(tmp_path, "inspect")["state"] == answered["state"]


def test_planner_checkpoint_survives_business_persistence_failure(tmp_path):
    failed = run_worker(tmp_path, "begin_crash", boundary="plan", expected_exit=2)
    assert failed["next"] == ["persist_plan"]
    assert failed["state"]["tree"]
    assert call_names(tmp_path) == ["planner"]
    with LearningRepository(tmp_path / "learning.sqlite") as repo:
        original_project = repo.get_project("recovery_project")
        assert repo.get_tree("recovery_project") == failed["state"]["tree"]
    restored = run_worker(tmp_path, "inspect")
    assert restored["state"] == failed["state"]
    recovered = run_worker(tmp_path, "retry", boundary="plan")
    assert recovered["next"] == ["wait_learning"]
    assert call_names(tmp_path) == ["planner", "tutor"]
    with LearningRepository(tmp_path / "learning.sqlite") as repo:
        assert repo.get_project("recovery_project") == original_project
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_projects").fetchone()[0] == 1
