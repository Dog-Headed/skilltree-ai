"""Day 7 小样本诊断评价。默认 Fake，仅手动 --mode real 消耗模型用量。"""

import argparse
import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from langchain_core.messages import AIMessage
from app.agents import diagnosis
from app.db.repository import LearningRepository
from app.graph import route_after_diagnosis
from app.models.schemas import AssessmentEvaluation, AssessmentQuiz, validate_and_score_evaluation
from app.services.llm import ModelCallBudget, get_llm
from app.services.observability import configure_logging

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "data" / "evaluation" / "cases"


def load_cases(split="debug", case_dir=CASES):
    cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(Path(case_dir).glob("*.json"))]
    selected = [case for case in cases if case["split"] == split]
    if not selected:
        raise ValueError("没有找到指定分组的案例")
    return selected


def save_fixture_assessment(repo, state, record, round_no=1):
    quiz = AssessmentQuiz.model_validate(record["quiz"])
    evaluation = AssessmentEvaluation.model_validate(record["evaluation"])
    validate_and_score_evaluation(quiz, evaluation)
    assessment_id = record["assessment_id"]
    repo.create_prepared_assessment(assessment_id=assessment_id, project_id=state["project_id"],
                                    node_id=record["node_id"], round_no=round_no)
    repo.save_quiz_if_absent(assessment_id=assessment_id, quiz=quiz.model_dump())
    repo.save_answers_if_absent(assessment_id=assessment_id, answers=record["answers"])
    repo.save_evaluation_if_absent(assessment_id=assessment_id, evaluation=evaluation.model_dump())


def seed_case(case, db_path):
    """现有真实只读工具查询临时 SQLite，不读写用户学习记录。"""
    state = deepcopy(case["state"])
    state["learning_db_path"] = str(db_path)
    with LearningRepository(db_path) as repo:
        repo.create_project_with_tree(project_id=state["project_id"], goal=state["goal"], tree=state["tree"])
        for record in case["tool_context"]["completion_records"]:
            save_fixture_assessment(repo, state, record)
            repo.mark_node_completed(project_id=state["project_id"], node_id=record["node_id"], assessment_id=record["assessment_id"])
        for index, record in enumerate(case["tool_context"]["history"], start=2):
            save_fixture_assessment(repo, state, record, round_no=index)
        save_fixture_assessment(repo, state, {
            "assessment_id": state["assessment_id"], "node_id": state["current_node_id"],
            "quiz": state["quiz"], "answers": state["answers"], "evaluation": state["evaluation"],
        }, round_no=5)
    return state


class TrackingRunnable:
    def __init__(self, runnable, tracking, phase, structured=False):
        self.runnable, self.tracking, self.phase, self.structured = runnable, tracking, phase, structured

    def invoke(self, messages):
        record = {"phase": self.phase, "usage": None}
        self.tracking.append(record)
        output = self.runnable.invoke(messages)
        raw = output.get("raw") if self.structured else output
        if raw is not None:
            record["usage"] = (getattr(raw, "usage_metadata", None)
                               or getattr(raw, "response_metadata", {}).get("token_usage"))
        if self.structured:
            if output.get("parsing_error") is not None:
                raise output["parsing_error"]
            return output["parsed"]
        return output


class TrackingModel:
    def __init__(self, base):
        self.base = base
        self.requests = []

    def bind_tools(self, schemas):
        return TrackingRunnable(self.base.bind_tools(schemas), self.requests, "tool_selection")

    def with_structured_output(self, schema, *, method):
        return TrackingRunnable(self.base.with_structured_output(schema, method=method, include_raw=True),
                                self.requests, "final_diagnosis", structured=True)


class SmokeModel:
    """固定补弱建议且首次伪造证据；不从预期标签生成答案。"""
    def __init__(self, state):
        self.state = state
        self.requests = []
        self.tool_round = 0
        self.final_attempt = 0

    def bind_tools(self, schemas):
        return self

    def with_structured_output(self, schema, *, method):
        return SmokeFinal(self)

    def invoke(self, messages):
        self.requests.append({"phase": "tool_selection", "usage": None})
        self.tool_round += 1
        if self.tool_round == 1:
            return AIMessage(content="", tool_calls=[
                {"name": "get_learning_history", "args": {"node_id": self.state["current_node_id"], "limit": 3}, "id": "history"},
                {"name": "get_prerequisite_status", "args": {"node_id": self.state["current_node_id"]}, "id": "prerequisite"},
            ])
        return AIMessage(content="结束查询")


