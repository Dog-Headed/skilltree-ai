from uuid import uuid4
from pprint import pprint

from langgraph.types import Command

from app.graph import graph
from app.services.quiz_answers import display_option, normalize_choice_answer


def print_separator(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def show_result_info(result):
    # 有评分结果时显示
    if result.get("evaluation"):
        print_separator("本轮逐题评价")

        for item in result["evaluation"].get("question_results", []):
            print(f"\n题目：{item['question_id']}")
            print(f"得分：{item['score']}")
            print(f"错误标签：{item.get('error_tags', [])}")
            print(f"证据：{item.get('evidence', '')}")
            print(f"反馈：{item.get('feedback', '')}")

    if result.get("score_summary"):
        print_separator("本轮总分")
        pprint(result["score_summary"], sort_dicts=False)

    if result.get("diagnosis"):
        print_separator("Diagnosis")
        pprint(result["diagnosis"], sort_dicts=False)

    if result.get("lesson"):
        print_separator("Tutor 教学")
        print(result["lesson"])


def read_multiline_answer():
    print("\n请输入答案，多行答案请逐行输入。")
    print("最后单独输入一行 END 表示结束（单行答案也需要 END）：")

    lines = []

    while True:
        line = input()

        if line.strip() == "END":
            return "\n".join(lines)

        # 保留代码缩进和空行，只移除 input() 已消费的行结束符。
        lines.append(line)


def read_answers(public_quiz):
    answers = {}

    print_separator(
        f"测验 {public_quiz['assessment_id']}"
    )

    # 显式检查不能泄露答案
    quiz_text = str(public_quiz)

    assert "answer_key" not in quiz_text
    assert "rubric" not in quiz_text

    print("Public Quiz 检查通过：未包含 answer_key / rubric")

    for index, question in enumerate(
        public_quiz["questions"],
        start=1,
    ):
        print("\n" + "-" * 60)
        print(f"第 {index} 题")
        print("-" * 60)

        print(question["prompt"])

        options = question.get("options")

        if options:
            print("\n选项：")
            for option_index, option in enumerate(options):
                print(display_option(option_index, option))

        question_type = question["type"]

        if question_type == "multiple_choice":
            raw = input(
                "\n请输入答案，多个选项用英文逗号分隔："
            )

            answer = [
                normalize_choice_answer(item.strip(), options or [])
                for item in raw.split(",")
                if item.strip()
            ]

        elif question_type == "short_answer":
            answer = read_multiline_answer()

        else:
            answer = normalize_choice_answer(
                input("\n你的答案（选项字母或完整内容）：").strip(),
                options or [],
            )

        answers[question["id"]] = answer

    return answers


def run_interactive(graph, result, config, *, demo_name="Day 4", result_observer=None):
    config = {**config, "recursion_limit": 30}
    round_number = 0
    last_assessment_id = None


    while True:
        if result_observer is not None:
            result_observer(result)
        show_result_info(result)

        interrupts = result.get("__interrupt__", [])

        # ========================================================
        # Graph 已经跑完
        # ========================================================

        if not interrupts:
            print_separator("流程结束")

            print(
                "最终分支：",
                result.get("branch_result"),
            )

            if (
                result.get("branch_result", "")
                .startswith("advance")
            ):
                print(f"\n成功到达 advance，{demo_name} 闭环完成！")
            else:
                print("\n流程已结束，但没有到达 advance。")

            break

        interrupt_data = interrupts[0].value
        interrupt_type = interrupt_data["type"]

        # ========================================================
        # 等待学习阶段
        # ========================================================

        if interrupt_type == "wait_learning":
            print_separator("等待你的学习操作")

            print("1. 继续提问")
            revisiting = result.get("lesson_mode") == "revisit"
            print("2. 结束复习并开始当前节点测验" if revisiting else "2. 开始测验 / 开始复测")
            if revisiting:
                print("3. 结束复习，返回当前节点学习")
            allowed_choices = {"1", "2", "3"} if revisiting else {"1", "2"}
            choice_prompt = "请选择 1、2 或 3：" if revisiting else "请选择 1 或 2："

            while True:
                choice = input("\n" + choice_prompt).strip()

                if choice in allowed_choices:
                    break

                print("输入无效。" + choice_prompt)

            if choice == "1":
                question = input(
                    "\n你想问 Tutor 什么？"
                ).strip()

                result = graph.invoke(
                    Command(
                        resume={
                            "action": "ask",
                            "message": question,
                        }
                    ),
                    config=config,
                    durability="sync",
                )

            elif choice == "2":
                result = graph.invoke(
                    Command(
                        resume={
                            "action": "start_quiz"
                        }
                    ),
                    config=config,
                    durability="sync",
                )

            elif choice == "3":
                result = graph.invoke(
                    Command(resume={"action": "return_to_current"}),
                    config=config,
                    durability="sync",
                )

        # ========================================================
        # 等待答题阶段
        # ========================================================

        elif interrupt_type == "wait_answer":
            public_quiz = interrupt_data["quiz"]

            current_assessment_id = public_quiz[
                "assessment_id"
            ]

            if last_assessment_id is not None and current_assessment_id != last_assessment_id:
                print_separator("复测检查")

                print(
                    "上一轮 assessment_id：",
                    last_assessment_id,
                )

                print(
                    "本轮 assessment_id：",
                    current_assessment_id,
                )

                assert (
                    current_assessment_id
                    != last_assessment_id
                )

                print("assessment_id 已更新")

                # 新一轮刚开始时旧数据应清空
                print(
                    "当前 answers：",
                    result.get("answers"),
                )

                print(
                    "当前 evaluation：",
                    result.get("evaluation"),
                )

            if current_assessment_id != last_assessment_id:
                last_assessment_id = current_assessment_id
                round_number += 1

            print(interrupt_data["message"])

            print(
                f"\n这是第 {round_number} 轮测验。"
            )

            if round_number == 1:
                print(
                    "第一轮可以故意答错一些，"
                    "我们要验证 remediate。"
                )
            else:
                print(
                    "这一轮认真答，"
                    "看看能不能达到 advance。"
                )

            answers = read_answers(public_quiz)

            result = graph.invoke(
                Command(
                    resume={
                        "action": "submit_answer",
                        "answers": answers,
                    }
                ),
                config=config,
                durability="sync",
            )

        elif interrupt_type == "pause":
            print(interrupt_data["message"])
            choice = input("1. 休息（保存暂停并退出）  2. 再试 3 轮：").strip()
            if choice not in {"1", "2"}:
                continue
            result = graph.invoke(Command(resume={
                "action": "rest" if choice == "1" else "retry_3",
                "pending_input_id": interrupt_data["pending_input_id"],
            }), config=config, durability="sync")
            if choice == "1":
                print("已保持暂停，下次继续此项目时仍在这里等待。")
                break
        else:
            raise ValueError(f"未知 interrupt 类型：{interrupt_type}")

    return result, round_number, last_assessment_id


if __name__ == "__main__":
    from pathlib import Path
    from app.services.observability import configure_logging
    configure_logging(Path(__file__).resolve().parent / "data" / "day7_events.jsonl")
    print_separator("Day 4 真实学习闭环开始")
    goal = input("请输入学习目标（直接回车默认：学习 Python for 循环）：").strip()
    goal = goal or "学习 Python for 循环"
    project_id = f"day4-demo-{uuid4()}"
    config = {"configurable": {"thread_id": project_id}, "recursion_limit": 30}
    result = graph.invoke(
        {"project_id": project_id, "goal": goal, "lesson_mode": "normal"}, config=config,
        durability="sync",
    )
    result, round_number, last_assessment_id = run_interactive(graph, result, config)
