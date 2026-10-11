from pathlib import Path
from uuid import uuid4

from app.db.repository import (
    LearningRepository,
)


DB_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "learning.sqlite"
)


assessment_id = (
    f"assessment_2b_{uuid4().hex[:8]}"
)


answers = {
    "q1": "A",
    "q2": "B",
}


evaluation = {
    "assessment_id": assessment_id,
    "question_results": [],
}


diagnosis = {
    "weak_points": [
        "demo_weak_point"
    ],
    "evidence_ids": [
        "demo_evidence"
    ],
    "recommended_action": "advance",
    "reason": "Day 6 Demo",
    "review_node_id": None,
}


print("=" * 70)
print("创建本轮业务事实")
print("=" * 70)


with LearningRepository(
    DB_PATH
) as repo:

    repo.create_prepared_assessment(
        assessment_id=assessment_id,
        project_id="day6_demo_project",
        node_id="python_variables",
        round_no=1,
    )

    repo.save_quiz_if_absent(
        assessment_id=assessment_id,
        quiz={
            "assessment_id": assessment_id,
            "node_id": "python_variables",
            "questions": [],
        },
    )

    repo.save_answers_if_absent(
        assessment_id=assessment_id,
        answers=answers,
    )

    repo.save_evaluation_if_absent(
        assessment_id=assessment_id,
        evaluation=evaluation,
    )

    repo.save_diagnosis_if_absent(
        assessment_id=assessment_id,
        diagnosis=diagnosis,
    )

    first_completion = (
        repo.mark_node_completed(
            project_id="day6_demo_project",
            node_id="python_variables",
            assessment_id=assessment_id,
        )
    )


print("\n💥 假装整个 Python 进程崩了")


print("\n" + "=" * 70)
print("重新建立连接，重复执行")
print("=" * 70)


with LearningRepository(
    DB_PATH
) as repo:

    restored = repo.get_assessment(
        assessment_id
    )

    assert restored is not None

    assert (
        restored["answers"]
        == answers
    )

    assert (
        restored["evaluation"]
        == evaluation
    )

    assert (
        restored["diagnosis"]
        == diagnosis
    )

    second_completion = (
        repo.mark_node_completed(
            project_id="day6_demo_project",
            node_id="python_variables",
            assessment_id=assessment_id,
        )
    )


assert (
    first_completion[
        "completed_at"
    ]
    == second_completion[
        "completed_at"
    ]
)

assert (
    first_completion[
        "completion_assessment_id"
    ]
    == second_completion[
        "completion_assessment_id"
    ]
)


print("✅ Answers 成功恢复")
print("✅ Evaluation 成功恢复")
print("✅ Diagnosis 成功恢复")
print("✅ Completion 重复执行没有产生第二条")
print("✅ 原 completed_at 没有被覆盖")

print("\n🎉 Day 6 Step 2B Repository 验收通过")