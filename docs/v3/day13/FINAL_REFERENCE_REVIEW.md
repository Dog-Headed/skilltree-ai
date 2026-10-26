# Day 13 新独立验证集：12例参考标准（待用户复核）

原保留集因参与发现评价脚本缺陷，不再承担最终未见验证。本套新题在通用输入修复、dev-v7真实运行完成后预先登记，不根据本套模型输出写标准；尚未调用模型，也未据它修改运行代码或Prompt。作者为主 Agent，不能冒称已获人工或独立AI批准。

实际案例见 `evals/v3/day13/final_suite/`，结构化标准见 `final_standards.json`。冻结候选版本、用户批准标准后才运行；若据本套失败修复，则必须换新独立案例，不复称未见。

共同门槛沿用已批准协议，分科报告：MAE≤1/10、单例≤2/10；错误推进、关键错误放行、完整正确误拒、无理由拒评与技术失败均0，行动与状态一致。每科4例中3例有有效分、1例期望材料冲突暂停；不靠全部拒评满足零错误推进。

每科第3例两个必要目标采用90+10分，第二目标失败，即使总分90也不能推进。全部是固定题评价/Diagnosis/守卫测试，不冒充完整教学演示。第4例仅把实际矛盾材料原文送入，测试设计标签不入模型输入。

|案例|参考总分|有效行动|关键错误|
|---|---:|---|---|
|python_holdout_final01|10/10|advance|否|
|python_holdout_final02|0/10|remediate|是|
|python_holdout_final03|90/100|remediate|否|
|python_holdout_final04|不产生有效分/10|pause_review|否|
|mathematics_holdout_final01|20/20|advance|否|
|mathematics_holdout_final02|0/10|remediate|是|
|mathematics_holdout_final03|90/100|remediate|否|
|mathematics_holdout_final04|不产生有效分/10|pause_review|否|
|english_holdout_final01|10/10|advance|否|
|english_holdout_final02|6/10|remediate|是|
|english_holdout_final03|90/100|remediate|否|
|english_holdout_final04|不产生有效分/10|pause_review|否|

## 逐例答案、量规与引用依据

### python_holdout_final01

题目：阅读代码，列出输出并说明为什么停止：
n=3
while n>0:
    n=n-1
    print(n)

学生答案：输出依次二、一、零；每轮先减1再打印，n到0后0>0为假而停止。

参考：输出2、1、0，条件在每次进入前检查，n减到0后不再进入。

量规：
- q1_c1（4分）：正确给出2、1、0的顺序。
- q1_c2（4分）：说明每轮先减1后打印，且n逐次变为2、1、0。
- q1_c3（2分）：说明n=0后条件为假而停止。

来源：materials/v3/python/teaching.md §py-while, materials/v3/python/teaching.md §py-explain, materials/v3/python/assessment_private.md §py-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### python_holdout_final02

题目：x=2
if x>5:
    label='A'
else:
    label='B'
给出label并解释选择原因。

学生答案：A；有if就执行第一个分支，不需要判断真假。

参考：B；2>5是假，所以执行else。

量规：
- q1_c1（4分）：给出正确的B。
- q1_c2（4分）：结合2>5为假解释分支选择；不能声称有if就无条件执行首分支。【冻结关键项】
- q1_c3（2分）：说明此处走else而不执行A分支。

来源：materials/v3/python/teaching.md §py-condition, materials/v3/python/assessment_private.md §py-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### python_holdout_final03

题目：for label in ['a','b']:
    print(label)
给出输出并解释label取得什么。

学生答案：输出a、b；label依次取两个元素，不是下标，列表取完就结束。

参考：a、b，取得元素而非下标，取完结束。

量规：
- q1_c1（36分）：正确给出a、b顺序。
- q1_c2（36分）：说明label取元素而不是下标。
- q1_c3（18分）：说明列表遍历完毕即结束。

来源：materials/v3/python/teaching.md §py-for, materials/v3/python/teaching.md §py-foundation, materials/v3/python/assessment_private.md §py-private-criteria。

题目：for n in range(3,3)的循环体执行几次？说明为什么。

