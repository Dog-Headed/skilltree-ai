# R01–R11 汇总

日期：2026-11-06。代码基线：GitHub `main` `d9482127ef3e2de07a15886aa45e4a7f6ef339e7`（PR #19 squash；父提交为 PR #18 `bbdb3bce0d2d172f0c49c5378f67f0736c82f4fd`）。本文件是离线回归与文档对齐记录。独立 REVIEW 保持原结论，这里不把它改成独立验收通过。

GitHub 与服务器已同步。生产部署目标为上述 `main`。回环 `/healthz` 的 `version` 来自环境变量 `SKILLTREE_COMMIT`（`deploy/update.sh` 写入 `/etc/skilltree/runtime.env`，`deploy/asgi.py` 原样返回），不是目录 `git HEAD`。此前目录与健康标记不一致的根因是这份变量滞后；运维侧已按实际部署提交写回。本工作区同日看到公网 `/` 为 303 到 `/learn#/garden`、`/login` 为 200，公网 `/healthz` 仍被 Nginx 403，因此不用公网响应充当提交号。Windows 本机仓未强制覆盖、待用户自行同步。那次同步没有覆盖用户未提交文件，也没有跑真实模型浏览器闭环。同日运维在已部署的 PR #19（`d948212`）上交付 R09；文档里的「待运维」出自随后的 PR #20（`a538f02`），本记录改为已交付。本段为早期同步记录。R08 的后续真实模型与截图见 [R08_REPORT.md](R08_REPORT.md)。

## 汇总

| 编号 | 状态 | 提交 SHA | 验证方式与结果 | 证据路径 | 剩余限制 |
| --- | --- | --- | --- | --- | --- |
| R01 | 已修 | `bbdb3bc`（PR #18；实现曾在 squash 前的 `7e7b828`） | 见下方同一次专项：`test_claim_checks_permission_before_idempotency_and_keeps_one_project`、`test_concurrent_claims_create_one_project_without_resetting_progress` 包含在 66 passed 中 | `tests/test_training_course_semantics.py`；较早记录见 `docs/training-demo/day06/FIX_REPORT.md` | 幂等键仍是单位内 `request_id`，复用到其他目标时拒绝。未做跨进程压测 |
| R02 | 已修 | 同上 | 同一次专项含 `test_placeholder_tree_is_rejected_and_draft_publication_ignores_it`、`test_publish_page_uses_the_confirmed_draft_instead_of_placeholder_nodes` | 同上 | 发布页不调用模型。本轮没有真实模型生成记录 |
| R03 | 已修 | 同上 | 同一次专项含 `test_two_employees_keep_published_semantics_and_distinct_chunk_identities` | 同上 | 历史缺配置的课程须重新发布，不会自动补齐 |
| R04 | 已修 | 同上 | 同一次专项含 `test_publish_rejects_each_invalid_course_without_a_leftover_row` | 同上 | 已成功的 `request_id` 重放仍返回第一次的版本 |
| R05 | 已修 | 同上 | 同上两项草稿发布用例覆盖新课程身份与修订 | 同上 | 修订必须显式提交已有 `course_id` |
| R06 | 已修（离线检测）；真实模型首讲待真实模型证据 | `d948212`（PR #19 squash；实现曾在 `b95c1e4`） | 同一次专项中 `tests/test_v3_tutor_fidelity.py` 30 项通过。未调用真实模型 | `docs/training-demo/day02/r06-r07-evidence.json`；`docs/training-demo/R06_R07_FIX_REPORT.md` | 检测器仍是分句规则。没有新的教学 JSON。旧超时记录保持原样 |
| R07 | 已修 | 同上 | 同一次专项中 `tests/test_training_split.py` 10 项通过，含原先「同一章不得同时含 CHAPTERONE 与 CHAPTERTWO」 | 同上 JSON 的 `chapters` | 无可靠标题时按页或按长度，并写明不是按标题。扫描件仍不 OCR |
| R08 | 真实模型 API 主闭环、浏览器关键页已补证 | 实际业务代码为 `a538f02`（与重启提交 `2af9722` 等同） | 甲一次通过，乙错答后补弱，重启恢复后复测通过。看板 2/2/2 | [R08_REPORT.md](R08_REPORT.md) | 补弱画面是只读历史回放。游客完整课程、注册保留与入单位归属待专项复验 |
| R09 | 已交付 | 适用生产 `d948212`（PR #19）。此前「待运维」写在文档同步 `a538f02`（PR #20）。无新产品提交 | 2026-11-06（Asia/Shanghai）。只经后端 `python -m deploy.training_admins` 创建 `admin.qa1@example.test`、`admin.qa2@example.test`、`admin.qa3@example.test`，角色 admin，单位 `demo-qinghe`。原管理员保留（`admin@example.test`、既有 `1287203475@qq.com` 等）。重跑得到 `already_admin` / `reused_existing_password`，不重置已有密码。登录冒烟：`https://skilltree.goutouren.work/login` → `https://skilltree.goutouren.work/training/admin` | 服务器私密文件 mode 0600：`/home/admin/skilltree-secrets/qa-admins-20261106.json`（只记路径）。非机密说明：`/home/admin/skilltree-secrets/qa-admins-20261106.txt` | 密码、口令哈希与 `.env` 不进本仓库。重跑不会轮换已有密码。邮箱归属验证、邀请邮件、多单位仍未做 |
| R10 | 已修文档；健康标记由运维写回 | `a538f02`（PR #20 文档同步） | 更新 PROGRESS、START、CONTRACTS、Day 1/3/5 与账号阶段报告、两份 README。历史「未部署／后续未实现／公网仍是 `80d53f4`」都标明了日期和当时提交 | 上述文档 | 公网 `/healthz` 仍 403，本工作区不能复读运行中的 `SKILLTREE_COMMIT`。Windows 本机仓已在后续同步中保留未提交文件并快进 |
| R11 | 已记录 | `a538f02`（PR #20 文档同步） | 专项 66 passed / 0 failed / 0 skipped，40.96 秒。全量一次：11 failed / 1387 passed / 24 skipped，353.12 秒。失败原因见下，不与专项数字相加 | 本文件 | 全量那 11 项是本环境缺少 `pip` 模块，不是培训逻辑失败。补装 pip 后只重跑该文件，不把它算进上面的全量计数 |

