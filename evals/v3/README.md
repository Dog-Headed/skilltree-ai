# V3 Day 10 · 三科资料与评价案例准备

版本：`3.0.0-day10-1`；编写及资料规则核对日期：2026-10-16，Asia/Shanghai。

本目录有 Python、数学、英语各 12 个完整案例，预先划为 **8 个 debug + 4 个 holdout**。这些是 Agent 编写、等待用户复核的标准草案。所有 `human_expectation` 均保持 `review_status=pending_user_review`、`authored_by=assistant_draft`，没有人工批准，也没有真实模型运行结果。

## 资料依据与范围

教学正文、原创示例与私有评价说明位于 `materials/v3/{subject}/`，分别标记 `teaching` 与 `assessment_private`。每包 `manifest.json` 记录原始参考 URL、资料范围、版本、可见性、正文哈希及稳定章节行号。`agent_fact_checked` 表示 Agent 核对过规则，不表示用户人工认可，来源存在也不自动证明所有内容正确。

| 单元 | 本轮资料范围 | 不宣称的能力 |
|---|---|---|
| Python 条件与循环 | 变量/比较与列表前置、分支边界、for/range、while 终止与阅读证据 | 执行学生代码或证明任意程序正确 |
| 一元一次方程 | 等号与有理数、两边同加减/乘除、多步解与代回 | 一般符号证明、执行任意表达式 |
| 英语一般过去时 | 有限规则/不规则肯定式、did 否定/疑问、文字改写与短段落 | 听力、发音、口语交流 |

Python 规则核对使用 [Python 3.11 官方入门教程](https://docs.python.org/3.11/tutorial/introduction.html) 和 [控制流教程](https://docs.python.org/3.11/tutorial/controlflow.html)；材料中的数值、代码阅读任务与中文说明自行编写。

数学规则核对使用 OpenStax Prealgebra 2e [§8.1 两边同加减](https://openstax.org/books/prealgebra-2e/pages/8-1-solve-equations-using-the-subtraction-and-addition-properties-of-equality)、[§8.2 两边同乘除](https://openstax.org/books/prealgebra-2e/pages/8-2-solve-equations-using-the-division-and-multiplication-properties-of-equality)、[§8.3 多步方程](https://openstax.org/books/prealgebra-2e/pages/8-3-solve-equations-with-variables-and-constants-on-both-sides)，未复制其成套题目。

英语规则核对使用 British Council 的 [规则动词与 did 句型](https://learnenglishteens.britishcouncil.org/grammar/a1-a2-grammar/past-simple-regular-verbs)、[过去时肯定/否定](https://learnenglishkids.britishcouncil.org/grammar-vocabulary/grammar-practice/past-simple-sentences) 和 [不规则动词](https://learnenglishteens.britishcouncil.org/grammar/a1-a2-grammar/past-simple-irregular-verbs)，例句和任务自行编写。后缀拼写只限定文中列出的常用词，不把简略规则扩展到所有动词。

## 固定分组与覆盖

三科使用相同的编号与覆盖安排，但题目、答案、学生错误和前置历史各自编写。

| 编号 | 分组 | 覆盖的行为 |
|---|---|---|
| 01 | debug | 正确答案，所有本题必要目标和证据齐全 |
| 02 | debug | 部分正确，必要目标未达标 |
| 03 | debug | 触发本题冻结的关键标准；不能靠总分覆盖 |
| 04 | debug | 缺少必要解释或结构证据；不计系统原因的失败轮数 |
| 05 | debug | 候选评分结构合法、引用存在，但内容结论错误 |
| 06 | debug | 题面或答案键不支持公平唯一判断 |
| 07 | debug | 学生答案诱导改量规、改门槛或写完成记录 |
| 08 | debug | 当前错误与对应前置历史一致；过去完成不能排除薄弱点 |
| 09 | holdout | 等价表述、缩写、替代步骤或相等数值 |
| 10 | holdout | 当前目标错误，存在基础对照证据，不无故回退前置 |
| 11 | holdout | 总分可为 90%，第二个必要目标为零，必须拒绝推进 |
| 12 | holdout | 明确标记的冲突资料附件，暂停处理来源矛盾 |

冲突案例的假材料只存在于该案例的 `context_anomalies`，不属于正常课程资料。不能把它当作可信知识导入标准资料包。

每例包含当前节点与必要目标、前置节点、完整题面、参考答案、允许变体、分项满分与给分说明、学生实际作答、可定位的原文证据、可查历史、预期行动及理由、允许引用的证据，以及资料章节位置。数学第 09 例同时包含数值输入和文字推理，两种目标分别评价。

## 当前能力与预期的含义

Day 9 注册表中的通用 `text_rubric` 与 `numeric_scalar` 尚未实装。案例中的 `expected_action/expected_passed` 是**所需评价器实装、标准经用户复核后的内容验收目标**，不能据此在当前系统授予正式测评或解锁权限。每例 `formal_completion_allowed_now` 都为 `false`。

当前若演示缩小后的 `choice_exact` 目标，应明确它只验证选择辨认部分，不等于完整文字解释、数值推导或三科教学质量通过。Fake 演示验证契约、身份与状态，不能计为真实模型内容指标。

评分范围和关键标准仍待用户逐例确认。分项部分得分的草案以满分一半作为可审阅起点，不能把这个约定当成已校准评分器。

## 冻结与后续评价纪律

1. 人工先审阅资料、题目、答案、量规与预期，记录真实审核者和日期；当前保持待复核。
2. 每科 manifest 已保存 2 份资料与 12 个案例的 SHA-256。`frozen_before_model_execution.real_model_runs=0`；任何改动都须产生新版本和新清单，不能静默覆写已运行的评价集。
3. 后续只用 debug 调试。Prompt、模型、评价器和策略版本冻结后，再一次运行 holdout；不得据保留结果反复调提示并继续称其保留验证。
4. 下游 runner 应明确选择模型输入字段。`human_expectation`、`candidate_content_error`、Agent 核对说明等标签不能作为待评模型的答案提示；候选评分仅在对应“错误评分审查”任务中作为被审查对象。
5. 真实报告分别记录结构/业务合法率、各科错误推进/拒绝、评分差异、拒评原因、引用支持抽查、调用数/耗时/usage。没有运行的指标为未运行，不填 100%。

## 可复现的离线检查

从项目根目录运行：

```powershell
& 'D:\conda_envs\edu_agent\python.exe' -B day10_check_fixtures.py
& 'D:\conda_envs\edu_agent\python.exe' -B -m pytest tests/test_day10_fixtures.py -q
```

检查脚本只读文件，不导入 Agent、不调用网络或模型、不执行学生代码、不更新冻结清单。它验证哈希、分组、章节位置、身份、量规分值、证据原文及权限标记；数学用 `Fraction` 独立核对预置一次方程解值，Python 用白名单有限见证数据核对范围/元素/分支，英语仅检查预置例句中的有限规则形式。

这些离线检查不证明一般数学推导正确、任意程序可运行、所有英语表达可判断，也不替代人工金标准。审核状态变化后应明确升级资料/案例版本并更新检查约定，而不是把 Agent 改字段当成人工复核完成。

本次离线检查通过，36 例均待用户复核、真实模型运行数为 0；冻结摘要为 `7757f996e8d16816f25ebb768d5d8543117a2e8cf095198ddcafb2aed6085369`。专用测试实际结果：**13 passed，4.25 秒**。这两项属于资料与测试完整性证据，不是教学或模型评价通过率。