学生答案：一次，因为写了for就至少运行一次。

参考：零次；起点与被排除的stop相同，所以序列为空。

量规：
- q2_c1（4分）：明确执行零次。
- q2_c2（4分）：说明range(3,3)是空序列。
- q2_c3（2分）：联系stop排除规则解释起点等于终点仍无元素。

来源：materials/v3/python/teaching.md §py-for, materials/v3/python/assessment_private.md §py-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### python_holdout_final04

题目：n=0；while n>0的循环体执行几次？解释条件检查顺序。

学生答案：按本页先判断应为零次，但补充资料写至少一次，两个说法不一致。

参考：零次；0>0为假，先判断再决定进入。

量规：
- q1_c1（4分）：指出零次。
- q1_c2（4分）：说明先判断条件再进入循环体。
- q1_c3（2分）：说明首次0>0为假。

来源：materials/v3/python/teaching.md §py-while, materials/v3/python/teaching.md §py-explain, materials/v3/python/assessment_private.md §py-private-criteria, materials/v3/python/assessment_private.md §py-private-quality。

实际附加资料：while总是先执行一次循环体，再检查条件；即使初值使条件为假也至少执行一次。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### mathematics_holdout_final01

题目：解5x+2=2x+14，只填写单个无单位数值x；下一题另外说明过程。

学生答案：4.000

参考：4

量规：

来源：materials/v3/mathematics/teaching.md §math-multistep, materials/v3/mathematics/assessment_private.md §math-private-criteria。

题目：解释5x+2=2x+14的等价求解步骤，并代回原式检验。

学生答案：两边同减2x再同减2，得3x=12；两边同除3得x=4。原式左22、右22。

参考：两边减2x与2，再除3，x=4；两边均22。

量规：
- q2_c1（4分）：解值x=4正确。
- q2_c2（4分）：说明两边同减2x、同减2、同除非零3的等价过程。
- q2_c3（2分）：代回原式分别得到22和22。

来源：materials/v3/mathematics/teaching.md §math-multistep, materials/v3/mathematics/teaching.md §math-check, materials/v3/mathematics/assessment_private.md §math-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### mathematics_holdout_final02

题目：解-2x=10，说明除法符号，并代回检验。

学生答案：x=5，因为正数除负数总是正数。

参考：x=-5；两边除以-2，正除负得负；-2*(-5)=10。

量规：
- q1_c1（4分）：正确解x=-5。
- q1_c2（4分）：说明两边同除-2且10除-2为负；不得宣称正除负总为正。【冻结关键项】
- q1_c3（2分）：代回-2*(-5)=10检验。

来源：materials/v3/mathematics/teaching.md §math-foundation, materials/v3/mathematics/teaching.md §math-multiply, materials/v3/mathematics/teaching.md §math-check, materials/v3/mathematics/assessment_private.md §math-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### mathematics_holdout_final03

题目：解3x-6=9，解释步骤并检验。

学生答案：两边同加6得3x=15，再同除3得x=5；代回3*5-6=9。

参考：x=5，同加6再同除3，代回左右均9。

量规：
- q1_c1（36分）：正确解x=5。
- q1_c2（36分）：说明两边同加6和同除3。
- q1_c3（18分）：正确代回原式检验。

来源：materials/v3/mathematics/teaching.md §math-add, materials/v3/mathematics/teaching.md §math-multiply, materials/v3/mathematics/teaching.md §math-check, materials/v3/mathematics/assessment_private.md §math-private-criteria。

题目：能将4x=12两边同除以0来求解吗？解释原因。

学生答案：能，除以零合法而且总保持相同的解。

参考：不能，除数必须非零，除以0没有定义。

量规：
- q2_c1（4分）：明确不能除以0。
- q2_c2（4分）：说明除以0没有定义。
- q2_c3（2分）：说明求解的同除操作要求除数非零，不能以除0得到解。

来源：materials/v3/mathematics/teaching.md §math-multiply, materials/v3/mathematics/assessment_private.md §math-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### mathematics_holdout_final04

题目：解6x=18，并说明为什么能两边同除6。

学生答案：按本页x=3，因为6非零；补充资料却说不能同除6，我无法按两份相反规则接受评价。

