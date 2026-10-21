# Day 12 浏览器与公开 API 契约

实现日期：2026-10-20—21。沿用 V3 contract 3.0.0、Day 10 准备 Graph、Day 11 学习 Graph 和三份独立数据库，不改写 V2 数据。

## 启动与数据

日常入口 `app.py` 已统一为本新版工作台，自动打开浏览器，地址保持 `http://127.0.0.1:8765/`。旧进程需先停止后重新运行，不能只刷新页面。V2 历史仍通过只读适配读取。

已完成 Day 11 初始化的目录也可以使用独立入口启动：

```powershell
& 'D:/conda_envs/edu_agent/python.exe' day12_server.py --root data/v3 --port 8012
```

打开 `http://127.0.0.1:8012/`。现有 `day11_server.py` 也会提供同一网页。默认仅监听本机。初次安装请先按 Day 9—11 的显式初始化/迁移说明操作；启动和 GET 都不自动迁移业务数据。

业务库 `data/v3/learning.sqlite`；准备存档 `data/v3/checkpoints.sqlite`；学习存档 `data/v3/learning-checkpoints.sqlite`。默认 V2 历史只读读取 `data/learning.sqlite` 和 `data/checkpoints.sqlite`，可以用启动参数指定其他恢复副本。不存在的旧文件不会创建。

## 路由

| 方法与地址 | 输入/结果 | 行为 |
|---|---|---|
| GET `/`、`/assets/v3.js`、`/assets/v3.css` | 本地网页与静态文件 | 无模型调用 |
| GET `/projects` | V3 摘要数组 | 只读；V2 使用独立列表 |
| POST `/projects` | `{request_id,profile}` | UUID 确定项目身份；完全相同请求复用；不同载荷冲突 |
| GET `/projects/{id}` | 公开学习视图 | 不运行 Graph、不自动恢复、不请求模型 |
| POST `/projects/{id}/begin` | `{request_id}` | 仅已冻结正式计划或明确选择的探索项目可开始；已有会话复用 |
| POST `/projects/{id}/resume` | `{request_id,pending_input_id,draft_revision,action,...}` | 按当前阶段接受准备或学习命令 |
| POST `/projects/{id}/retry` | `{request_id,retry_token,action}` | action 为 retry 或 continue_with_new_budget；不会重置逻辑任务预算 |
| POST `/projects/{id}/sources` | request_id/title/source_description/visibility + content 或 filename/data_base64；可带 source_id 更新版本 | 只导入，不暗中恢复 Graph；改变资料使旧计划确认失效 |
| GET `/projects/{id}/sources` | 教学来源目录 | 只列可公开内容；正式项目只列冻结版本 |
| GET `/projects/{id}/sources/{source_id}/versions/{version}` | 来源说明、原文、哈希、片段及行号 | 项目内精确版本；私有来源和越权请求 404 |
| PATCH `/projects/{id}` | `{display_name}` | 仅改变显示名称，1—80 字符；不改原目标或冻结标准 |
| DELETE `/projects/{id}` | `{confirm_project_id}` | 删除所选 V3 业务记录和两类存档；保留最小删除回执，旧创建请求不能复活记录 |
| GET `/capabilities` | 服务端实际能力表 | 不接受模型或资料注册执行工具 |
| GET `/material-packs`、`/material-packs/{python,mathematics,english}` | 三科示例档案及公开教学资料 | 无私有答案、案例或保留验证题；仍保留待用户审核标记 |
| GET `/legacy/projects`、`/legacy/projects/{id}` | version=v2、read_only=true、allowed_actions=[] | 专用 SQLite 只读适配；不反序列化或执行旧 Checkpoint |

所有写请求在同一项目的进程锁与操作系统锁内完成检查、阶段分派和执行，嵌套服务调用复用本线程持锁身份。V2 ID 的 V3 写请求返回 `409 legacy_readonly`。V3 查询旧 ID 返回 404。中断中的项目先恢复操作，再删除，避免与未完成写入竞态。

重命名/删除使用附加的 `web_project_metadata` 表，仅第一次显式管理写操作建表；读取旧目录不建表。删除回执不保存课程正文。删除后清理存档若中断，可重复 DELETE 完成；恢复和旧创建请求不能重新生成项目。

## 公开字段与动作

页面只根据 `allowed_actions` 展示按钮。每次请求携带当时的输入身份；服务器验证当前身份，不能把旧答案作用于新卷。