## 专项（一次跑完，不拆开相加）

环境：Linux，Python 3.11.18，虚拟环境安装仓库 `requirements.txt`（含 `docling==2.147.0`）。`CUDA_VISIBLE_DEVICES` 为空。工作区代码为 `d948212` 加本轮文档修改；这些测试不读上述 Markdown。

```text
python -m pytest \
  tests/test_training_registration_members.py \
  tests/test_training_publish_assign.py \
  tests/test_training_employee_start.py \
  tests/test_training_dashboard.py \
  tests/test_training_day05_rehearsal.py \
  tests/test_v3_tutor_fidelity.py \
  tests/test_training_split.py \
  tests/test_training_garden_skin.py \
  tests/test_training_course_semantics.py \
  -q --tb=short
```

结果：**66 passed**，0 failed，0 skipped，1 条 Starlette `BlockingPortal` 弃用警告，40.96 秒。按文件收集到的数量（与这次通过数一致）：

| 文件 | 项 |
| --- | --- |
| `tests/test_training_registration_members.py` | 6 |
| `tests/test_training_publish_assign.py` | 1 |
| `tests/test_training_employee_start.py` | 1 |
| `tests/test_training_dashboard.py` | 2 |
| `tests/test_training_day05_rehearsal.py` | 2 |
| `tests/test_v3_tutor_fidelity.py` | 30 |
| `tests/test_training_split.py` | 10 |
| `tests/test_training_garden_skin.py` | 7 |
| `tests/test_training_course_semantics.py` | 7 |

## 全量离线回归（另一次，单独计数）

```text
python -m pytest -q -ra --tb=line
```

结果：**11 failed，1387 passed，24 skipped**，3 条弃用警告，353.12 秒。

24 项跳过都是因为当前环境没有 Playwright，不是产品失败，也不是 Windows 断言：

| 数量 | 位置 | 原因 |
| --- | --- | --- |
| 8 | `tests/test_day12_frontend.py` | Playwright is required for the real frontend regressions |
| 6 | `tests/test_day13_private_reference_frontend.py` | Playwright is required for the real browser checks |
| 8 | `tests/test_goal_first_browser.py` | Playwright required |
| 2 | `tests/test_streaming_frontend.py` | Playwright is optional |

