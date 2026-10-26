# Day 13 原12例曝光验证：答案与量规复核（待用户确认）

这12例于第一份候选冻结后打开，尚未调用真实模型。预检暴露评价脚本的历史评分与标签泄漏问题，已用于修正评价输入，因而后续只能称为“曝光验证”，不能再称为最终未见集。原36例文件保持原样。最终验收另需独立12例。

以下是主 Agent 的参考标准草案，不是独立审阅、人工金标准或评测结果。原稿宽区间被展开为可复核的分项中心，未根据这些案例的模型输出制定答案。

## 拟采用的共同规则

三科分别使用此前批准的门槛：10分制MAE≤1、单例误差≤2；错误推进、关键错误推进、完整正确误拒、普通有效题意外拒评、技术失败均为0；状态与行动全部一致。09/10/11是普通评分，12是含实际矛盾补充材料的普通评分，期望needs_review；不将拒评样本计入评分误差分母。

10的先修历史均为正确对照，预置10/10并保留原题与答案。历史已完成或一次正确不能证明现在没有薄弱点；也不能把正确历史伪造成零分、强行先修回顾。

11的q1占90分，q2占10分，各自是必要目标。q1正确、q2不达标时，即使总分90也必须拒绝推进。q2分项描述改为具体要求，Python q1删除未在题面要求的等号边界知识。

12仅把实际附件身份、可见性和原文传入；剔除source_conflict、假材料、conflicts_with等设计标签。题面和目标删除“请指出冲突”的提示；仍保留学生实际提出的异议。冻结题目与补充材料确有规则矛盾，期望停下复核而非计有效失败。该测试只证明固定输入下评分器处理补充内容的行为，不证明生产导入链路会自动发现所有冲突。

|案例|建议总分/满分|状态与行动|
|---|---:|---|
|python_holdout_09|10/10|graded / advance|
|python_holdout_10|4/10|graded / remediate|
|python_holdout_11|90/100|graded / remediate|
|python_holdout_12|不产生有效分/10|needs_review / pause_review|
|mathematics_holdout_09|20/20|graded / advance|
|mathematics_holdout_10|6/10|graded / remediate|
|mathematics_holdout_11|90/100|graded / remediate|
|mathematics_holdout_12|不产生有效分/10|needs_review / pause_review|
|english_holdout_09|10/10|graded / advance|
|english_holdout_10|4/10|graded / remediate|
|english_holdout_11|90/100|graded / remediate|
|english_holdout_12|不产生有效分/10|needs_review / pause_review|

## 逐例题目、答案与依据

### python_holdout_09

题目：列出range(6,0,-2)并解释为什么不取0。

学生答案：六，四，二。每次减二，下界0不取。

参考：6、4、2；步长-2，0是被排除的stop。

量规（按原分项满分）：
- q1_c1（4分）：给出正确的分支、序列或结果
- q1_c2（4分）：用实际取值说明执行顺序
- q1_c3（2分）：说明边界或终止依据

来源：
- materials/v3/python/teaching.md §py-for，行29–36；源SHA256 `b42b057efa2f726124fada0ba9a2bd419f16973392f12b22cbebb1d394bc18fc`。
- materials/v3/python/assessment_private.md §py-private-criteria，行6–13；源SHA256 `ee4614a178b553d693234c2f8137ad2f7dc2106da60d0e64cd6f8604dbc33f45`。

允许引用的当前/历史原文：answer:python_holdout_09:q1:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### python_holdout_10

题目：列出range(2,5)并说明最后一项。

学生答案：2、3、4、5，最后5。

参考：2、3、4；5排除。

量规（按原分项满分）：
- q1_c1（4分）：完整正确序列4分；非空正确前缀但多列或漏列终点2分；无正确序列0分。
- q1_c2（4分）：实际取值顺序完全正确4分；列出连续正确前缀但错误地包含stop时2分；无相关证据0分。
- q1_c3（2分）：正确指出最后为4且5排除2分；只正确一项1分；两项都错0分。

来源：
- materials/v3/python/teaching.md §py-for，行29–36；源SHA256 `b42b057efa2f726124fada0ba9a2bd419f16973392f12b22cbebb1d394bc18fc`。
- materials/v3/python/assessment_private.md §py-private-criteria，行6–13；源SHA256 `ee4614a178b553d693234c2f8137ad2f7dc2106da60d0e64cd6f8604dbc33f45`。