| page_state | 可用动作（服务端按条件裁剪） |
|---|---|
| profile_review | confirm_profile、update_profile、import_material、rest |
| materials_required | import_material、adjust_scope、replan；明确允许时 choose_exploration；rest |
| plan_review | confirm_plan、adjust_plan、import_material、replan、rest；过期草案移除 confirm_plan |
| learning / exploring，学习 Graph 尚未启动 | begin |
| learning | ask、start_quiz、rest；先修回顾时 return_to_current |
| exploring | ask、rest；无正式出题与通过权限 |
| quiz | submit_answer、return_to_teaching、rest |
| assessment_review | view_feedback、annotate_dispute、replace_assessment、return_to_teaching、rest |
| paused | rest；首次轮数用完可 retry_3；追加后仍暂停，允许 return_to_teaching；换题上限后只暂存 |
| budget_exhausted | continue_with_new_budget（最多一次）、rest；已追加则只暂存 |
| error | retry；按业务状态允许 return_to_teaching、受限 replace_assessment、rest；中断恢复时只 retry |
| running / completed / legacy_readonly | 无业务写动作；仍可只读刷新或浏览历史 |

公开视图包括 profile、plan/nodes/progress、sources、tutor/conversation、公开 quiz、分目标 feedback、guard、rounds、operation_budget 和版本/恢复身份。nodes.passed 来自唯一完成记录；feedback.guard 按对应 assessment_id 取 transition，不能把上一节点通过误显示成本卷通过。前端展示分数和冻结门槛，不把它们称为掌握概率，也不自行使用 80 分判定通过。无法可靠评价时不展示伪造的零分。

只公开题面、选项和满分，不公开答案键、量规、数值参考规则、完整 State、内部评价/诊断 JSON、私有资料标题与片段 ID、路径或密钥。反馈采用窄字段与已知私有内容过滤；这不是语义层面防止所有答案转述的证明，内容质量仍需独立评估。

## 错误与断连

- 409 state_conflict：输入身份或状态过期；页面先 GET 最新状态，再由用户决定下一步。
- 422 invalid_input：载荷或当前动作不合法；不回显请求原文。
- 404 not_found：记录/公开资料版本不存在或不可读取。
- 403 invalid_origin：跨来源网页写入被拒绝。
- 500 service_error：隐藏内部异常；提示先查状态，不盲重放。

2026-10-21 修正：学习任务已达到请求上限或已终止输出修复时，公开 `error_code=model_task_exhausted` 与粗粒度 `failed_task_kind`，不再提供普通 retry；用新请求身份重试终止任务，在写入前返回 409。已记账重试命令的完全相同重放仍只返回当前投影。Tutor 可通过原 `return_to_teaching` 动作显式“重新生成讲解”，作为新的教学请求；旧任务及消耗保留，不重置原预算。临时技术故障仍可在原任务剩余额度内 retry。中断执行的 journal 恢复和已保存结果复用保持原逻辑。内部异常标识在网页折叠显示。

浏览器写请求只有一次 fetch，没有自动写重试。响应截断/断连后先 GET 项目与列表；创建请求使用已保存的 UUID 定位项目，重复创建仍复用身份。作答草稿按 project_id + assessment_id 保存；切换试卷不会沿用旧答案。忙碌时阻止连点；跨标签页由服务器身份检查兜底。

创建请求身份仅保留到结果明确为止：收到成功响应或 GET 确认项目存在后，结束该次请求；再次“新建学习”即使档案相同，也使用新的 UUID。旧版遗留的创建缓存先只读核对，再结束已成功的请求；断连或项目尚不存在时保留原身份供用户重试。示例资料批量导入结束后，统一恢复记录切换及更多菜单按钮，失败和查询恢复失败也会解除忙碌状态。

资料和模型文字用 DOM 文本节点渲染；HTML 不解释，javascript 链接不生成。支持安全 Markdown 代码块和常用公式符号、上下标、简单分式文本；复杂 LaTeX 原样保留，不宣称完整符号排版或证明。静态资源不依赖外部 CDN，CSP 限制本源脚本。

## 验证入口

`tests/test_day12_public_api.py`、`tests/test_day12_legacy.py`、`tests/test_day12_legacy_api.py`、`tests/test_day12_reliability.py`。跨进程断点见 `tests/day12_process_worker.py`；浏览器隔离演示可使用 `day12_demo_server.py --root work/新演示目录 --port 18120`，必须明确标记 Fake，不使用部署目录。

前端交互回归：`python -m pytest tests/test_day12_frontend.py -q`，需测试环境提供 Node 和 Playwright；Windows 默认使用已有 Edge 的独立无界面实例，其它环境使用 Playwright Chromium。可用 `SKILLTREE_TEST_BROWSER_CHANNEL` 指定已安装浏览器、`SKILLTREE_TEST_NODE` 指定 Node，`DAY12_FRONTEND_EVIDENCE_DIR` 保留截图和请求序列；不会改运行依赖或访问部署库。
