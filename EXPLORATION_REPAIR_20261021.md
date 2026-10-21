# 探索讲解误拦截与无效重试修复

2026-10-21，依据用户“我都懂了”后的真实失败记录定位。

## 原因

1. 模型首次返回的说明包含“我不会据此认为你已经通过……”。原 Tutor 校验只搜索“你已经通过”，忽略同一分句中的明确否定，误触发输出修复。
2. 该任务输出检查最终停止后，页面仍提供 retry。重复点击不会发出新模型请求，却不断返回 LogicalTaskExhausted，造成无法继续的错觉。2/12 是本操作请求消耗，不代表原任务仍有输出修复次数。

## 修改

- `app/v3/tutor.py`：允许由同一分句的明确否定词和判断动词支配的宣称，例如“不会据此认为……”。否定出现在其他句子、转折后的独立肯定宣称、双重否定均不能绕过检查。实际通过仍只由确定性守卫与完成记录决定。
- `app/v3/learning.py`：从当前 operation 家族的持久化任务判断是否已终止；完成缓存和中断 journal 恢复保持原处理。终止任务不公开普通 retry，接口也在记账前拒绝。仍允许合法的教学/受限换题/暂存等恢复路径。
- `app/static/v3.js`：终止的教学任务显示“重新生成讲解”，沿用 return_to_teaching 动作。错误标识折叠，主提示使用易懂说明。
- `tests/test_v3_tutor_denial_recovery.py`：复现原句、检查中英文否定/真正宣称/转折与双重否定，以及任务停止、重复重试、重启、重新生成、技术故障和坏评分不落库。
- `tests/test_v3_learning_recovery.py`：将坏评分后的旧重试预期更新为明确拒绝，继续验证没有新调用、重试记账、评分、诊断或完成记录。

“重新生成讲解”是用户显式发起的新教学请求，旧任务的次数、错误和记录保持不变；没有增加共享预算上限或重新放行失败的评分。没有自动把探索切换为正式模式。

## 验证

- 定向验证：**84 passed in 24.34s**，日志 `work/exploration-fix-20261021/targeted.log`。
- 恢复专项：**32 passed in 64.51s**，日志 `work/exploration-fix-20261021/recovery-regressions.log`，包含进程突然退出、冻结结果复用及坏评分拒绝重试。
- 首轮全量为 828 通过、1 失败：旧用例仍要求耗尽后的 retry 返回错误投影。已按新行为改为断言 ConflictError，并增加不记账、不改业务事实的检查；评分安全断言保留。
- 隔离浏览器实际检查：停止的任务没有普通重试按钮；“重新生成讲解”可回到同一项目的探索问答。截图 `recovery-options.png` / `exploration-recovered.png` 位于同一证据目录。使用 Fake 模型验证状态，无收费 HTTP。
- 恢复后的旧任务仍为 invalid、2 次请求/1 次修复；新教学为 completed、1 次请求；测评记录数为 0。证据 `browser-recovery-evidence.json`。原部署五份数据库哈希均未改变，见 `runtime-preservation.json`。
- 最终全量：**829 passed in 632.18s（10 分 32 秒）**，日志 `work/exploration-fix-20261021/full-pytest-final.log`。五份原部署数据库再次校验均与修复前一致。

用户原学习记录只读检查时已回到 exploring，先前失败任务保留；修复不修改或删除用户学习记录。已在确认无执行中 journal 后，仅重启 Agent 之前启动的 8012 服务；GET 验证新字段可用、原项目仍为 exploring，重启前后五份数据库哈希一致。证据 `product-restart-evidence.json`。用户自行启动的 `app.py` 进程未停止，需用户重启后加载修复。