先修历史原题：for value in [3,8]时value分别是什么？

历史答案：3和8，直接取元素。（本草案10/10）。

允许引用的当前/历史原文：answer:python_holdout_10:q1:1, history:python_holdout_10:foundation:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### python_holdout_11

题目：x=4。判断if x>=3是否成立并解释。

学生答案：成立，4>=3为真。

参考：成立，因为4大于3，进入该分支。

量规（按原分项满分）：
- q1_c1（36分）：正确判断条件成立，得36分。
- q1_c2（36分）：根据实际x=4解释4>=3为真，得36分。
- q1_c3（18分）：结合本题取值作出一致判断得18分；不要求未被题面提出的x=3边界举例。

来源：
- materials/v3/python/teaching.md §py-condition，行14–28；源SHA256 `b42b057efa2f726124fada0ba9a2bd419f16973392f12b22cbebb1d394bc18fc`。
- materials/v3/python/assessment_private.md §py-private-criteria，行6–13；源SHA256 `ee4614a178b553d693234c2f8137ad2f7dc2106da60d0e64cd6f8604dbc33f45`。

题目：n=0
while n>0:
    n=n-1
说明循环体执行几次及首次条件判断。

学生答案：有while就至少执行一次。

参考：零次；首次0>0为假。

量规（按原分项满分）：
- q2_c1（4分）：正确判断执行零次4分。
- q2_c2（4分）：说明先判断条件再决定进入循环4分。
- q2_c3（2分）：指出首次0>0为假2分。

来源：
- materials/v3/python/teaching.md §py-while，行37–48；源SHA256 `b42b057efa2f726124fada0ba9a2bd419f16973392f12b22cbebb1d394bc18fc`。
- materials/v3/python/assessment_private.md §py-private-criteria，行6–13；源SHA256 `ee4614a178b553d693234c2f8137ad2f7dc2106da60d0e64cd6f8604dbc33f45`。

允许引用的当前/历史原文：answer:python_holdout_11:q1:1, answer:python_holdout_11:q2:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### python_holdout_12

题目：列出range(1,4)的取值，说明边界。

学生答案：1、2、3，另一资料说包含4，与本页规则冲突。

参考：1、2、3；stop=4被排除。

量规（按原分项满分）：
- q1_c1（4分）：给出正确结果
- q1_c2（4分）：根据实际取值解释顺序
- q1_c3（2分）：解释边界或终止

来源：
- materials/v3/python/teaching.md §py-for，行29–36；源SHA256 `b42b057efa2f726124fada0ba9a2bd419f16973392f12b22cbebb1d394bc18fc`。
- materials/v3/python/assessment_private.md §py-private-criteria，行6–13；源SHA256 `ee4614a178b553d693234c2f8137ad2f7dc2106da60d0e64cd6f8604dbc33f45`。

实际附加资料：range的stop总是包含。

允许引用的当前/历史原文：answer:python_holdout_12:q1:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### mathematics_holdout_09

题目：解3(x-2)=9，只填无单位的单个数值x；q2解释并检验。

学生答案：5.0

参考：5

量规（按原分项满分）：

来源：
- materials/v3/mathematics/teaching.md §math-multistep，行26–32；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/teaching.md §math-check，行33–40；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/assessment_private.md §math-private-criteria，行6–12；源SHA256 `b0d5e7a7f8a78cbceba3b2701b9e7d47764cb1a06bd01e08757dc87a28c174c5`。

题目：解3(x-2)=9，展示等价步骤并检验。

学生答案：5.0。先展开为3x-6=9，得3x=15，再除3；3*(5-2)=9。

参考：先除3得x-2=3，再加2得x=5；3*(5-2)=9。

量规（按原分项满分）：
- q2_c1（4分）：给出正确解值
- q2_c2（4分）：说明两边相同的等价操作
- q2_c3（2分）：代回原式检验

来源：
- materials/v3/mathematics/teaching.md §math-multistep，行26–32；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/teaching.md §math-check，行33–40；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/assessment_private.md §math-private-criteria，行6–12；源SHA256 `b0d5e7a7f8a78cbceba3b2701b9e7d47764cb1a06bd01e08757dc87a28c174c5`。

允许引用的当前/历史原文：answer:mathematics_holdout_09:q1:1, answer:mathematics_holdout_09:q2:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### mathematics_holdout_10

