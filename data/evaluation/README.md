# Day 7 诊断评价

`cases/` 有12个案例：3 advance、3 remediate、2 critical_misconception、2 collect_more_evidence、2 prerequisite_issue。每个含完整节点和目标/依赖、学生答案、评分证据、工具可查询历史及完成事实、草案期望和证据白名单。8个 debug，4个 holdout。

所有 `human_expectation` 由助手起草，已于2026-10-11由用户明确回复“确认 12 例预期”统一批准，填写 `approved`、`reviewed_by=user` 和时间。行动、理由、学生答案、评分及允许证据没有根据模型回答调整。复核清单见 `EXPECTATION_REVIEW.md`；前后快照和批准记录在 `reports/`。

本次真实输出先于用户批准。原始暂定报告不覆盖，确认后另存 `real-debug-v2-user-reviewed.*` 和 `real-holdout-v2-user-reviewed.*`，复用输出汇总，不重复请求。确认后的数字属于描述性评价，不声称预先登记的盲测。未来新增案例仍应在运行模型前完成人工复核；未复核案例的正式指标保持null。

在仓库根目录运行，不需要密钥的流程验收：

```powershell
D:\conda_envs\edu_agent\python.exe evaluate_diagnosis.py --mode fake --split debug
```

Fake 固定发出补弱建议且首次伪造证据，验证一次业务修复，不依照预期标签生成“标准答案”。它验证评价管线，不代表真实模型能力。

用户复核后手动运行真实模型（读取现有 .env）：

```powershell
D:\conda_envs\edu_agent\python.exe evaluate_diagnosis.py --mode real --split debug
```

仅在调试结束后验证保留组：

```powershell
D:\conda_envs\edu_agent\python.exe evaluate_diagnosis.py --mode real --split holdout
```

`--output 路径.json` 可指定输出位置；同时产生 Markdown 报告和 `.events.jsonl` 结构化日志。默认保存到 `reports/`。工具调用实际使用原有 executor 查询每案例独立的临时 SQLite；退出后删除临时库，不更改用户学习记录。模型使用与产品相同的有界工具循环及最终诊断治理。

runner 记录每次最终输出的结构/业务合法性、动作、真实推进守卫模拟、工具名与参数、证据、请求与修复次数、耗时、Prompt/案例版本和哈希。真实模型的可获得 usage 从原始消息提取；服务不返回时保存 null。网络失败不纳入“首次收到的输出”分母，但计入运行失败。

前置问题案例增加 `required_tool_queries`，按工具名、node_id及成功状态检查。`required_tools_used` 只证明调用过该工具；不能证明查询的是相关前置节点。对应查询指标只以声明必要查询的案例为分母。本次两例前置问题均查询对应变量／列表历史，2/2。

本次Prompt为 `day7-v2-prerequisite-evidence`：先对照节点目标查询相关前置历史，禁止从completed推断现在没有薄弱点。真实debug8首次/最终结构8/8、行动一致8/8；调试结束冻结Prompt后holdout4首次/最终结构4/4、行动一致4/4；两组错误放行均0。用户提供的原v1调试报告归档为 `real-debug-v1-review.*`，原样保留6/8暂定行动一致率。保留组运行后未再修改Prompt。

工具/证据白名单检查不等于教学合理性；JSON 的 `manual_review` 留给用户逐例填写。报告模板见 `REPORT_TEMPLATE.md`。本版评测只模拟路由，不执行 advance 节点；“错误放行”指本应拦截却经守卫允许推进的案例数。
