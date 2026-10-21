# Day 11 交付验收记录

开始：2026-10-19；交付：2026-10-20。

2026-10-20 独立验收发现的三项问题及后续修复，见 [Day 10 / Day 11 修复记录](DAY10_DAY11_REPAIR_20261020.md)。本页 728 项结果为此前交付基线，最新验证以该修复记录为准。

本轮实现了通用学习后端、冻结测评、三类评价器、诊断与确定性推进、持久化预算和恢复；另按新增要求实现现有网页的项目三点菜单、重命名与删除。代码没有提交或推送，已有工作区改动保留。

## 验证结论

最终全量测试：**728 项通过，397.94 秒（6 分 37 秒）**。实际命令、完整输出保存在 `work/day11/final-delivery-pytest.log`。此前首轮 678 项、独立修复后 720 项均实际通过；它们不替代最终一轮结果。

专项验证包括：

- 三科使用同一套接口，Fake 各跑完 4 个节点；正式资料版本、绑定、准备确认、试卷和实际数据库参与运行。
- 必要目标未达标、关键错误、伪分、伪数值证据、非法诊断或伪证据都不能解锁。数值结果无法替代解释目标。
- 第三次有效失败暂停，第三次通过先推进；不确定、无效题、评分或诊断技术失败不计有效学生轮次。
- 追加三轮只发生一次且不自动教学；休息和重启保持暂停。原轮次保留。系统换题最多两次，返回教学不能绕过。
- 每个逻辑任务 3/1/1、操作 12+12、预占后崩溃不返还、普通重试不刷新、追加请求去重和任务结果复用。
- 7 个真实进程 `os._exit` 窗口：session 初始化前、Tutor 请求中、出题请求中、试卷写入后、评分写入后、完成事务后、最终等待点后。均通过原身份重启恢复。
- 捕获到的软异常也单独验证：完成事务或 prepare_wait 已提交但 Checkpoint 未提交时，重试保留业务阶段，无重复评分、完成和调用。
- 真实网页点击验证：三点菜单只含重命名/删除；新名称同步列表和当前标题，刷新保留；取消删除保留记录；确认删除当前演示记录后清空画面，刷新不复活，另一条记录保留。

## 演示与真实模型边界

Fake 六类流程报告：`work/day11/fake-six-scenarios/Day11_六类流程演示.md`，逐项身份与计数：同目录 `day11-demo.json`。Fake 仅证明机制，不证明内容质量；演示数据库已标记 demo_only，真实学习服务拒绝打开。

最新真实适配器冒烟：`work/day11/real-smoke-delivery-20261019/report.md`，逐科 JSON 包含状态、模型名称、提供者可用的 usage、请求/修复次数和耗时。规划使用固定 Fake 候选，作答使用模型自身私有参考答案；**它不是独立人工质量评价，也不统计人工答案准确率。**

| 主题 | 最新真实冒烟结果 | 真实 HTTP 预占数 | 耗时 |
|---|---|---:|---:|
| Python | 评分满分，但 Diagnosis 认为证据未覆盖整个必要目标；保留学习/补证据状态，未通过 | 5 | 42.116 秒 |
| 数学 | 完成一个正式节点 | 4 | 36.224 秒 |
| 英语 | 完成一个正式节点 | 4 | 29.291 秒 |

Python 的结果展示了“模型给满分仍不能独自通过”：本次选取的文字证据仅覆盖赋值片段，不能据此认定比较和列表目标也已掌握。需要人工审阅题目覆盖、评分锚点及诊断建议；不通过隐藏此分歧或强迫 advance 来让演示变绿。

早期冒烟也保留在 `work/day11/real-smoke-*`：准备脚本的并发替身冲突已修复；真实模型曾生成额外结构字段和替换冻结量规 ID，均被拒绝，之后强化 Prompt 的精确键名和冻结 ID 约束。最新报告不引用早期成功样本替代当前结果。

