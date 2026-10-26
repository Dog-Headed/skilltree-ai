# 第四主题复核稿：SQL查询阅读（待用户确认）

主题在三科新独立集实质审查通过后选择。只增加资料、档案配置和案例；没有专用Graph、学科分支或SQL执行器，真实模型尚未运行。

## 两个依赖步骤

1. SELECT列投影：区分列与行、列出姓名结果，明确查询不改原表。
2. WHERE条件筛选：先修为列投影；在age>=18下列出Lin、Mei并解释边界。

真实Planner须生成并校验相应依赖、正式确认后再学习；后续需真实Tutor/出题/评价/诊断，完成至少两个依赖节点，并跨进程恢复原项目。此复核稿不是已完成演示。

## 来源与已核对参考

[SQLite官方SELECT文档](https://www.sqlite.org/lang_select.html)的Overview、WHERE筛选、结果列和ORDER BY规则用于事实核对；课程与小表为原创合成数据。
本地SQLite仅执行作者预先写定的查询核对参考：SELECT name结果为Yan/Lin/Mei；WHERE age>=18结果集合为Lin/Mei；18<=age相同；原三行不变。未执行任何学生输入。

## 共同题目与量规

people表为(id,name,age)：(1,Yan,17)、(2,Lin,18)、(3,Mei,20)。写出只查询age>=18者姓名的SELECT；列出返回姓名（行顺序不限）；解释18与17边界以及查询会否改变原表。

参考：SELECT name FROM people WHERE age >= 18; 返回Lin、Mei（顺序不限）；18包含，17排除；原表不变。

SQL4分；姓名结果4分；18包含且17排除1分，原表不变1分。大小写、可选分号、条件等价与结果行顺序不同不扣分。只对第03例冻结关键错误：明确声称查询永久删除原表行；其余题不凭空追加关键标签。

每例允许证据：实际学生答案中的可定位原文、本例冻结材料与实际工具返回。没有预置历史，不能用completed推断当前掌握或薄弱。

## 六类对照（这些预期是Agent草案，尚非人工金标准）

|案例|类型|参考分|状态|预期行动|关键错误|
|---|---|---:|---|---|---|
|sql_reading_novel_01|正确|10|graded|advance|False|
|sql_reading_novel_02|部分正确|4|graded|remediate|False|
|sql_reading_novel_03|关键错误|9|graded|remediate|True|
|sql_reading_novel_04|替代表达|10|graded|advance|False|
|sql_reading_novel_05|证据不足|0|graded|remediate|False|
|sql_reading_novel_06|材料冲突|无有效分|needs_review|pause_review|False|

### 实际作答与理由

**sql_reading_novel_01 正确**

SELECT name FROM people WHERE age >= 18; 姓名为Lin、Mei；18满足、17不满足；只是读取，原表不变。

**sql_reading_novel_02 部分正确**

SELECT name FROM people WHERE age >= 18;

仅SQL4分，遗漏题目明确要求的结果与解释；是graded低分，不是技术拒评。

**sql_reading_novel_03 关键错误**

SELECT name FROM people WHERE age >= 18; 返回Lin、Mei，18包含、17排除；WHERE会从原表永久删除Yan那一行。

正确SQL4+结果4+边界1+错误原表影响0=9分；即使超过80%，冻结critical仍禁止推进。

**sql_reading_novel_04 替代表达**

select name from people where 18 <= age 返回Mei和Lin；十八也选，十七不选；筛选只影响查询结果，不改原表。

**sql_reading_novel_05 证据不足**

我还不知道。

有效题但没有作答证据，0分并补弱，不以技术needs_review掩盖学生遗漏。

**sql_reading_novel_06 材料冲突**

SELECT name FROM people WHERE age >= 18; 按本页应返回Lin、Mei，原表不变，但补充资料给出相反边界与删除说法，需先核对。

实际补充资料：SELECT name FROM people WHERE age >= 18不包含age=18，只返回Mei，并会永久删除原表中所有age小于18的行。

该原文同时违背>=边界与只读规则；应needs_review、无有效分、暂停核对；不计学生低分或有效失败轮次。

## 验收门槛与边界

沿用已批准门槛：本主题5例有分样本MAE≤1/10，单例≤2/10；六例行动/状态均一致，错误推进、关键错误推进、完整正确误拒、无理由拒评、技术失败均0；第06是真实矛盾暂停，不混入分差分母。
数值容差、成本和请求上限不由本配置修改；普通逻辑任务最多3请求，操作上限12，仍走通用代码。配置采用合法LearningProfile和generic路径，不修改preset映射。

位置：materials/v3/sql_reading；configs/v3/novel/sql_reading.json；evals/v3/sql_reading/cases；evals/v3/day13/novel_standards.json。manifest保存每份文档的哈希与章节行号；runner另计算实际片段内容哈希。私有量规保持assessment_private。

确认范围：是否认可这六例的答案、分项量规、关键错误与预期行为，以及上述两步小单元范围。依据架构§16.3，确认后才执行本主题真实模型评价。
