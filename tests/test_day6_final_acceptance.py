from copy import deepcopy

import pytest

import app.agents.planner as planner
from app.db import repository
from app.db.repository import LearningRepository
from app.graph import advance_node, persist_plan_node
from app.services.learning_session import open_learning_session
import day6_restore_demo as demo


def session_paths(tmp_path):
    return {"learning_db_path": tmp_path / "learning.sqlite", "checkpoint_db_path": tmp_path / "checkpoints.sqlite"}


def test_planner_only_returns_state_and_persistence_is_separate(tmp_path):
    path = tmp_path / "learning.sqlite"
    state = {"project_id": "plan_only", "goal": "学习 Python", "learning_db_path": str(path)}
    update = planner.planner_node(state)
    assert not path.exists()
    state.update(update)
    assert persist_plan_node(state) == {}
    with LearningRepository(path) as repo:
        original = repo.get_project("plan_only")
        progress = repo.get_progress(project_id="plan_only", node_id=state["current_node_id"])
        assert repo.get_tree("plan_only") == state["tree"]
        assert progress["started_at"]
    persist_plan_node(state)
    with LearningRepository(path) as repo:
        assert repo.get_project("plan_only") == original
        assert repo.get_progress(project_id="plan_only", node_id=state["current_node_id"]) == progress
        assert repo.conn.execute("SELECT COUNT(*) FROM knowledge_nodes").fetchone()[0] == 8


@pytest.mark.parametrize("conflict", ["goal", "tree"])
def test_persist_plan_refuses_to_overwrite_existing_business_facts(tmp_path, conflict):
    path = tmp_path / "learning.sqlite"
    state = {"project_id": "plan_conflict", "goal": "学习 Python", "learning_db_path": str(path)}
    state.update(planner.planner_node(state))
    persist_plan_node(state)
    changed = deepcopy(state)
    if conflict == "goal":
        changed["goal"] = "不同目标"
    else:
        changed["tree"][0]["description"] = "不同规划"
    with pytest.raises(ValueError, match="不一致"):
        persist_plan_node(changed)
    with LearningRepository(path) as repo:
        assert repo.get_project(state["project_id"])["goal"] == state["goal"]
        assert repo.get_tree(state["project_id"]) == state["tree"]


def test_orphan_business_project_cannot_be_restarted_from_start(tmp_path):
    paths = session_paths(tmp_path)
    state = {"project_id": "orphan", "goal": "学习 Python", "learning_db_path": str(paths["learning_db_path"])}
    state.update(planner.planner_node(state))
    persist_plan_node(state)
    with open_learning_session("orphan", **paths) as session:
        with pytest.raises(ValueError, match="找不到对应 Checkpoint"):
            session.start(state["goal"])
        assert session.snapshot().values == {}


def test_advance_clears_round_state_and_completion_remains_idempotent(tmp_path, answers_for_quiz):
    paths = session_paths(tmp_path)
    with open_learning_session("advance_project", **paths) as session:
        first = session.start("学习 Python")
        old_messages = [message.id for message in first["tutor_messages"]]
        quiz_state = session.resume({"action": "start_quiz"})
        quiz = quiz_state["quiz"]
        result = session.resume({"action": "submit_answer", "answers": answers_for_quiz(quiz)})
        assert session.snapshot().next == ("wait_learning",)
        assert result["current_node_id"] == "lists"
        assert result["last_completed_node_id"] == "variables"
        assert result["last_assessment_id"] == quiz["assessment_id"]
        assert result["assessment_id"] is None
        assert result["rounds_by_node"] == {"variables": 1}
        assert result["quiz"] == result["answers"] == result["evaluation"] == result["diagnosis"] == result["score_summary"] == {}
        assert result["assessment_history"] == []
        assert not set(old_messages) & {message.id for message in result["tutor_messages"]}
        assert len(result["tutor_messages"]) == 1
        assert result["lesson_mode"] == "normal"
        assert result["review_node_id"] is None
    with LearningRepository(paths["learning_db_path"]) as repo:
        assessment = repo.get_assessment(quiz["assessment_id"])
        old_progress = repo.get_progress(project_id="advance_project", node_id="variables")
        assert assessment["status"] == "graded"
        assert all(assessment[field] is not None for field in ("quiz", "answers", "evaluation", "diagnosis"))
        assert old_progress["completed_at"]
        # 重复调用时使用原评分现场，不能拿新节点的空轮次当成已通过。
        old_state = {**quiz_state, "evaluation": assessment["evaluation"], "diagnosis": assessment["diagnosis"],
                     "score_summary": {"percentage": 100.0}}
    assert advance_node(old_state)["current_node_id"] == "lists"
    assert advance_node(old_state)["current_node_id"] == "lists"
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.get_progress(project_id="advance_project", node_id="variables") == old_progress
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_progress WHERE project_id=? AND node_id=?", ("advance_project", "variables")).fetchone()[0] == 1
    with open_learning_session("advance_project", **paths) as session:
        assert session.restore()["current_node_id"] == "lists"
        assert session.restore()["last_assessment_id"] == quiz["assessment_id"]


