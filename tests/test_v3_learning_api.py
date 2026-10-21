"""Public backend contracts against real stores and an explicit Fake model."""

import json
import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.v3.learning_api import create_learning_app
from app.v3.learning_repository import LearningRepository
from app.v3.runtime_storage import learning_checkpoint_path
from tests.day11_support import FakeLearningModel, answers_for_quiz, build_frozen_project, learning_event


@pytest.fixture
def api(tmp_path):
    frozen = build_frozen_project(tmp_path / "v3", node_count=1)
    client = TestClient(create_learning_app(frozen["paths"], llm=frozen["model"]))
    return client, frozen


def begin(client, frozen, request_id=None):
    response = client.post(f"/projects/{frozen['project_id']}/begin", json={"request_id": str(request_id or uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def resume(client, view, action, **changes):
    return client.post(f"/projects/{view['project_id']}/resume", json=learning_event(view, action, **changes))


def private_quiz(frozen, view):
    with LearningRepository(frozen["paths"]) as repo:
        return json.loads(repo.get_assessment(frozen["project_id"], view["assessment_id"])["quiz_json"])


def snapshots(frozen):
    paths = frozen["paths"]
    return {path: path.read_bytes() for path in (paths.learning, paths.checkpoints, learning_checkpoint_path(paths))}


def assert_same_files(before):
    assert all(path.read_bytes() == value for path, value in before.items())


def all_keys(value):
    if isinstance(value, dict):
        return set(value) | set().union(*(all_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(all_keys(item) for item in value))
    return set()


def test_preparation_read_is_dispatched_without_starting_learning_then_begin_is_idempotent(api):
    client, frozen = api
    pid = frozen["project_id"]
    calls = len(frozen["model"].calls)
    prior = client.get(f"/projects/{pid}").json()
    assert prior["frozen"] and not prior["learning_runtime_ready"]
    assert len(frozen["model"].calls) == calls
    request_id = uuid4()
    started = begin(client, frozen, request_id)
    assert started["learning_runtime_ready"] and started["page_state"] == "learning", started
    assert "start_quiz" in started["allowed_actions"]
    before = snapshots(frozen)
    calls = len(frozen["model"].calls)
    assert begin(client, frozen, request_id) == started
    assert len(frozen["model"].calls) == calls
    assert_same_files(before)


def test_restarted_get_and_rest_are_read_only_and_do_not_call_model(api):
    client, frozen = api
    started = begin(client, frozen)
    before = snapshots(frozen)
    calls = len(frozen["model"].calls)
    restarted = TestClient(create_learning_app(frozen["paths"], llm=lambda: pytest.fail("GET created a model")))
    for _ in range(3):
        assert restarted.get(f"/projects/{frozen['project_id']}").json() == started
    rest = resume(restarted, started, "rest")
    assert rest.status_code == 200 and rest.json() == started
    assert len(frozen["model"].calls) == calls
    assert_same_files(before)


def test_quiz_and_sources_never_expose_answer_keys_private_rubrics_or_raw_snapshot(api):
    client, frozen = api
    started = begin(client, frozen)
    response = resume(client, started, "start_quiz")
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["page_state"] == "quiz", view
    private = private_quiz(frozen, view)
    assert any(question.get("answer_key") or question.get("rubric") for question in private["questions"])
    forbidden = {"answer_key", "rubric", "numeric_rules", "snapshot", "evaluation_json", "diagnosis_json", "api_key", "checkpoint_path"}
    assert not all_keys(view) & forbidden
    sources = client.get(f"/projects/{frozen['project_id']}/sources")
    assert sources.status_code == 200
    assert not all_keys(sources.json()) & forbidden
    with LearningRepository(frozen["paths"]) as repo:
        private_documents = [item for item in repo.list_sources(frozen["project_id"], include_private=True) if item["visibility"] == "assessment_private"]
        for document in private_documents:
            assert document["content"] not in response.text and document["content"] not in sources.text


def test_accepted_submission_replay_has_one_evaluation_and_completion(api):
    client, frozen = api
    view = resume(client, begin(client, frozen), "start_quiz").json()
    assert view["page_state"] == "quiz", view
    event = learning_event(view, "submit_answer", answers=answers_for_quiz(private_quiz(frozen, view)))
    url = f"/projects/{frozen['project_id']}/resume"
    first = client.post(url, json=event)
    assert first.status_code == 200, first.text
    result = first.json()
    assert result["page_state"] == "completed", result
    calls = len(frozen["model"].calls)
    before = snapshots(frozen)
    assert client.post(url, json=event).json() == result
    assert len(frozen["model"].calls) == calls
    assert_same_files(before)
    changed = {**event, "answers": {key: "different answer" for key in event["answers"]}}
    assert client.post(url, json=changed).status_code == 409
    with LearningRepository(frozen["paths"]) as repo:
        assert repo.conn.execute("SELECT COUNT(*) FROM assessments WHERE project_id=? AND evaluation_json IS NOT NULL", (frozen["project_id"],)).fetchone()[0] == 1
        progress = repo.get_progress(frozen["project_id"])
        assert len(progress) == 1 and progress[0]["completion_assessment_id"] == view["assessment_id"]
        assert repo.rounds(frozen["project_id"], view["current_node_id"])["effective_rounds"] == 1


def test_stale_input_wrong_assessment_and_bad_payload_map_to_safe_errors_without_write(api):
    client, frozen = api
    view = begin(client, frozen)
    url = f"/projects/{frozen['project_id']}/resume"
    stale = learning_event(view, "ask", question="为什么？")
    stale["pending_input_id"] = "stale-private-identifier"
    before = snapshots(frozen); calls = len(frozen["model"].calls)
    response = client.post(url, json=stale)
    assert response.status_code == 409 and response.json()["error"]["code"] == "state_conflict"
    assert "stale-private-identifier" not in response.text
    invalid = {**learning_event(view, "ask", question="为什么？"), "api_key": "SECRET_DO_NOT_ECHO"}
    response = client.post(url, json=invalid)
    assert response.status_code == 422 and "SECRET_DO_NOT_ECHO" not in response.text
    assert len(frozen["model"].calls) == calls
    assert_same_files(before)
    quiz = resume(client, view, "start_quiz").json()
    event = learning_event(quiz, "submit_answer", answers=answers_for_quiz(private_quiz(frozen, quiz)))
    event["assessment_id"] = "wrong-assessment"
    before = snapshots(frozen); calls = len(frozen["model"].calls)
    assert client.post(url, json=event).status_code == 409
    assert len(frozen["model"].calls) == calls
    assert_same_files(before)


def test_incomplete_answers_do_not_become_a_submission_or_grade(api):
    client, frozen = api
    view = resume(client, begin(client, frozen), "start_quiz").json()
    calls = len(frozen["model"].calls); before = snapshots(frozen)
    response = resume(client, view, "submit_answer", answers={"ghost": "not a valid question"})
    assert response.status_code == 422
    assert len(frozen["model"].calls) == calls
    assert_same_files(before)
    with LearningRepository(frozen["paths"]) as repo:
        row = repo.get_assessment(frozen["project_id"], view["assessment_id"])
        assert row["answers_json"] is None and row["evaluation_json"] is None


def test_technical_model_error_hides_details_and_retry_reuses_existing_task(tmp_path):
    model = FakeLearningModel(faults={"TutorReply": [RuntimeError("SECRET_CONFIG_PATH_AND_CREDENTIALS")]})
    frozen = build_frozen_project(tmp_path / "v3", node_count=1, model=model)
    client = TestClient(create_learning_app(frozen["paths"], llm=model))
    failed = begin(client, frozen)
    assert failed["page_state"] == "error" and failed["error_type"] == "RuntimeError"
    assert "SECRET_CONFIG_PATH_AND_CREDENTIALS" not in json.dumps(failed)
    url = f"/projects/{frozen['project_id']}/retry"
    assert client.post(url, json={"request_id": str(uuid4()), "retry_token": "stale-token"}).status_code == 409
    retried = client.post(url, json={"request_id": str(uuid4()), "retry_token": failed["retry_token"]})
    assert retried.status_code == 200, retried.text
    assert retried.json()["page_state"] == "learning", retried.text
    with LearningRepository(frozen["paths"]) as repo:
        tasks = repo.conn.execute("SELECT requests FROM model_tasks WHERE project_id=? AND task_key LIKE 'tutor:%'", (frozen["project_id"],)).fetchall()
        assert len(tasks) == 1 and tasks[0][0] == 2


def test_v2_project_identity_is_not_reinterpreted_as_v3_or_modified(api, tmp_path):
    client, frozen = api
    legacy = tmp_path / "learning.sqlite"
    with sqlite3.connect(legacy) as conn:
        conn.execute("CREATE TABLE learning_projects(id TEXT PRIMARY KEY,goal TEXT)")
        conn.execute("INSERT INTO learning_projects VALUES ('v2_history','旧版等待项目')")
    before = legacy.read_bytes()
    assert client.get("/projects/v2_history").status_code == 404
    assert client.post("/projects/v2_history/begin", json={"request_id": str(uuid4())}).status_code == 404
    assert legacy.read_bytes() == before
