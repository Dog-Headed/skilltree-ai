# 单位学习正式方向：启动与账号

2026-11-05，Day 2。用户已明确要求本地、GitHub、现有公网同步，学习版成为正式首页；这覆盖原总计划“只本地、不部署公网”的限制。旧学习数据保留，学习运行数据独立。

包含 Day 1 独立验收后的调整：对外改称“学习”，保留游客自主学习。Day 2 新增办公资料上传和解析，实际交付及部署证据见 `day02/REPORT.md`。

## 本地

始终使用现有 `edu_agent` 环境。在 PowerShell 中：

```powershell
Set-Location D:\SkillTree_AI\skilltree
& D:\conda_envs\edu_agent\python.exe -m pip install -r requirements.txt
& D:\conda_envs\edu_agent\python.exe -m deploy.training_demo
```

打开 <http://127.0.0.1:18780/>。进程保持运行，按 Ctrl+C 停止。启动自动初始化四个账号，已有密码、项目、进度和会话不会被重置。无需另装环境；Python 3.11.15，FastAPI 0.117.1，Uvicorn 0.32.1，依赖沿用 `requirements.txt`。仓库旧 `venv` 和默认 Python 不是本次启动环境。

仅初始化、不监听端口：

```powershell
& D:\conda_envs\edu_agent\python.exe -m deploy.training_demo --init-only
```

| 身份 | 本地账号 | 本地示例密码 |
|---|---|---|
| 学习管理员 | admin@example.test | SkillTreeDemo2026! |
| 员工甲 | employee.a@example.test | SkillTreeDemo2026! |
| 员工乙 | employee.b@example.test | SkillTreeDemo2026! |
| 员工丙 | employee.c@example.test | SkillTreeDemo2026! |

账号仅为虚构示例，不发送邮件。未登录访问首页可直接成为游客，登录页也提供“以游客身份继续学习”。游客可以独立生成知识树、上传 TXT/Markdown、学习与测评，不属于虚构单位。首页可“切换账号”；同一浏览器使用同一个会话，不同账号同时操作请用不同浏览器配置或独立隐私窗口。

本地根目录：`D:\SkillTree_AI\skilltree\work\training-demo\instance`。

| 路径 | 内容 |
|---|---|
| `auth.sqlite` | 学习账号、会话、登录限速 |
| `training.sqlite` | 单位成员、课程版本／任务／员工任务最小关系 |
| `gateway.sqlite` | 项目归属、持久队列、额度、账号模型设置、资料库归属与解析状态 |
| `materials/{material_id}/original`、`parsed.json` | 个人／单位原件和解析正文、表格、来源位置 |
| `learning/original-files/` | 已导入课程的原件，以 SHA256 命名；随来源版本保留 |
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

- 管理员首页：`/training/admin`；员工与游客首页：`/training/home`。游客只显示个人学习入口。
- 个人学习：`/learn`，项目哈希路由继续可用。
- 资料学习：`/training/materials` → 开始资料学习 → 创建课程 → “粘贴 / 上传资料”。当前支持 UTF-8 TXT/Markdown；PDF、Word、Excel、PPT 留待 Day 2。
- 单位资料、发布、下发和看板仍提供真实空状态或建设中说明。Day 1 不包含任务发放功能。

## 公网

正式入口：<https://skilltree.goutouren.work/>。仍由原 Nginx／TLS 转发到 127.0.0.1:8767，不开放新公网端口。8767 启用学习模式；8765 及旧 `data/v3`、`data/evaluation-v3`、原账号库均保留。

服务器学习根目录：`/home/admin/skilltree-ai/work/training-demo/production`。独立账号与项目不和本地互相复制；同步的是代码与配置结构。

服务器以 `skilltree-evaluation.service` 运行。私有 `/etc/skilltree/training.env` 配置 `SKILLTREE_TRAINING_ENABLED=1`、独立 `SKILLTREE_TRAINING_ROOT` 和独立初始密码；服务 drop-in 仅为 8767 加载该文件。公网必须 HTTPS + Secure/HttpOnly Cookie；拒绝使用上表本地示例密码初始化公网。具体公网密码在本机未入库的 `work/training-demo/private/PUBLIC_ACCOUNTS.md`，不写入源码或公开报告。

正常重启：`sudo systemctl restart skilltree-evaluation`。不要对已有实例再次初始化新密码、复制旧 Checkpoint 或清空库。代码回退可以撤除学习 drop-in 恢复旧入口；恢复前先备份新学习目录，旧数据库不覆盖当前记录。

## Day 2 资料学习

- 游客／员工：[个人资料入口](http://127.0.0.1:18780/training/materials)。上传 → 核对解析全文和表格／来源位置 → 填目标 → 用资料准备课程 → AI 整理计划 → 确认并开始学习。
- 管理员：[单位资料入口](http://127.0.0.1:18780/training/admin/materials)。本日可上传、预览、下载原件，尚不发布或下发。
- 现有课程准备页的“粘贴／上传资料”也支持 PDF/DOCX/XLSX/PPTX，原 TXT/Markdown 保留。
- 可直接使用 `docs/training-demo/samples/` 的四份虚构办公样例；事实和位置见 `day02/SAMPLE_CHECKS.md`。真实桌面政策只用于本地验收，不随代码发布。

办公原件最多 8 MiB、正文 12,000 字符；TXT/Markdown 最多 128 KiB。PDF 10 页，PPTX 15 张，XLSX 8 表／500 单元格。无需打开密码的 PDF 权限标记不影响正常读取；需打开密码、扫描件、旧版 Office 和宏暂不支持。超限给出原因，不自动截断。完整上下文仍有 24,000 字符目录上限，多份材料可能需要缩小范围。

上传仍经过同域会话和 CSRF 检查。部署时 Nginx 请求体上限须允许 base64 后的 8 MiB 原件（本次设为 12m）；应用只为资料上传路径开放较大请求，其他接口沿用 256 KiB。无需启动 Office、OCR、Docling、向量库或额外解析端口。
