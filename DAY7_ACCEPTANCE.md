# Day 7 治理与评价验收

按《SkillTree AI Agent 学习版架构 V2.0》和 Astra 的 Day 7 任务增量实现；已有 Day 1–6、Step 1A/1B/2A/2B 保留。开发前全量基线为170项通过。

2026-10-11 第一轮开发验收：`216 passed in 193.81s`，新增46项测试。该轮只执行Fake评价，当时真实评价和人工预期复核尚未完成。

随后复验补齐 `AIMessage.invalid_tool_calls` 校验：损坏工具参数通过原共享预算最多修复一次，连续损坏直接停止，不能执行部分合法调用或进入最终诊断。真实适配器配合模拟HTTP新增3项回归，第一轮全量 `219 passed in 163.35s`；用户批准记录写入后最终全量 `219 passed in 167.58s`。

真实评价与人工预期现已补齐：用户在本次对话明确回复“确认 12 例预期”（记录时间2026-10-11 17:45:24 +08:00）。8例debug在修订提示后首次/最终结构均8/8、行动一致8/8；冻结同一Prompt后运行4例holdout，首次/最终结构均4/4、行动一致4/4。两组推进守卫模拟错误放行均0。模型为deepseek-flash，Prompt为day7-v2-prerequisite-evidence。

本批模型输出早于用户确认；教学预期没有随结果修改。原暂定报告保留，另存确认后的汇总，因此这些数字是用户确认预期后的描述性评价，不称为预先登记的盲测。原始/确认后报告、复核前后案例快照和批准记录见 `data/evaluation/reports/`；逐例复核清单见 `data/evaluation/EXPECTATION_REVIEW.md`。

## 评分与诊断

`grade_short_answer` 复用 `invoke_with_shared_budget`，每道简答题共享最多3请求/1网络重试/1输出修复，错误送入修复消息。负分、超满分、NaN/Inf 及结构错误都在写入前拒绝。客观题仍程序评分，不把整卷另做模型重试。

整卷 assessment_id、题号匹配、不漏评/不重复、逐题分数和有限总分复用原校验器；逐题 ID 与测验 ID 由程序绑定。全部合法才保存 evaluation，按业务库中已评分 assessment_id 去重计算轮数。推进守卫重新检查真实分数，不相信缓存百分比。

最终 DiagnosisResult 的结构、行动枚举、证据白名单和前置闭包在同一个逻辑调用里验证/修复。第二次输出仍非法即停止，diagnosis 不写库。工具选择模型也有独立 HTTP 预算，工具循环仍最多2轮/3次执行；进入executor的非法工具申请也消耗执行额度。适配器解析失败的invalid_tool_calls在执行前拒绝，只消耗HTTP模型预算。

证据收集提示包含当前目标和前置目标，要求按具体概念错误查询相关节点历史；completed只表示过去通过，不能排除当前薄弱点。两个前置案例新增按tool+node_id+查询成功检查的指标，避免把查询循环历史当作已查询变量／列表历史。本次两例均取到对应历史并引用当前及前置错误证据；没有强制低分都回退。

## 暂停与运行边界

每节点默认上限3。`advance` 且满足原通过条件优先推进，包括第3轮；否则达到上限先 `prepare_pause → pause`。pause 只做 interrupt 和输入校验，不调用 Agent、不写业务库、不增加额度。

休息继续等待，同一个暂停输入 ID 保留。再试3轮走独立 `extend_round_limit`，只增加当前节点上限且保留 rounds；记录已兑现暂停 ID 拦截重复兑现。纯 State 更新配合 Day 6 的同步 Checkpoint，后续 Tutor 失败重试从 Tutor 继续，不再次加额度。

新建、恢复输入、失败重试和所有已有交互入口都用顶层 `recursion_limit=30`。Tutor 仅取当前教学节点最近6轮完整对话；新消息标记节点，旧无标签消息仅按现有节点兼容，前进时继续清空旧消息。测验答案/rubric 不加入 Tutor 历史。

JSONL 日志使用白名单字段：project_id、node_id、assessment_id、node、logical_call_id、operation、request_count、network_retry_count、output_repair_count、elapsed_ms、tool、error_type。记录类型而不记录敏感异常正文。业务表仍原来的四张，没有引入新框架或迁移已有数据。

## 自动与手动验收

```powershell
D:\conda_envs\edu_agent\python.exe -m pytest tests/test_day7_governance.py tests/test_day7_pause_process.py tests/test_day7_evaluation.py -q
D:\conda_envs\edu_agent\python.exe -m pytest tests/test_invalid_tool_calls.py -q
D:\conda_envs\edu_agent\python.exe -m pytest -q
D:\conda_envs\edu_agent\python.exe evaluate_diagnosis.py --mode fake --split debug
```

新增测试覆盖评分/证据非法不落库不解锁、混合故障最多3请求、持续工具请求的2轮/3执行、第3轮失败/通过、休息无自动模型调用、独立进程重启暂停、额度重放、增加额度后失败重试、Tutor 六轮完整上下文和日志不含敏感异常文本。原 Day 6 跨进程崩溃、持久结果复用和同步保存对照全部继续运行。

手动用新项目连续三轮未通过，观察 pause；选择休息后退出并重启，确认仍停在 pause。主动再试，观察仅当前节点上限3→6，rounds保持3。第6轮仍未通过应再次暂停。第3轮通过应直接推进。

12案例的答案/评分/预期及允许证据现已由用户确认，已填写approved、reviewed_by=user和reviewed_at。原始模型报告中的null保持原样，确认后的报告重新汇总8/8与4/4行动一致、0错误放行；复用已保存输出，没有再次调用模型。Fake报告始终只验证管线。实际模型理由/工具/证据的逐例教学判断没有由助手代填为人工意见；可继续在manual_review记录用户意见。指标口径见data/evaluation/README.md。

开发仍遵循原限制：不承诺旧Checkpoint在State结构升级后的完全兼容。请用新演示项目验证新字段；默认上限回退为3，已有业务事实与SQLite不重建。这12例只用于发现诊断故障，不以结构率或行动一致率宣称学生学习效果提升。
