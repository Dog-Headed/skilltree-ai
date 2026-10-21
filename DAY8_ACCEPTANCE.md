# Day 8：中文学习工作台验收

## 实现契约（2026-10-11）

本地 FastAPI 同源提供单个 HTML 页面；单 Uvicorn worker，绑定 127.0.0.1。沿用四类 Agent、两份 SQLite、同步 Graph 和顶层 recursion_limit=30。

桌面为 216px 项目栏 / 弹性阅读区 / 304px 技能路径。深色背景 #0B1017，荧光绿主操作 #C8F36A，青色当前节点；1024px 路径变抽屉，390px 两侧栏均为抽屉。节点依赖以真实 prerequisite_ids 文字表达 AND，不绘制虚假的线性依赖。

公开页面状态：learning / quiz / paused / completed / error / running。公共响应白名单包含 project_id、goal、nodes、completed_count、total_count、current_node_id、teaching_node_id、lesson_mode、page_state、pending_input_id、allowed_actions、lesson、conversation、quiz、answers、answer_error、results、rounds、round_limit、error、retry_token。结果仅来自本项目已评分业务记录，公开题面沿用 build_public_quiz。

| 接口 | 输入与行为 |
| --- | --- |
| GET / | 本地单页工作台 |
| GET /projects | 真实项目摘要；包含创建阶段失败的 Checkpoint 项目 |
| POST /projects | goal，request_id（UUID）；项目身份为 project_<UUID hex>，重复创建409，可按已知身份查询 |
| GET /projects/{id} | 只读恢复和公开投影；不执行 Graph 或模型 |
| POST /projects/{id}/resume | pending_input_id、action、message或answers；锁内校验最新等待点与权限 |
| POST /projects/{id}/retry | retry_token（失败 Checkpoint 身份）；只继续未完成节点 |

learning允许ask/start_quiz，前置复习增加return_to_current；quiz只允许submit_answer/return_to_teaching；paused允许rest/retry_3；error仅有可恢复失败时允许retry。非法输入422、项目不存在404、陈旧输入/并发执行409。错误消息固定公开文案，不回传原异常、路径或内部消息。

学习与答题的输入标识由独立 prepare 节点产生并先提交。合法的部分答卷是已接受事件，保留已有答案并更换输入标识；非法类型/题号/选项在API拒绝，不变更标识。rest只重新展示原暂停，不执行模型、不消费标识；retry_3只兑现当前标识一次。返回教学幂等标记 abandoned 后清理卷与草稿，下次生成新卷，不增加有效评分轮数。

前端只存项目身份与本页测验草稿；草稿键为项目+assessment_id，恢复前与公开卷匹配。请求按项目隔离，状态冲突或网络响应丢失先GET确认，不自动重放POST。Markdown使用DOM构造白名单，原始HTML作为文字显示，链接仅允许http/https。

## 验证记录

### 自动测试

执行环境：`D:\conda_envs\edu_agent\python.exe`，Python 3.11.15；FastAPI 0.117.1、Uvicorn 0.32.1、httpx 0.28.1，已加入固定版本依赖。

```powershell
D:\conda_envs\edu_agent\python.exe -m pytest -q
D:\conda_envs\edu_agent\python.exe -m pytest tests/test_day8_web.py -q
```

- 改动前基线：219 passed in 169.89s。
- 第一轮接入：新增22项API测试；全量241 passed in 180.68s。
- 浏览器发现补弱正文应从新教学轮开始，修复公开对话投影并增加一项回归；最终全量：**242 passed in 183.74s**。
- 加入`app.py`后，GitHub提交前再次全量复验：**242 passed in 180.24s**。启动入口从工作区根目录运行，正常加载项目包，服务就绪后自动打开浏览器，主页返回HTTP 200。
- 新增23项API测试：新建与只读恢复、追问、原卷跨应用实例恢复、部分答案及标识更换、连续两节点与AND解锁、全路径完成、弃卷、新卷身份、非法操作/答案/选项、暂停休息与额度幂等、追加测评、前置复习返回、创建失败保留身份、评分故障retry、双线程竞争、重复创建、缺失Checkpoint、公开嵌套字段检查、项目隔离及Origin校验。
- 原Day 6跨进程崩溃恢复、Day 7共享预算与暂停等219项全部继续通过。测试全部使用Fake模型与临时数据库。
- 页面JavaScript用`node --check work/day8/frontend-check.js`检查语法通过；页面使用Prettier 3.6.2整理，只格式化新增HTML，不批量格式化用户文件。
- 环境已有pytest-asyncio的fixture loop scope弃用提示；不影响通过，未更改用户现有测试配置。