class SmokeFinal:
    def __init__(self, model):
        self.model = model

    def invoke(self, messages):
        model = self.model
        model.requests.append({"phase": "final_diagnosis", "usage": None})
        model.final_attempt += 1
        evidence_id = ("forged_smoke_evidence" if model.final_attempt == 1
                       else f"assessment:{model.state['assessment_id']}:q1")
        return {"weak_points": ["固定测试建议"], "evidence_ids": [evidence_id],
                "recommended_action": "remediate", "reason": "Fake 固定输出，仅验证评价管线。", "review_node_id": None}


def evaluate_case(case, mode="fake"):
    trace, tool_result, result = [], {}, None
    budget = ModelCallBudget()
    error_type = None
    with TemporaryDirectory(prefix="skilltree-evaluation-") as directory:
        state = seed_case(case, Path(directory) / "evaluation.sqlite")
        model = SmokeModel(state) if mode == "fake" else TrackingModel(get_llm())
        started = perf_counter()
        try:
            tool_result = diagnosis.run_diagnosis_tool_loop(state, llm=model)
            registry = diagnosis.build_diagnosis_evidence_registry(state, tool_result["tool_logs"])
            result = diagnosis.generate_final_diagnosis(
                state, evidence_registry=registry, llm=model, budget=budget, attempt_records=trace,
                tool_execution_summary=diagnosis.build_tool_execution_summary(tool_result),
            ).model_dump()
        except Exception as exc:
            # 不把服务异常正文或密钥写入报告。
            error_type = type(exc).__name__
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
    expectation = case["human_expectation"]
    approved = (expectation["review_status"] == "approved" and bool(expectation["reviewed_by"])
                and bool(expectation["reviewed_at"]))
    output_attempts = [r for r in trace if r["structure_valid"] is not None]
    route = route_after_diagnosis({**state, "diagnosis": result}) if result else "blocked"
    matches = bool(result and result["recommended_action"] in expectation["acceptable_actions"]
                   and (result["recommended_action"] != "revisit_prerequisite"
                        or result["review_node_id"] == expectation["expected_review_node_id"]))
    logs = [{"tool": log["tool_name"], "args": log["tool_args"], "executed": log["executed"],
             "ok": log["result"].get("ok"), "status": log["result"].get("status"),
             "error_type": log["result"].get("error_type")} for log in tool_result.get("tool_logs", [])]
    executed = {log["tool"] for log in logs if log["executed"]}
    required_queries = expectation.get("required_tool_queries", [])
    queries_used = all(any(log["executed"] and log["ok"]
                          and log["tool"] == query["tool"]
                          and log["args"].get("node_id") == query["node_id"]
                          for log in logs) for query in required_queries)
    return {
        "case_id": case["id"], "category": case["category"], "split": case["split"],
        "expectation_approved": approved, "expected_actions": expectation["acceptable_actions"],
        "expected_reason_pending_review": expectation["reason"], "diagnosis": result,
        "first_structure_valid": output_attempts[0]["structure_valid"] if output_attempts else None,
        "final_structure_valid": output_attempts[-1]["structure_valid"] if output_attempts else None,
        "accepted": result is not None, "attempts": trace, "action_match_provisional": matches,
        "guarded_route": route, "would_unlock": route == "advance",
        "false_release_provisional": bool(route == "advance" and expectation["must_not_advance"]),
        "evidence_within_expected_allowlist": bool(result and set(result["evidence_ids"]).issubset(expectation["allowed_evidence_ids"])),
        "tools_within_expected_allowlist": executed.issubset(expectation["allowed_tools"]),
        "required_tools_used": set(expectation["required_tools"]).issubset(executed),
        "required_tool_queries": required_queries, "required_tool_queries_used": queries_used,
        "tool_logs": logs, "tool_summary": diagnosis.build_tool_execution_summary(tool_result) if tool_result else None,
        "final_request_count": budget.request_count, "network_retry_count": budget.network_retry_count,
        "output_repair_count": budget.output_repair_count, "elapsed_ms": elapsed_ms,
        "requests_and_available_usage": model.requests, "error_type": error_type,
        "manual_review": {"reason_supported": None, "tool_choice_reasonable": None,
                          "evidence_reference_reasonable": None, "difference_analysis": "待用户逐例复核"},
    }


def rate(values):
    eligible = [value for value in values if value is not None]
    return {"numerator": sum(bool(value) for value in eligible), "denominator": len(eligible),
            "rate": sum(bool(value) for value in eligible) / len(eligible) if eligible else None}


