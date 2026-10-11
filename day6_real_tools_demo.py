"""直接查看三个工具从真实 learning.sqlite 查询到的结果，不调用模型。"""
import argparse
from pathlib import Path
from pprint import pprint

from app.db.repository import DEFAULT_DB_PATH
from app.tools.history import get_learning_history
from app.tools.knowledge import get_node_material, get_prerequisite_status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default="day6_demo_project")
    parser.add_argument("--node-id", default="python_variables")
    parser.add_argument("--exclude-assessment-id")
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args(argv)
    common = {"project_id": args.project_id, "node_id": args.node_id, "db_path": args.db_path}
    results = (
        ("真实学习历史", get_learning_history(
            **common, limit=3, exclude_assessment_id=args.exclude_assessment_id,
        )),
        ("真实前置状态", get_prerequisite_status(**common)),
        ("真实节点材料", get_node_material(**common)),
    )
    print(f"业务数据库：{args.db_path.resolve()}")
    print(f"项目：{args.project_id}；节点：{args.node_id}")
    for title, result in results:
        print("\n" + "=" * 70)
        print(title)
        print("=" * 70)
        pprint(result, sort_dicts=False)
    return 0 if all(result["ok"] for _, result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
