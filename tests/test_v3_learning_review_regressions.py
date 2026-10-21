"""Regression cases from independent Day 11 workflow review."""

import json
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.v3.learning import LearningService
from app.v3.learning_api import create_learning_app
from app.v3.learning_repository import LearningRepository
from app.v3.repository import ConflictError
from tests.day11_support import build_frozen_project, learning_event, answers_for_quiz


def test_uuid_spelling_cannot_reuse_a_command_identity_for_different_question(tmp_path):
    ready = build_frozen_project(tmp_path / "v3", node_count=1)
    service = LearningService(ready["paths"], llm=ready["model"])
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    identity = uuid4()
    first = learning_event(view, "ask", question="先解释这个概念。")
    first["request_id"] = str(identity)
    accepted = service.resume(pid, first)
    calls = len(ready["model"].calls)
    before = ready["paths"].learning.read_bytes()
    equivalent_replay = {**first, "request_id": str(identity).upper()}
    assert service.resume(pid, equivalent_replay) == accepted
    assert len(ready["model"].calls) == calls and ready["paths"].learning.read_bytes() == before
    changed = learning_event(accepted, "ask", question="同一UUID不能另问一个问题。")
    changed["request_id"] = str(identity).upper()
    with pytest.raises(ConflictError):
        service.resume(pid, changed)
    assert len(ready["model"].calls) == calls and ready["paths"].learning.read_bytes() == before
    with LearningRepository(ready["paths"]) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_commands WHERE project_id=? AND request_id=?", (pid, identity.hex)).fetchone()[0] == 1


@pytest.mark.parametrize("failed_schema", ["TextBatchScore", "DiagnosisDecision"])
def test_return_to_teaching_cannot_bypass_system_replacement_limit_after_technical_failure(tmp_path, failed_schema):
    ready = build_frozen_project(tmp_path / "v3", node_count=1)
    model = ready["model"]
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    saved = []
    for index in range(3):
        view = service.resume(pid, learning_event(view, "start_quiz"))
        assert view["page_state"] == "quiz", view
        with LearningRepository(ready["paths"]) as repo:
            quiz = json.loads(repo.get_assessment(pid, view["assessment_id"])["quiz_json"])
        model.faults[failed_schema].extend([{}, {}])
        view = service.resume(pid, learning_event(view, "submit_answer", answers=answers_for_quiz(quiz)))
        assert view["rounds"]["effective_rounds"] == 0 and not view["completed_node_ids"]
        with LearningRepository(ready["paths"]) as repo:
            saved.append(dict(repo.get_assessment(pid, view["assessment_id"])))
        if index < 2:
            assert view["page_state"] == "error", view
            view = service.resume(pid, learning_event(view, "return_to_teaching"))
            assert view["page_state"] == "learning"
        else:
            assert view["page_state"] == "paused" and view["pause_reason"] == "replacement_limit", view
    assert len({row["id"] for row in saved}) == 3
    assert view["rounds"]["replacements"] == 2
    calls = len(model.calls)
    with pytest.raises(ValueError):
        service.resume(pid, learning_event(view, "start_quiz"))
    assert len(model.calls) == calls
    with LearningRepository(ready["paths"]) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments WHERE project_id=?", (pid,)).fetchone()[0] == 3
        for prior in saved:
            current = repo.get_assessment(pid, prior["id"])
            for field in ("snapshot_json", "quiz_json", "answers_json", "evaluation_json", "diagnosis_json"):
                assert current[field] == prior[field]


def test_startup_journal_without_session_has_api_recovery_and_cannot_be_overwritten(tmp_path):
    ready = build_frozen_project(tmp_path / "v3", node_count=1)
    pid = ready["project_id"]
    service = LearningService(ready["paths"], llm=ready["model"])
    with patch.object(LearningRepository, "start_session", side_effect=SystemExit("after journal before initialize commit")):
        with pytest.raises(SystemExit):
            service.start(pid, str(uuid4()))
    with LearningRepository(ready["paths"]) as repo:
        assert repo.session(pid) is None
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_execution WHERE project_id=?", (pid,)).fetchone()[0] == 1
        original_operation = repo.get_project(pid)["operation_id"]
    calls = len(ready["model"].calls)
    with TestClient(create_learning_app(ready["paths"], llm=ready["model"])) as client:
        response = client.get(f"/projects/{pid}")
        assert response.status_code == 200
        interrupted = response.json()
        assert interrupted["page_state"] == "error" and interrupted["recovery_required"]
        assert interrupted["allowed_actions"] == ["retry"] and interrupted["learning_runtime_ready"]
        assert len(ready["model"].calls) == calls
        assert client.post(f"/projects/{pid}/begin", json={"request_id": str(uuid4())}).status_code == 409
        fixed = client.post(f"/projects/{pid}/retry", json={"request_id": str(uuid4()), "retry_token": interrupted["retry_token"]})
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["page_state"] == "learning" and not fixed.json()["recovery_required"]
    with LearningRepository(ready["paths"]) as repo:
        assert repo.session(pid) is not None
        assert repo.get_project(pid)["operation_id"] == original_operation
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_execution WHERE project_id=?", (pid,)).fetchone()[0] == 0


