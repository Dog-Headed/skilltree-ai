# 单位学习最小契约（Day 1–2）

2026-11-05（4A 更新）。身份、入口、个人注册、单位成员选择、资料解析、课程发布、任务下发与员工开课已实现；进度看板见 Day 4。

## 关系与不变量

| 表／现有存储 | 关系与用途 |
|---|---|
| `auth_accounts` / `auth_sessions` | 复用真实密码校验、不可猜会话、CSRF；成员引用 canonical account，浏览器不能选择权限 |
| `training_units` → `training_members` | 虚构单位；账号最多属于一个单位；角色为 admin/employee；管理员可按邮箱加入已注册个人账号为员工 |
| `training_material_versions` | 单位、所有者、unit/private、版本、原件路径、解析路径、来源定位 JSON；Day 2 单位 ready 资料写入 version=1，供后续发布关联 |
| `training_course_versions` | 课程身份 + 版本唯一；知识树、必学节点、通过规则 JSON；发布版本行禁止更新／删除 |
| `training_course_materials` | 同单位课程版本 → 资料版本；Day 3 发布事务须固定完整资料关联，不能事后改变依据 |
| `training_tasks` | 同单位任务 → 一个已发布课程版本；标题、可空截止时间、创建者 |
| `training_employee_tasks` | 任务 × 员工唯一；独立项目 ID 唯一、首次开始时间；重复下发查回原记录，新一轮使用新 task ID |
| `training_node_bindings` | 员工任务／项目 → 课程节点与项目节点映射；项目必须属于该员工任务，不能复制管理员执行快照 |
| 现有 `learning_projects`、`learning_progress`、`assessments` 与两套 Checkpoint | 每名员工独立执行时间线；题目、作答、评价、补弱和正式达标事实仍由原引擎负责 |

学习库连接启用外键；跨单位课程／任务／成员关联被拒绝。同一课程版本可以被多个任务引用，一项任务可以关联多个独立员工项目。Day 1 只开放读取接口，运行库不预置课程、任务、成绩或学习统计；关系测试中的合成记录只存在 pytest 临时目录。

## 角色与隐私

- 服务端用会话中的 canonical account 查询成员表。请求体、URL、`X-Role`、`X-Evaluation-User` 不能改变角色。
- 管理员可读取本单位成员与学习列表；不因此获得员工私人项目、资料、对话、答案或 Checkpoint。现有 `/projects/...` 对管理员同样执行所有者检查。
- 员工只能读取自己的项目、队列任务和员工任务。`/training/api/my-tasks` 不接受目标员工参数。
- 学习实例保留游客，并开放个人注册。游客复用原有匿名身份、持久 Cookie、CSRF、个人项目归属、调用限额和队列；不插入单位成员表、不授予单位任务或管理权限。公网与本地使用不同账号库、会话 Cookie 名及数据目录。
- 游客可完成通用学习和个人资料学习（TXT/Markdown 与 PDF/DOCX/XLSX/PPTX）；`/session.training.role=guest`、`unit_id=null`。注册个人账号优先保留 canonical account；登录已有账号时沿用原有课程归属迁移，进行中的模型任务须先完成。
- 个人注册账号 `/session.training.role=personal`、`unit_id=null`：可自由学习与上传资料，不能访问单位任务或管理接口。请求体中的 role/unit_id/admin 参数一律忽略。
- 管理员按完整邮箱或账号 ID 查找已注册用户并加入本单位为员工；幂等；跨单位拒绝；不能经此接口提权为管理员或加入游客。后端脚本可授予管理员（见 `deploy/training_admins.py`）。
- 浏览器课程草稿、创建身份、选中项目、答案暂存沿用 `skilltree.v3.<encodeURIComponent(account)>.`。跨标签登录变更会刷新旧页；登出清除当前账号前缀。主题是公共偏好，不是学习数据。

## 状态与进度口径

员工任务的学习状态由真实学习事实派生，**不存可由客户端修改的 completed 或百分比字段**。尚未关联项目为“未开始”；已开始且未全部达标为“进行中”；全部必学节点按照原有评价与推进规则达标才是“已完成”。必要人工核验显示“待复核”；逾期为单独标记，不能覆盖学习状态或自动算完成。

