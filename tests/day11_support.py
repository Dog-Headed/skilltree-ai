"""Reusable offline Day 11 fixtures; real stores/bindings, explicitly Fake content.

No case labels or holdout data are loaded. There are no capability overrides.
The Fake model checks workflow contracts only, never real teaching quality.
"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage
from openai import APITimeoutError

from app.v3 import planner
from app.v3.context import ContextBuilder
from app.v3.contracts import EvaluationPolicy, FrozenSnapshot, LearningPlan, LearningProfile, SkillNode
from app.v3.materials import MaterialService
from app.v3.preparation import PreparationService
from app.v3.repository import BudgetExhaustedError, V3Repository
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage


ROOT = Path(__file__).resolve().parents[1]


def _payload(messages):
    text = messages[1].content
    return json.loads(text[text.index("{"):])


class FakeLearningModel:
    def __init__(self, *, grade_ratio=1.0, grading_status="graded", invalid_quiz=False, faults=None):
        self.grade_ratio = grade_ratio
        self.grading_status = grading_status
        self.invalid_quiz = invalid_quiz
        self.faults = defaultdict(deque, {key: deque(values) for key, values in (faults or {}).items()})
        self.calls = []
        self.node_specs = []
        self.numeric_problems = {}

    @property
    def call_counts(self):
        return Counter(item["schema"] for item in self.calls)

    def with_structured_output(self, schema, **kwargs):
        return _BoundFake(self, schema.__name__)

    def bind_tools(self, tools):
        return _BoundFake(self, "tool_selection")

    def _invoke(self, schema, messages):
        data = _payload(messages)
        self.calls.append({"schema": schema, "node_id": data.get("node_id", data.get("node", {}).get("node_id")),
                           "assessment_id": data.get("assessment_id")})
        if self.faults[schema]:
            fault = self.faults[schema].popleft()
            if fault == "timeout":
                raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid/fake"))
            if fault == "budget":
                raise BudgetExhaustedError("Explicit Fake operation-budget fault")
            if isinstance(fault, Exception):
                raise fault
            if fault is not None:
                return fault(messages) if callable(fault) else deepcopy(fault)
        if schema == "LearningPlan":
            return self._plan(data)
        if schema == "TutorReply":
            citations = [item for context in data["teaching_contexts"] for item in context["public_citations"]]
            unique = {(item["source_id"], item["source_version"], item["chunk_id"]): item for item in citations}
            quote = next((block["content"] for context in data["teaching_contexts"] for block in context["blocks"]), "这是标注清楚的文字探索。")
            return {"text": "Fake教学示例，仅验证状态与来源契约。\n" + quote[:700] + "\n请用自己的话解释本次目标。",
                    "citations": [{key: value[key] for key in ("source_id", "source_version", "chunk_id")} for value in unique.values()],
                    "exploration": data["exploration"]}
        if schema == "AssessmentQuiz":
            return self._quiz(data)
        if schema == "TextBatchScore":
            return self._grade(data)
        if schema == "DiagnosisDecision":
            valid = data["grading_status"] == "graded"
            passing = valid and all(item["score"] / item["max_score"] >= 0.8 for item in data["question_results"])
            return {"project_id": data["project_id"], "node_id": data["node_id"], "assessment_id": data["assessment_id"],
                    "snapshot": data["snapshot"], "action": "advance" if passing else "remediate" if valid else "collect_more_evidence",
                    "reason": "Fake诊断依据当前有限样例得分；仅证明流程，不证明模型内容质量。",
                    "evidence_ids": [item["evidence_id"] for item in data["current_evidence"]], "review_node_id": None}
        if schema == "tool_selection":
            return AIMessage(content="", tool_calls=[])
        raise ValueError("Unknown Fake schema: " + schema)

    def _plan(self, data):
        nodes = []
        kinds = {"choice_exact": "choice", "text_rubric": "text_excerpt", "numeric_scalar": "numeric_result"}
        for index, spec in enumerate(self.node_specs, 1):
            chunks = [item for item in data["teaching_material_catalog"] if item["heading"] and any(
                item["heading"].startswith(section + " ") for section in spec["sections"])]
            if len(chunks) != len(spec["sections"]):
                raise ValueError("Fixture material section unavailable")
            objectives = []
            for capability in data["profile"]["requested_capabilities"]:
                oid = f"objective_{index}_{capability}"
                outcome = spec["outcome"]
                if capability == "numeric_scalar":
                    outcome = "依据两边同样运算的规则计算并给出数值：" + self.numeric_problems[f"node_{index}"][0]
                objectives.append({"objective_id": oid, "observable_outcome": outcome,
                    "required_capability_ids": [capability], "evidence_requirement": [kinds[capability]],
                    "source_chunk_ids": [item["chunk_id"] for item in chunks],
                    "criterion_ids": ["criterion_" + oid] if capability == "text_rubric" else []})
            nodes.append({"node_id": f"node_{index}", "title": spec["outcome"], "description": "Fake计划契约演示：" + spec["outcome"],
                          "estimated_minutes": 15, "prerequisite_ids": [f"node_{index - 1}"] if index > 1 else [],
                          "objectives": objectives})
        return {"project_id": data["project_id"], "draft_revision": data["draft_revision"],
                "plan_version": data["plan_version"], "nodes": nodes}

    def _quiz(self, data):
        questions = []
        for index, objective in enumerate(data["node"]["objectives"], 1):
            context = data["contexts"][objective["objective_id"]]
            citation = {key: context["blocks"][0]["citation"][key] for key in ("source_id", "source_version", "chunk_id")}
            capability = objective["required_capability_ids"][0]
            q = {"question_id": f"q{index}", "objective_ids": [objective["objective_id"]],
                 "max_score": 100.0 / len(data["node"]["objectives"]), "evaluator_id": capability,
                 "evaluator_version": "1.0.0", "source_citations": [citation]}
            suffix = "；测验身份 " + data["assessment_id"]
            if capability == "numeric_scalar":
                prompt, expected = self.numeric_problems[data["node"]["node_id"]]
                q.update(question_type="numeric_scalar", prompt=prompt + "，仅填单个数值" + suffix,
                         numeric_rules={"expected": expected, "unit": None, "allowed_units": [], "abs_tolerance": 0.0, "rel_tolerance": 0.0})
            elif capability == "text_rubric":
                criteria = objective["criterion_ids"] or ["criterion_" + objective["objective_id"]]
                q.update(question_type="text", prompt="依据绑定资料说明：" + objective["observable_outcome"] + suffix,
                         answer_key="Fake参考说明：" + context["blocks"][0]["content"][:250],
                         rubric=[{"criterion_id": identity, "description": objective["observable_outcome"],
                                  "max_score": q["max_score"] / len(criteria)} for identity in criteria])
            else:
                q.update(question_type="single_choice", prompt="根据资料选择符合目标的解释：" + objective["observable_outcome"] + suffix,
                         options=[{"option_id": "A", "text": "符合当前资料的解释"}, {"option_id": "B", "text": "相反解释"}], answer_key="A")
            questions.append(q)
        output = {"project_id": data["project_id"], "node_id": data["node"]["node_id"], "assessment_id": data["assessment_id"],
                  "snapshot": data["snapshot"], "questions": questions, "previous_assessment_id": data["previous_assessment_id"]}
        if self.invalid_quiz:
            output["assessment_id"] = "fake_invalid_assessment_identity"
        return output

    def _grade(self, data):
        if self.grading_status != "graded":
            return {"project_id": data["project_id"], "node_id": data["node_id"], "assessment_id": data["assessment_id"],
                    "snapshot": data["snapshot"], "grading_status": self.grading_status, "questions": [],
                    "uncertainty_reasons": ["Fake不确定/无效题目场景，不能计为学生有效失败。"]}
        scored = []
        for question in data["questions"]:
            answer = data["answers"][question["question_id"]]
            scored.append({"question_id": question["question_id"], "max_score": question["max_score"], "criteria": [
                {"criterion_id": criterion["criterion_id"], "max_score": criterion["max_score"],
                 "score": criterion["max_score"] * self.grade_ratio,
                 "anchors": [{"quote": answer, "start": 0, "end": len(answer)}], "severity": None}
                for criterion in question["rubric"]], "feedback": "Fake量规分项结果，仅供流程验证。"})
        return {"project_id": data["project_id"], "node_id": data["node_id"], "assessment_id": data["assessment_id"],
                "snapshot": data["snapshot"], "grading_status": "graded", "questions": scored, "uncertainty_reasons": []}


class _BoundFake:
    def __init__(self, parent, schema):
        self.parent, self.schema = parent, schema

    def invoke(self, messages):
        return self.parent._invoke(self.schema, messages)


def preparation_command(service, view, action):
    return service.resume(view["project_id"], {"request_id": str(uuid4()), "action": action,
        "pending_input_id": view["pending_input_id"], "draft_revision": view["draft_revision"]})


def build_frozen_project(directory, subject="python", *, node_count=2, model=None):
    manifest_path = ROOT / "materials" / "v3" / subject / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = json.loads((ROOT / "docs" / "v3" / "day10_demo_plans.json").read_text(encoding="utf-8"))[subject]
    if not 1 <= node_count <= len(fixtures):
        raise ValueError("Fixture node_count outside available plan")
    model = model or FakeLearningModel()
    model.node_specs = fixtures[:node_count]
    model.numeric_problems = {"node_1": ("计算-3-2", -5.0), "node_2": ("求解x+5=12的x", 7.0),
                              "node_3": ("求解3x=12的x", 4.0), "node_4": ("求解2x+5=17的x", 6.0)}
    paths = initialize_storage(V3Paths(Path(directory).resolve()))
    service = PreparationService(paths)
    scope = [item["outcome"] for item in model.node_specs]
    profile = LearningProfile(subject_label=manifest["subject_label"], topic=manifest["topic"],
        goal="、".join(scope), bounded_goal="、".join(scope), scope_in=scope, scope_out=manifest["scope_out"],
        requested_capabilities=manifest["suggested_plan"]["full_goal_required_evaluators"])
    view = service.create(str(uuid4()), profile)
    pid = view["project_id"]
    with V3Repository(paths) as repo:
        material = MaterialService(repo)
        for document in manifest["documents"]:
            raw = (manifest_path.parent / document["filename"]).read_bytes()
            if sha256(raw).hexdigest() != document["content_hash"]:
                raise ValueError("Fixture material changed after freeze")
            material.import_upload(pid, request_id=uuid4(), data=raw, filename=document["filename"],
                source_id=document["source_id"], title=document["title"], visibility=document["visibility"],
                source_description="Fake流程使用真实绑定资料；资料内容与预期仍待用户复核。")
    with patch.object(planner, "get_llm", lambda: model):
        preview = preparation_command(service, service.read(pid), "confirm_profile")
        if preview["page_state"] != "plan_review":
            raise AssertionError(preview)
        frozen = preparation_command(service, preview, "confirm_plan")
    if not frozen["frozen"]:
        raise AssertionError(frozen)
    initialize_learning_storage(paths)
    with V3Repository(paths) as repo:
        project = repo.get_project(pid)
        plan = LearningPlan.model_validate(project["candidate_plan"])
        node = plan.nodes[0]
        builder = ContextBuilder(repo)
        contexts = {objective.objective_id: builder.for_assessment(pid, node.node_id, objective.objective_id) for objective in node.objectives}
    return {"paths": paths, "project_id": pid, "profile": profile, "plan": plan, "node": node,
            "snapshot": FrozenSnapshot.model_validate(project["frozen_snapshot"]),
            "policy": EvaluationPolicy.model_validate(project["policy"]), "model": model, "contexts": contexts}


def answers_for_quiz(quiz):
    quiz = quiz.model_dump() if hasattr(quiz, "model_dump") else quiz
    answers = {}
    for question in quiz["questions"]:
        if question["question_type"] == "numeric_scalar":
            answers[question["question_id"]] = str(question["numeric_rules"]["expected"])
        else:
            answers[question["question_id"]] = deepcopy(question["answer_key"])
    return answers


def learning_event(view, action, **payload):
    event = {"request_id": str(uuid4()), "pending_input_id": view["pending_input_id"],
             "draft_revision": view["draft_revision"], "action": action, **payload}
    if action in {"submit_answer", "annotate_dispute", "replace_assessment"}:
        event["assessment_id"] = view["assessment_id"]
    return event


def private_quiz(paths, project_id, assessment_id):
    from app.v3.learning_repository import LearningRepository
    with LearningRepository(paths) as repo:
        record = repo.get_assessment(project_id, assessment_id)
        return json.loads(record["quiz_json"])


def build_exploration_project(directory, *, model=None, direct_profile=False):
    paths = initialize_storage(V3Paths(Path(directory).resolve()))
    service = PreparationService(paths)
    model = model or FakeLearningModel()
    profile = LearningProfile(subject_label="开放探索主题", topic="文字讨论", goal="围绕一个新主题提出问题",
        bounded_goal="围绕一个新主题提出问题，不形成正式测评通过", requested_capabilities=["text_explanation"],
        learning_mode="exploration" if direct_profile else "formal")
    view = service.create(str(uuid4()), profile)
    view = preparation_command(service, view, "confirm_profile")
    if not direct_profile:
        view = preparation_command(service, view, "choose_exploration")
    if view["page_state"] != "exploring":
        raise AssertionError(view)
    initialize_learning_storage(paths)
    return {"paths": paths, "project_id": view["project_id"], "model": model}
