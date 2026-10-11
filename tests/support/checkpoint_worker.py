"""跨进程测试：只替换模型和故障点，实际执行 Graph、SQLite Saver 和 Repository。"""

import json
import os
import sys
import time
from threading import Event
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import app.agents.assessment as assessment
import app.agents.diagnosis as diagnosis
import app.agents.planner as planner
import app.agents.tutor as tutor
from app.db.repository import LearningRepository
from app.models.schemas import AssessmentQuiz, DiagnosisResult, ShortAnswerGrade, TreePlan
from app.services.learning_session import open_learning_session
from langgraph.checkpoint.sqlite import SqliteSaver


phase, directory, project_id, boundary = sys.argv[1:]
directory = Path(directory)
business_path = directory / "learning.sqlite"
checkpoint_path = directory / "checkpoints.sqlite"
immediate_crash = phase in {"begin_immediate_crash", "interactive_immediate_crash", "async_immediate_crash"}
prepare_checkpoint_started = Event()
prepare_checkpoint_committed = Event()
prepare_writes_started = Event()


if immediate_crash:
    original_put = SqliteSaver.put

    def delayed_prepare_checkpoint(self, config, checkpoint, metadata, new_versions):
        values = checkpoint["channel_values"]
        preparing = bool(values.get("assessment_id") and not values.get("quiz"))
        if preparing:
            prepare_checkpoint_started.set()
            time.sleep(0.75)
        result = original_put(self, config, checkpoint, metadata, new_versions)
        if preparing:
            prepare_checkpoint_committed.set()
        return result

    SqliteSaver.put = delayed_prepare_checkpoint
    original_put_writes = SqliteSaver.put_writes

    def delayed_prepare_writes(self, config, writes, task_id, task_path=""):
        # ID 也会进入增量写入；只延迟完整 Checkpoint 仍可能通过它恢复 ID。
        if any(channel == "assessment_id" and value for channel, value in writes):
            prepare_writes_started.set()
            time.sleep(0.75)
        return original_put_writes(self, config, writes, task_id, task_path)

    SqliteSaver.put_writes = delayed_prepare_writes
    original_save_quiz = LearningRepository.save_quiz_if_absent

    def commit_quiz_then_exit(self, **kwargs):
        result = original_save_quiz(self, **kwargs)
        # 这里直接终止整个进程，不抛异常，不等图返回，不执行连接清理。
        print(json.dumps({
            "assessment_id": result["id"], "crash_point": "quiz_business_commit",
            "prepare_checkpoint_started": prepare_checkpoint_started.is_set(),
            "prepare_checkpoint_committed": prepare_checkpoint_committed.is_set(),
        }), flush=True)
        os._exit(3)

    LearningRepository.save_quiz_if_absent = commit_quiz_then_exit


