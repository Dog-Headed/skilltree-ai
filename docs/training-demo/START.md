# 单位培训正式方向：启动与账号

2026-11-04，Day 1。用户已明确要求本地、GitHub、现有公网同步，培训版成为正式首页；这覆盖原总计划“只本地、不部署公网”的限制。旧学习数据保留，培训运行数据独立。

## 本地

始终使用现有 `edu_agent` 环境。在 PowerShell 中：

```powershell
Set-Location D:\SkillTree_AI\skilltree
& D:\conda_envs\edu_agent\python.exe -m deploy.training_demo
```

打开 <http://127.0.0.1:18780/>。进程保持运行，按 Ctrl+C 停止。启动自动初始化四个账号，已有密码、项目、进度和会话不会被重置。无需另装环境；Python 3.11.15，FastAPI 0.117.1，Uvicorn 0.32.1，依赖沿用 `requirements.txt`。仓库旧 `venv` 和默认 Python 不是本次启动环境。

仅初始化、不监听端口：

```powershell
& D:\conda_envs\edu_agent\python.exe -m deploy.training_demo --init-only
```

| 身份 | 本地账号 | 本地示例密码 |
|---|---|---|
| 培训管理员 | admin@example.test | SkillTreeDemo2026! |
| 员工甲 | employee.a@example.test | SkillTreeDemo2026! |
| 员工乙 | employee.b@example.test | SkillTreeDemo2026! |
| 员工丙 | employee.c@example.test | SkillTreeDemo2026! |

账号仅为虚构示例，不发送邮件。首页可“切换账号”；同一浏览器使用同一个会话，不同账号同时操作请用不同浏览器配置或独立隐私窗口。

本地根目录：`D:\SkillTree_AI\skilltree\work\training-demo\instance`。

| 路径 | 内容 |
|---|---|
| `auth.sqlite` | 培训账号、会话、登录限速 |
| `training.sqlite` | 单位成员、课程版本／任务／员工任务最小关系 |
| `gateway.sqlite` | 项目归属、持久队列、额度、账号模型设置 |
| `model-settings.key` | 仅本实例使用的模型设置加密密钥 |
| `learning/learning.sqlite` | 原引擎项目、资料、测评、达标事实 |
| `learning/checkpoints.sqlite`、`learning/learning-checkpoints.sqlite` | 准备与学习 Checkpoint |
| `training-demo.json` | 实例目录标记；启动防止误用其他已有数据目录 |

再次演示优先新建独立实例，**不删除或覆盖旧目录**：

```powershell
& D:\conda_envs\edu_agent\python.exe -m deploy.training_demo --port 18781 --data-root D:\SkillTree_AI\skilltree\work\training-demo\rehearsal-02
```

端口只允许 18780–18879；占用则拒绝启动，不停止原进程。目录只允许 `work/training-demo/` 下带演示标记的实例或新空目录。不要把运行库、加密密钥与模型密钥提交到 Git。

## 模型与页面

读取项目现有 `.env` 平台模型配置，复用账号模型设置，默认 DeepSeek；没有凭据或模型失败会显示真实错误。不会使用 Fake 作为运行模型。员工首页 → 自由学习 → 写目标与已有基础 → 种下这棵树 → AI 整理学习计划。首次准备耗时受模型服务影响，可刷新读取任务状态，不要反复新建请求。

- 管理员首页：`/training/admin`；员工首页：`/training/home`。
- 个人学习：`/learn`，项目哈希路由继续可用。
- 上传／发布／下发／看板今天只提供真实空状态或建设中说明。Day 1 不包含培训发放功能。

## 公网

正式入口：<https://skilltree.goutouren.work/>。仍由原 Nginx／TLS 转发到 127.0.0.1:8767，不开放新公网端口。8767 启用培训模式；8765 及旧 `data/v3`、`data/evaluation-v3`、原账号库均保留。

服务器培训根目录：`/home/admin/skilltree-ai/work/training-demo/production`。独立账号与项目不和本地互相复制；同步的是代码与配置结构。

服务器以 `skilltree-evaluation.service` 运行。私有 `/etc/skilltree/training.env` 配置 `SKILLTREE_TRAINING_ENABLED=1`、独立 `SKILLTREE_TRAINING_ROOT` 和独立初始密码；服务 drop-in 仅为 8767 加载该文件。公网必须 HTTPS + Secure/HttpOnly Cookie；拒绝使用上表本地示例密码初始化公网。具体公网密码在本机未入库的 `work/training-demo/private/PUBLIC_ACCOUNTS.md`，不写入源码或公开报告。

正常重启：`sudo systemctl restart skilltree-evaluation`。不要对已有实例再次初始化新密码、复制旧 Checkpoint 或清空库。代码回退可以撤除培训 drop-in 恢复旧入口；恢复前先备份新培训目录，旧数据库不覆盖当前记录。
