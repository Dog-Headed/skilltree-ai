# SkillTree V3：Day 9 共享基础

记录日期：2026-10-14（Asia/Shanghai）。依据《SkillTree 通用学习 Agent 架构说明 V3.0》，只实现Day 9基础。四类Agent、V2 Graph、V2 State、网页及原学习数据保留。新代码位于 `app/v3/`，避免用新契约反序列化旧存档。根代理统一审阅契约、版本、状态与数据库；并行任务不各自改共享旧模块。

## 目标与能力表

学科是开放文本，模板只提供术语及建议，不授予权限。能力检查按目标所需的具体能力，不使用“数学支持所有数学题”一类结论。只有代码中注册的实际处理器能执行评价。

| 具体任务 | 能力 | Day 9实际状态 | 可核验范围 |
|---|---|---|---|
| 单选、多选精确匹配 | choice_exact@1.0.0 | available，真实确定性处理器 | 冻结选项ID；多选集合无序、全对得分；无资料是needs_material |
| 有资料且仅需选择判断 | choice_exact | supported | 仍需确认目标、材料、策略；评分本身不写完成 |
| 文字解释、问答 | text_explanation / text_question_answer | 文字通道已知；V3 Tutor待Day11接入 | 探索讲解不授予测评通过权限 |
| Python条件与循环解释 | text_rubric + choice_exact | 完整目标exploration_only | 不宣称执行程序；通用文字评价器尚未实装 |
| 一元一次方程求解及解释 | numeric_scalar + text_rubric | 完整目标exploration_only | 数值/量规处理器待Day11，不宣称形式证明 |
| 英语一般过去时改写和短文 | text_rubric + choice_exact | 完整目标exploration_only | 不宣称听说、发音评价 |
| 任意程序执行 | code_execution | unsupported | 未接代码沙箱 |
| 一般证明/符号验证 | symbolic_proof | unsupported | 不以文字分数冒充证明 |
| 音频、图像、实验过程 | 相应模态/执行能力 | unsupported | 不用文字替代真实操作 |
| 未知评价器或未知版本 | 未注册ID/版本 | 拒绝正式评价 | 上传配置不能安装处理器 |

四种检查结果：`supported`、`needs_material`、`exploration_only`、`unsupported`；`formal_assessment_allowed`仅在supported时为true。`has_material`代表调用者已核验实际目标覆盖，不代表“传来一个文件就足够”。Day9正式冻结还检查本项目真实片段、每目标能力与策略，不能伪造这个布尔值绕过。

通用、Python、数学、英语模板在 `configs/v3/subjects/`。`choice-foundation`策略可执行；`numeric-text-draft`与`text-rubric-draft`仅是经过结构检查的建议，不可启用。新学科使用generic模板，不新增学科枚举。Day9的第四档案只验证开放字段，真正未调试学习主题留到Day13选择。

## 配置与快照表

| 信息 | 所有者 | 可变与冻结约定 |
|---|---|---|
| subject_label/topic/原始goal/语言/时长/范围 | 用户草稿，服务器校验 | 草稿修改递增draft_revision；冻结后新项目承接 |
| bounded_goal | 用户确认范围 | 正式冻结必须非空 |
| prior_knowledge.self_reported | 用户自述 | 可调整起点，不生成测评证据或通过记录 |
| prior_knowledge.assessed_evidence | 服务端核验后的结果引用 | Day9创建/修改拒绝非空引用，不接受用户伪造；未来需真实graded核验 |
| 能力/处理器/工具注册 | 可信代码 | 模型、资料、模板均不能增加可执行工具 |
| EvaluationPolicy | 模板建议，服务端授权 | 校验题型、实际评价器版本、每目标规则、门槛与上限；确认时冻结 |
| SourceDocument/SourceChunk | 本项目版本化事实 | 原文UTF-8哈希与稳定行号；同版本不可原位覆盖 |
| NodeMaterialLink | 程序校验的目标绑定 | 同项目、正确节点/目标、真实来源版本；私有片段不得教学 |
| source_manifest | 冻结计划依据 | 仅冻结实际绑定的版本；同计划不可混用同来源两个版本 |
| assessment snapshot | 稳定测验身份绑定 | profile/plan/policy/source/evaluator版本一起保存；身份重用但快照不同要停止 |
| 服务端上限 | config.py，limits_version=day9-1 | 用户/模型无覆盖字段；部署改动需新版本与复验 |
| 完成/正式推进 | 后续确定性守卫 | Day9只开放started和查询；不提供直接标passed接口 |

公开契约采用白名单。`PublicQuiz.from_private`只保留题面、选项、目标、满分；不含answer_key、numeric_rules、私有rubric或内部State/路径/模型配置。`assessment_private`资料不能成为PublicSource。用户资料默认“用户提供，未独立核验”。ID存在与引用可定位不代表内容在学术上正确，仍需后续内容评估。

## 身份、版本与输入责任

| 身份 | 用途 | 去重/冲突规则 |
|---|---|---|
| create request_id | 一次创建意图，UUID | 同ID同输入返回原项目；同ID改输入冲突；并发仍只有1项目 |
| project_id/thread_id | V3项目与Graph稳定身份 | `v3_<创建UUID>`，两者相等；不接收V2 thread做续学 |
| draft_revision | 配置/资料变更世代 | 候选计划记录生成世代；不匹配requires_replan，旧确认拒绝 |
| pending_input_id | 当前可操作等待画面 | 由服务器生成；用户操作同时核对当前身份，不能作用于下一等待点 |
| assessment_id | 一张冻结测验 | prepare request在节点内去重，快照固定；round_no不承担去重 |
| operation_id | 一次逻辑公开写操作 | 请求前事务预占；崩溃视为已用；普通retry复用原ID |
| retry_token | 技术失败/预算继续的当前身份 | 与pending_input不同；追加预算必须匹配token和唯一继续request |
| root/parent operation | 一次显式预算继续 | 根12请求，最多1个子operation再12；重复继续复用子ID，累计最多24 |