### 浏览器检查（Codex内置浏览器）

实际启动并检查127.0.0.1服务，默认入口使用真实API，无演示降级。

| 视口 | 实际检查 |
| --- | --- |
| 1440 × 900 | 三栏、真实长中文目标、长课程、代码块、已评分记录、所有节点可滚动、节点详情和AND依赖 |
| 1024 × 768 | 左侧项目栏216px，右侧路径收为抽屉；document clientWidth/scrollWidth均1009（含15px纵向滚动条） |
| 390 × 844 | 单栏、项目与路径抽屉、完整单/多选和多行答案、刷新恢复草稿、补交、补弱与节点详情；clientWidth/scrollWidth均375，标题栏64px |

Fake页面通过公开API与浏览器实际检查：创建、追问、部分答卷提示、评分55/100后的补弱、暂停3/3→休息→增加3轮、前置复习与返回、失败后原项目retry、已完成8/8页面、追加测评、未解锁节点只读详情。条件场景的建立使用独立Fake库；连续两节点与全路径推进同时有API自动测试覆盖。

渲染安全：Fake课程包含`<img onerror>`、`<script>`与`javascript:`链接。浏览器内均显示为文字，学习主区域的脚本/图片/iframe/事件属性/危险链接元素计数为0。页面代码不使用不可信innerHTML；安全链接只允许http/https。公开接口递归字段检查不含answer_key、rubric、路径和内部消息，新测验不会混入已结束评价。

浏览器检查中修正了手机路径按钮竖排、正文切换后滚动停留、抽屉关闭时的键盘可达性、草稿清理、补弱课程重复以及评分列表的DOM插入；最终逐题反馈实际有4个条目，没有`[object HTMLElement]`占位文本。页面设置可见focus、标签、live状态、44px主要触控区域与prefers-reduced-motion规则。实际键盘验收完成：Tab进入路径节点、Escape关闭抽屉、Enter打开/确认返回教学、Ctrl+Enter发送追问。手机抽屉打开时移除纵向滚动条，clientWidth/scrollWidth同时为390。

### 真实模型演示（与Fake验收分开）

使用本地已有模型配置及新建的独立业务/Checkpoint数据库：`work/day8/real/`。未改动用户原项目成绩，没有读取私有answer_key辅助作答。

- 项目：`project_75a684733d6d4eef97c2d15c164e75c6`。
- 学习目标：从零学习Python变量、基本数据类型和条件判断，能写一个简单记账程序；Planner生成10个节点。
- 浏览器完成首课程「Python环境搭建与第一个程序」，追问编辑器/解释器和未保存文件的区别，收到真实回复。
- 根据公开题面独立填写2道单选、1道多选、1道多行简答，提交后真实评分15/15，Diagnosis建议advance。
- Graph进入「变量与赋值」，完成数1/10；在测评记录展开4道逐题反馈，原结果仍可查看。
- 完整重启真实验收服务后，project_id、current_node_id、pending_input_id、完成计数、assessment_id和得分全部保持；结果见`work/day8/real-restart-check.json`。
- 公开状态记录在`work/day8/real-public.json`与`work/day8/real-evidence.json`；均由公开API读取，无私有试卷字段。

这是一轮由Agent作答的有界真实链路验证，不是人工教学质量评估。没有把Fake效果写成真实模型效果，也没有声称真实模型已完成整条10节点路径。

### 截图

最终截图位于`work/day8/screenshots/`。文件名含real的是上面的真实验收项目，其他课程/分支截图为明确标记的Fake场景。

