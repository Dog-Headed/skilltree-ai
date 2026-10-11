"""Day 6 总演示：新建项目、恢复等待点、查看持久化评分。"""
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4

from app.agents.assessment import build_public_quiz
from app.db import repository
from app.graph import CHECKPOINT_DB_PATH
from app.services.learning_session import open_learning_session
from day4_demo import print_separator, run_interactive, show_result_info


def choose_project(learning_db_path):
    print_separator("SkillTree Day 6 持久化演示")
    print("1. 新建项目")
    print("2. 继续已有项目")
    while True:
        choice = input("\n请选择 1 或 2：").strip()
        if choice in {"1", "2"}:
            break
        print("请输入 1 或 2。")
    if choice == "1":
        goal = input("请输入学习目标（回车默认：学习 Python for 循环）：").strip()
        return f"project_{uuid4().hex[:12]}", goal or "学习 Python for 循环", False
    with repository.LearningRepository(learning_db_path) as repo:
        projects = repo.list_projects()
    if not projects:
        print("目前没有已有项目。")
        return None
    print("\n已有项目：")
    for index, project in enumerate(projects, 1):
        print(f"{index}. {project['id']} | {project['goal']}")
    while True:
        selected = input("\n请输入项目序号：").strip()
        if selected.isdecimal() and 1 <= int(selected) <= len(projects):
            return projects[int(selected) - 1]["id"], None, True
        print(f"请输入 1 到 {len(projects)} 之间的序号。")


def show_checkpoint(session, *, details=False):
    snapshot = session.snapshot()
    print("Checkpoint 数据库：", session.checkpoint_db_path)
    print("业务数据库：", session.learning_db_path)
    print("project_id / thread_id：", session.project_id)
    print("已有 State：", bool(snapshot.values))
    print("当前节点：", snapshot.values.get("current_node_id"))
    print("恢复 assessment_id：", snapshot.values.get("assessment_id"))
    print("上一张通过的测验：", snapshot.values.get("last_assessment_id"))
    print("下一步 Node：", snapshot.next)
    quiz = snapshot.values.get("quiz")
    if quiz:
        public_quiz = build_public_quiz(quiz)
        print("恢复第 1 题：", public_quiz["questions"][0]["prompt"])
        if details:
            print("恢复题面：", json.dumps(public_quiz, ensure_ascii=False, indent=2))
    if details and snapshot.values.get("lesson"):
        print("恢复教学内容：", snapshot.values["lesson"])
        print("恢复教学对话条数：", len(snapshot.values.get("tutor_messages", [])))
    return snapshot