def make_report(cases, mode, split):
    rows = [evaluate_case(case, mode) for case in cases]
    reviewed = [row for row in rows if row["expectation_approved"]]
    official = mode == "real" and len(reviewed) == len(rows)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "mode": mode, "split": split,
        "purpose": "real_model_evaluation" if mode == "real" else "infrastructure_smoke_only",
        "model": os.getenv("LLM_MODEL") if mode == "real" else "fixed_fake_no_api",
        "prompt_version": diagnosis.DIAGNOSIS_PROMPT_VERSION,
        "prompt_source_sha256": hashlib.sha256(Path(diagnosis.__file__).read_bytes()).hexdigest(),
        "case_versions": sorted({case["case_version"] for case in cases}),
        "cases_sha256": hashlib.sha256(json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
        "gold_standard_status": "user_reviewed" if official else "pending_or_fake_not_gold_standard",
        "metrics": {
            "first_structure_valid": rate([r["first_structure_valid"] for r in rows]),
            "final_structure_valid": rate([r["final_structure_valid"] for r in rows]),
            "repaired_structure_valid": rate([r["final_structure_valid"] for r in rows if r["output_repair_count"]]),
            "accepted": rate([r["accepted"] for r in rows]),
            "evidence_allowlist": rate([r["evidence_within_expected_allowlist"] for r in rows]),
            "tools_allowlist": rate([r["tools_within_expected_allowlist"] for r in rows]),
            "required_tools_used": rate([r["required_tools_used"] for r in rows]),
            "required_tool_queries_used": rate([r.get("required_tool_queries_used") for r in rows
                                                if r.get("required_tool_queries")]),
            "official_action_agreement": rate([r["action_match_provisional"] for r in rows]) if official else None,
            "provisional_action_agreement": rate([r["action_match_provisional"] for r in rows]),
            "official_false_release_count": sum(r["false_release_provisional"] for r in rows) if official else None,
            "provisional_false_release_count": sum(r["false_release_provisional"] for r in rows),
            "guard_scope": "纯路由推进守卫模拟；不实际解锁学生项目",
            "total_elapsed_ms": sum(r["elapsed_ms"] for r in rows),
            "available_usage_records": [u for r in rows for u in r["requests_and_available_usage"] if u["usage"] is not None],
            "usage_note": "未提供用量为 null；不估算为0，不以小样本宣称学习效果提升。",
        }, "cases": rows,
    }


def markdown_report(report):
    metric = report["metrics"]
    lines = ["# Day 7 诊断评价报告", "", f"模式：{report['mode']}；分组：{report['split']}；模型：{report['model']}",
             f"Prompt：{report['prompt_version']}；金标准状态：{report['gold_standard_status']}", "",
             ("Fake 报告只检查工具、校验、修复和报告流程。" if report["mode"] == "fake"
              else "真实模型结果；未由用户复核的预期仅用于暂定比较。"),
             "未由用户复核的预期不构成人工金标准。", "",
             f"首次结构合法率：{metric['first_structure_valid']}",
             f"最终结构合法率：{metric['final_structure_valid']}",
             f"修复案例结构合法率：{metric['repaired_structure_valid']}",
             f"正式行动一致率：{metric['official_action_agreement']}",
             f"草案预期一致率（暂定）：{metric['provisional_action_agreement']}",
             f"错误放行数（草案预期、推进守卫模拟）：{metric['provisional_false_release_count']}",
             f"指定节点的必要工具查询完成率：{metric.get('required_tool_queries_used')}",
             "", "| 案例 | 建议 | 守卫路由 | 首次/最终结构 | 输出修复 | 耗时ms |", "|---|---|---|---|---|---|"]
    for row in report["cases"]:
        lines.append(f"| {row['case_id']} | {(row['diagnosis'] or {}).get('recommended_action', row['error_type'])} | {row['guarded_route']} | {row['first_structure_valid']}/{row['final_structure_valid']} | {row['output_repair_count']} | {row['elapsed_ms']} |")
    lines += ["", "完整工具选择、证据引用、每次最终输出的结构/业务结果、请求数及可获得 usage 见同名 JSON。",
              "逐例人工复核：理由是否由答案支持、工具是否合理、证据是否足以支持行动、分歧及下一步修订。",
              "首次结构率按首次收到的模型输出计算（网络失败不构成输出）；最终结构率不等于业务通过率。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument("--split", choices=["debug", "holdout"], default="debug")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or ROOT / "data" / "evaluation" / "reports" / f"{args.mode}-{args.split}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    configure_logging(output.with_suffix(".events.jsonl"))
    report = make_report(load_cases(args.split), args.mode, args.split)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.with_suffix(".md").write_text(markdown_report(report), encoding="utf-8")
    print(f"报告已保存：{output}")
    print(f"模式={args.mode}, 案例={len(report['cases'])}, 状态={report['gold_standard_status']}")
    return int(any(row["error_type"] for row in report["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
