# Day 12｜API、网页与可靠性集成交付

日期：2026-10-21。开发与本轮自动/浏览器验证完成，待用户亲自体验页面。保留原 Day 1—11 成果与 V2 运行数据，未升级旧 Checkpoint。

## 实际验证结果

- **全量：805 passed in 509.44s（8 分 29 秒）**。日志：[full-pytest-final.log](work/day12-delivery/full-pytest-final.log)。本轮新增 46 项测试，使用实际运行结果，不沿用上轮数量。
- 独立故障/恢复验证：新增 12 项与原 Day 11 恢复 11 项联合运行 23 项通过；这 12 项也包含在最终全量中。报告：[故障矩阵](work/day12-reliability/Day12_故障矩阵与恢复证据.md)、[逐例数据](work/day12-reliability/matrix.json)。
- 浏览器实际走通三科各 2 个依赖节点，覆盖选择、数值、文字题、刷新草稿、连点、两个标签页和截断响应后的只读恢复；另检查复核、换题、错误重试、轮数暂停、探索及旧版历史。详见[操作记录与截图](work/day12-browser/Day12_浏览器操作记录.md)。
- 5 份原部署数据库在最终验证前后 SHA-256 全部一致：[数据保留证据](work/day12-delivery/runtime-preservation.json)。所有测试写入隔离目录，正式端口只做 GET 检查。

第一轮全量发现旧 Day 10 演示子类没有新注入模型属性导致 AttributeError，已兼容并通过定向复验与最后全量。浏览器联调修复了档案版本、删除后选中状态、窄屏题型标签和历史字段适配。反馈守卫按 assessment_id 关联，避免把上一节点的通过显示为当前待复核试卷通过。

## 完成范围

| 验收点 | 证据与结论 |
|---|---|
| 三科同一网页/接口，至少两个依赖节点 | 已验证；真实服务链路 + Fake provider，用于流程证明 |
| 分数/必要目标/通过状态 | 分目标反馈显示冻结标准；是否通过读取 guard/唯一完成事实，前端不硬编码 80 分或掌握概率 |
| 新状态与出口 | 档案、资料、计划、学习、作答、复核、预算追加、暂停、错误、中断、完成、探索、legacy 均有页面/允许动作 |
| 过期输入与重复操作 | pending_input_id / draft_revision / assessment_id / retry_token 校验，旧计划确认与旧卷提交均拒绝；原命令重放复用结果 |
| 私有资料和公开视图 | 白名单题面、过滤反馈、公开资料版本/行号；私有答案/量规/片段身份/原始 State/密钥不直接序列化 |
| 保存后突然退出 | quiz/evaluation/diagnosis/completion 四个硬退出断点恢复复用；调用计数与事实数量匹配，无重复完成 |
| 预算追加提交后突然退出 | 复用已提交 child，只有一份追加，assessment_id 不变；普通 retry 不刷新额度 |
| 等待、刷新、响应丢失 | 纯 GET 不写业务或请求模型；等待重入无业务副作用；真实浏览器截断响应后先 GET，未自动 POST 重放 |
| V2 历史 | 专用 SQLite mode=ro 投影、版本与只读标识；所有 V3 写接口拒绝旧项目；不解码旧 Checkpoint |
| 桌面/390px 与安全显示 | 已保存截图；代码块独立滚动，常用公式可读；资料中的脚本/危险链接不执行 |

**证据边界：**本轮没有收费真实模型请求，Fake 流程/评分结果不证明真实教学质量。三科材料与 36 个案例仍保留待人工复核状态；Day 7 已确认的 12 例不自动替代这些 V3 标准。复杂 LaTeX 当前保留可读原文，未引入完整数学排版引擎。

## 使用

2026-10-21 入口补正：用户日常运行的 `app.py` 原来仍加载 V2，现已统一加载与 Day 12 相同的 V3 工作台，保留 8765 端口和自动打开浏览器。旧服务需停止后重启；V2 数据仍仅通过历史适配查看。此前 805 项结果对应本补正前的完整测试；本次启动入口与 Day 12 公开接口定向验证 **13 passed in 15.39s**，包括正常入口、实际 V3 页面/接口、数据不变和不兼容存储拒绝回退：[日志](work/day12-delivery/launcher-tests.log)。

正式工作台：**http://127.0.0.1:8012/**，使用现有 `data/v3` 与真实模型配置。旧 V2 默认只读展示。当前服务已打开供用户体验；没有自动执行现有草案的恢复或模型调用。

重启方式：

```powershell
& 'D:/conda_envs/edu_agent/python.exe' day12_server.py --root data/v3 --port 8012
```

详细路由、公开字段、状态/动作、初始化约定、错误和恢复语义：[DAY12_API.md](docs/v3/DAY12_API.md)。

隔离 Fake 演示使用 `day12_demo_server.py --root work/新目录 --port 18120`；它不会访问部署数据。截断响应注入和预置异常项目只存在隔离演示，不进入正式服务。

## 修改文件

- 公开接口与投影：`app/v3/learning_api.py`、`public_view.py`、`legacy.py`。
- 管理与兼容：`app/v3/project_management.py`、`execution.py`、`preparation.py`、`contracts.py`、`capabilities.py`。
- 网页：`app/static/v3.html`、`v3.js`、`v3.css`，沿用深色与绿色视觉、三点菜单和本机草稿。
- 启动与隔离演示：`day12_server.py`、`day12_demo_server.py`。
- 测试：`tests/test_day12_public_api.py`、`test_day12_legacy.py`、`test_day12_legacy_api.py`、`test_day12_reliability.py`、`day12_process_worker.py`。
- 文档：本文件、`docs/v3/DAY12_API.md`；证据目录 `work/day12-browser`、`work/day12-reliability`、`work/day12-delivery`。

代码/测试/API 文件哈希清单：[changed-files.json](work/day12-delivery/changed-files.json)。未提交 Git，未覆盖已有未提交修改，也未把 .env 或运行库加入交付包。

## 用户下一步

请在正式页面亲自体验一次创建、资料、计划与学习流程，检查操作感；三科内容与人工标准的独立质量评价继续留给 Day 13。本轮未发现仍阻断 API/网页/恢复流程的已知问题。

## 2026-10-21 独立验收后的前端修复

独立验收发现的“相同档案新建复用已完成项目”和“导入示例后列表按钮未恢复”已修复。新增 8 项实际 Edge 页面回归，联合公开接口和学习接口共 **26 项通过（49.78s）**；同档案重学保留旧完成事实，断连重试仍复用原身份，导入成功及失败后均可切换记录并打开菜单。五份部署数据库哈希一致。本轮为定向复验，没有把独立报告原有 829 项全量结果记作新增验证。详见 [修复记录与浏览器证据](DAY12_FRONTEND_REPAIR_20261021.md)；待用户审阅结项。
