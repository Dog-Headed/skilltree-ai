"""仅供明确标记的 Fake 浏览器验收；生产入口 app.main 不导入此文件。

python -m tests.support.day8_browser_server
使用 work/day8/fake 中独立数据库，不接触用户数据库或真实模型。
"""

from pathlib import Path

import uvicorn
from app.models.schemas import AssessmentQuiz, DiagnosisResult, ShortAnswerGrade
from tests.conftest import make_fake_plan
import app.agents.planner as planner
import app.agents.tutor as tutor
import app.agents.assessment as assessment
import app.agents.diagnosis as diagnosis
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2] / "work" / "day8" / "fake"
FAILED_ONCE = set()


def fake_tutor(state, node):
    if "[失败]" in state["goal"] and state["project_id"] not in FAILED_ONCE:
        FAILED_ONCE.add(state["project_id"])
        raise TimeoutError("Fake 故障验收")
    if "[XSS]" in state["goal"]:
        return "## 不可信内容验收\n\n<img src=x onerror=alert(1)>\n\n<script>alert(1)</script>\n\n[危险链接](javascript:alert(1))\n\n**这些内容应该作为普通文字显示。**"
    if state.get("user_event", {}).get("action") == "ask":
        return "## 换个角度理解\n\n变量像一个有名字的标签，**赋值**让名字与一个值关联。标签可以重新指向新的值。\n\n```python\nscore = 10\nscore = score + 5\nprint(score)  # 15\n```\n\n每次赋值都重新绑定名字。你可以先写出每一步的值，再检查最后输出。"
    return f"""## 从一个名字，理解{node['title']}

在 Python 中，你不需要为每个值记住一个存储位置。**变量**让我们用一个有意义的名字，表示程序正在使用的数据。

想象你正在记录一周的学习时间：你会为每天的数据贴上标签，而不是直接记住所有数字。程序里的变量，也扮演着这样的角色。

### 01 / 让数据有一个名字

用 `=` 把右侧的值赋给左侧的变量。Python 会根据值识别类型，不需要预先声明。

```python
# 记录你的学习计划
learner = "Python 初学者"
daily_minutes = 30
is_ready = True

print(learner)
print(daily_minutes)  # 30
```

这里的 `learner` 是字符串，`daily_minutes` 是整数，`is_ready` 是布尔值。名字让代码能够表达意图，而不只是处理数字。

### 02 / 值可以改变，名字继续使用

程序从上到下执行。你可以让一个变量接收新值，也可以通过已有的值计算下一步。

```python
minutes = 20
minutes = minutes + 10
print(minutes)  # 30
```

> 记住：`=` 表示赋值，`==` 才表示比较。先计算右侧，再把结果赋给左侧。

### 03 / 试着在脑海中运行

- 为一项日常活动起一个清楚的变量名。
- 给它一个初始值，再更新一次。
- 解释最后打印的结果，以及每一步为什么得到这个值。

这只是一个不计分的思考练习。准备好了，再用测验检验你的理解。
"""


def fake_quiz(node, assessment_id, *, retest_context=None):
    suffix = assessment_id[-6:]
    specs = [
        ("single_choice", "哪一个符号用于给 Python 变量赋值？", ["=", "==", "!=", "<= "], "=", "赋值符号"),
        ("multiple_choice", "以下哪些是合理的 Python 变量名？（可多选）", ["daily_minutes", "total_score", "2days", "for"], ["daily_minutes", "total_score"], "变量命名"),
        ("short_answer", "解释以下程序最后会输出什么，说明你的思路。\n\n```python\nminutes = 20\nminutes = minutes + 10\nprint(minutes)\n```", None, "30", "输出与过程"),
        ("short_answer", "写两行 Python 代码：定义变量 name 并赋值为你的名字，然后打印它。", None, "name = '学习者'\nprint(name)", "定义与打印"),
    ]
    return AssessmentQuiz.model_validate({"assessment_id": assessment_id, "node_id": node.id, "questions": [
        {"id": f"q{i+1}", "type": kind, "objective_id": node.objectives[0].id,
         "prompt": f"{prompt}\n\n练习版本 {suffix}", "options": options, "answer_key": answer,
         "rubric": rubric, "max_score": 25.0} for i, (kind, prompt, options, answer, rubric) in enumerate(specs)
    ]})


def fake_grade(question, answer):
    correct = "不知道" not in answer
    return ShortAnswerGrade(score=question["max_score"] if correct else 5.0,
        error_tags=[] if correct else ["needs_practice"], evidence="Fake 验收：按预设答案模式检查输入。",
        feedback="思路清楚，继续保持练习。" if correct else "再检查赋值的执行顺序，先计算右侧表达式。")


def fake_diagnosis(state, **kwargs):
    action = "advance" if state["score_summary"]["percentage"] >= 80 else "remediate"
    if "[追加]" in state["goal"]:
        action = "collect_more_evidence"
    if "[前置]" in state["goal"] and state["current_node_id"] != "variables":
        action = "revisit_prerequisite"
    return DiagnosisResult(weak_points=[] if action == "advance" else ["变量赋值的执行顺序"],
        evidence_ids=["fake_browser"], recommended_action=action,
        reason="Fake 验收：本轮学习目标已覆盖，可以继续下一节点。" if action == "advance" else "Fake 验收：建议用一个新例子巩固赋值顺序，再进行练习。",
        review_node_id="variables" if action == "revisit_prerequisite" else None)


planner.generate_plan = lambda goal: make_fake_plan()
tutor.generate_tutor_content = fake_tutor
assessment.generate_quiz = fake_quiz
assessment.grade_short_answer = fake_grade
diagnosis.run_real_diagnosis = fake_diagnosis
app = create_app(learning_db_path=ROOT / "learning.sqlite", checkpoint_db_path=ROOT / "checkpoints.sqlite")

if __name__ == "__main__":
    print("Fake 浏览器验收，独立数据库；不调用真实模型。")
    uvicorn.run(app, host="127.0.0.1", port=8766, workers=1)
