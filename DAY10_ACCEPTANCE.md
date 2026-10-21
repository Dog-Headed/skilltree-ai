# SkillTree V3 Day 10 验收记录

> 2026-10-19 更新：下文是 2026-10-16 的历史交付记录。独立验收复现了硬退出恢复、重试去重、片段顺序、上下文修正入口四项缺陷，因此原结论不能代表稳定通过。修复及最新实际复验见 [Day10 四项缺陷修复记录](DAY10_REPAIR_20261019.md)。人工审核状态仍为待复核。

记录日期：2026-10-16，Asia/Shanghai。结论：**准备后端及自动验证完成；三科计划、资料与 36 例标准仍待用户复核，完整学科开课留待 Day 11 真实评价器复验。**

本轮沿用 Day 9 契约、SQLite Repository、LangGraph、现有模型预算及日志 helper。V2 业务代码与网页未在本轮重写，工作区原有 Day 8/Day 9 修改保留。原 V2 业务库与 Checkpoint 的前后 SHA-256 相同；Day 9 V3 原有 4 个项目的既存业务字段及其余业务表逐项保持一致，仅显式升级 V3 版本和增加准备流程结构。

## 实际测试

| 验证 | 本次实际结果 | 证据 |
|---|---|---|
| 开始修改前全量基线 | 362 passed，265.98 秒 | work/day10/baseline-pytest.log |
| 最终全量 pytest | **471 passed，231.70 秒** | work/day10/full-pytest-final.log |
| 最后 Planner + 三科 Fake 演示专项 | 44 passed，4.91 秒 | tests/test_v3_planner.py、tests/test_day10_demo.py |
| 三科评价数据离线核对 | 3 包、36 例、每科 8 debug/4 holdout，哈希与引用一致 | work/day10/fixture-check.json |
| 实际 Day 9 V3 成对备份与迁移 | 两库均 v3-day10-1 / v3-day10-preparation / contract 3.0.0 | work/day10/migration.json、day9-paired-backup/manifest.json |
| V2 原库哈希、Day 9 V3 原业务事实 | 均保持 | work/day10/data-attestation.json |

保留了 Day 6 的持久化/跨进程恢复和 Day 7/8/9 的既有回归。pytest 有既存 pytest-asyncio 默认 fixture scope 的弃用提示，无测试失败。测试数来自本次运行，不使用历史验收数量代替。

## 验收项与边界

| 标准 | 结果与证据 |
|---|---|
| 三科共用 Planner 与资料接口 | 自动验证通过；同一 PreparationService/Graph、MaterialService/ContextBuilder；三科完整主题 Fake 冻结演示及三科缩小目标真实预览均完成 |
| 相同 node_id 的项目隔离 | 通过；真实项目外键、上下文所有权校验、三演示项目复用 node_1…node_4 |
| 私有答案不进教学、公开引用或页面 | 通过；私有导入后公开响应/Planner 不含私有标题或正文，教学上下文只取 teaching |
| 引用可定位；无来源/无关来源拒绝 | 通过存在、项目、版本、哈希、原文行号及保守相关性校验；真实数学一次关联错误被拒并修复。词汇检查不等同学术支持证明，人工抽查仍待进行 |
| 缺资料、能力不可用、环与不存在先修 | 明确等待/拒绝；不可用能力不调用模型、不冻结；非法计划修复一次后仍错则停止 |
| 只上传资料也立即使旧确认失效 | 通过；导入事务更新 revision，GET 显示 requires_replan，旧确认409；显式 replan 才产生新身份 |
| 未确认不能正式学习；确认后版本固定 | 通过；未确认无正式节点；确认原子冻结。Day10 learning_runtime_ready=false，不启动学习闭环；已冻结项目拒绝原位改资料/标准 |
| 资料指令不能增加权限或修改评分 | 通过；JSON 数据边界、额外工具/策略字段拒绝、能力与门槛只由服务端控制 |
| 参考答案、量规、预期先于模型评价 | 数据已完成且哈希冻结；36例均未运行模型评价，保持 pending_user_review；holdout未进入调试模型 |

## 真实模型与 Fake 分开记录

**完整主题 Fake 契约演示**：三个项目各有 4 节点，模拟档案确认、计划预览及确认冻结；调整流程另有集成测试。模拟确认不代表用户批准。所需 text_rubric/numeric_scalar 仅在离线 CLI 进程中使用显式 Fake 能力；真实注册表保持 planned。演示库有 demo_only 标记，真实 PreparationService 无法打开。模型 HTTP 和真实评价次数均为 0。

证据：`work/day10/three-topic-contract-demo-v2/plans.json`、《三科计划复核稿.md》。它验证契约、状态、身份、私有隔离和冻结，不证明真实内容质量。