11 项失败全部在 `tests/test_day13_recovery.py`。栈是 `python -m pip list --format=json` 退出码 1。当时用 uv 建的虚拟环境没有 pip 模块，直接执行得到 `No module named pip`。`day13_recovery.py` 用这条命令盘点已装包。这不是课程发布、领取或拆章失败。

装上 pip 26.3 之后，只重跑该文件：`13 passed in 14.78s`。这 13 项不并入上面的 1387，也不把全量改写成一次新的总数。

## Windows 不适用断言

Astra 清单里 Windows、`edu_agent` 上那 8 个文件曾是 33 passed / 5 failed：4 项与缺少 Docling 有关，1 项是 `tests/test_training_registration_members.py` 里 `private.stat().st_mode & 0o777 == 0o600`。`deploy/training_admins.py` 的 `write_private` 会 `chmod(0o600)`。该断言检查的是 POSIX 权限位。Windows 的 `st_mode` 不表达这组权限位，所以那 1 项失败不适用于 Windows，也不记成产品逻辑失败。本次 Linux 专项里该文件 6 项通过，包含这一条。

缺少 Docling 造成的失败同样不是产品逻辑失败。本次已安装 Docling，`tests/test_training_split.py` 的 10 项在专项里通过，其中包括原先服务器上失败的章节标记混合用例。不要把那次服务器失败改记成 Windows 缺包。

## R09 生产测试管理员

2026-11-06（Asia/Shanghai），生产代码为 PR #19 `d948212`。运维只执行后端 `python -m deploy.training_admins`。

- 账号：`admin.qa1@example.test`、`admin.qa2@example.test`、`admin.qa3@example.test`。角色 admin，单位 `demo-qinghe`。
- 原管理员保留，包括 `admin@example.test` 与既有 `1287203475@qq.com`。
- 再次执行得到 `already_admin` / `reused_existing_password`，不重置已有密码。
- 登录冒烟：`https://skilltree.goutouren.work/login`，进入 `https://skilltree.goutouren.work/training/admin`。
- 密码只在服务器文件 `/home/admin/skilltree-secrets/qa-admins-20261106.json`（mode 0600）。非机密说明在 `/home/admin/skilltree-secrets/qa-admins-20261106.txt`。本记录只写路径。

本段为早期同步记录。R08 的后续真实模型与截图见 [R08_REPORT.md](R08_REPORT.md)。本补记没有新的模型输出。

## 2026-11-18 复验反例（R02、R06）

2026-11-18（北京时间）对 `22dab06eea00a189df72fb804d4871b37d00fb0b` 的独立复验没有签 11/11。R02、R06 各有产品反例。本节只记录这两处修改和本次重跑，不把 2026-11-06 的 66 passed、1387 passed / 11 failed / 24 skipped、以及补装 pip 后的 13 passed 加在一起。上面的汇总表保持当时的说法。

### R02

反例：同一草稿挂上两份合法单位资料 A、B，学习目标只引用 A。草稿列表 `publishable: true`，`material_version_ids` 却是两份。页面用该列表原样发布，得到 422 `material_mismatch`；只提交 A 则 201。

原因：`list_drafts` 收集全部已挂载教学资料，`app/static/training.js` 把这个列表放进 `material_version_ids`，`publish_from_draft` 则按目标实际引用的 `source_id` 校验。

修改：`deploy/training_course.py` 的 `referenced_material_version_ids` 同时给出预览和发布使用的引用集。`material_version_ids` 只含该集合。已挂载但目标未引用的资料放在 `unreferenced_material_version_ids` 和 `materials`（`referenced: false`）里。发布页单独显示后者，提交体仍然只送 `draft.material_version_ids`。来源锚点、内容哈希和“客户端集合与引用集不一致则 422”都保留。资料在确认草稿之后再挂上，仍因 `draft_revision` 变化而不可发布，原因仍是“资料已变化，请重新生成草稿。”

回归：`tests/test_training_r02_material_set.py`。覆盖只引用一份、两份都引用、确认后新增资料必须重做计划，以及预览字段发布后员工领取到的来源就是引用集。

### R06