进度 = **已达标必学节点数 / 课程版本全部必学节点数**，通过节点与课程节点通过映射核对。私人同名课程不抵扣学习。零节点不能推导出学习完成；技术失败不能记成学生答错或通过。员工开课后 `my-tasks` 已附必学节点进度摘要；完整管理看板见 Day 4。

## 已实现接口

| 方法／地址 | 当前行为与权限 |
|---|---|
| `GET /` | 未登录自动建立限速保护的游客身份 → `/training/home`；管理员 → `/training/admin`，员工 → `/training/home` |
| `GET /login` / `POST /auth/login` | 学习登录页；沿用 account/password/remember、`X-SkillTree-Login: 1`；设置 HttpOnly 会话 |
| `POST /auth/logout` | 必须有效会话 + `X-CSRF-Token`；撤销当前会话 |
| `POST /auth/register` | 开放个人注册；忽略客户端 role/unit_id；游客升级保留进度；返回个人账号会话 |
| `GET /session` | account/login/csrf_token/guest/logout + training(unit_id, unit_name, account, display_name, role) |
| `GET /training/api/me` | 当前成员或游客个人空间身份 |
| `GET /training/api/admin/overview` | 仅管理员：本单位 members、courses、tasks；publishing_available=false |
| `GET /training/api/admin/members/lookup?q=` | 仅管理员：按完整邮箱/账号 ID 查找已注册非游客；最少字段；不列目录 |
| `POST /training/api/admin/members` | 仅管理员：加入本单位为 employee；幂等；跨单位 409；忽略客户端 role |
| `POST /training/api/admin/members/remove` | 仅管理员：撤销员工成员身份，保留个人账号与学习数据；不能移除管理员 |
| `GET /training/admin/members` | 仅管理员：成员管理页 |
| `GET /training/api/my-tasks` | 当前成员的员工任务列表；learning_available=false；游客/个人账号 403 |
| `GET /training/admin[/materials\|/courses\|/tasks\|/dashboard]` | 仅管理员；`/materials` 已可上传／预览／下载单位资料；`/courses`、`/tasks`、`/dashboard` 仍为建设中或真实空状态 |
| `GET /training/home`、`/training/materials` | 员工、游客或个人账号首页、个人资料学习入口（含办公四格式上传／预览） |
| `GET /training/tasks` | 成员真实空任务页；游客 403 |
| `GET /learn` | 复用现有知识树与学习台页面；新增返回学习首页导航 |
| `GET/POST /projects`、`GET /projects/{id}` | 原有个人课程列表／目标创建／准备详情，执行所有权检查 |
| `POST /projects/{id}/resume` | 原准备和学习动作；confirm_profile 等慢操作进入现有持久队列，响应 202；返回稳定 job ID |
| `POST /projects/{id}/begin`、`/retry` | 原学习／恢复入口，不改变评价规则 |
| `GET /jobs/active`、`/jobs/{id}`、`/jobs/{id}/events` | 原账号隔离的任务读取／事件流 |
| `GET/POST /model-settings` | 原账号模型设置；密码与密钥不进入页面课程 DTO |

课程发布、任务下发与员工开始任务已开放（见下方 Day 3）。进度看板写接口仍未作为独立写面；未知路由 404。

## Day 3 发布 / 下发 / 开课（2026-11-05）

| 方法／地址 | 行为 |
|---|---|
| `POST /training/api/admin/courses/publish` | 仅管理员；冻结课程版本与资料关联；`request_id` 幂等 |
| `GET /training/api/admin/courses/{id}` | 仅管理员；读取已发布版本 |
| `POST /training/api/admin/tasks/assign` | 仅管理员；创建任务与员工任务行；`request_id` 幂等 |
| `GET /training/api/admin/tasks/{id}` | 仅管理员；任务与指派人 |
| `POST /training/api/my-tasks/{employee_task_id}/start` | 仅任务所属员工；按发布课程初始化独立项目并冻结；不调用 Planner 改写目标；`request_id` 幂等 |
| `GET /training/api/my-tasks` | 成员任务列表；`learning_available=true`；已开课附真实必学节点进度 |

