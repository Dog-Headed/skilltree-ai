from pathlib import Path

from app.db.repository import (
    LearningRepository,
)


DB_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "learning.sqlite"
)


ASSESSMENT_ID = (
    "assessment_idempotency_demo"
)


with LearningRepository(
    DB_PATH
) as repo:

    # 确保 demo project/node 已存在
    project = repo.get_project(
        "day6_demo_project"
    )

    assert project is not None

    # 第一次准备测验
    first = repo.create_prepared_assessment(
        assessment_id=ASSESSMENT_ID,
        project_id="day6_demo_project",
        node_id="python_variables",
        round_no=1,
    )

    print(
        "第一次 prepared：",
        first["status"],
    )


    fake_quiz = {
        "assessment_id": ASSESSMENT_ID,
        "node_id": "python_variables",
        "questions": [
            {
                "id": "q1",
                "prompt": "第一次固定的题目",
            }
        ],
    }


    saved = repo.save_quiz_if_absent(
        assessment_id=ASSESSMENT_ID,
        quiz=fake_quiz,
    )

    print(
        "第一次保存 Quiz：",
        saved["quiz"],
    )


print("\n💥 假装这里 Python 进程崩了")


# ============================================================
# 新连接模拟重启 / 重试
# ============================================================

with LearningRepository(
    DB_PATH
) as repo:

    second = (
        repo.create_prepared_assessment(
            assessment_id=ASSESSMENT_ID,
            project_id="day6_demo_project",
            node_id="python_variables",
            round_no=1,
        )
    )

    print(
        "\n重新读取 status：",
        second["status"],
    )

    assert (
        second["quiz"]
        == fake_quiz
    )


    # 假装模型又生成了另一张卷
    dangerous_new_quiz = {
        "assessment_id": ASSESSMENT_ID,
        "node_id": "python_variables",
        "questions": [
            {
                "id": "evil_q2",
                "prompt": "这张新题不应该覆盖旧题",
            }
        ],
    }


    result = repo.save_quiz_if_absent(
        assessment_id=ASSESSMENT_ID,
        quiz=dangerous_new_quiz,
    )


    # 必须依然是原题
    assert (
        result["quiz"]
        == fake_quiz
    )


print(
    "\n✅ 同一 assessment_id 重试后"
    "没有生成第二份业务事实"
)

print(
    "✅ 已固定 Quiz 不会被覆盖"
)