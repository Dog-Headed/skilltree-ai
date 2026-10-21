"""Independent Day 12 recovery evidence; real SQLite/Graph, explicit Fake content.

Set DAY12_EVIDENCE_DIR to retain compact fault-matrix JSON records. No live
project or evaluation holdout is used, and no real model request is issued.
"""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.learning import LearningService
from app.v3.learning_api import create_learning_app
from app.v3.learning_repository import LearningRepository
from app.v3.repository import BudgetExhaustedError, ConflictError
from app.v3.runtime_storage import learning_checkpoint_path
from tests.day11_support import (answers_for_quiz, build_frozen_project, learning_event,
                                 private_quiz)
from tests.day12_process_worker import logged_model


def evidence(name, payload):
    directory = os.environ.get("DAY12_EVIDENCE_DIR")
    if directory:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        (target / (name + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def business_counts(case):
    pid = case["project_id"]
    with LearningRepository(case["paths"]) as repo:
        def count(sql):
            return repo.conn.execute(sql, (pid,)).fetchone()[0]
        return {"assessments": count("SELECT COUNT(*) FROM assessments WHERE project_id=?"),
                "quizzes": count("SELECT COUNT(*) FROM assessments WHERE project_id=? AND quiz_json IS NOT NULL"),
                "evaluations": count("SELECT COUNT(*) FROM assessments WHERE project_id=? AND evaluation_json IS NOT NULL"),
                "diagnoses": count("SELECT COUNT(*) FROM assessments WHERE project_id=? AND diagnosis_json IS NOT NULL"),
                "completions": count("SELECT COUNT(*) FROM learning_progress WHERE project_id=? AND completed_at IS NOT NULL"),
                "transitions": count("SELECT COUNT(*) FROM learning_transitions WHERE project_id=?"),
                "effective_rounds": count("SELECT COALESCE(SUM(effective_rounds),0) FROM node_runtime WHERE project_id=?"),
                "charged_requests": count("SELECT COALESCE(SUM(requests),0) FROM model_tasks WHERE project_id=?"),
                "continuations": count("SELECT COUNT(*) FROM model_operations WHERE project_id=? AND parent_operation_id IS NOT NULL")}


def file_snapshot(case):
    paths = case["paths"]
    return {str(p): p.read_bytes() for p in (paths.learning, paths.checkpoints, learning_checkpoint_path(paths))}


def provider_counts(path):
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    return dict(Counter(item["schema"] for item in records))


def provider_observations(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def die(case, hook, command, tmp_path, log_path):
    (case["paths"].root / "day12-isolated-test-store").write_text("Explicit isolated test fixture", encoding="utf-8")
    event_file = tmp_path / "command.json"
    event_file.write_text(json.dumps(command), encoding="utf-8")
    run = subprocess.run([sys.executable, "-m", "tests.day12_process_worker", str(case["paths"].root),
                          case["project_id"], hook, str(event_file), str(log_path)],
                         cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=50)
    assert run.returncode == 72, run.stdout + run.stderr


@pytest.mark.parametrize("hook", ["quiz_saved", "evaluation_saved", "diagnosis_saved", "completion_saved"])
def test_hard_exit_after_each_business_fact_reuses_identity_and_results(tmp_path, hook):
    calls = tmp_path / "provider.jsonl"
    model = logged_model(calls)
    case = build_frozen_project(tmp_path / "v3", model=model, node_count=1)
    # The preparation model call is outside the learning operation being measured.
    calls.write_text("", encoding="utf-8")
    pid = case["project_id"]
    service = LearningService(case["paths"], llm=model)
    view = service.start(pid, str(uuid4()))
    if hook == "quiz_saved":
        command = learning_event(view, "start_quiz")
    else:
        view = service.resume(pid, learning_event(view, "start_quiz"))
        command = learning_event(view, "submit_answer", answers=answers_for_quiz(private_quiz(case["paths"], pid, view["assessment_id"])))
    die(case, hook, command, tmp_path, calls)
    crashed = business_counts(case)
    with LearningRepository(case["paths"]) as repo:
        rows_before = [dict(row) for row in repo.conn.execute("SELECT * FROM assessments WHERE project_id=?", (pid,))]
        operation_id = repo.get_project(pid)["operation_id"]
    resumed_model = logged_model(calls)
    restarted = LearningService(case["paths"], llm=resumed_model)
    interrupted = restarted.read(pid)
    assert interrupted["recovery_required"] and interrupted["allowed_actions"] == ["retry"]
    before_refresh = file_snapshot(case)
    assert restarted.read(pid) == interrupted
    assert file_snapshot(case) == before_refresh
    request_id = str(uuid4())
    result = restarted.retry(pid, retry_token=interrupted["retry_token"], request_id=request_id)
    assert result["project_id"] == result["thread_id"] == pid
    assert result["page_state"] == ("quiz" if hook == "quiz_saved" else "completed"), result
    assert not result["recovery_required"]
    after = business_counts(case)
    assert after["assessments"] == after["quizzes"] == 1
    if hook == "quiz_saved":
        assert after["evaluations"] == after["diagnoses"] == after["completions"] == 0
        assert resumed_model.call_counts["AssessmentQuiz"] == 0
    else:
        assert after["evaluations"] == after["diagnoses"] == after["completions"] == after["transitions"] == after["effective_rounds"] == 1
        assert resumed_model.call_counts["TextBatchScore"] == 0
    if hook in {"diagnosis_saved", "completion_saved"}:
        assert resumed_model.call_counts["tool_selection"] == resumed_model.call_counts["DiagnosisDecision"] == 0
    with LearningRepository(case["paths"]) as repo:
        assert repo.get_project(pid)["operation_id"] == operation_id
        for saved in rows_before:
            current = repo.get_assessment(pid, saved["id"])
            for field in ("snapshot_json", "quiz_json", "answers_json", "evaluation_json", "diagnosis_json"):
                if saved[field] is not None:
                    assert current[field] == saved[field]
    before_replay = file_snapshot(case)
    count = provider_counts(calls)
    assert restarted.retry(pid, retry_token=interrupted["retry_token"], request_id=request_id) == result
    assert file_snapshot(case) == before_replay and provider_counts(calls) == count
    assert sum(count.values()) == after["charged_requests"]
    assert count["AssessmentQuiz"] == 1
    evidence(hook, {"scenario": hook, "hard_exit_code": 72, "crashed": crashed, "recovered": after,
                    "provider_calls": count, "recovery_provider_calls": dict(resumed_model.call_counts),
                    "provider_observations": provider_observations(calls),
                    "saved_facts_unchanged": True, "retry_replay_unchanged": True, "status": "passed"})


def test_budget_child_commit_crash_replay_adds_one_allowance_and_keeps_assessment(tmp_path):
    calls = tmp_path / "provider.jsonl"
    model = logged_model(calls)
    case = build_frozen_project(tmp_path / "v3", model=model, node_count=1)
    calls.write_text("", encoding="utf-8")
    pid = case["project_id"]
    service = LearningService(case["paths"], llm=model)
    view = service.start(pid, str(uuid4()))

    def exhaust(messages):
        with LearningRepository(case["paths"]) as repo:
            with repo.transaction():
                op = repo.get_project(pid)["operation_id"]
                repo.conn.execute("UPDATE model_operations SET reserved_requests=12,status='budget_exhausted' WHERE operation_id=?", (op,))
        raise BudgetExhaustedError("Explicit test-only exhaustion of the same operation")

    model.faults["AssessmentQuiz"].append(exhaust)
    view = service.resume(pid, learning_event(view, "start_quiz"))
    assert view["page_state"] == "budget_exhausted"
    assessment_id, old_token = view["assessment_id"], view["retry_token"]
    continuation_id = str(uuid4())
    die(case, "budget_child_saved", {"kind": "retry", "request_id": continuation_id,
        "retry_token": old_token, "continue_budget": True}, tmp_path, calls)
    assert business_counts(case)["continuations"] == 1
    recovered_model = logged_model(calls)
    restarted = LearningService(case["paths"], llm=recovered_model)
    interrupted = restarted.read(pid)
    assert interrupted["recovery_required"] and interrupted["assessment_id"] == assessment_id
    result = restarted.retry(pid, retry_token=interrupted["retry_token"], request_id=str(uuid4()))
    assert result["page_state"] == "quiz" and result["assessment_id"] == assessment_id
    assert result["operation_budget"] == {"used": 13, "limit": 24}
    before = file_snapshot(case)
    count = provider_counts(calls)
    assert restarted.retry(pid, retry_token=old_token, request_id=continuation_id, continue_budget=True) == result
    assert file_snapshot(case) == before and provider_counts(calls) == count
    with pytest.raises(ConflictError):
        restarted.retry(pid, retry_token=old_token, request_id=str(uuid4()), continue_budget=True)
    assert business_counts(case)["continuations"] == 1
    with LearningRepository(case["paths"]) as repo:
        family = [dict(row) for row in repo.conn.execute("SELECT parent_operation_id,reserved_requests,request_limit FROM model_operations WHERE project_id=? AND root_operation_id=(SELECT root_operation_id FROM model_operations WHERE operation_id=?)", (pid, repo.get_project(pid)["operation_id"]))]
    assert len(family) == 2 and sum(row["request_limit"] for row in family) == 24
    evidence("budget_child_saved", {"scenario": "budget_child_saved", "hard_exit_code": 72,
        "assessment_identity_preserved": True, "family": family, "recovered": business_counts(case),
        "operation_budget": result["operation_budget"], "provider_calls": count,
        "provider_observations": provider_observations(calls),
        "note": "The test seeds 12 prior operation reservations; provider counts are not presented as those 12 simulated calls.",
        "status": "passed"})


def test_two_clients_duplicate_submission_and_lost_response_preserve_one_fact_chain(tmp_path):
    case = build_frozen_project(tmp_path / "v3", node_count=2)
    pid, model = case["project_id"], case["model"]
    app = create_learning_app(case["paths"], llm=model)
    clients = [TestClient(app), TestClient(app)]
    view = clients[0].post(f"/projects/{pid}/begin", json={"request_id": str(uuid4())}).json()
    view = clients[0].post(f"/projects/{pid}/resume", json=learning_event(view, "start_quiz")).json()
    command = learning_event(view, "submit_answer", answers=answers_for_quiz(private_quiz(case["paths"], pid, view["assessment_id"])))
    barrier = Barrier(2)

    def send(client):
        barrier.wait(timeout=10)
        return client.post(f"/projects/{pid}/resume", json=deepcopy(command))

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, clients))
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    result = responses[0].json()
    assert result["current_node_id"] == "node_2" and result["completed_node_ids"] == ["node_1"]
    # Treat both write responses as lost: the next client action is a GET.
    before = file_snapshot(case)
    calls_before = len(model.calls)
    queried = clients[1].get(f"/projects/{pid}")
    assert queried.status_code == 200 and queried.json() == result
    assert len(model.calls) == calls_before and file_snapshot(case) == before
    # An explicit replay of the ORIGINAL request is safe after querying. It is
    # never rebuilt using node_2's new pending identity.
    replay = clients[1].post(f"/projects/{pid}/resume", json=command)
    assert replay.status_code == 200 and replay.json() == result
    assert len(model.calls) == calls_before and file_snapshot(case) == before
    counts = business_counts(case)
    assert counts["assessments"] == counts["evaluations"] == counts["diagnoses"] == counts["completions"] == counts["transitions"] == 1
    evidence("two_clients_lost_response", {"scenario": "two_clients_lost_response",
        "statuses": [r.status_code for r in responses], "recovered": counts,
        "query_and_explicit_same_request_replay_provider_delta": len(model.calls) - calls_before,
        "next_node": result["current_node_id"], "status": "passed"})


def test_two_tabs_distinct_commands_one_stale_identity_is_rejected_without_second_quiz(tmp_path):
    case = build_frozen_project(tmp_path / "v3", node_count=1)
    pid, model = case["project_id"], case["model"]
    app = create_learning_app(case["paths"], llm=model)
    clients = [TestClient(app), TestClient(app)]
    view = clients[0].post(f"/projects/{pid}/begin", json={"request_id": str(uuid4())}).json()
    commands = [learning_event(view, "start_quiz"), learning_event(view, "start_quiz")]
    barrier = Barrier(2)

    def send(index):
        barrier.wait(timeout=10)
        return clients[index].post(f"/projects/{pid}/resume", json=commands[index])

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(send, range(2)))
    assert sorted(r.status_code for r in responses) == [200, 409], [r.text for r in responses]
    assert model.call_counts["AssessmentQuiz"] == 1 and business_counts(case)["assessments"] == 1
    evidence("two_tabs_distinct_commands", {"scenario": "two_tabs_distinct_commands",
        "statuses": sorted(r.status_code for r in responses), "recovered": business_counts(case),
        "quiz_provider_calls": model.call_counts["AssessmentQuiz"], "status": "passed"})