题目：解4x-5=19并检验原式。

学生答案：x=6，因为4x=24；检验原式4*6-5=24。

参考：两边加5再除4得x=6；4*6-5=19。

量规（按原分项满分）：
- q1_c1（4分）：给出正确解x=6得4分。
- q1_c2（4分）：明确两边同加5再同除4得4分；仅正确列出4x=24而不说明等价操作得2分；无有效操作证据0分。
- q1_c3（2分）：正确代回并比较19=19得2分；实际算错验证结果0分。

来源：
- materials/v3/mathematics/teaching.md §math-multistep，行26–32；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/teaching.md §math-check，行33–40；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/assessment_private.md §math-private-criteria，行6–12；源SHA256 `b0d5e7a7f8a78cbceba3b2701b9e7d47764cb1a06bd01e08757dc87a28c174c5`。

先修历史原题：计算-8除以-2并解释。

历史答案：4，同号相除为正。（本草案10/10）。

允许引用的当前/历史原文：answer:mathematics_holdout_10:q1:1, history:mathematics_holdout_10:foundation:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### mathematics_holdout_11

题目：解2x+6=14并代回检验。

学生答案：两边减6再除2，x=4；代回14=14。

参考：两边减6得2x=8，再除2得x=4；2*4+6=14。

量规（按原分项满分）：
- q1_c1（36分）：给出正确解值
- q1_c2（36分）：说明两边相同的等价操作
- q1_c3（18分）：代回原式检验

来源：
- materials/v3/mathematics/teaching.md §math-add，行12–18；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/teaching.md §math-multiply，行19–25；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/assessment_private.md §math-private-criteria，行6–12；源SHA256 `b0d5e7a7f8a78cbceba3b2701b9e7d47764cb1a06bd01e08757dc87a28c174c5`。

题目：为什么不能只将等式左边减6而保持右边不变？

学生答案：只改变左边也总会保持等式。

参考：两边必须同减6，才保持等价。

量规（按原分项满分）：
- q2_c1（4分）：说明等式两边必须同减6得4分。
- q2_c2（4分）：说明只改变一边通常破坏相等或解集得4分。
- q2_c3（2分）：能将上述理由应用到本题，而非宣称只改左边总成立，得2分。

来源：
- materials/v3/mathematics/teaching.md §math-add，行12–18；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/assessment_private.md §math-private-criteria，行6–12；源SHA256 `b0d5e7a7f8a78cbceba3b2701b9e7d47764cb1a06bd01e08757dc87a28c174c5`。

允许引用的当前/历史原文：answer:mathematics_holdout_11:q1:1, answer:mathematics_holdout_11:q2:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### mathematics_holdout_12

题目：解2x+3=13，说明等价步骤并检验。

学生答案：x=5，但只减左边的资料与两边同减规则矛盾。

参考：两边同减3再同除2，x=5；2*5+3=13。

量规（按原分项满分）：
- q1_c1（4分）：给出正确解值
- q1_c2（4分）：说明两边相同的等价操作
- q1_c3（2分）：代回原式检验

来源：
- materials/v3/mathematics/teaching.md §math-add，行12–18；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/teaching.md §math-multiply，行19–25；源SHA256 `c77f74e720098a8956628d99c7bcb830ccfbafe071bd853f4538240fb8247091`。
- materials/v3/mathematics/assessment_private.md §math-private-criteria，行6–12；源SHA256 `b0d5e7a7f8a78cbceba3b2701b9e7d47764cb1a06bd01e08757dc87a28c174c5`。

实际附加资料：等式只改变左边也总是保持等价。

允许引用的当前/历史原文：answer:mathematics_holdout_12:q1:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### english_holdout_09

题目：把We saw the comet last night.改为否定句。

学生答案：We didn't see the comet last night.

参考：We did not see the comet last night.

量规（按原分项满分）：
- q1_c1（4分）：符合目标句型
- q1_c2（4分）：动词形式正确
- q1_c3（2分）：保留原意与时间且可理解

来源：
- materials/v3/english/teaching.md §en-negative，行20–26；源SHA256 `8c3435f1ed5054519da4ca0ea49cf58655aac06815ed7625517b913570fed65c`。
- materials/v3/english/assessment_private.md §en-private-criteria，行6–13；源SHA256 `9a50725250493fcac6c20d83331c1a4240e21af3e251908993ada892eb2f2a9d`。

