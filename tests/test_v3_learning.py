from copy import deepcopy
import json
from uuid import uuid4

import pytest

from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from tests.day11_support import (
    FakeLearningModel, answers_for_quiz, build_exploration_project, build_frozen_project,
    learning_event, private_quiz,
)


def submit_round(service, ready, view):
    pid = ready["project_id"]
    quiz_view = service.resume(pid, learning_event(view, "start_quiz"))
    assert quiz_view["page_state"] == "quiz", quiz_view
    quiz = private_quiz(ready["paths"], pid, quiz_view["assessment_id"])
    return service.resume(pid, learning_event(quiz_view, "submit_answer", answers=answers_for_quiz(quiz)))


@pytest.mark.parametrize("subject", ["python", "mathematics", "english"])
def test_three_subjects_use_same_learning_flow_and_real_frozen_material_bindings(tmp_path, subject):
    ready = build_frozen_project(tmp_path / subject, subject)
    service = LearningService(ready["paths"], llm=ready["model"])
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    assert view["page_state"] == "learning", view
    assert view["tutor"]["citations"]
    assert all(context.citations for context in ready["contexts"].values())
    for _ in ready["plan"].nodes:
        view = submit_round(service, ready, view)
    assert view["page_state"] == "completed", view
    assert len(view["completed_node_ids"]) == 2
    assert view["guard"]["passed"] is True
    before = deepcopy(ready["model"].calls)
    assert service.read(pid)["page_state"] == "completed"
    assert ready["model"].calls == before
    with LearningRepository(ready["paths"]) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments WHERE project_id=?", (pid,)).fetchone()[0] == 2
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_transitions WHERE project_id=?", (pid,)).fetchone()[0] == 2


def test_third_failed_round_pauses_and_rest_restart_and_extension_do_not_autocall_models(tmp_path):
    model = FakeLearningModel(grade_ratio=0.2)
    ready = build_frozen_project(tmp_path, model=model)
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    for number in range(1, 4):
        view = submit_round(service, ready, view)
        assert view["page_state"] == ("paused" if number == 3 else "learning"), view
    assert view["rounds"]["effective_rounds"] == view["rounds"]["round_limit"] == 3
    assert view["completed_node_ids"] == []
    assert model.call_counts["TutorReply"] == 3
    before = deepcopy(model.calls)
    rested = service.resume(pid, learning_event(view, "rest"))
    reopened = LearningService(ready["paths"], llm=model).read(pid)
    assert rested["page_state"] == reopened["page_state"] == "paused"
    assert model.calls == before
    extension = learning_event(reopened, "retry_3")
    extended = service.resume(pid, extension)
    repeated = service.resume(pid, extension)
    assert extended["page_state"] == repeated["page_state"] == "paused"
    assert repeated["rounds"]["round_limit"] == 6
    assert repeated["rounds"]["effective_rounds"] == 3
    assert repeated["rounds"]["extension_used"] == 1
    assert model.calls == before


def test_third_round_that_passes_advances_before_failure_pause_rule(tmp_path):
    model = FakeLearningModel(grade_ratio=0.2)
    ready = build_frozen_project(tmp_path, model=model)
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    view = submit_round(service, ready, view)
    view = submit_round(service, ready, view)
    model.grade_ratio = 1.0
    view = submit_round(service, ready, view)
    assert view["page_state"] == "learning" and view["current_node_id"] == "node_2", view
    assert view["completed_node_ids"] == ["node_1"] and view["guard"]["passed"]
    with LearningRepository(ready["paths"]) as repo:
        assert repo.rounds(pid, "node_1")["effective_rounds"] == 3


@pytest.mark.parametrize("status", ["needs_review", "invalid_item"])
def test_system_uncertainty_annotation_and_replacement_preserve_original_facts(tmp_path, status):
    model = FakeLearningModel(grading_status=status)
    ready = build_frozen_project(tmp_path, model=model)
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    view = submit_round(service, ready, view)
    assert view["page_state"] == "assessment_review", view
    assert view["rounds"]["effective_rounds"] == 0 and view["completed_node_ids"] == []
    old_id = view["assessment_id"]
    with LearningRepository(ready["paths"]) as repo:
        old = dict(repo.get_assessment(pid, old_id))
    before = deepcopy(model.calls)
    annotated = service.resume(pid, learning_event(view, "annotate_dispute", annotation="请保留原答案，我认为此题有歧义。"))
    assert annotated["page_state"] == "assessment_review"
    assert model.calls == before
    with LearningRepository(ready["paths"]) as repo:
        assert dict(repo.get_assessment(pid, old_id)) == old
        assert repo.conn.execute("SELECT COUNT(*) FROM assessment_annotations WHERE project_id=?", (pid,)).fetchone()[0] == 1
    replaced = service.resume(pid, learning_event(annotated, "replace_assessment"))
    assert replaced["page_state"] == "quiz", replaced
    assert replaced["assessment_id"] != old_id
    with LearningRepository(ready["paths"]) as repo:
        fresh = repo.get_assessment(pid, replaced["assessment_id"])
        assert fresh["previous_assessment_id"] == old_id
        assert json.loads(fresh["quiz_json"])["snapshot"] == json.loads(old["quiz_json"])["snapshot"]
        assert repo.get_assessment(pid, old_id)["evaluation_json"] == old["evaluation_json"]


@pytest.mark.parametrize("direct_profile", [False, True])
def test_exploration_can_ask_but_never_generate_a_quiz_or_complete(tmp_path, direct_profile):
    ready = build_exploration_project(tmp_path, direct_profile=direct_profile)
    service = LearningService(ready["paths"], llm=ready["model"])
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    assert view["page_state"] == "exploring", view
    view = service.resume(pid, learning_event(view, "ask", question="请先解释这个主题可以如何探索。"))
    assert view["page_state"] == "exploring", view
    assert "start_quiz" not in view["allowed_actions"]
    with pytest.raises(ValueError):
        service.resume(pid, learning_event(view, "start_quiz"))
    assert ready["model"].call_counts["AssessmentQuiz"] == 0
    assert view["completed_node_ids"] == []


def test_illegal_generated_quiz_never_persists_or_unlocks(tmp_path):
    model = FakeLearningModel(invalid_quiz=True)
    ready = build_frozen_project(tmp_path, model=model)
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    view = service.resume(pid, learning_event(view, "start_quiz"))
    assert view["page_state"] == "error" and view["completed_node_ids"] == [], view
    assert model.call_counts["AssessmentQuiz"] == 2
    with LearningRepository(ready["paths"]) as repo:
        assert repo.get_assessment(pid, view["assessment_id"])["quiz_json"] is None
        assert repo.rounds(pid, "node_1")["effective_rounds"] == 0
