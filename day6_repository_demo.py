from pathlib import Path
from pprint import pprint

from app.db.repository import (
    LearningRepository,
)
import sqlite3

from pathlib import Path

from langgraph.checkpoint.sqlite import (
    SqliteSaver,
)

from app.graph import build_graph

PROJECT_ROOT = Path(
    __file__
).resolve().parent

DB_PATH = (
    PROJECT_ROOT
    / "data"
    / "learning.sqlite"
)


PROJECT_ID = "day6_demo_project"


tree = [
    {
        "id": "python_basics",
        "title": "Python 基础",
        "description": (
            "学习 Python 最基础语法。"
        ),
        "objectives": [
            {
                "id": "obj_basics_1",
                "description": (
                    "理解基本程序执行方式"
                ),
            }
        ],
        "prerequisite_ids": [],
        "difficulty": "beginner",
        "estimated_minutes": 30,
    },

    {
        "id": "python_variables",
        "title": "变量与赋值",
        "description": (
            "学习变量、类型和赋值。"
        ),
        "objectives": [
            {
                "id": "obj_variables_1",
                "description": (
                    "理解变量和赋值"
                ),
            },
            {
                "id": "obj_variables_2",
                "description": (
                    "区分 = 和 =="
                ),
            },
        ],
        "prerequisite_ids": [
            "python_basics"
        ],
        "difficulty": "beginner",
        "estimated_minutes": 40,
    },

    {
        "id": "python_for_loops",
        "title": "for 循环",
        "description": (
            "学习使用 for 遍历数据。"
        ),
        "objectives": [
            {
                "id": "obj_loop_1",
                "description": (
                    "能够使用 for 遍历列表"
                ),
            }
        ],
        "prerequisite_ids": [
            "python_variables"
        ],
        "difficulty": "beginner",
        "estimated_minutes": 45,
    },
]


print("=" * 70)
print("第一次连接：保存项目和 Skill Tree")
print("=" * 70)


with LearningRepository(
    DB_PATH
) as repo:

    existing = repo.get_project(
        PROJECT_ID
    )

    if existing is None:
        repo.create_project_with_tree(
            project_id=PROJECT_ID,
            goal="学习 Python 基础编程",
            tree=tree,
        )

        print(
            "✅ Project + Skill Tree 已保存"
        )

    else:
        print(
            "ℹ️ Project 已存在，跳过重复创建"
        )


print("\n✅ 第一个 SQLite 连接已经关闭")


print("\n" + "=" * 70)
print("重新建立一个 SQLite 连接")
print("=" * 70)


with LearningRepository(
    DB_PATH
) as repo:

    loaded_project = repo.get_project(
        PROJECT_ID
    )

    loaded_tree = repo.get_tree(
        PROJECT_ID
    )


print("\n重新读取的 Project：")

pprint(
    loaded_project,
    sort_dicts=False,
)


print("\n重新读取的 Skill Tree：")

pprint(
    loaded_tree,
    sort_dicts=False,
)


assert loaded_project is not None

assert (
    loaded_project["id"]
    == PROJECT_ID
)

assert (
    loaded_project["goal"]
    == "学习 Python 基础编程"
)

assert len(loaded_tree) == 3

assert (
    loaded_tree[1]["objectives"]
    == tree[1]["objectives"]
)

assert (
    loaded_tree[2][
        "prerequisite_ids"
    ]
    == ["python_variables"]
)


print(
    "\n🎉 Day 6 Step 1 验收通过"
)

print(
    "✅ 数据不是存在 Python 内存里"
)

print(
    "✅ 第一个连接关闭后仍然存在"
)

print(
    "✅ 新连接可以完整恢复 Project 和 Skill Tree"
)

print(
    "✅ JSON objectives / prerequisite_ids 正确还原"
)

checkpoint_conn = sqlite3.connect(
    CHECKPOINT_DB_PATH,
    check_same_thread=False,
)

checkpointer = SqliteSaver(
    checkpoint_conn
)

graph = build_graph(
    checkpointer=checkpointer
)