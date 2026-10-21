"""Six isolated Fake workflow demonstrations; no real HTTP or quality claims."""

from copy import deepcopy
from hashlib import sha256
import argparse
import json
from pathlib import Path
from uuid import uuid4

from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from tests.day11_support import (
    ROOT, FakeLearningModel, _payload, answers_for_quiz, build_frozen_project,
    learning_event, private_quiz,
)


def play_round(service, ready, view):
    pid = ready["project_id"]
    quiz_view = service.resume(pid, learning_event(view, "start_quiz"))
    if quiz_view["page_state"] != "quiz":
        raise AssertionError(quiz_view)
    quiz = private_quiz(ready["paths"], pid, quiz_view["assessment_id"])
    return service.resume(pid, learning_event(quiz_view, "submit_answer", answers=answers_for_quiz(quiz)))


def run_demo(destination):
    destination = Path(destination).resolve()
    if destination == ROOT or (ROOT / "data") == destination or (ROOT / "data") in destination.parents:
        raise ValueError("The Fake demonstration must use a new isolated directory outside runtime data")
    if destination.exists():
        raise FileExistsError("Use a new demonstration directory")
    destination.mkdir(parents=True)
    scenarios, stores = [], []

    for subject in ("python", "mathematics", "english"):
        ready = build_frozen_project(destination / subject, subject, node_count=4)
        stores.append(ready["paths"])
        service = LearningService(ready["paths"], llm=ready["model"])
        pid = ready["project_id"]
        view = service.start(pid, str(uuid4()))
        for _ in ready["plan"].nodes:
            view = play_round(service, ready, view)
        assert view["page_state"] == "completed" and len(view["completed_node_ids"]) == 4, view
        scenarios.append({"scenario": subject + "_same_flow", "project_id": pid, "passed": True,
                          "final_state": view["page_state"], "completed_nodes": view["completed_node_ids"],
                          "guard": view["guard"], "fake_calls": dict(ready["model"].call_counts)})

    model = FakeLearningModel(grade_ratio=0.2)
    ready = build_frozen_project(destination / "pause", model=model)
    stores.append(ready["paths"])
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    for _ in range(3):
        view = play_round(service, ready, view)
    assert view["page_state"] == "paused" and view["rounds"]["effective_rounds"] == 3
    calls = deepcopy(model.calls)
    view = service.resume(pid, learning_event(view, "rest"))
    service = LearningService(ready["paths"], llm=model)
    view = service.read(pid)
    event = learning_event(view, "retry_3")
    view = service.resume(pid, event)
    view = service.resume(pid, event)
    assert view["page_state"] == "paused" and view["rounds"]["round_limit"] == 6
    assert view["rounds"]["effective_rounds"] == 3 and model.calls == calls
    scenarios.append({"scenario": "third_failure_pause_rest_restart_extend_once", "project_id": pid, "passed": True,
                      "final_state": view["page_state"], "rounds": view["rounds"], "automatic_calls_after_pause": 0})

    model = FakeLearningModel(grading_status="needs_review")
    ready = build_frozen_project(destination / "review", model=model)
    stores.append(ready["paths"])
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    view = play_round(service, ready, view)
    old_id = view["assessment_id"]
    assert view["page_state"] == "assessment_review" and view["rounds"]["effective_rounds"] == 0
    with LearningRepository(ready["paths"]) as repo:
        old = dict(repo.get_assessment(pid, old_id))
    calls = deepcopy(model.calls)
    view = service.resume(pid, learning_event(view, "annotate_dispute", annotation="Fake用户声明：请记录争议，保留原答卷。"))
    assert model.calls == calls
    with LearningRepository(ready["paths"]) as repo:
        assert dict(repo.get_assessment(pid, old_id)) == old
    view = service.resume(pid, learning_event(view, "replace_assessment"))
    assert view["page_state"] == "quiz" and view["assessment_id"] != old_id
    with LearningRepository(ready["paths"]) as repo:
        fresh = repo.get_assessment(pid, view["assessment_id"])
        old_after = repo.get_assessment(pid, old_id)
        assert fresh["previous_assessment_id"] == old_id
        assert old_after["answers_json"] == old["answers_json"] and old_after["evaluation_json"] == old["evaluation_json"]
    scenarios.append({"scenario": "uncertain_annotation_and_new_quiz", "project_id": pid, "passed": True,
                      "original_assessment_id": old_id, "new_assessment_id": view["assessment_id"],
                      "original_answer_hash": sha256(old["answers_json"].encode()).hexdigest(),
                      "annotation_model_calls": 0, "effective_rounds": view["rounds"]["effective_rounds"]})

    model = FakeLearningModel(faults={"TutorReply": ["timeout", None]})

    def bad_quiz(messages):
        value = model._quiz(_payload(messages))
        value["assessment_id"] = "invalid_fake_identity"
        return value

    model.faults["AssessmentQuiz"].extend([bad_quiz, None])
    ready = build_frozen_project(destination / "repair", model=model, node_count=1)
    stores.append(ready["paths"])
    service = LearningService(ready["paths"], llm=model)
    pid = ready["project_id"]
    view = service.start(pid, str(uuid4()))
    assert view["page_state"] == "learning" and model.call_counts["TutorReply"] == 2, view
    view = play_round(service, ready, view)
    assert view["page_state"] == "completed" and model.call_counts["AssessmentQuiz"] == 2, view
    with LearningRepository(ready["paths"]) as repo:
        tasks = [dict(row) for row in repo.conn.execute(
            "SELECT task_key,requests,network_retries,output_repairs,status FROM model_tasks WHERE project_id=? ORDER BY task_key", (pid,))]
    assert any(task["network_retries"] == 1 for task in tasks)
    assert any(task["output_repairs"] == 1 for task in tasks)
    assert all(task["requests"] <= 3 for task in tasks)
    scenarios.append({"scenario": "timeout_and_invalid_output_bounded_repair", "project_id": pid, "passed": True,
                      "final_state": view["page_state"], "durable_logical_tasks": tasks})

    # Synthetic passes must not become a live learning environment later.
    for paths in stores:
        with LearningRepository(paths) as repo:
            with repo.transaction():
                repo.conn.execute("INSERT INTO runtime_metadata(key,value) VALUES ('demo_only','day11-isolated-fake-workflow')")
        try:
            LearningService(paths)
        except ValueError:
            pass
        else:
            raise AssertionError("A synthetic demonstration store was accepted as a live runtime")
    report = {"mode": "ISOLATED_FAKE_WORKFLOW_ONLY", "scenarios": scenarios, "scenario_count": len(scenarios),
              "all_checks_passed": all(item["passed"] for item in scenarios), "real_http_requests": 0,
              "model_quality_evaluated": False, "human_reference_review": "pending_user_review",
              "holdout_cases_read": 0, "demo_stores_rejected_by_live_service": True,
              "scope": "Real V3 repositories, frozen sources, graph, evaluators and guards with explicitly Fake model output."}
    (destination / "day11-demo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Day 11 · 六类隔离 Fake 流程演示", "", "真实 HTTP 请求为 0；不读取 holdout，不构成人工金标准或教学/评分质量通过证据。", "",
             "真实资料版本、绑定、确认冻结、Graph、业务库、独立Checkpoint及守卫参与运行；模型回答均由Fake提供。", "",
             "| 场景 | 机制检查 |", "|---|---|"]
    lines.extend("| " + item["scenario"] + " | 通过 |" for item in scenarios)
    lines.extend(["", "暂停后休息、重启和追加3轮不自动调用模型；原计数保留且额度只加一次。",
                  "争议说明只追加留档，新测验有新身份，原答卷及评价保留。超时和错误输出分别使用已有共享治理，持久化逻辑任务不超过3次请求。",
                  "", "这些隔离库在演示结束后标记 demo_only，真实服务拒绝打开；它们不在正式 data/v3 中。", "",
                  "逐项身份、轮次及逻辑任务次数见同目录 day11-demo.json。"])
    (destination / "Day11_六类流程演示.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_demo(args.output)
    print(json.dumps({key: result[key] for key in ("mode", "scenario_count", "all_checks_passed", "real_http_requests")}, ensure_ascii=False))
