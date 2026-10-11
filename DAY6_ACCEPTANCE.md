# Day 6 Step 5 验收

最终演示使用独立的业务库与 Checkpoint。`planner → persist_plan → tutor → wait_learning` 已接入真实图；通过节点后继续学习下一节点，整棵树完成才 END。所有执行入口显式采用 `durability="sync"`，包括 `LearningSession` 的新建、恢复输入和失败重试，以及 Day 6 复用的交互函数。

## 手工跨进程演示

在项目目录运行：

```powershell
D:\conda_envs\edu_agent\python.exe day6_restore_demo.py
```

1. 选择新建项目，记录显示的项目 ID。在教学菜单不输入，按 Ctrl+C 退出整个进程。
2. 重新启动，选择继续已有项目，选刚才的项目。教学内容与对话仍在，当前节点不变；可以继续提问。
3. 选择开始测验，记录测验 ID 和第一题，再按 Ctrl+C 退出。
4. 重新启动并选择同一项目。等待点仍为 `wait_answer`，ID 和原卷相同；恢复不会重新规划或出题。
5. 正常提交答案。观察评分、诊断和下一分支。通过后进入下一节点教学，当前轮次临时字段被清空。
6. 再退出整个进程。在新进程中查看原测验的业务事实：

```powershell
D:\conda_envs\edu_agent\python.exe day6_restore_demo.py --project-id 记录的项目ID --inspect --assessment-id 记录的测验ID
```

该测验必须仍有原卷、答案、Evaluation 和 Diagnosis，状态为 `graded`。通过轮次的完成时间与完成测验 ID 必须仍在。检查模式公开原题面，不展示私有答案和评分规则。

可用 `--pause-at-learning` 和 `--pause-at-quiz` 自动退出对应等待点；`--inspect` 只读取存档，不调用模型。已有业务项目若缺少 Checkpoint，会明确拒绝初始化，避免覆盖旧学习记录。

## 八项回归验收

| 验收项 | 覆盖与判定 |
| --- | --- |
| 教学等待点恢复 | 子进程启动、`os._exit` 退出，新进程恢复原课程和对话，再追问；Planner 计数不增加 |
| 答题等待点恢复 | 新进程恢复完整私有原卷、稳定测验 ID 和等待中断；公开题面不含答案和评分规则 |
| 评分后恢复 | 当前 State 进入下一节点并清空临时字段，原评分和诊断仍从业务库查出 |
| 试卷落库后失败 | 测验 ID 的 Checkpoint 与增量写入均延迟 0.75 秒；试卷业务提交后在写入回调内立即 `os._exit`，不抛异常、不等待图结束。会话和交互入口均恢复到 `assessment_generate`，ID 与完整原卷不变、出题次数不增加，测验只有一条 |
| 评分落库后失败 | 提交评分后模拟节点失败，退出进程再 retry；评分模型次数不增加 |
| 项目隔离 | 同名节点在两个项目中分别保存历史与完成记录，查询不串项目 |
| 完成幂等 | 重试原 advance 多次，完成记录仍唯一，原时间和完成测验 ID 不变 |
| Planner/出题不重复 | 等待点只恢复，不启动图；另测 Planner Checkpoint 后业务写入失败，重试 persist_plan 不再规划 |

对应测试：`tests/test_sqlite_checkpoint_recovery.py`、`tests/test_day6_final_acceptance.py`、`tests/test_real_database_tools.py`。还验证整棵树按前置条件推进、对话清理、菜单非法序号、缺失 Checkpoint 拒绝初始化和跨项目测验查看拒绝。

延迟写入测试还有显式切回 `async` 的对照：在同一故障窗口中，试卷已落库但测验 ID 的 Checkpoint 尚未提交，重启回到 `assessment_prepare`，读不到原 ID，重试后产生两条试卷记录。测试同时延迟完整 Checkpoint 和含 ID 的增量写入，避免增量写入提前保存 ID 而错过故障窗口。该对照确保测试确实能发现原漏洞，而不是通过异常收尾等待后台写盘后才结束进程。

## 全量运行

```powershell
D:\conda_envs\edu_agent\python.exe -m pytest -s
```

同步持久化修复后的全量结果：`124 passed`，新增的三个用例覆盖会话入口、交互入口和异步对照。运行日志保存在 `data/day6_sync_pytest.log`。

普通 pytest 使用临时 SQLite 和模型替身，阻止真实模型服务调用；子进程测试也显式使用临时的两个数据库，不写入用户的 `data/learning.sqlite` 或 `data/checkpoints.sqlite`。真实模型演示使用本地 `.env` 配置；专门验收时使用新的项目 ID，保留既有项目。

Day 4 保留单节点闭环演示，用 InMemorySaver；Day 6 的 SQLite 会话运行完整多节点流程。