def test_soft_exception_after_final_completion_commit_recovers_completed_phase_without_model(tmp_path, monkeypatch):
    ready = build_frozen_project(tmp_path / "v3", node_count=1)
    pid = ready["project_id"]
    service = LearningService(ready["paths"], llm=ready["model"])
    view = service.start(pid, str(uuid4()))
    view = service.resume(pid, learning_event(view, "start_quiz"))
    with LearningRepository(ready["paths"]) as repo:
        quiz = json.loads(repo.get_assessment(pid, view["assessment_id"])["quiz_json"])
    original = LearningRepository.apply_transition
    crashed = []

    def commit_then_fail(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if not crashed:
            crashed.append(True)
            raise RuntimeError("completion committed before checkpoint failed")
        return result

    monkeypatch.setattr(LearningRepository, "apply_transition", commit_then_fail)
    failed = service.resume(pid, learning_event(view, "submit_answer", answers=answers_for_quiz(quiz)))
    assert failed["page_state"] == "error" and failed["completed_node_ids"] == ["node_1"]
    assert "return_to_teaching" not in failed["allowed_actions"]
    with LearningRepository(ready["paths"]) as repo:
        assert repo.get_project(pid)["lifecycle"] == "completed"
        original_completion = repo.get_progress(pid)[0]
    calls = len(ready["model"].calls)
    restarted = LearningService(ready["paths"], llm=ready["model"])
    fixed = restarted.retry(pid, retry_token=failed["retry_token"], request_id=str(uuid4()))
    assert fixed["page_state"] == "completed" and fixed["error_type"] is None
    assert len(ready["model"].calls) == calls
    with LearningRepository(ready["paths"]) as repo:
        assert repo.get_progress(pid)[0] == original_completion
        assert repo.rounds(pid, "node_1")["effective_rounds"] == 1
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_transitions WHERE project_id=?", (pid,)).fetchone()[0] == 1


def test_soft_exception_after_prepare_wait_commit_recovers_quiz_without_regeneration(tmp_path, monkeypatch):
    ready = build_frozen_project(tmp_path / "v3", node_count=1)
    pid = ready["project_id"]
    service = LearningService(ready["paths"], llm=ready["model"])
    view = service.start(pid, str(uuid4()))
    original = LearningRepository.transaction
    crashed = []

    @contextmanager
    def commit_wait_then_fail(self):
        before = self.get_project(pid)
        with original(self):
            yield
        after = self.get_project(pid)
        pending = after["pending_input_id"]
        if not crashed and pending and pending.startswith("input_") and pending != before["pending_input_id"]:
            crashed.append(True)
            raise RuntimeError("prepare_wait committed before checkpoint failed")

    monkeypatch.setattr(LearningRepository, "transaction", commit_wait_then_fail)
    failed = service.resume(pid, learning_event(view, "start_quiz"))
    assert crashed and failed["page_state"] == "error", failed
    assessment_id = failed["assessment_id"]
    with LearningRepository(ready["paths"]) as repo:
        original_quiz = repo.get_assessment(pid, assessment_id)["quiz_json"]
        assert original_quiz is not None and repo.get_project(pid)["lifecycle"] == "quiz"
    calls = len(ready["model"].calls)
    fixed = LearningService(ready["paths"], llm=ready["model"]).retry(pid, retry_token=failed["retry_token"], request_id=str(uuid4()))
    assert fixed["page_state"] == "quiz" and fixed["assessment_id"] == assessment_id
    assert fixed["error_type"] is None and len(ready["model"].calls) == calls
    with LearningRepository(ready["paths"]) as repo:
        assert repo.get_assessment(pid, assessment_id)["quiz_json"] == original_quiz
        assert repo.rounds(pid, "node_1")["effective_rounds"] == 0