版本分别存储：`db_schema_version=v3-day9-1`、`graph_version=v3-day9-foundation`、`contract_version=3.0.0`；profile/plan/source为项目版本，policy/evaluator/prompt分别有版本。foundation不是已完成的V3学习Graph。

## 公开状态与动作上界

下表是后续API共享契约，不表示Day9已开放全部网页操作。实际服务只能返回已经实现且在当前事实下允许的子集；页面不能自行追加动作。

| 状态 | 允许动作上界 | 输入/额外条件 |
|---|---|---|
| profile_review | confirm_profile / update_profile / rest | pending_input_id；配置字段严格校验 |
| materials_required | import_material / adjust_scope / choose_exploration / replan / rest | pending_input_id；资料不暗中resume Graph |
| plan_review | confirm_plan / adjust_plan / import_material / replan / rest | pending_input_id + draft_revision；过期不允许confirm_plan |
| learning | ask / start_quiz / return_to_current / rest | 当前等待身份；提问不直接计通过 |
| quiz | submit_answer / return_to_teaching / rest | 当前assessment_id及等待身份；答案对应冻结题面 |
| assessment_review | view_feedback / annotate_dispute / replace_assessment / rest | needs_review/invalid_item；追加说明不覆写原答案、不直接改分 |
| budget_exhausted | continue_with_new_budget / rest | 继续须retry_token和request_id；休息不追加预算 |
| exploring | ask / rest | 不提供正式测验或依赖解锁 |
| paused | rest / retry_3 | 当前暂停身份；默认3轮有效评价、最多追加1次3轮 |
| error | retry / rest | retry用retry_token，普通技术重试不重置operation额度 |
| running | 无 | 读取最新状态 |
| completed | 无 | 查看/导出既有事实，不能原位改历史分数 |
| legacy_readonly | 无写动作 | Day12只读适配器；V3不得resume/retry V2项目 |

## 数据与Repository

默认新目录：`data/v3/learning.sqlite`与`data/v3/checkpoints.sqlite`。原V2仍在 `data/learning.sqlite`、`data/checkpoints.sqlite`。使用前显式initialize；查询构造器不初始化Schema、不启动Graph、不运行模型。初始化先只读检查两库，V2或未知版本文件明确拒绝，不原位迁移。

业务库包括learning_projects、knowledge_nodes、learning_progress、assessments、source_documents、source_chunks、node_material_links、model_operations，另有runtime_metadata/schema_migrations；Checkpoint单独使用SqliteSaver及版本元数据。两份SQLite不宣称共同事务。

基础API：create/get/list_project、update_profile、save_candidate_plan、put_source/list_sources/get_chunk、freeze_plan、prepare/get_assessment、mark_node_started/get_progress、create/get_operation/reserve_model_request。源码中SQLite外键、复合身份、唯一请求键、immutable比较与BEGIN IMMEDIATE一起保证隔离/并发/幂等。

测验状态约定：`prepared → awaiting_answer → submitted → graded / needs_review / invalid_item`，未有效评价可abandoned。技术失败不伪造任何成功评分。有效轮数未来只统计同节点唯一graded assessment；不确定和无效题不消耗学生失败轮数。Day9未开放评分或正式通过写入；这些状态用于Day11接入时的共有契约。

资料基础持久化不是完整Day10导入/切分/检索服务；只接收经过哈希、行号校验的来源与片段。系统上限以UTF-8实际字节计，项目累计包含各版本，避免资料版本无限增长。默认读取隐藏assessment_private，冻结前重验节点/目标/来源/能力/策略，不相信Planner声明。

预算基础在HTTP之前提交reserved_requests，重开数据库不返还额度。Day11要把它接到共同模型入口及错误状态；Day9不会声称当前V2调用已经受V3 operation预算控制。

## 服务端上限

- 默认规划3–12节点，硬上限20；每节点1–5目标。
- 默认4–6题，单卷最多10题；覆盖要求必须能装入题数上限。
- 单文件128KiB，项目资料累计1MiB，上下文最多24000字符。
- 单operation12次HTTP，最多显式追加1次12；逻辑任务3请求、网络重试1、输出修复1；SDK隐式重试0，单请求timeout45秒。
- 默认3轮有效评价，最多追加1次3轮；系统换题最多2次；澄清最多2轮；工具2轮/3次；Tutor最近6轮。
- 初始总分/必要目标门槛最低0.8，保存在版本化策略/服务器配置，而非Python错误标签或学科分支；领域校准可由可信部署改配置版本，模型不能自行降低。

准确Schema与数值见 `contracts.schema.json`、`server-limits.json`，实际能力见 `capabilities.json`。

## 初始化、恢复与下一轮

```powershell
& 'D:\conda_envs\edu_agent\python.exe' day9_demo.py --init-only
& 'D:\conda_envs\edu_agent\python.exe' day9_demo.py
& 'D:\conda_envs\edu_agent\python.exe' -m pytest -q
```

demo保存三科与开放主题草稿，重复运行复用同一身份，纯查询不改业务库；不调用模型，不把合同验证当真实教学效果。V2恢复包说明见 `work/day9/V2_RECOVERY.md`。

Day10接资料导入、有限上下文与计划确认冻结；Day11接四Agent、通用评分/守卫和共同预算入口；Day12才把V3接口和网页切换上线，旧V2历史只读；Day13做预先人工确认后的跨学科/新主题真实评价及干净环境运行。Day9不代替这些验收。