@pytest.mark.parametrize("identity", ["pending_input_id", "draft_revision", "retry_token"])
def test_stale_identities_rejected_without_writes_or_model_calls(tmp_path, identity):
    case = build_frozen_project(tmp_path / "v3", node_count=1)
    pid, model = case["project_id"], case["model"]
    client = TestClient(create_learning_app(case["paths"], llm=model))
    view = client.post(f"/projects/{pid}/begin", json={"request_id": str(uuid4())}).json()
    if identity == "retry_token":
        payload = {"request_id": str(uuid4()), "retry_token": "retry_stale_day12"}
        url = f"/projects/{pid}/retry"
    else:
        payload = learning_event(view, "start_quiz")
        payload[identity] = payload[identity] + 1 if identity == "draft_revision" else "input_stale_day12"
        url = f"/projects/{pid}/resume"
    before = file_snapshot(case)
    calls = len(model.calls)
    response = client.post(url, json=payload)
    assert response.status_code == 409, response.text
    assert file_snapshot(case) == before and len(model.calls) == calls
    evidence("stale_" + identity, {"scenario": "stale_" + identity, "status_code": 409,
        "business_files_unchanged": True, "provider_delta": 0, "status": "passed"})


def test_refresh_restart_and_wait_reentry_are_read_only_and_side_effect_free(tmp_path):
    case = build_frozen_project(tmp_path / "v3", node_count=1)
    pid, model = case["project_id"], case["model"]
    service = LearningService(case["paths"], llm=model)
    view = service.start(pid, str(uuid4()))
    before = file_snapshot(case)
    calls = len(model.calls)
    restarted = LearningService(case["paths"], llm=model)
    client = TestClient(create_learning_app(case["paths"], llm=model))
    for _ in range(3):
        assert restarted.read(pid) == view
        assert client.get(f"/projects/{pid}").status_code == 200
        # The Graph's pure wait node may be re-entered without dispatching any
        # business command; this proves it contains no provider or fact writes.
        with restarted._graph() as graph:
            snap = graph.get_state(restarted._config(pid))
            assert snap.interrupts
            graph.invoke(None, restarted._config(pid), durability="sync")
        assert restarted.read(pid) == view
    # Graph re-entry may add an equivalent checkpoint; business facts and model
    # requests stay byte-identical, while pure GET changed neither store.
    assert Path(str(case["paths"].learning)).read_bytes() == before[str(case["paths"].learning)]
    assert len(model.calls) == calls and business_counts(case)["assessments"] == 0
    pure_before = file_snapshot(case)
    for _ in range(3):
        client.get(f"/projects/{pid}")
    assert file_snapshot(case) == pure_before
    evidence("refresh_restart_wait", {"scenario": "refresh_restart_wait", "get_count": 6,
        "wait_reentry_count": 3, "provider_delta": 0, "business_files_unchanged": True,
        "get_all_database_files_unchanged": True, "status": "passed"})


