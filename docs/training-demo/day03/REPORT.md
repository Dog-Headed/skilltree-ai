# Day 3 报告：发布、下发与员工开课

更新日期：2026-11-05（Asia/Shanghai）。

## 完成标准对照

| 项 | 结果 |
|---|---|
| 管理员发布冻结课程版本 + 资料关联 | 完成，`request_id` 幂等 |
| 下发任务给甲乙，丙不可见 | 完成 |
| 员工开始任务 → 独立学习项目 | 完成 |
| 不调用 Planner 改写已发布目标 | 完成（按发布节点标题合成可冻结计划） |
| SourceChunk 按员工项目新建身份 | 完成（chunk_id 含 project_id；甲乙 chunk 集合不相交） |
| 不复制他人 Checkpoint/测评 | 完成 |
| 至少一人真实教学+测评过一节 | 离线 Fake 内容路径完成（`n1` 通过） |
| 开始幂等 | 完成（同 `request_id` / 已开课复用） |

## API

| 方法 | 说明 |
|---|---|
| `POST /training/api/admin/courses/publish` | 冻结课程版本 |
| `POST /training/api/admin/tasks/assign` | 下发员工任务行 |
| `POST /training/api/my-tasks/{employee_task_id}/start` | 按已发布课程初始化独立项目并冻结 |
| `GET /training/api/my-tasks` | `learning_available=true`，附进度摘要 |

## 关系

`training_material_versions` → `training_course_versions` + `training_course_materials` → `training_tasks` → `training_employee_tasks.project_id` → `training_node_bindings` + 原引擎 `learning_*`。

员工开课时：导入单位资料原件到**本项目** → 用发布节点标题生成目标（绑定本项目 chunk）→ `freeze_plan` → 写入绑定与 `started_at`。

## 测试

```bash
.venv/bin/python -m pytest \
  tests/test_training_employee_start.py \
  tests/test_training_publish_assign.py \
  tests/test_training_registration_members.py \
  tests/test_training_demo.py -q
```

本机记录：**16 passed**。

## 未纳入本交付 / 后续

下列四条是 **2026-11-05、Day 3 合并（发布下发 `a40004d`，员工开课 `f2998f3`）** 当时未纳入的范围，不是 2026-11-06 的现状：

- 管理员侧用真实 Planner 生成草稿后按该修订发布。当时管理页用节点标题发布，开课时服务端合成可测评目标。2026-11-06 起 PR #18（`bbdb3bc`）改为发布已确认草稿，并在领取时保留已发布语义。
- Day 4 看板明细与逾期时区展示。随后由 PR #6（`7baff8f`）落地。
- Day 5 隔离实例全流程演练。随后由 PR #7（`3a98441`）落地。
- 「生产环境仍停在旧 SHA，本轮不自动部署」只适用于 2026-11-05 的这次交付。2026-11-06：GitHub 与服务器已同步到 `d948212`；`SKILLTREE_COMMIT` 已在运维侧按该部署写回。Windows 本机仓未强制覆盖、待用户自行同步。见 [PROGRESS.md](../PROGRESS.md)。
