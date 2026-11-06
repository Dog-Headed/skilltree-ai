# R01–R05 修复记录

日期：2026-11-06。实现提交：`7e7b828fa832e2ad52327eaa313f24aaa9e6df86`。基线：`d38857b2f4cd0097de77ebb31cf504f6b0de9b07`。

本轮只打通「资料生成草稿 → 管理员确认发布固定版本 → 员工按同一标准领取 → 进度不被重置」。没有重做产品，没有升级多租户、OCR 或向量检索，也没有改写历史课程行。

## 结果

| 编号 | 状态 | 提交 | 验证 | 证据 | 剩余限制 |
| --- | --- | --- | --- | --- | --- |
| R01 | 已修 | `7e7b828fa832e2ad52327eaa313f24aaa9e6df86` | 跨账号复用 K 返回 409 且响应正文不含对方项目；同账号跨任务复用 K 返回 409 且另一任务仍未建项目；同任务再次领取返回原项目，已通过的 n1 仍在；两线程并发领取只产生一个项目 | `tests/test_training_course_semantics.py` 中 `test_claim_checks_permission_before_idempotency_and_keeps_one_project`、`test_concurrent_claims_create_one_project_without_resetting_progress` | 幂等键仍是单位内唯一的 `request_id`，复用到其他目标时拒绝，而不是另开命名空间。同一进程内按员工任务加锁。学习项目身份由员工任务决定，重复创建会落到同一项目；本轮没有做跨进程压测 |
| R02 | 已修 | 同上 | 不带草稿、只交空树和未知规则的发布请求返回 422 `draft_required`，课程列表不变。带草稿发布时，请求体里的手填树和未知规则被忽略，发布结果仍是服务端草稿。发布页选择草稿后发布，页面不再使用 `unit-course` 或逗号占位节点 | 同上文件的 `test_placeholder_tree_is_rejected_and_draft_publication_ignores_it`；`app/static/training.js`；浏览器在 `127.0.0.1:18781/training/admin/courses` 发布后，库中行为 `course_id=course_2e1ebbd1b5484fa2b4ad7443600aec9b`、`version=1` | 模型生成仍走原有学习引擎里的 Planner。发布页读取已经保存的候选计划与 revision，本页本身不调用模型。调整草稿要回到学习引擎，再发布新的 revision。本轮没有真实模型生成记录 |
| R03 | 已修 | 同上 | 发布的 n3 只依赖 n1，n1 依赖未列入必学的 n_pre；两名员工的计划都保留这条分叉，并带上 n_pre。n1 与 n2 引用不同资料片段，员工片段哈希与发布锚点一致且彼此不同。文字目标保留 `crit_scope` 和文字作答任务。评价阈值保持 1.0，没有改成 0.8。旧占位课开课返回 409 `course_needs_republish`，原树仍在 | 同上文件的 `test_two_employees_keep_published_semantics_and_distinct_chunk_identities` 与领取测试中的历史课段落 | 必学节点的前置会进入员工计划，否则依赖会悬空；进度分母仍只算发布时勾选的必学节点。低于服务端 0.8 底线的阈值在发布时拒绝，不会静默抬高。历史课不会自动补齐，需要重新发布 |
| R04 | 已修 | 同上 | 空树、悬空必学节点、未知规则、环、悬空依赖、重复节点、错误来源、0.5 阈值、非法课程身份均在写入前拒绝；发布版本数和发布请求数不变。合法树可以发布，且 1.0 阈值被原样保存 | 同上文件的 `test_publish_rejects_each_invalid_course_without_a_leftover_row` | 已成功的 `request_id` 重放仍返回第一次的版本。校验使用现有 `LearningPlan`、`validate_learnability` 和 `validate_evaluation_policy` |
| R05 | 已修 | 同上 | 省略 `course_id` 的两次发布得到两个不同的 `course_<hex>`，版本都是 1。用其中一门的 `course_id` 再发布得到它的 v2，另一门仍是 v1。已下发任务仍指向第一版的 `cv_` 行。页面选项「发布为新课程」的 value 为空，避免把中文标签当成课程身份 | 同上文件的草稿发布测试；`tests/test_training_course_semantics.py::test_publish_page_uses_the_confirmed_draft_instead_of_placeholder_nodes`；上述浏览器发布记录 | 修订必须显式提交已有 `course_id`。课程身份只允许字母、数字和 `_. :-` |

## 本轮命令

在新建的虚拟环境中安装除 Docling 以外的 `requirements.txt` 直接依赖后执行。Docling 只在超限拆章时导入，这些用例没有走到那条路径。

```text
/tmp/st-venv/bin/python -m pytest \
  tests/test_training_course_semantics.py \
  tests/test_training_employee_start.py \
  tests/test_training_publish_assign.py \
  tests/test_training_dashboard.py \
  tests/test_training_day05_rehearsal.py -q --tb=line
13 passed, 1 warning in 19.02s
```

更早一次、在课程身份字符校验收紧之前，同一环境还跑过：

```text
tests/test_training_day05_rehearsal.py \
tests/test_training_demo.py \
tests/test_training_materials.py \
tests/test_training_registration_members.py
37 passed, 1 warning in 29.91s
```

这 37 项不是上面 13 项的超集，也不要加总。Day 5 演练已包含在后来的 13 项里并再次通过。全量离线回归、真实模型和服务器部署不在本轮。

## 浏览器

隔离目录 `work/training-demo/ui-check2`（已被 `work/*` 忽略，未进 Git）。管理员登录后打开课程发布页，选择已确认草稿「基础制度短课 · revision 2」，身份保持「发布为新课程」，点击「确认发布这一版本」。页面上不再出现逗号分隔的「时限要求,适用范围,常见问题」输入框。发布后的库记录：

```text
course_id = course_2e1ebbd1b5484fa2b4ad7443600aec9b
version   = 1
id        = cv_a999e91cebfa4cdd80ec591f44285eea
title     = 基础制度短课
```

第一次页面验证曾把选项文字「发布为新课程」提交成 `course_id`。该次数据只留在同样被忽略的 `work/training-demo/ui-check`，代码已改为空 value，并拒绝非标识符课程身份。上面的 `ui-check2` 记录是修复后的发布。

## 尚未纳入本 PR

| 编号 | 状态 | 说明 |
| --- | --- | --- |
| R06 | 未修 | 资料忠实度对否定、主体和条件仍可能漏判；没有新的真实模型首讲记录 |
| R07 | 未修 | PDF 超十页拆章仍可能把两个章节标记放进同一章。本环境未安装 Docling，没有把该失败改记为通过 |
| R08 | 未做 | 没有真实模型的整课通过、答错补弱和重启恢复证据 |
| R09 | 未做 | 没有创建三个测试管理员，也没有写入密码文件 |
| R10 | 未做 | 没有部署，没有把运行版本和文档全部对齐。只更新了 `docs/training-demo/CONTRACTS.md` 里已经改变的发布与开课契约 |
| R11 | 部分 | 已为 R01–R05 增加权限、语义和来源映射回归。没有跑完整离线套件，也没有改独立 REVIEW 的结论 |

自检通过指上述 13 项和修复后的发布页。这不是独立验收通过。