def test_old_quiz_identity_cannot_be_attached_to_the_new_nodes_wait_point(tmp_path):
    case = build_frozen_project(tmp_path / "v3", node_count=2)
    pid, model = case["project_id"], case["model"]
    client = TestClient(create_learning_app(case["paths"], llm=model))
    view = client.post(f"/projects/{pid}/begin", json={"request_id": str(uuid4())}).json()
    view = client.post(f"/projects/{pid}/resume", json=learning_event(view, "start_quiz")).json()
    old_assessment = view["assessment_id"]
    old_answers = answers_for_quiz(private_quiz(case["paths"], pid, old_assessment))
    old_submission = learning_event(view, "submit_answer", answers=old_answers)
    view = client.post(f"/projects/{pid}/resume", json=old_submission).json()
    assert view["current_node_id"] == "node_2"
    view = client.post(f"/projects/{pid}/resume", json=learning_event(view, "start_quiz")).json()
    assert view["assessment_id"] != old_assessment
    forged = learning_event(view, "submit_answer", answers=old_answers)
    forged["assessment_id"] = old_assessment
    before = file_snapshot(case)
    calls = len(model.calls)
    rejected = client.post(f"/projects/{pid}/resume", json=forged)
    assert rejected.status_code == 409, rejected.text
    # Exact replay of the old accepted command returns current state. It never
    # applies node_1's answers to the new node_2 assessment.
    replay = client.post(f"/projects/{pid}/resume", json=old_submission)
    assert replay.status_code == 200 and replay.json()["assessment_id"] == view["assessment_id"]
    assert file_snapshot(case) == before and len(model.calls) == calls
    with LearningRepository(case["paths"]) as repo:
        assert repo.get_assessment(pid, view["assessment_id"])["answers_json"] is None
    evidence("old_quiz_new_wait_point", {"scenario": "old_quiz_new_wait_point",
        "stale_assessment_status": 409, "original_command_replay_status": 200,
        "new_assessment_answers_untouched": True, "provider_delta": 0,
        "recovered": business_counts(case), "status": "passed"})