样例 `docs/training-demo/samples/培训制度.docx` 的 SHA-256 为 `820b1a41c487bd19b3a8aa7be52179a390053b13ab5786e2f016af53d82f9158`，与 [R08_REPORT.md](R08_REPORT.md) 里 2026-11-06 演练记录的哈希一致。正文有“入职后 5 个工作日”，没有写明从入职当天还是次日起算，也没有写周末和法定节假日口径。

反例一句：“若某员工周一入职，则最迟应在下周一（入职后第5个工作日）前完成基础制度学习。”旧检测器返回 `false`。原因是截止日期模式只认“最晚/截止”，并且要求“周几”紧贴“前完成”；“最迟”和括号里的“第5个工作日”都绕过了它。另一条构造负例“本制度不设置罚款”对“未完成学习，罚款100元”也返回 `false`，因为罚款模式只认“将面临罚款”这类句式，不认金额。这句不是真实模型输出。

修改在 `app/v3/tutor.py`，提示词版本 `v3-day2-fidelity-3`。检测器仍是分句规则，不是全文蕴含模型，也没有加大修复次数：

- 把“N 个工作日”说成唯一周几时，若资料没有写明起算和工作日历，则拦截。同时写出当天起算得到本周五、次日起算得到下周一，并写明不能据此确定唯一截止日的回答不拦截。
- 资料写明起算（当天或次日，只取一种）以及周一至周五、不含周末和法定节假日时，与该规则相符的周几可以通过；另一种起算得到的周几仍拦截。
- “罚款100元”这类金额句按肯定罚款处理。资料写“不设置罚款”时拦截；资料自己写了同一金额时不拦截。

仓库里没有 2026-11-18 的真实模型全文。本次环境 `LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL` 均未设置，也没有 `.env`。没有调用书生 intern-s2 或 DeepSeek，没有编造教学 JSON。离线检测覆盖上面三类材料。

### 如何重跑

相关用例：

```bash
python -m pytest \
  tests/test_training_r02_material_set.py \
  tests/test_v3_tutor_fidelity.py \
  tests/test_v3_tutor.py \
  tests/test_training_course_semantics.py \
  tests/test_training_publish_assign.py \
  tests/test_training_employee_start.py \
  -q --tb=short
```

全量另一次跑，不与上面的数字相加：

```bash
python -m pytest -q -ra --tb=line
```

浏览器用例依赖 Playwright。本环境没有安装 Playwright 时，这些跳过要单独列出，不能并进一次全绿。

### 本次测试记录

环境：Linux，Python 3.12.3（`GCC 13.3.0`），虚拟环境安装仓库 `requirements.txt`（含 `docling==2.147.0` 与 `pip`）。无 `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`，无 `.env`，未安装 Playwright。未部署，未改生产库。仓库先前写明依赖在 Python 3.11 上验证过；这次机器是 3.12.3，结果按这次实际环境记录。

相关用例（上面第一条命令）:**98 passed**，0 failed，0 skipped，1 条 Starlette `BlockingPortal` 弃用警告，13.83 秒。

全量（上面第二条命令，另一次，不与 98 相加）:**1414 passed，0 failed，24 skipped**，3 条弃用警告，274.10 秒。24 项跳过都是因为没有 Playwright，不是产品失败：

| 数量 | 位置 | 原因 |
| --- | --- | --- |
| 8 | `tests/test_day12_frontend.py` | Playwright is required for the real frontend regressions |
| 6 | `tests/test_day13_private_reference_frontend.py` | Playwright is required for the real browser checks |
| 8 | `tests/test_goal_first_browser.py` | Playwright required（含 Node/Playwright 检查） |
| 2 | `tests/test_streaming_frontend.py` | Playwright is optional |

没有浏览器或 Playwright 全程点击记录。上面的 1414 不能写成全绿。全量是在产品代码定稿、本节计数写入之前跑的。相关 98 项在记录 SHA 的最终提交上再跑一次；这两次之间没有产品代码差异。SHA 见拉取请求说明，也写在下一行补记里。

测量提交：（补记）

## 自检

自检通过。2026-11-06 补记只改文档：R09 改为已交付，本段为早期同步记录。R08 的后续真实模型与截图见 [R08_REPORT.md](R08_REPORT.md)。未写入密码、口令哈希或 `.env`。2026-11-18 一节同样没有写入密钥或口令。
