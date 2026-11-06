# R06 / R07 整改记录

日期：2026-11-06。基线：`main` 已合入 PR #18，squash `bbdb3bce0d2d172f0c49c5378f67f0736c82f4fd`。本记录只覆盖 R06 与 R07。未做 R08–R11，未清历史库，未升级多租户、OCR 或向量检索。

独立 REVIEW 没有改成“验收通过”。

## 结果

| 编号 | 状态 | 提交 SHA | 验证 | 证据 | 剩余限制 |
| --- | --- | --- | --- | --- | --- |
| R06 | 已修检测与离线回归；真实模型首讲待外部条件 | `b95c1e40392f38ac9bd0ae6ba9e4a3ab453c44f7` | `pytest tests/test_v3_tutor_fidelity.py tests/test_v3_tutor.py` | `docs/training-demo/day02/r06-r07-evidence.json` | 无 `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL`，也无 `.env`。没有真实模型教学 JSON，也没有编造一份。检测器仍是分句规则，不是全文蕴含模型。 |
| R07 | 已修 | `b95c1e40392f38ac9bd0ae6ba9e4a3ab453c44f7` | `pytest tests/test_training_split.py` | 同上 JSON 的 `chapters`；原失败用例仍保留“同一章不得同时含 CHAPTERONE 与 CHAPTERTWO” | 无可靠标题时按页或按长度，并写明不是按标题。长度续分可能在切开的那一页上让相邻两段的页码范围相接。扫描件仍不 OCR。 |

## R06

根因：`has_ungrounded_policy_assertion` 只要资料里出现“罚款 / 审批”等词，就放行该类别的肯定句。资料写“本制度不设置罚款”时，输出“未完成学习将面临罚款”得到 `False`。

修改在 `app/v3/tutor.py`，提示词版本 `v3-day2-fidelity-2`：

- 肯定句必须对上资料里的肯定句，并核对主体和条件。关键词不够。
- 资料明确否定时，不能改写成相反的处罚、审批人、起算或截止日期。
- 写明“假设”或“原文未规定 / 原文明确否定”的句子仍可作例子。
- 普通复述、词语解释、没有资料的通用讲解不因此被整段拒答。
- 输出修复仍是原有 1 次，没有加大重试或取消预算。

离线反例记录在证据 JSON 的 `detector_cases`。审查给出的原句返回 `true`。同一主体同一条件的罚款、审批和截止日期返回 `false`。虚构 `docs/training-demo/samples/培训制度.docx` 只有“入职后 5 个工作日”和“每周五 16:00 前提交、直属导师复核”。历史虚构说法“从入职当天起算、下周一前完成”对这份正文返回 `true`。这是检测器结果，不是模型输出。

真实模型：本环境三个配置都为空，未调用 `generate_tutor_reply`。因此没有首讲和“周一入职具体哪天截止”的模型原文。旧 `day02/FIX_REPORT.md` 里的超时记录保持原样。

## R07

根因：`NativePdfPipeline` 不标标题，12 页文字 PDF 里的 `Chapter 1` / `Chapter 2` 都是普通文本（字号约 17 对正文约 8）。`HybridChunker` 把它们收成同一个“正文”，再按 12,000 字符切开，第二段同时含 `CHAPTERONE` 和 `CHAPTERTWO`。探测时现拆结果是 2 段，第 2 段两个标记都在。

修改在 `app/v3/split_policy.py`，仍用 NativePdfPipeline，不加载版面模型：

- 稀疏的 `Chapter N` / `第N章`，或明显大于正文的短行，才当成标题。同一标题跨页延续；标题被拆到下一页的续行（如“第一章”+“总则”）并进同一标题。
- 超长的同一标题按长度续分，依据写成“未并入其他标题”，不把后一章切进来。
- 没有可靠标题时依据写成按页或按长度，标题用“第N–M页”，不称作按标题。
- 章节正文保留源文本顺序。页码来自文字单元的 provenance。源行拼回去与抽取结果一致，不另删断言。

可复查章节（证据 JSON，输入就是测试里的字节，不是未记录的 33 页文件）：

| 输入 | 段 | 标题 | 依据 | 页码 | 字符 |
| --- | --- | --- | --- | --- | --- |
| 12 页 `Chapter 1` / `Chapter 2` | 1 | Chapter 1（1） | heading-length | 1–7 | 11994 |
| 同上 | 2 | Chapter 1（2） | heading-length | 7–8 | 2344 |
| 同上 | 3 | Chapter 2 | heading | 9–12 | 7141 |
| DOCX 三章 | 1–3 | 第一章 服务响应；第二章 交接复核；第三章 记录留存 | heading | — | 4020 / 4020 / 5020 |
| 12 页无章节行 | 1 | 第1–12页 | page | 1–12 | 按页 |

先前清单里的“3/3、33/33”没有可核对的输入版本，这里不沿用。上面 DOCX 是 3 个标题段；PDF 样例因第一章超长变成 3 段，不是 33 段。

`tests/test_training_split.py::test_upload_creates_parent_pack_and_ready_chapters` 仍把拆出的一章导入课程，正文不超过 12,000 字符。上传警告按 `split_basis` 书写，按页结果不再写“按标题自动拆分”。

## 验证

在本机新建的虚拟环境中安装仓库 `requirements.txt`（含 `docling==2.147.0`）后执行：

```bash
python -m pytest tests/test_v3_tutor_fidelity.py tests/test_v3_tutor.py tests/test_training_split.py -q --tb=line
```

实现提交 `b95c1e40392f38ac9bd0ae6ba9e4a3ab453c44f7`。本次结果：**83 passed**，1 条 Starlette `BlockingPortal` 弃用警告，6.86 秒。未跑全量离线回归（R11 另开）。未改生产库，未部署。本表中的 SHA 在随后一次只改本文件的提交里写入，代码没有再变。