def show_saved_assessment(session, assessment_id):
    with repository.LearningRepository(session.learning_db_path) as repo:
        assessment = repo.get_assessment(assessment_id)
        if assessment is None or assessment["project_id"] != session.project_id:
            raise ValueError("当前项目中不存在该测验，不能查看其他项目的记录。")
        progress = repo.get_progress(project_id=session.project_id, node_id=assessment["node_id"])
    print_separator("业务库中的测验记录")
    print("assessment_id：", assessment["id"])
    print("考核节点：", assessment["node_id"])
    print("状态：", assessment["status"])
    if assessment["quiz"]:
        print("原题面：", json.dumps(build_public_quiz(assessment["quiz"]), ensure_ascii=False, indent=2))
    print("已保存答案：", json.dumps(assessment["answers"], ensure_ascii=False))
    show_result_info({"evaluation": assessment["evaluation"], "diagnosis": assessment["diagnosis"]})
    print("节点完成记录：", json.dumps(progress, ensure_ascii=False))
    return assessment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", help="同一个项目始终使用同一个 ID；不带参数时进入项目菜单")
    parser.add_argument("--goal", help="仅新项目需要的学习目标")
    parser.add_argument("--inspect", action="store_true", help="只查看存档，不调用模型")
    parser.add_argument("--assessment-id", help="与 --inspect 一起查看旧轮次的业务记录")
    pause = parser.add_mutually_exclusive_group()
    pause.add_argument("--pause-at-quiz", action="store_true", help="到达答题等待点后退出")
    pause.add_argument("--pause-at-learning", action="store_true", help="到达教学等待点后退出")
    parser.add_argument("--retry", action="store_true", help="继续失败节点，不重复提交用户输入")
    parser.add_argument("--learning-db", type=Path, help="业务数据库，默认项目 data/learning.sqlite")
    parser.add_argument("--checkpoint-db", type=Path, default=CHECKPOINT_DB_PATH)
    args = parser.parse_args(argv)
    if args.assessment_id and not args.inspect:
        parser.error("--assessment-id 需要与 --inspect 一起使用")
    business_path = (args.learning_db or repository.DEFAULT_DB_PATH).resolve()
    project_id = args.project_id
    goal = args.goal
    continue_existing = False
    try:
        if not project_id:
            if args.inspect or args.retry or args.goal or args.pause_at_quiz or args.pause_at_learning:
                # 保留 Step 3 的无菜单命令，便于脚本验收。
                project_id = "day6_restore_demo"
            else:
                selected = choose_project(business_path)
                if selected is None:
                    return 0
                project_id, goal, continue_existing = selected

        with open_learning_session(
            project_id, checkpoint_db_path=args.checkpoint_db, learning_db_path=business_path,
        ) as session:
            print_separator("Day 6 SQLite 重启恢复演示")
            snapshot = show_checkpoint(session, details=args.inspect)
            try:
                if args.inspect:
                    # get_state 不会启动图；restore 只核验线程与数据库身份。
                    result = session.restore()
                    saved_id = args.assessment_id or result.get("last_assessment_id")
                    if saved_id:
                        show_saved_assessment(session, saved_id)
                    return 0
                if not snapshot.values:
                    if continue_existing:
                        raise ValueError("业务项目存在，但找不到对应 Checkpoint；请恢复原存档，不能重新初始化旧项目。")
                    if args.retry:
                        raise ValueError("新项目没有失败节点可重试。")
                    print("新项目：", project_id)
                    goal = goal or input("请输入学习目标（回车默认：学习 Python for 循环）：").strip()
                    result = session.start(goal or "学习 Python for 循环")
                else:
                    print("成功恢复原执行现场。")
                    result = session.restore()
                    if snapshot.next and not snapshot.interrupts:
                        if not args.retry:
                            print("上次执行尚未完成；请使用相同项目 ID 加 --retry 从失败节点继续。")
                            return 0
                        result = session.retry()
                    elif args.retry:
                        raise ValueError("当前没有失败执行可重试；等待输入的项目请正常启动后继续回答。")

                if args.pause_at_learning:
                    show_checkpoint(session, details=True)
                    if session.snapshot().next != ("wait_learning",):
                        raise ValueError("项目当前不在教学等待点，请使用同一项目 ID 正常继续。")
                    print("已停在 wait_learning；退出后选择继续此项目即可。")
                    return 0
                if args.pause_at_quiz:
                    interrupts = result.get("__interrupt__", ())
                    if interrupts and interrupts[0].value["type"] == "wait_learning":
                        result = session.resume({"action": "start_quiz"})
                    show_checkpoint(session, details=True)
                    if session.snapshot().next != ("wait_answer",):
                        raise ValueError("项目当前不在答题等待点。")
                    print("已停在 wait_answer；退出后用同一个项目 ID 继续原试卷。")
                    return 0

                shown_id = None
                def show_completed_round(current):
                    nonlocal shown_id
                    saved_id = current.get("last_assessment_id")
                    if saved_id and saved_id != shown_id:
                        show_saved_assessment(session, saved_id)
                        shown_id = saved_id

                run_interactive(
                    session.graph, result, session.config, demo_name="Day 6",
                    result_observer=show_completed_round,
                )
                return 0
            except (EOFError, KeyboardInterrupt):
                print("\n已退出。存档已保存，下次在菜单选择继续已有项目，或带相同 --project-id 启动。")
                return 0
            except Exception as exc:
                print(f"\n执行失败：{type(exc).__name__}: {exc}")
                snapshot = session.snapshot()
                print("下一步 Node：", snapshot.next)
                if snapshot.next and not snapshot.interrupts:
                    print("下次使用相同项目 ID 加 --retry 重试，不需要再次提交答案。")
                elif snapshot.interrupts:
                    print("项目正在等待输入，正常启动后继续回答。")
                return 1
    except (EOFError, KeyboardInterrupt):
        print("\n已退出项目选择。")
        return 0


if __name__ == "__main__":
    from app.services.observability import configure_logging
    configure_logging(Path(__file__).resolve().parent / "data" / "day7_events.jsonl")
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
