# Day 10：需要用户复核的内容

当前状态：**待用户复核**。本轮 Agent 检查了有限答案与资料依据，但这不等同人工金标准。此前 Day 7 的 12 例认可不适用于本轮新建的 36 例。

三科完整计划预览见交付目录《三科计划复核稿.md》。该稿来自隔离 Fake 契约演示，模拟了确认和冻结；真实运行时尚不能用未实现的文字/数值评价器开课。请重点判断四个节点顺序、范围、目标及引用是否符合你的学习目标。每科默认总分和必要目标门槛均为 0.8，critical 阻断，不以总分掩盖必要目标失败。

## 开发样题抽查

以下全部来自 debug，不展示 holdout 的具体题目，避免把保留集变成调试材料。

| 学科与案例 | 题目 | 参考答案草案 | 量规草案 | 来源定位 |
|---|---|---|---|---|
| Python debug_01 | x=3，if x>=3 令 label=A，否则 B；说明分支及等号边界 | A；3>=3 为真，包含等号边界 | 结果4分、取值与顺序4分、边界2分 | teaching.md py-condition；私有 py-private-criteria |
| 数学 debug_01 | 解 2x+5=17，说明两边操作并代回 | 两边减5得2x=12；两边除2得x=6；2×6+5=17 | 解值4分、等价操作4分、代回2分 | math-add、math-multiply、math-check；私有 math-private-criteria |
| 英语 debug_01 | 将 Mira visits the gallery. 改为含 yesterday 的过去肯定句 | Mira visited the gallery yesterday.；允许 Yesterday, Mira visited the gallery. | 目标句型4分、动词形式4分、原意/时间/可理解性2分 | en-affirmative；私有 en-private-criteria |

这三份完整正确作答的草案预期均是：评价有效、10/10、必要目标满足、无 critical、advance。部分分边界、关键错误条件和替代表述仍请检查后再批准，不把“分项一半”当作已校准的评分器。

## 每科 12 例与资料复核

资料：`materials/v3/{python,mathematics,english}/` 的 teaching.md、assessment_private.md、manifest.json。案例：`evals/v3/{subject}/cases/`。清单与参考依据：`evals/v3/README.md`。各例都预先包含题面、答案、量规、实际作答、可查历史、证据位置、期望行动及允许证据。

开发编号 01–08 分别覆盖：全对、部分正确、关键错误、缺证据、结构合法但评分内容错误、题目无效、答案诱导改规则、前置薄弱点。holdout 09–12 已冻结，不进入当前 Planner 或调试输入；后续 Prompt 冻结后再用于一次保留验证。

确认时需要区分两件事：计划范围与顺序是否合适；36 例的答案、量规、关键错误和行为预期是否可作为后续评价依据。未经你明确确认，所有 review_status 保持 pending_user_review；需要修改时先记录版本变更，再生成新摘要。不能由 Agent 自己把状态改成已人工批准。
