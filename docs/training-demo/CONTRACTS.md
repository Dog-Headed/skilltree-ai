# 单位培训最小契约（Day 1）

2026-11-04。只建立身份、页面入口、数据关系，发布和下发尚未实现。

## 关系与不变量

| 表／现有存储 | 关系与用途 |
|---|---|
| `auth_accounts` / `auth_sessions` | 复用真实密码校验、不可猜会话、CSRF；成员引用 canonical account，浏览器不能选择权限 |
| `training_units` → `training_members` | 一个虚构单位，1 管理员、3 员工；当前账号唯一单位、角色为 admin/employee |
| `training_material_versions` | 单位、所有者、unit/private、版本、原件路径、解析路径、来源定位 JSON；Day 1 无上传记录 |
| `training_course_versions` | 课程身份 + 版本唯一；知识树、必学节点、通过规则 JSON；发布版本行禁止更新／删除 |
| `training_course_materials` | 同单位课程版本 → 资料版本；Day 3 发布事务须固定完整资料关联，不能事后改变依据 |
| `training_tasks` | 同单位任务 → 一个已发布课程版本；标题、可空截止时间、创建者 |
| `training_employee_tasks` | 任务 × 员工唯一；独立项目 ID 唯一、首次开始时间；重复下发查回原记录，新一轮使用新 task ID |
| `training_node_bindings` | 员工任务／项目 → 课程节点与项目节点映射；项目必须属于该员工任务，不能复制管理员执行快照 |
| 现有 `learning_projects`、`learning_progress`、`assessments` 与两套 Checkpoint | 每名员工独立执行时间线；题目、作答、评价、补弱和正式达标事实仍由原引擎负责 |

培训库连接启用外键；跨单位课程／任务／成员关联被拒绝。同一课程版本可以被多个任务引用，一项任务可以关联多个独立员工项目。Day 1 只开放读取接口，运行库不预置课程、任务、成绩或学习统计；关系测试中的合成记录只存在 pytest 临时目录。

## 角色与隐私

- 服务端用会话中的 canonical account 查询成员表。请求体、URL、`X-Role`、`X-Evaluation-User` 不能改变角色。
- 管理员可读取本单位成员与培训列表；不因此获得员工私人项目、资料、对话、答案或 Checkpoint。现有 `/projects/...` 对管理员同样执行所有者检查。
- 员工只能读取自己的项目、队列任务和员工任务。`/training/api/my-tasks` 不接受目标员工参数。
- 培训实例关闭访客和注册；复用原有登录、登出、来源检查、CSRF、归属和队列。公网与本地使用不同账号库、会话 Cookie 名及数据目录。
- 浏览器课程草稿、创建身份、选中项目、答案暂存沿用 `skilltree.v3.<encodeURIComponent(account)>.`。跨标签登录变更会刷新旧页；登出清除当前账号前缀。主题是公共偏好，不是学习数据。

## 状态与进度口径

员工任务的学习状态由真实学习事实派生，**不存可由客户端修改的 completed 或百分比字段**。尚未关联项目为“未开始”；已开始且未全部达标为“进行中”；全部必学节点按照原有评价与推进规则达标才是“已完成”。必要人工核验显示“待复核”；逾期为单独标记，不能覆盖学习状态或自动算完成。

进度 = **已达标必学节点数 / 课程版本全部必学节点数**，通过节点与课程节点通过映射核对。私人同名课程不抵扣培训。零节点不能推导出培训完成；技术失败不能记成学生答错或通过。Day 1 不计算／展示培训进度，Day 3–4 接入真实事实后实现。

## 已实现接口

| 方法／地址 | 当前行为与权限 |
|---|---|
| `GET /` | 未登录 → 登录；管理员 → `/training/admin`，员工 → `/training/home` |
| `GET /login` / `POST /auth/login` | 培训登录页；沿用 account/password/remember、`X-SkillTree-Login: 1`；设置 HttpOnly 会话 |
| `POST /auth/logout` | 必须有效会话 + `X-CSRF-Token`；撤销当前会话 |
| `POST /auth/register` | 403，本阶段只用预置身份 |
| `GET /session` | account/login/csrf_token + training(unit_id, unit_name, account, display_name, role) |
| `GET /training/api/me` | 当前成员 |
| `GET /training/api/admin/overview` | 仅管理员：本单位 members、courses、tasks；publishing_available=false |
| `GET /training/api/my-tasks` | 当前账号的员工任务列表；learning_available=false |
| `GET /training/admin[/materials\|/courses\|/tasks\|/dashboard]` | 仅管理员；首页或清楚的功能建设中页面 |
| `GET /training/home`、`/training/materials`、`/training/tasks` | 员工首页、资料建设中、真实空任务页 |
| `GET /learn` | 复用现有知识树与学习台页面；新增返回培训首页导航 |
| `GET/POST /projects`、`GET /projects/{id}` | 原有个人课程列表／目标创建／准备详情，执行所有权检查 |
| `POST /projects/{id}/resume` | 原准备和学习动作；confirm_profile 等慢操作进入现有持久队列，响应 202；返回稳定 job ID |
| `POST /projects/{id}/begin`、`/retry` | 原学习／恢复入口，不改变评价规则 |
| `GET /jobs/active`、`/jobs/{id}`、`/jobs/{id}/events` | 原账号隔离的任务读取／事件流 |
| `GET/POST /model-settings` | 原账号模型设置；密码与密钥不进入页面课程 DTO |

课程发布、培训下发、员工开始任务与进度看板 **没有开放写接口**。`/training/...` 写请求对员工先校验管理员范围（403），管理员在正确 CSRF 下仍返回 405。未知路由 404。现有 TXT/Markdown 课程资料接口仍保留；四类办公文件适配留 Day 2。