发布后的课程版本与资料关联不可更新／删除。员工项目的 SourceChunk 在本项目内新建，不复制其他员工或管理员执行快照。

## Day 2 资料契约（2026-11-05）

`gateway.sqlite.training_assets` 保存账号所有者、private/unit 范围、单位、请求 UUID、内容指纹、标题、文件名和 processing/ready/failed 状态。上传在同一 HTTP 请求中完成解析，页面真实显示上传解析中；失败持久保存原因。重启将未完成的 processing 标记为 failed，不伪造成功。相同账号、范围和请求 UUID 重放复用原记录，变更内容 409。

私人资料属于游客或账号，管理员不能读员工私人资料；游客登录已有账号时与个人项目一起迁移归属。单位资料仅当前单位管理员可上传、预览和下载，员工暂不能读取未发布原件。单位 ready 资料同时建立不可变 `training_material_versions`（version=1），供下一天关联共享课程；每次新上传建立独立资料版本 ID，本阶段不提供覆盖修改。尚未发布或下发任何课程。

| 方法／地址 | 行为 |
|---|---|
| `GET/POST /training/api/materials` | 当前身份个人资料列表／上传解析；POST 字段 request_id(UUID)、filename、title、data_base64 |
| `GET /training/api/materials/{material_id}` | 本人解析状态；ready 时包含 parsed(content, blocks, warnings, parser, original_sha256) |
| `GET /training/api/materials/{material_id}/original` | 本人原件附件下载，不提供文件系统路径 |
| `POST /training/api/materials/{material_id}/attach` | 将已解析资料导入自己已有的课程草稿；project_id、request_id(UUID)；冻结或进行中项目 409，其他账号项目 404 |
| `/training/api/admin/materials[/{material_id}[/original\|/attach]]` | 同上资料能力，范围为本单位；服务端管理员检查；没有发布副作用 |
| `POST /projects/{id}/sources` | 保留粘贴正文、TXT/Markdown，并支持四种办公文件；沿用原有所有权、CSRF、排队准入和冻结保护 |
| `GET /projects/{id}/sources/{sid}/versions/{v}` | 原来源正文、片段，附 file 元信息和各片段重叠的 locations；私有测评来源继续禁止公开读取 |
| `GET /projects/{id}/sources/{sid}/versions/{v}/original` | 同样检查项目归属、可见性后下载保留的原件；不暴露服务器路径 |

四类办公原件最多 8 MiB，解析全文最多 12,000 字符；TXT/Markdown 仍最多 128 KiB。PDF 最多 10 页，PPTX 最多 15 张；XLSX 最多 8 表、总范围 500 单元格；单个 DOCX 表最多 500 单元格。Office ZIP 解压总量最多 8 MiB、512 项。超限整份拒绝，不静默截断。PDF 可带编辑/复制权限加密，只要无需打开密码即可读取；真正需要打开密码、扫描/无文字页、旧 Office、宏与加密 Office 暂不支持。公式保留原式及已有缓存，不执行或重算；缺缓存明确标注。

`SourceDocument/SourceChunk` 复用原模型和行号/哈希契约。解析正文的标题携带 PDF 页码、DOCX 章节/段落/表号、XLSX 工作表/范围、PPTX 张号/形状。学习库新增 `source_files` 保存资料版本对应的原件相对位置及结构元信息，和 SourceDocument 在同一事务写入；原件按 SHA256 留存于 `learning/original-files`。教学引用仍是 chunk_id/source_id/source_version，通过行范围与 blocks 对应，不另建虚构引用。

没有向量数据库或检索服务。现有学习引擎将完整教学资料片段组成有界上下文（序列化目录上限 24,000 字符）；多份资料累计超限时明确停止规划，要求缩小范围。解析成功不等于课程生成成功或完成学习；仍需真实模型规划、确认计划、讲解、原评价与推进事实。
