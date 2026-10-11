import argparse

from app.graph import CHECKPOINT_DB_PATH
from app.services.learning_session import open_learning_session


def main():
    parser = argparse.ArgumentParser(description="检查指定项目的 SQLite 执行存档，不调用模型。")
    parser.add_argument("--project-id", default="day6_restore_demo")
    args = parser.parse_args()
    with open_learning_session(args.project_id) as session:
        snapshot = session.snapshot()
        print("Checkpoint 数据库：", CHECKPOINT_DB_PATH)
        print("project_id / thread_id：", args.project_id)
        print("是否已有 State：", bool(snapshot.values))
        print("下一步 Node：", snapshot.next)
        print("当前节点：", snapshot.values.get("current_node_id"))
        print("当前测验：", snapshot.values.get("assessment_id"))


if __name__ == "__main__":
    main()