允许引用的当前/历史原文：answer:english_holdout_09:q1:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### english_holdout_10

题目：把Nia goes home.改为含yesterday的过去肯定句。

学生答案：Nia goed home yesterday.

参考：Nia went home yesterday.

量规（按原分项满分）：
- q1_c1（4分）：过去肯定构式完整4分；主语与肯定语序正确但过去式错误2分；无相关构式0分。
- q1_c2（4分）：使用go的正确过去式went得4分；goed为0分。
- q1_c3（2分）：保留原叙述意义1分，保留yesterday时间1分；不重复扣语法分。

来源：
- materials/v3/english/teaching.md §en-affirmative，行12–19；源SHA256 `8c3435f1ed5054519da4ca0ea49cf58655aac06815ed7625517b913570fed65c`。
- materials/v3/english/assessment_private.md §en-private-criteria，行6–13；源SHA256 `9a50725250493fcac6c20d83331c1a4240e21af3e251908993ada892eb2f2a9d`。

先修历史原题：把She visits school.改为现在时否定句。

历史答案：She does not visit school. does后用原形。（本草案10/10）。

允许引用的当前/历史原文：answer:english_holdout_10:q1:1, history:english_holdout_10:foundation:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### english_holdout_11

题目：把Mia visits the library.改为含yesterday的过去肯定句。

学生答案：Mia visited the library yesterday.

参考：Mia visited the library yesterday.

量规（按原分项满分）：
- q1_c1（36分）：符合目标句型
- q1_c2（36分）：动词形式正确
- q1_c3（18分）：保留原意与时间且可理解

来源：
- materials/v3/english/teaching.md §en-affirmative，行12–19；源SHA256 `8c3435f1ed5054519da4ca0ea49cf58655aac06815ed7625517b913570fed65c`。
- materials/v3/english/assessment_private.md §en-private-criteria，行6–13；源SHA256 `9a50725250493fcac6c20d83331c1a4240e21af3e251908993ada892eb2f2a9d`。

题目：把Mia visited the library yesterday.改为一般疑问句。

学生答案：Mia visited the library yesterday.

参考：Did Mia visit the library yesterday?

量规（按原分项满分）：
- q2_c1（4分）：用Did前置构成一般疑问结构4分。
- q2_c2（4分）：在Did之后正确使用visit原形4分；重复visited的陈述句不满足本项。
- q2_c3（2分）：完整表达原意和时间的疑问意图2分；只重复原陈述而无疑问表达0分。

来源：
- materials/v3/english/teaching.md §en-question，行27–32；源SHA256 `8c3435f1ed5054519da4ca0ea49cf58655aac06815ed7625517b913570fed65c`。
- materials/v3/english/assessment_private.md §en-private-criteria，行6–13；源SHA256 `9a50725250493fcac6c20d83331c1a4240e21af3e251908993ada892eb2f2a9d`。

允许引用的当前/历史原文：answer:english_holdout_11:q1:1, answer:english_holdout_11:q2:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。

### english_holdout_12

题目：把They played cards yesterday.改为否定句。

学生答案：They did not play cards yesterday. 另一资料要求played，与本页规则冲突。

参考：They did not play cards yesterday.

量规（按原分项满分）：
- q1_c1（4分）：符合目标句型
- q1_c2（4分）：动词形式正确
- q1_c3（2分）：保留原意与时间且可理解

来源：
- materials/v3/english/teaching.md §en-negative，行20–26；源SHA256 `8c3435f1ed5054519da4ca0ea49cf58655aac06815ed7625517b913570fed65c`。
- materials/v3/english/assessment_private.md §en-private-criteria，行6–13；源SHA256 `9a50725250493fcac6c20d83331c1a4240e21af3e251908993ada892eb2f2a9d`。

实际附加资料：did not后必须使用过去式。

允许引用的当前/历史原文：answer:english_holdout_12:q1:1。实际运行的当前评分证据ID以验证后的结果注册表为准，须核对对应原文。


复核对象：`evals/v3/day13/exposed_standards.json` SHA256 `ade5102181eb6e28f8976e1d07685c2f90a67b719d6f50bc09533158bc551d09`。

本文件和结构化标准均为待用户复核。未收到明确批准前，不运行这12例真实评价，也不把其分数写成正式内容质量指标。