参考：x=3；两边同除非零6。

量规：
- q1_c1（4分）：正确解x=3。
- q1_c2（4分）：说明两边同时除6。
- q1_c3（2分）：说明6非零，同除合法。

来源：materials/v3/mathematics/teaching.md §math-multiply, materials/v3/mathematics/teaching.md §math-uncertainty, materials/v3/mathematics/assessment_private.md §math-private-criteria, materials/v3/mathematics/assessment_private.md §math-private-quality。

实际附加资料：等式两边同除非零的6会改变解集，不能用来求解6x=18；只改变左边才保证等价。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### english_holdout_final01

题目：把Nora had lunch yesterday.改为一般疑问句，保留原意与时间。

学生答案：Yesterday, did Nora have lunch?

参考：Did Nora have lunch yesterday?

量规：
- q1_c1（4分）：用Did前置构成一般疑问。
- q1_c2（4分）：did后have为正确原形。
- q1_c3（2分）：保留Nora吃午饭的意义与yesterday；时间状语放句首也有效。

来源：materials/v3/english/teaching.md §en-question, materials/v3/english/teaching.md §en-affirmative, materials/v3/english/teaching.md §en-paragraph, materials/v3/english/assessment_private.md §en-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### english_holdout_final02

题目：把Leo wrote a note yesterday.改为一般疑问句。

学生答案：Did Leo wrote a note yesterday? 因为是过去，did后必须继续用过去式。

参考：Did Leo write a note yesterday?

量规：
- q1_c1（4分）：Did前置、主语与普通实义动词的一般疑问结构正确4分。
- q1_c2（4分）：did后使用write原形；明确宣称did后必须用过去式属于关键错误。【冻结关键项】
- q1_c3（2分）：保留原叙述意义1分，保留yesterday时间1分；不重复扣动词错误。

来源：materials/v3/english/teaching.md §en-question, materials/v3/english/teaching.md §en-affirmative, materials/v3/english/assessment_private.md §en-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### english_holdout_final03

题目：把They saw the show last night.改为否定句。

学生答案：They didn't see the show last night.

参考：They did not see the show last night.

量规：
- q1_c1（36分）：did not或didn’t否定结构正确。
- q1_c2（36分）：助动词后使用see原形。
- q1_c3（18分）：保留原叙述意义与last night。

来源：materials/v3/english/teaching.md §en-negative, materials/v3/english/assessment_private.md §en-private-criteria。

题目：把Iris played chess yesterday.改为一般疑问句。

学生答案：Iris played chess yesterday.

参考：Did Iris play chess yesterday?

量规：
- q2_c1（4分）：Did前置形成疑问结构。
- q2_c2（4分）：在Did后使用play原形；原陈述不满足该要求。
- q2_c3（2分）：形成保留原意与时间的疑问表达；只重复陈述不得本项分。

来源：materials/v3/english/teaching.md §en-question, materials/v3/english/teaching.md §en-paragraph, materials/v3/english/assessment_private.md §en-private-criteria。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

### english_holdout_final04

题目：把We ate rice last night.改为否定句。

学生答案：We did not eat rice last night. 可是补充资料说要用ate，与本页原形规则矛盾。

参考：We did not eat rice last night.

量规：
- q1_c1（4分）：did not或didn’t否定结构正确。
- q1_c2（4分）：did后使用eat原形。
- q1_c3（2分）：保留原意及last night。

来源：materials/v3/english/teaching.md §en-negative, materials/v3/english/assessment_private.md §en-private-criteria, materials/v3/english/assessment_private.md §en-private-quality。

实际附加资料：普通实义动词过去否定句使用did not以后，后面的行为动词必须继续用过去式ate或went，不能用原形。

允许证据：只允许本例学生实际答案中的可定位原文、实际工具返回及上述冻结来源。没有预置历史；completed本身不是当前掌握证据。

标准SHA256：`df99f181b5aec7b72cfae0d9a3a512eb50557b9d42931a5dc4005397aa8063c5`。

本套仍为待用户复核，0次真实模型调用。不得把作者自己的标准标为人工金标准。