def test_whole_tree_finishes_only_after_all_prerequisites_are_completed(tmp_path, answers_for_quiz):
    paths = session_paths(tmp_path)
    visited, saved_ids = [], []
    with open_learning_session("whole_tree", **paths) as session:
        state = session.start("学习 Python")
        for _ in range(8):
            current_id = state["current_node_id"]
            node = next(node for node in state["tree"] if node["id"] == current_id)
            with LearningRepository(paths["learning_db_path"]) as repo:
                for prerequisite_id in node["prerequisite_ids"]:
                    assert repo.get_progress(project_id="whole_tree", node_id=prerequisite_id)["completed_at"]
            visited.append(current_id)
            state = session.resume({"action": "start_quiz"})
            saved_ids.append(state["assessment_id"])
            state = session.resume({"action": "submit_answer", "answers": answers_for_quiz(state["quiz"])})
        assert session.snapshot().next == ()
        assert state["project_completed"] is True
        assert state["current_node_id"] is None
        assert state["last_assessment_id"] == saved_ids[-1]
        assert state["lesson"] == ""
        assert state["tutor_messages"] == []
        assert len(set(visited)) == len(set(saved_ids)) == 8
    with LearningRepository(paths["learning_db_path"]) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_progress WHERE completed_at IS NOT NULL").fetchone()[0] == 8
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments WHERE status='graded'").fetchone()[0] == 8
    with open_learning_session("whole_tree", **paths) as session:
        assert session.restore()["project_completed"] is True
        assert session.snapshot().next == ()


def cli_paths(tmp_path):
    return ["--learning-db", str(tmp_path / "learning.sqlite"), "--checkpoint-db", str(tmp_path / "checkpoints.sqlite")]


def test_menu_creates_new_project_and_restores_without_running_planner_again(tmp_path, monkeypatch, capsys):
    captured = []
    def leave_at_wait(graph, result, config, **kwargs):
        captured.append((result, config))
        raise KeyboardInterrupt
    monkeypatch.setattr(demo, "run_interactive", leave_at_wait)
    answers = iter(["x", "1", "学习 Python"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert demo.main(cli_paths(tmp_path)) == 0
    first = captured[0][0]
    assert first["project_id"].startswith("project_")
    assert captured[0][1]["configurable"]["thread_id"] == first["project_id"]
    def must_not_plan(*args, **kwargs):
        raise AssertionError("恢复不能重新规划")
    monkeypatch.setattr(planner, "generate_plan", must_not_plan)
    answers = iter(["2", "0", "-1", "100", "bad", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert demo.main(cli_paths(tmp_path)) == 0
    assert captured[1][0]["project_id"] == first["project_id"]
    assert captured[1][0]["lesson"] == first["lesson"]
    assert captured[1][0]["tutor_messages"] == first["tutor_messages"]
    assert "成功恢复" in capsys.readouterr().out


def test_menu_rejects_business_project_without_checkpoint(tmp_path, monkeypatch, capsys):
    path = tmp_path / "learning.sqlite"
    state = {"project_id": "orphan", "goal": "学习 Python", "learning_db_path": str(path)}
    state.update(planner.planner_node(state))
    persist_plan_node(state)
    answers = iter(["2", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert demo.main(cli_paths(tmp_path)) == 1
    assert "找不到对应 Checkpoint" in capsys.readouterr().out


def test_inspect_old_graded_round_after_advance_uses_business_database(tmp_path, answers_for_quiz, capsys):
    paths = session_paths(tmp_path)
    with open_learning_session("graded_inspect", **paths) as session:
        session.start("学习 Python")
        state = session.resume({"action": "start_quiz"})
        quiz_id = state["assessment_id"]
        session.resume({"action": "submit_answer", "answers": answers_for_quiz(state["quiz"])})
    assert demo.main(cli_paths(tmp_path) + ["--project-id", "graded_inspect", "--inspect", "--assessment-id", quiz_id]) == 0
    output = capsys.readouterr().out
    assert quiz_id in output
    assert "graded" in output
    assert "completed_at" in output
    assert "本轮逐题评价" in output
    assert "answer_key" not in output and "rubric" not in output


def test_cannot_inspect_another_projects_assessment(tmp_path, answers_for_quiz):
    paths = session_paths(tmp_path)
    with open_learning_session("project_A", **paths) as session:
        session.start("学习 Python")
        state = session.resume({"action": "start_quiz"})
        saved_id = state["assessment_id"]
    with open_learning_session("project_B", **paths) as session:
        session.start("学习 Python")
        with pytest.raises(ValueError, match="其他项目"):
            demo.show_saved_assessment(session, saved_id)
