# Day 11 教学与评价后端

交付日期：2026-10-20。架构依据：`SkillTree_通用学习Agent架构_V3.0.md`。

## 数据与运行入口

V2 网页入口保持原有服务；本轮增加项目三点菜单、显示名称与单条删除。V3 学习后端独立运行，网页全面接入仍属于 Day 12。

```powershell
# 本次默认 data/v3 已完成此增量迁移，并保存配对备份。
# 其他既有 V3 目录必须停写，指定一个尚不存在的备份目录：
& D:/conda_envs/edu_agent/python.exe day11_storage.py --root data/v3 --backup work/my-new-day11-backup

# 新的空目录可省略 --backup；不要把 V2 data 目录作为 V3 根目录。
& D:/conda_envs/edu_agent/python.exe day11_server.py --root data/v3 --port 8011
```

基础业务 schema 保持 `v3-day10-2`；新增独立扩展版本 `learning_schema_version=v3-day11-1`。准备 Graph 保持 `v3-day10-preparation`，学习 Graph 使用 `v3-day11-learning`。三个文件分别是业务库 `learning.sqlite`、原准备存档 `checkpoints.sqlite`、学习存档 `learning-checkpoints.sqlite`。两个 Graph 都使用原 `project_id=thread_id`，不把旧等待点交给另一张状态机解释。契约版本为 `3.0.0`，服务端上限版本为 `day11-1`。

迁移只增加表、索引及扩展元数据；正式计划、旧资料、测验和学习进度保持原内容。运行时工厂只校验版本，GET 不自动迁移、运行模型或修复状态。

## 接口与身份

保留准备接口 `/projects`、资料导入、确认及重试。正式计划冻结后显式调用 `POST /projects/{id}/begin`，载荷为 `request_id` UUID。探索项目必须先明确选择探索。开始学习后的 `/resume` 接收：

```json
{
  "request_id": "唯一UUID",
  "pending_input_id": "从最新GET读取",
  "draft_revision": 3,
  "action": "start_quiz"
}
```

提问另带 `question`；作答带当前 `assessment_id`、完整 `answers`（文字或选项数组）；争议说明带当前 `assessment_id`、`annotation`。request UUID 先规范化再去重，大小写/连字符差异不能产生第二条命令。同一身份改载荷返回冲突。

| 状态 | 主要动作与出口 |
|---|---|
| learning | ask、start_quiz、rest；先修回顾可 return_to_current |
| exploring | ask、rest；无正式测验和完成权限 |
| quiz | submit_answer、return_to_teaching、rest |
| assessment_review | view_feedback、annotate_dispute、replace_assessment、return_to_teaching、rest |
| paused / round_limit | rest；未用过追加时可 retry_3 |
| paused / extension_ready | rest、显式 return_to_teaching；追加自身不调用 Tutor |
| paused / replacement_limit | 暂存，检查资料或评价配置；不可无限换题 |
| error | 原任务 retry、暂存；有合法当前节点时可返回教学，额度内可明确换题 |
| budget_exhausted | rest；根操作可显式追加一次，子操作耗尽后不再提供追加 |
| completed | 查询与结果复用，不自动运行模型 |

最终允许动作以服务端当次返回为准。技术重试走 `/retry`，携带新的 `request_id` 和当次 `retry_token`；追加模型额度使用同接口的 `action=continue_with_new_budget`。普通 retry 保留操作族与逻辑任务计数。

## 持久化与推进规则

- `prepare_assessment` 独立节点先同步保存测验身份、前一测验关联、资料/评价器/策略快照，再执行出题。回到教学后再次打开未作答卷会复用原卷。
- 评分、诊断、完成转换分别保存并复用。补充说明只追加，不能改写答案或触发原卷重评分。重测使用新卷、新身份和同一冻结策略。
- 三个评价器均由代码注册：选择精确匹配、有限数值解析、文字量规。数值不执行表达式，未知单位、非有限数和无法解析值进入 needs_review。数值结果不能替代解释目标。
- 数值默认零容差。模型不能增大容差；题目受冻结策略限制，策略再受服务端上限限制。数值守卫再次独立计算原答案，拒绝伪满分或伪数值证据。
- 文字评分校验题目、分项、满分、版本、真实答案锚点及目标到量规的对应关系。模型信心不能单独授予通过。
- 诊断建议受实际证据、目标门槛、总分、关键错误、身份与先修守卫限制。资料存在、模型给满分或过去已完成都不能独立证明当前目标达成。
- 只有有效评分、合法诊断及守卫决定均完成，才在唯一转换事务中计一轮。第三轮通过先推进；第三轮有效失败再暂停。技术失败、不确定和无效题不计学生失败轮次。
- 连续系统换题最多两次，技术评分/诊断失败后返回教学也不能绕过。最多追加三轮一次，原计数保留，追加节点与 interrupt 分离。
- 每个模型逻辑任务持久化 3 次请求 / 1 次网络重试 / 1 次输出修复。Diagnosis 的工具轮数 2、工具执行数 3 是另一组限制，不当成额外 HTTP 额度。
- 操作默认预占 12 次；显式追加一个关联操作后最多 24 次。请求预占在 HTTP 前提交，崩溃不返还；重启和重试不刷新额度。第二次非法输出或网络重试用尽的逻辑任务不再偷偷发请求。
- 学习执行 journal 与进程锁区分“仍在运行”和“已中断”。即使初始化 session 前退出，GET 也会给出学习恢复入口。异常投影不覆盖已提交的 quiz / paused / completed 业务阶段。
- 所有 Graph 入口 recursion_limit=30。Tutor 只用当前教学节点最近 6 轮完整问答。日志仅记录白名单身份、次数、耗时、tool 和错误类型。

## 运行与演示

```powershell
& D:/conda_envs/edu_agent/python.exe -m pytest -q
& D:/conda_envs/edu_agent/python.exe day11_demo.py --output work/a-new-fake-demo
& D:/conda_envs/edu_agent/python.exe day11_real_smoke.py --output work/a-new-real-smoke
```

Fake 演示使用真实仓库/Graph/资料与契约，证明流程和状态，不证明教学或评分质量；结束后隔离库标记为 demo_only，真实服务拒绝打开。真实冒烟使用固定 Fake 规划与真实适配器；作答来自模型自身参考答案，仍不构成人工质量基准。案例预期待用户复核，保留集未用于真实开发调参。

## 现有网页的项目菜单

每条项目右侧 `⋯` 仅含“重命名、删除”。名称存入独立 `project_labels` 表，原学习目标及 Graph、测验、进度不改变。`PATCH /projects/{id}` 只接收 `display_name`，1–80 字符，禁止空白和控制字符。

删除要求确认同一 `project_id`。服务先写删除标记并在业务事务中级联清理，再通过存档库公共接口删除该线程；中途故障也不会让旧存档复活，重复删除可继续清理。运行中的项目拒绝重命名或删除。菜单支持 Esc、上下键和点击外部关闭；名称通过纯文本渲染。

日常网页若仍运行修改前的后端，需要重启原服务并刷新页面。`18119` 的页面是本轮自建的隔离演示，不是用户真实记录目录。