**缩小目标的真实 Planner 冒烟**：使用本地已配置 deepseek-flash，仅规划 choice_exact 可测的规则/结果辨认，不测完整解释、数值求解过程或听说。只产生 plan_review，未确认、未冻结、未出题、未写任何通过记录；不读取评价案例或私有答案。

| 单元 | 最终节点 / 分钟 | 预占模型请求 | 耗时 | 结果 |
|---|---|---|---|---|
| 英语 | 6 / 120 | 1 | 28.646 秒 | plan_review |
| 数学 | 5 / 100 | 3 | 50.602 秒 | plan_review；首个已解析候选的一个目标引用不匹配，修复后通过 |
| Python | 4 / 115 | 1 | 33.710 秒 | plan_review |

最终 Prompt 为 `v3-day10-planner-2`，共预占 5 次请求，均未超单逻辑 3 次及操作预算。此前 Prompt 1 调试还预占 5 次：英语/数学因可观察动词筛查误拒进入 error，Python成功；随后补充“选出/辨认/辨识/recognize”等合法可观察表达和 4 条回归，并用新版本重新验证。原始失败报告保留，不删改为成功。

证据：`work/day10/real-choice-previews-v2/real-previews.json`、`validation-summary.json`、`*-planner-outputs.json`；初次调试在 `real-choice-previews/`。usage 不可获得：沿用的 structured adapter 只返回解析结果，报告记录 null，不推算 token 数量。上述是准备流程冒烟，不是 36 例真实质量评价或完整主题正式开课证据。

## 关键实现与恢复

资料导入原文/版本/片段/去重台账/revision 同事务提交。私有资料仅经明确 assessment/grading 绑定进入受信评价上下文，默认准备 Graph 冻结教学绑定。上下文含元数据最多 24,000 字符，超限拒绝；模型或上传配置不能扩大上限。

所有新建/恢复入口 recursion_limit=30，同步 Checkpoint。用户输入提交前检查当前 revision/input/action 和服务端版本权限，非法输入422保持原等待点。已接受命令的原样重复请求只读返回，换载荷同身份409。

HTTP 前持久化预占，技术重试复用 operation；根操作12次，最多显式追加一次12次。候选计划、输入事务和冻结分别覆盖“业务提交成功、Checkpoint未提交”的故障窗口：复用候选、不重复增 revision、不重复插节点；冻结前失败保留原确认身份，冻结后失败恢复 learning。

版本迁移成对预检；旧 Graph 有持久化等待记录时拒绝换版本标签，保留旧运行环境并新建目录。本机 Day 9 Checkpoint 原为空，因此已完成显式升级。迁移前代码及原库副本保存在 `work/day10/day9-before-migration/`，再次成对 SQLite 备份在 `work/day10/day9-paired-backup/`。

## 修改文件清单

Day 9 文件小改：`app/v3/config.py`、`contracts.py`、`state.py`、`storage.py`、`repository.py`；同步刷新 `docs/v3/contracts.schema.json`。能力注册表及服务端数值上限未放宽。

新增业务：`app/v3/materials.py`、`context.py`、`planner.py`、`preparation.py`、`preparation_api.py`。

新增运行与验证入口：`day10_storage.py`、`day10_demo.py`、`day10_preview.py`、`day10_check_fixtures.py`。

新增测试：`tests/test_v3_materials.py`、`test_v3_context.py`、`test_v3_planner.py`、`test_v3_preparation.py`、`test_v3_migration.py`、`test_day10_fixtures.py`、`test_day10_demo.py`。

资料与案例：`materials/v3/{python,mathematics,english}/` 共6份正文/私有资料及3份 manifest；`evals/v3/{subject}/cases/` 共36个 JSON，及 `evals/v3/README.md`。

文档：本记录、`docs/v3/DAY10_PREPARATION.md`、`DAY10_HUMAN_REVIEW.md`、`day10_demo_plans.json`、`preparation.openapi.json`。测试日志、迁移记录、计划演示与数据核对证据在 `work/day10/`；不把真实学习库、模型密钥或 .env 打入交付包。

## 仍需人工与后续事项

1. 用户审阅《三科计划复核稿》及《DAY10_HUMAN_REVIEW》，抽查三科 debug_01 的关键答案、给分项和来源，再检查36例标准；当前明确保持待复核。
2. Day 11 实装真实 text_rubric/numeric_scalar 后，复验完整三科的正式开课、出题、评价、Diagnosis和守卫；不能以当前 Fake 演示提前开放。
3. 获得标准确认后，仅用每科8个debug开发，冻结 Prompt/模型/策略/评价器版本后再跑4个holdout。当前真实案例质量指标均为未运行。
4. Day 12 接通通用网页与完整学习公开视图。本轮可用独立准备 API，启动和请求说明见 `docs/v3/DAY10_PREPARATION.md`。
