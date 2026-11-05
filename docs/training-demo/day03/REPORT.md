# Day 3 进展报告（基础层）

更新日期：2026-11-05（Asia/Shanghai）。**本阶段尚未达到交接验收完成标准。**

## 已完成

| 项 | 状态 |
|---|---|
| `publish_course` 冻结课程版本 + 资料关联 | 完成，request_id 幂等 |
| `assign_task` 下发员工任务行 | 完成，request_id 幂等；甲乙可见、丙不可见 |
| 课程/资料行不可变触发器 | 完成 |
| Admin API | `POST /training/api/admin/courses/publish`、`POST .../tasks/assign`、对应 GET |
| 管理页 UI | 课程发布、任务下发表单；员工任务列表可见 |
| 离线测试 | `tests/test_training_publish_assign.py` |

## 明确未完成（阻断完整 Day 3 验收）

1. **员工开始任务**：创建独立学习项目、按已发布课程初始化树/资料/SourceChunk 映射、节点绑定。
2. 管理员侧 **Planner 生成草稿**（当前 UI 用简化节点标题发布；测试用合成 tree）。
3. 至少一人完成一节真实教学+测评的证据。
4. Day 4 看板、Day 5 演练。

## 测试

```bash
.venv/bin/python -m pytest \
  tests/test_training_publish_assign.py \
  tests/test_training_demo.py \
  tests/test_training_registration_members.py -q
```

本机记录：15 passed。

## 关系

`training_material_versions` → `training_course_versions` + `training_course_materials` → `training_tasks` → `training_employee_tasks`（`project_id` 仍为空直到开课接入）。