36 个 V3 案例的人工预期仍为 **待用户复核**；此前确认的 Day 7 的 12 个诊断案例不等于批准本批 36 个案例。本轮没有用保留集进行真实模型调参。

## 数据保护与迁移

V3 已实际执行加法迁移，配对备份为 `work/day11/runtime-backup-20261019`，清单含源路径和备份哈希。迁移回执：`work/day11/runtime-migration.json`。

原 V3 项目、资料、进度等各原始业务表逐行一致；原准备 Checkpoint 的哈希一致。仅增加学习扩展表、索引、扩展版本和独立学习 Checkpoint，没有替换旧 Graph 存档。

本轮期间检测到原 V2 库存在新增学习记录，因此不能声称原 V2 文件哈希仍相同。已逐表核对基线：原有记录均完整保留，没有删除或回滚新增记录。具体行数与核验值见 `work/day11/data-preservation.json`。

删除和重命名只在隔离测试库及 `18119` 演示库执行，未替用户选择或删除真实学习记录。

## 关键设计与修改文件

详细运行方式、动作表和预算说明：`docs/v3/DAY11_RUNTIME.md`；当前服务端上限快照：`docs/v3/server-limits-day11.json`。

| 范围 | 文件 |
|---|---|
| 教学、出题与评价 | `app/v3/tutor.py`、`assessment.py`、`evaluators.py` |
| 诊断与推进 | `app/v3/diagnosis.py`、`guard.py` |
| 学习 Graph、API 与事实持久化 | `app/v3/learning.py`、`learning_api.py`、`learning_repository.py` |
| 预算和存档版本 | `app/v3/model_tasks.py`、`runtime_storage.py` |
| 共享契约与能力、上限 | `app/v3/contracts.py`、`capabilities.py`、`config.py` |
| 当前模板说明 | `configs/v3/subjects/python.json`、`mathematics.json`、`english.json` |
| V3 运行和复现 | `day11_storage.py`、`day11_server.py`、`day11_demo.py`、`day11_real_smoke.py` |
| 原网页项目菜单与元数据 | `app/static/index.html`、`app/main.py`、`app/models/web.py`、`app/db/repository.py`、`app/services/project_view.py` |
| 删除与阻止旧存档复活 | `app/services/project_deletion.py`、`app/services/learning_session.py` |
| 新测试和共享 Fake | `tests/day11_support.py`、`day11_process_worker.py`、`test_v3_tutor.py`、`test_v3_assessment.py`、`test_v3_evaluators.py`、`test_v3_diagnosis.py`、`test_v3_guard.py`、`test_v3_learning.py`、`test_v3_learning_api.py`、`test_v3_learning_recovery.py`、`test_v3_learning_review_regressions.py`、`test_v3_model_tasks.py`、`test_v3_runtime_storage.py`、`test_project_deletion.py`、`test_project_rename.py` |
| 既有测试的能力阶段断言调整 | `tests/test_v3_capabilities.py`、`test_v3_preparation.py`、`test_v3_planner.py`、`test_v3_storage.py`、`test_day10_demo.py`，以及 `day10_demo.py` |

清单指本轮涉及文件；不把这些文件内原有工作区修改都归为本轮新改动。完整交付清单另存 `work/day11/changed-files.json`。

## 还需用户执行或复核

1. 日常网页若后端仍是旧进程，重启原服务并刷新，再查看记录右侧 `⋯`。该菜单只有重命名、删除两项。名称不改学习目标；删除有单独确认且不可在页面恢复。
2. 查看六类流程报告和截图；三科完整 V3 网页联调仍属于 Day 12。本轮提供可运行后端，不能把原 Python 网页称为已经完成 V3 三科网页。
3. 审阅本批 36 例答案、量规和预期，尤其文字题实际目标覆盖、证据锚点和 Python 最新冒烟分歧。批准标准后再做独立的正式真实模型评价及保留集验证；目前不宣称内容质量已经验收通过。
