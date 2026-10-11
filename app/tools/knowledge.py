from copy import deepcopy
from pathlib import Path
from typing import Any

from app.db import repository
from app.db.repository import LearningRepository


# 人工登记的短材料；模型不能指定任意文件路径。
_LOCAL_MATERIALS = {
    "python_basics": {
        "material_id": "material_python_basics_v1",
        "title": "Python 基础与程序运行",
        "content": "Python 脚本保存在 .py 文件中，使用 python 文件名.py 运行。"
                   "print() 输出结果；缩进决定代码块，注释以 # 开头。",
        "objectives": ["运行 Python 脚本", "区分代码、输出和注释", "理解缩进"],
    },
    "python_variables": {
        "material_id": "material_python_variables_v1",
        "title": "Python 变量与赋值",
        "content": "= 将右侧表达式求值后绑定到左侧变量；== 比较两个值。"
                   "再次赋值会改变变量当前绑定的值。print(x) 输出 x 当前的值。"
                   "例如 x = 2; x = x + 3 后，x 的值为 5。",
        "objectives": ["理解变量与赋值", "区分赋值和比较", "跟踪变量值与输出"],
    },
    "python_for_loops": {
        "material_id": "material_python_for_loops_v1",
        "title": "Python for 循环",
        "content": "for 逐个访问可迭代对象。range(n) 产生从 0 到 n-1 的整数。"
                   "累加变量应在循环前初始化，在循环体内使用 total += value 更新；"
                   "在循环体中重新赋值为 0 会丢失前面累积的结果。",
        "objectives": ["理解 for 与 range", "正确初始化和更新累加器", "追踪每轮执行"],
    },
}


def get_prerequisite_status(
    *, project_id: str, node_id: str, db_path: str | Path | None = None,
) -> dict[str, Any]:
    base = {"tool": "get_prerequisite_status", "node_id": node_id}
    try:
        with LearningRepository(db_path or repository.DEFAULT_DB_PATH) as repo:
            node = repo.get_node(project_id=project_id, node_id=node_id)
            if node is None:
                return {**base, "ok": False, "status": "node_not_found",
                        "error_type": "node_not_found", "error": "当前项目中不存在该节点"}
            prerequisites = []
            for prerequisite_id in node["prerequisite_ids"]:
                if repo.get_node(project_id=project_id, node_id=prerequisite_id) is None:
                    raise ValueError(f"项目的前置节点不存在：{prerequisite_id}")
                progress = repo.get_progress(project_id=project_id, node_id=prerequisite_id)
                prerequisites.append({
                    "node_id": prerequisite_id,
                    "completed": bool(progress and progress["completed_at"]),
                    "completed_at": progress["completed_at"] if progress else None,
                    "completion_assessment_id": progress["completion_assessment_id"] if progress else None,
                })
    except Exception as exc:
        return {**base, "ok": False, "status": "query_error",
                "error_type": "query_error", "error": f"前置状态查询失败：{exc}"}
    return {**base, "ok": True, "status": "found", "prerequisites": prerequisites,
            "all_completed": all(item["completed"] for item in prerequisites)}


def get_node_material(
    *, project_id: str, node_id: str, db_path: str | Path | None = None,
) -> dict[str, Any]:
    base = {"tool": "get_node_material", "node_id": node_id}
    try:
        with LearningRepository(db_path or repository.DEFAULT_DB_PATH) as repo:
            if repo.get_node(project_id=project_id, node_id=node_id) is None:
                return {**base, "ok": False, "status": "node_not_found", "material": None,
                        "error_type": "node_not_found", "error": "当前项目中不存在该节点"}
    except Exception as exc:
        return {**base, "ok": False, "status": "query_error", "material": None,
                "error_type": "query_error", "error": f"节点材料查询失败：{exc}"}
    material = _LOCAL_MATERIALS.get(node_id)
    return {**base, "ok": True, "status": "found" if material else "no_material",
            "material": deepcopy(material),
            "message": "已读取本地材料" if material else "该节点暂未配置本地材料"}