| 文件 | 内容 |
| --- | --- |
| desktop-welcome.jpg | 默认入口与新建目标 |
| desktop-learning.jpg | 桌面课程与节点路径（Fake） |
| desktop-quiz.jpg | 桌面单选、多选与多行测验（Fake） |
| desktop-paused.jpg | 轮数限制与保存的评分（Fake） |
| desktop-review.jpg | 考核节点与前置复习目标（Fake） |
| desktop-error.jpg | 保留项目的失败与重试（Fake） |
| desktop-completed.jpg | 整条路径8/8完成（Fake） |
| mobile-learning.jpg、mobile-quiz.jpg、mobile-path.jpg | 390px课程、测验与路径抽屉（Fake） |
| tablet-learning.jpg | 1024px布局过渡（Fake） |
| real-desktop-learning.jpg | 首节点完成后真实课程与1/10进度 |
| real-desktop-results.jpg | 真实评分、诊断与逐题反馈 |

### 已知边界与未验证项

- 本地单用户、单worker；未实现登录和多进程/多用户分布式锁。
- 没有输入标识的升级前存档保持只读错误说明，不自动迁移或重新规划；原CLI继续可用。
- 原成绩只读展示最近12条有效评分；历史无效演示记录跳过。完整记录仍留在业务库中。
- Markdown支持常用标题、段落、列表、表格、引用、链接与代码，复杂嵌套/扩展语法可能以简化排版或文字展示。
- 物理手机软键盘、系统减少动效开关、真实断网丢失响应，以及两个真实浏览器标签同时提交未做设备级/人工验证。相应响应式和减少动效规则已实现；并发提交由线程API测试验证，网络异常路径先GET确认且无POST自动重放。
- 真实服务仅运行一轮首节点闭环；其余困难诊断分支由明确Fake场景验证，教学质量需进一步人工评估。

## 页面与Graph的对应关系

页面根据allowed_actions发送ask/start_quiz/submit_answer/return_to_teaching等事件，API在项目锁中核对最新pending_input_id后交给LearningSession.resume，Graph执行到下一次interrupt。失败恢复使用retry与失败Checkpoint身份，不重新提交已固定答案。后端以Checkpoint等待类型决定当前画面，以业务完成事实决定进度/解锁，并从已结束测评构造评分记录。GET不运行Graph，输入身份在独立节点同步保存，重复/过期事件409，因此刷新和连点不会重复推进。

## 2026-10-13：诊断反馈可读性修复

问题来源是将内部诊断分析原样展示：目标 ID、题目 ID、错误标签和工具调用记录混入正文，并使长薄弱点标签不换行。中文编码本身正常。

- 公开反馈只读转换已结束测评：目标编号变为中文目标描述，题目与证据编号变为对应轮次/题号，错误标签转为中文或去掉附注；工具执行记录不进入学习反馈。Python 示例和具体报错名称保留。
- 原始 Diagnosis、评分、证据、项目进度和测验身份不变。用户截图对应的第二轮记录已在只读 SQLite 连接下验证；数据库文件哈希前后一致。
- 新诊断 Prompt 为`day8-v3-learner-feedback`，要求 reason 使用2–4句面向学习者的中文，内部证据仍独立填写在 evidence_ids，不新增模型调用。原 Day 7 真实评测报告仍对应旧版 v2，本次没有重跑真实模型评价。
- 逐题反馈按原试卷顺序展示，使正文中的“第几题”与展开反馈一致；长诊断分段显示，薄弱点标签允许换行。
- 新增8项回归覆盖旧记录转换且原诊断不变、刷新不调用模型、乱序评分、历史题号、Python代码与报错名称保留、未知旧编号、纯英文错误标签和追加测评兜底文案。专项35项通过；全量 **250 passed in 176.41s**。
- 独立 Fake 浏览器检查：桌面1280px与手机390×844；可见反馈不含内部编号/标签，页面宽度分别1265/375px且无横向溢出，手机长标签完整换行。截图：`work/diagnosis-feedback/desktop.png`、`work/diagnosis-feedback/mobile.png`。

重启`app.py`并刷新网页即可加载修复；已有学习记录使用同一展示转换，无需重新评分或新建项目。