def record_call(name):
    with (directory / "model_calls.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"phase": phase, "name": name}) + "\n")


def forbidden(*args, **kwargs):
    raise AssertionError("恢复执行不得重复调用已完成的模型步骤")


def fake_plan(goal):
    record_call("planner")
    return TreePlan.model_validate({"nodes": [{
        "id": f"node_{index}", "title": f"知识点 {index}",
        "description": "变量与赋值", "difficulty": "beginner", "estimated_minutes": 20,
        "objectives": [{"id": f"objective_{index}", "description": "理解赋值"}],
        "prerequisite_ids": [] if index == 0 else [f"node_{index - 1}"],
    } for index in range(8)]})


def fake_tutor(state, node):
    record_call("tutor")
    return "变量通过等号赋值。"


def fake_quiz(node, assessment_id, *, retest_context=None):
    if immediate_crash:
        # 确认延迟窗口已打开；async 对照不能靠线程调度侥幸避开窗口。
        assert prepare_checkpoint_started.wait(timeout=5)
        assert prepare_writes_started.wait(timeout=5)
    record_call("quiz")
    # 异步负控恢复丢失的 ID 时模拟一张新卷，继续验证业务记录重复问题。
    # 其余恢复路径必须复用原卷，不会执行这个生成函数。
    round_number = len((retest_context or {}).get("previous_questions", [])) // 2 + 1
    return AssessmentQuiz.model_validate({
        "assessment_id": assessment_id, "node_id": node.id,
        "questions": [
            {"id": "q1", "type": "single_choice", "objective_id": node.objectives[0].id,
             "prompt": f"哪一项表示赋值？（第 {round_number} 轮）", "options": ["x = 3", "x == 3"],
             "answer_key": "x = 3", "rubric": "选择赋值语句。", "max_score": 50.0},
            {"id": "q2", "type": "short_answer", "objective_id": node.objectives[0].id,
             "prompt": f"说明赋值符号的作用。（第 {round_number} 轮）", "options": None,
             "answer_key": "变量通过 = 赋值。", "rubric": "正确说明赋值。", "max_score": 50.0},
        ],
    })


def fake_grade(question, answer):
    record_call("grade")
    return ShortAnswerGrade(score=question["max_score"], error_tags=[], evidence=answer, feedback="正确")


def fake_diagnosis(state, **kwargs):
    record_call("diagnosis")
    return DiagnosisResult(
        weak_points=[], evidence_ids=[f"assessment:{state['assessment_id']}:q1"],
        recommended_action="advance", reason="测验满分，满足通过条件。", review_node_id=None,
    )


# 不允许意外访问任何真实模型服务。
for module in (planner, tutor, assessment, diagnosis):
    module.get_llm = forbidden
planner.generate_plan = fake_plan if phase in {"begin", "begin_crash", "begin_learning"} or immediate_crash else forbidden
tutor.generate_tutor_content = fake_tutor if phase in {
    "begin", "begin_crash", "begin_learning", "ask", "submit", "submit_crash", "retry"
} or immediate_crash else forbidden
assessment.generate_quiz = fake_quiz if phase in {"begin", "begin_crash", "retry_async_control"} or immediate_crash else forbidden
assessment.grade_short_answer = fake_grade if phase in {"submit", "submit_crash"} else forbidden
diagnosis.run_real_diagnosis = (
    fake_diagnosis if phase in {"submit", "submit_crash"} or (phase == "retry" and boundary == "evaluation")
    else forbidden
)


if phase in {"begin_crash", "submit_crash"}:
    method_name = {
        "plan": "create_project_with_tree",
        "quiz": "save_quiz_if_absent", "evaluation": "save_evaluation_if_absent",
        "diagnosis": "save_diagnosis_if_absent", "completion": "mark_node_completed",
    }[boundary]
    original_save = getattr(LearningRepository, method_name)

    def save_then_fail(self, **kwargs):
        original_save(self, **kwargs)
        raise RuntimeError("模拟业务提交后、Checkpoint 更新前中断")

    setattr(LearningRepository, method_name, save_then_fail)


with open_learning_session(
    project_id, checkpoint_db_path=checkpoint_path, learning_db_path=business_path
) as session:
    if phase == "async_immediate_crash":
        # 仅测试旧版行为的对照；生产入口仍显式要求 sync。
        original_invoke = session.graph.invoke
        def use_async(*args, **kwargs):
            return original_invoke(*args, **{**kwargs, "durability": "async"})
        session.graph.invoke = use_async
    try:
        if immediate_crash:
            result = session.start("学习变量")
            if phase == "interactive_immediate_crash":
                import builtins
                from day4_demo import run_interactive
                builtins.input = lambda prompt="": "2"
                run_interactive(session.graph, result, session.config, demo_name="Day 6")
            else:
                session.resume({"action": "start_quiz"})
            raise AssertionError("业务提交后必须立即终止进程")
        elif phase in {"begin", "begin_crash"}:
            session.start("学习变量")
            session.resume({"action": "start_quiz"})
        elif phase == "begin_learning":
            session.start("学习变量")
        elif phase == "ask":
            session.resume({"action": "ask", "message": "再解释一下刚才的例子"})
        elif phase in {"submit", "submit_crash"}:
            result = session.restore()
            session.resume({
                "action": "submit_answer",
                "answers": {question["id"]: question["answer_key"] for question in result["quiz"]["questions"]},
            })
        elif phase in {"retry", "retry_async_control"}:
            session.restore()
            session.retry()
        elif phase == "inspect":
            session.restore()
        else:
            raise ValueError(phase)
        exit_code = 0
    except RuntimeError as exc:
        assert "Checkpoint 更新前" in str(exc)
        exit_code = 2

    snapshot = session.snapshot()
    with LearningRepository(business_path) as repo:
        saved_id = snapshot.values.get("assessment_id") or snapshot.values.get("last_assessment_id")
        stored_assessment = repo.get_assessment(saved_id) if saved_id else None
        saved_node = snapshot.values.get("last_completed_node_id") or snapshot.values.get("current_node_id")
        progress = repo.get_progress(project_id=project_id, node_id=saved_node)
    print(json.dumps({
        "project_id": snapshot.values["project_id"], "thread_id": session.config["configurable"]["thread_id"],
        "next": snapshot.next, "interrupts": [item.value for item in snapshot.interrupts],
        "state": snapshot.values, "assessment": stored_assessment, "progress": progress,
    }, ensure_ascii=False, default=str), flush=True)
    # 真正终止进程，跳过上下文退出，验证数据库写入已提交而非仅保留在对象中。
    os._exit(exit_code)
