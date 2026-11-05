# Day 4 报告：管理看板

更新日期：2026-11-05（Asia/Shanghai）。

## 完成标准对照

| 项 | 结果 |
|---|---|
| 任务列表：下发 / 已开始 / 已完成人数 | `GET /training/api/admin/dashboard` |
| 员工明细：状态、必学进度、最近测评、待补弱、更新时间 | `GET /training/api/admin/tasks/{id}/board` |
| 进度 = 已达标必学节点 / 全部必学节点 | 来自 `learning_progress.completed_at` + `training_node_bindings` |
| 逾期独立标记（明确时区） | `due_at` 保留偏移；无时区按 Asia/Shanghai 解释 |
| 零节点不自动完成；个人学习不计入单位任务 | 遵守 |
| 空状态 / 错误提示 | 看板空态与员工 403 |

## 口径

- **已完成**：该员工项目上，课程 `required_nodes` 全部在绑定后的 project node 上具有 `completed_at`。
- **进行中**：已关联 `project_id` 且未全部达标。
- **未开始**：尚无 `project_id`。
- **逾期**：当前时间晚于任务 `due_at`，且该员工尚未课程完成；不覆盖学习状态。

## 测试

```bash
.venv/bin/python -m pytest tests/test_training_dashboard.py tests/test_training_employee_start.py -q
```

本机记录：3 passed（含时区助手）。

## 页面

`/training/admin/dashboard`：任务计数卡片 +「查看员工明细」。
