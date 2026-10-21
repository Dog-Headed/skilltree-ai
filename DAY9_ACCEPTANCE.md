# SkillTree V3 Day 9 验收

日期：2026-10-14（Asia/Shanghai）。范围：V2可恢复基线、V3共享契约、安全能力/模板、独立持久化、身份与服务端上限。没有提前切换V2网页到V3，也没有声称完成Day10–13。

## 实际测试结果

- 开发前按原正式测试文件清单运行：**250 passed in 190.42s**。不是引用Day8报告的242项。
- 契约31项、能力54项、数据库首轮14项融合：99项通过；恢复11项通过。
- 第一次全量因误收集恢复包内测试而失败；新增pytest.ini限定正式tests目录后，全量 **360 passed in 199.70s**。
- 随后补同node/chunk身份跨项目事实隔离，以及最后一个请求槽并发预占的回归。数据库最终16项通过；最终全量 **362 passed in 194.09s**，比实际基线新增112项；日志 `work/day9/final-pytest.log`。

## 验收清单

| 标准 | 结论 | 证据与范围 |
|---|---|---|
| V2隔离副本恢复原等待点，原数据未改 | 通过；作答场景有明确证据边界 | 真实网页wait_learning同身份恢复；另有隔离Fake wait_answer跨进程恢复。现存孤立awaiting_answer卷无Checkpoint，未补造真实待作答存档 |
| V3业务库/Checkpoint独立，与V2隔离 | 通过 | data/v3两库独立版本元数据；init拒绝V2及未知版本；真实SqliteSaver在独立库持久化重启 |
| 三科及开放新主题合法档案 | 通过 | 四模板与开放subject_label/topic；demo真实持久化4草稿，无新增学科枚举 |
| 未知/未实现评价能力不获正式许可 | 通过 | 只有choice_exact@1.0.0有处理器；numeric/text planned，完整三科目标明确exploration_only；freeze逐目标和策略重新授权 |
| 模型/资料配置不能增加工具或取消上限 | 通过 | strict extra forbid、可信注册表、不可扩大上限的服务端配置；typed copy/嵌套修改重验 |
| 重复创建不产生两项目；纯查询无副作用 | 通过 | 同request同指纹复用、改输入冲突；并发8创建仅1项目；查询DB字节/total_changes不变，模型调用禁止 |
| 版本/状态/身份/私有公开字段明确 | 通过 | docs/v3三张设计表、JSON Schema、独立State、公开DTO不含答案/私有量规/路径；项目/等待/测验/operation职责分开 |

“通过”表示Day9基础在上述验证范围内通过，不表示完整V3课程或真实跨学科评分已经可运行。

## V2恢复交付

正式恢复包：`work/day9/v2-baseline-verified-20261014/`，96份manifest记录文件。SQLite Backup API成套备份业务/Checkpoint，保存当前实际V2工作树（包括用户已有未提交改动）、资料、Python/依赖冻结信息、Git状态与实际250项基线证据；配置秘密不入包。

恢复演练：`work/day9/v2-recovery-verified/recovery-evidence.json`；说明 `work/day9/V2_RECOVERY.md`。旧候选包被首次pytest导入增加字节码，严格verify拒绝，已明确作废；正式包在限定收集范围后重新捕捉、演练和验证，没有把失败候选当交付证据。

真实项目：`project_db4878f84b0241fcad8d2245882c9a2d`，回到 `wait_learning` / `variables_and_types`，pending_input仍为 `learning_33bc9c2840a943709535c0ca38aa8b59`。两个独立进程均恢复同身份，模型/网络调用0。搬迁只对只读Saver返回的State做内存路径重定位，不改Checkpoint表，仍用匹配V2代码和身份校验。

原业务库4项目、33节点、7进度、9卷；Checkpoint87条、386writes。两个原始主库哈希与本轮首次捕捉一致，26份既有app源码字节未改；证明见 `work/day9/final-v2-hash-attestation.json`。孤立业务卷、旧线程无输入身份等既有问题保留原样，未升级测试改写。

## V3基础交付

- `app/v3/contracts.py` / `config.py` / `state.py`：开放学习档案、自述/证据、策略、目标计划/来源/试卷/评价/公开契约、版本与上限。
- `app/v3/capabilities.py` / `presets.py`、`configs/v3/subjects/`与`policies/`：实际注册能力、4模板、3策略示例。
- `app/v3/storage.py` / `repository.py`：独立初始化/版本检查、8业务表和基础操作、immutable来源/冻结快照、复合隔离/幂等、事务预算预占与一次继续。
- `day9_v2_recovery.py` / `day9_demo.py`：可复现恢复和无模型基础演示。
- `tests/test_day9_recovery.py` / `test_v3_contracts.py` / `test_v3_capabilities.py` / `test_v3_storage.py`；`pytest.ini`：恢复、契约、授权、数据库/并发测试与正式收集范围。
- `docs/v3/DAY9_FOUNDATION.md`、`contracts.schema.json`、`capabilities.json`、`server-limits.json`：三个共有设计表、完整机器契约与服务端限制。

新运行数据已初始化于 `data/v3/learning.sqlite`和`checkpoints.sqlite`。正式Web入口目前仍为V2；V3完整三科目标暂不授予正式测评许可，需Day11接通通用numeric/text评价并校准。缩小到有资料的选择目标可以获能力许可，但Day9没有完整V3教学/评分/推进runner。

## 未解决与后续依赖

Day9范围内没有已知失败的工程用例。可核验的真实旧等待点是教学等待，不是真实作答等待；新增作答恢复只作Fake证据。不得向用户展示不存在的历史。

Day10需要资料导入/确定性切分/上下文/Planner及完整用户确认，Day11需要把操作额度扣减接到统一模型HTTP入口、通用评价结果适配/守卫和异常Graph，Day12接API/网页及legacy只读路由。这里已定义上限、SQL预占和契约，但不声称V2当前请求受V3 operation预算控制。

本轮没有调用真实模型进行三科学习质量评价。三科学习范围采用你提供的Python条件与循环、一元一次方程、英语一般过去时；能力不含代码执行、复杂证明或听说。第四未调试主题到Day13再确定。真实评估须先确认案例/答案/量规，再运行模型。

## 演示与回滚

```powershell
& 'D:\conda_envs\edu_agent\python.exe' day9_demo.py
& 'D:\conda_envs\edu_agent\python.exe' day9_v2_recovery.py verify --package work/day9/v2-baseline-verified-20261014
& 'D:\conda_envs\edu_agent\python.exe' day9_v2_recovery.py demo --package work/day9/v2-baseline-verified-20261014 --directory work/day9/my-fresh-v2-demo --fake-wait-answer
& 'D:\conda_envs\edu_agent\python.exe' -m pytest -q
```

恢复目标必须新建且与原目录隔离。继续旧课程使用包内匹配V2代码/数据库及外置受保护配置；V3数据另保留，不塞回旧Schema。恢复包包含用户学习事实，留在本机，未提交/推送。
