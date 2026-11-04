# Demo Day 2 实施与自检报告

实施：2026-11-04 至 2026-11-05。范围：办公资料上传、解析预览、来源定位及原学习流程适配。保留 Astra 的全部未提交 Day 1 调整，包含对外“学习”命名和游客完整自主学习；不实施 Day 3 发布、任务下发或看板。

## 交付

- 游客／员工个人资料库：上传、真实解析状态、失败原因、全文和表格预览、原件下载、按资料创建自己的课程。
- 管理员单位资料库：复用同一解析器，服务端验证管理员和单位范围；未发布原件不向员工开放。
- 现有课程准备页同时支持四类办公文件及 TXT/Markdown。原 `SourceDocument`、`SourceChunk`、课程归属、持久队列、规划／讲解／测评引擎继续使用；不另建学习引擎。
- 原件 SHA256 留存，片段可以回到 PDF 页、DOCX 标题／段落／表、XLSX 工作表／范围、PPTX 张号／形状。表格保留表头、行列和数值关系。
- 四份真实格式的虚构办公样例及 [SAMPLE_CHECKS.md](SAMPLE_CHECKS.md)；没有写入伪造的课程、成绩或统计。浏览器验收新建的项目和上传记录是实际 API 产生的测试记录。

实际入口：[本地首页](http://127.0.0.1:18780/)、[个人资料](http://127.0.0.1:18780/training/materials)、[管理员单位资料](http://127.0.0.1:18780/training/admin/materials)、[正式公网](https://skilltree.goutouren.work/)。账号、命令、端口、目录见 [START.md](../START.md)，关系和实际 API 见 [CONTRACTS.md](../CONTRACTS.md)。

## 解析方案与安装

继续使用 `D:\conda_envs\edu_agent\python.exe`，未新建或替换环境。运行依赖已固定进 `requirements.txt`：

| 格式 | 实际解析器 | 定位及边界 |
|---|---|---|
| 文字 PDF | pypdf 6.16.2 | 逐页文字层、页码；复杂多栏／表格须核对原件，不做 OCR |
| DOCX | python-docx 1.1.2 | 正文顺序、标题、段落和表；不读页眉页脚、批注、文本框或图片 |
| XLSX | openpyxl 3.1.5 | 工作表和完整单元格范围；保留公式原式和原文件缓存，无缓存明确标注，不执行／重算 |
| PPTX | python-pptx 1.0.2 | 张号及形状顺序，文字与表格；不读图片、图表、动画及讲者备注 |
| TXT/Markdown | Python 严格 UTF-8 | 保留正文、BOM／CRLF 及原有行号／哈希行为 |

样例生成额外使用 reportlab 4.4.4，仅生成样例需要，线上解析无需安装。安装命令：`D:\conda_envs\edu_agent\python.exe -m pip install -r requirements.txt`。

先核验了 [Docling 格式支持](https://docling-project.github.io/docling/usage/supported_formats/) 与当前环境依赖。`pip install --dry-run docling` 完成，解析到 Docling 2.147.0：拟引入 Docling 模型／OCR／版面组件，替换现有 torch 为 2.15.0、numpy 为 2.4.6、python-docx 为 1.2.0、python-dotenv 为 1.2.4 等。该试算未实际安装 Docling，也未声称跑过其四格式转换。考虑现有环境和公网服务 700 MiB 内存限制，本阶段选成熟轻量库，并通过四份真实格式文件与真实资料核对。依赖试算日志：`work/training-demo/day02/docling-probe.log`。

提取边界参考：[pypdf 文字层／扫描件说明](https://pypdf.readthedocs.io/en/stable/user/extract-text.html)、[openpyxl 不计算公式](https://openpyxl.readthedocs.io/en/stable/simple_formulae.html)。

## 限制与失败行为

办公原件最多 8 MiB，解析全文最多 12,000 字符；TXT/Markdown 保持 128 KiB。PDF 最多 10 页、PPTX 最多 15 张；XLSX 最多 8 工作表、总范围 500 单元格；单个 DOCX 表最多 500 单元格。Office ZIP 解压总量最多 8 MiB、512 项。损坏、超限、无正文和旧 Office 文件明确失败，不静默截断，不建立可用课程。

PDF 的内部权限加密标记不等于用户设置了打开密码：无需密码即可读取的文件正常解析；只有确实需要打开密码才提示暂不支持。桌面三份带标记 PDF 已核实均可用空打开密码读取。扫描／无文字页仍提示提供文字版；35 页的考勤办法超出本阶段 10 页范围，需要按章节拆分，不属于密码问题。宏、加密 Office、图片语义暂不支持。

未引入向量库或检索服务。模型使用现有有界完整资料目录，序列化上下文上限 24,000 字符。多份材料累计超限明确停止规划，解析成功不冒充路线生成成功。资料文件仅是学习依据，不能修改角色、评分策略或工具权限。

## 自检证据

| 检查 | 实际结果 |
|---|---|
| 主回归 | 112 passed，104.30 秒；覆盖原认证、游客、队列、课程删除／归属、目标准备、公开 API、邮件注册和 Day 1／Day 2 |
| PDF 权限标记修正后资料回归 | 39 passed，13.15 秒；含新增“有权限标记但无需打开密码”的实际 PDF 测试，与主回归存在重叠，不相加 |
| 四格式事实和定位 | PDF 的 30 分钟／2 个工作日／17:30；DOCX 的 5 个工作日／16:00／180 天；XLSX 行列表头和 30／60／180；PPTX 三张的 09:00／10:00／17:00 均保留 |
| 失败／不支持 | 损坏、空白扫描 PDF、真正需要密码的 PDF、超页数、超字数、超原件大小、旧 DOC、宏、ZIP 解压超限均拒绝；失败上传不创建项目 |
| 防越权和版本 | CSRF、请求 UUID 重放／变更、员工伪造角色、另一员工／游客／管理员读取私人资料与原件、单位未发布原件、跨项目导入均核对；引用片段保持原正文切片哈希 |
| 实际 Edge 浏览器 | 四格式上传预览、移动端无横向溢出、管理员单位上传、员工个人上传、四账号登录、甲乙丙项目与草稿隔离通过；浏览器无页面脚本错误 |

可复核的本机证据目录（不入 Git）：`work/training-demo/day02/`。主测试 `full-regression.log`／`regression.xml`；资料修正 `pdf-fix-tests.log`；浏览器 `policy-browser/result.json`、四格式截图、路线和讲解 JSON；成员／草稿隔离 `roles/result.json`。自动化脚本为 `scripts/training_materials_acceptance.cjs` 和 `scripts/training_materials_roles.cjs`。

### 用户桌面真实资料

在用户授权的“政策资料”文件夹中，先验证《长缨富县落地方案.docx》：39,803 字节，解析 4,478 字符，真实生成路线并进入 learning，首节有 3 条来源引用。该轮浏览器脚本的学习态匹配随后修正，以后续完整 PDF 闭环作为正式浏览器通过证据。

正式完整闭环使用《中电信延安〔2026〕47号（关于2026年AI+行动工作部署的通知）.pdf》：601,835 字节、10 页，全文 5,565 字符。项目 `v3_9df9d08acfaf49acbfd7fa3a2bdd6da7`，真实模型规划耗时约 42.75 秒，形成 10 节路线，涵盖工作目标、报表自动化、智能派单、质检回访、知识库、组织保障、激励和工作要求。随后确认计划、进入首节讲解，返回 2 条实际资料引用，回到 PDF 第 1–2 页。

首节确实讲到原文的“四项原则”和“四大核心痛点”，而非任意通用课程。已核对讲解中的实用为主、基层减负、效率提升、全员参与，以及报表统计自动化、智能派单、智能质检、业务政策查询，均有原文依据。证据：`policy-browser/route.json`、`teaching.json` 和 `real-teaching.png`；第二游客读取该项目和资料均为 404。

真实模型证据仅证明这些实际生成内容及引用可回溯，不代表完成了测评或证实学习效果；自动化测评回归中的模型内容明确为 Fake。真实政策原件、正文、浏览器会话和私有账号不提交 GitHub，公网验收只上传虚构样例。

### 重启与同步

本地已实际停止并重新启动同一实例。重启前后核对 82 项学习表／资料文件与 53 张原有数据库表，全部一致：`restart-result.json`。随后用原游客会话读取同一政策课程、来源和原件，确认浏览器恢复结果。

实现提交 `5ef96069fa8f18fd2420bb3d345ae8c5812af6fb` 已推送 GitHub 并部署公网；报告和验收脚本修正随后以独立提交同步。服务器 Python 环境相关回归 **64 passed，74.00 秒**，`pip check` 无冲突。发布前等待队列空闲，备份位于 `/home/admin/skilltree-backups/before-training-day02-20261104T162529Z`；原有 85 张数据库表和学习实例原有 54 张表的记录逐表哈希一致。旧 `.env` 和模型设置密钥与 Day 1 备份 SHA256 一致。

公网四格式上传预览、四账号登录、单位／个人资料隔离、甲乙丙项目和草稿隔离均已实际核对。公网仅使用虚构《培训制度.docx》生成 6 节路线，规划约 22.46 秒，真实进入 learning，首节讲解返回 2 条来源引用；原会话恢复后可打开来源抽屉，定位到 DOCX 标题段及“第一条 学习安排”段落，下载原件 SHA256 与上传记录一致。独立游客读取其课程／资料为 404，管理资料为 403。Nginx 请求体设为 12m，337,194 字节的实际 DOCX 原件上传解析返回 201，证明已通过旧 256 KiB 限制。

公网浏览器验收遇到整页载入／重载超时，不能将首轮脚本标记为全程通过：后续按实际页面就绪等待，用原会话恢复课程和引用，未重新发起模型命令。独立恢复检查和角色检查通过，汇总为 `public-acceptance.json`；详细保留 `public-browser-v2/result.json` 中的超时、`teaching.json`、`resume-result.json`、`resumed-source-drawer.png`、`public-roles-v2/result.json` 及 `public-upload-limit.json`。额外静态资源探测均为 200，其中已有 `fonts.css` 为 526,081 字节、该次下载约 28.67 秒；本日未修改字体包，公网初次加载速度仍可优化。

发布保留旧端口 8765、旧学习目录与模型配置；8767 继续承载正式学习入口，原件及学习状态不随代码同步到另一环境。最终发布后再次重启两项服务，核对完整学习表／原件和旧数据，结果记录于服务器 `work/training-demo/day02/restart-result.json`；本地、GitHub、服务器与运行版本的最终 SHA 对齐记录于本机 `work/training-demo/day02/release-sync.json`。

## 尚未完成与交接

本日未开放共享课程发布、员工下发、任务学习和进度看板；它们保持真实空状态／功能建设中，不伪造数据。Docling 完整版式转换、OCR、旧 Office、宏、公式计算、大文件／长文范围选择不在本日能力中。等待独立 Day 2 验收，不自动实施 Day 3。
