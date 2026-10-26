# final-v2 真实评价十二例：独立 AI 复核

日期：2026-10-23。仅审查 `work/day13-20261023/final-v2`；不改生产代码、标准、原始输出或主审报告，不重跑真实模型，不读取秘密配置。

**结论：Python、数学、英语均为 `approved_independent_review`，限这十二例的评分、最终诊断与证据。未发现内容阻断；英语两处摘录覆盖偏窄列为非阻断备注。此结论不是人工批准，也不批准整体发布。**

本轮是 freeze04 后对同字节已批准独立集的复验，身份为 `independent_final_revalidation`、`first_unseen_execution=false`。不是第一次未见执行，不能重新宣称为全新盲测。原始 final-v1 及各历史失败均保留。

## 按科结论

| 学科 | 行动 | 有效计分样本 | MAE（归一化 / 10分制） | 错误推进 / 正确误拒 | 请求 | 独立语义结论 |
|---|---:|---:|---:|---:|---:|---|
| python | 4/4 | 3 | 0 / 0 | 0 / 0 | 10 | 通过，限本轮证据 |
| mathematics | 4/4 | 3 | 0 / 0 | 0 / 0 | 10 | 通过，限本轮证据 |
| english | 4/4 | 3 | 0 / 0 | 0 / 0 | 10 | 通过，限本轮证据 |

三个04为预期资料冲突暂停，不计MAE分母；三个02为冻结关键错误，均拒绝推进；三个03均为90分但必要o2=0，均补弱；三个01的完整正确作答均通过。无意外拒评或技术失败。

## 机械核对与正式输出口径

- 十二份 `result.json` 与原 `report.json` 逐例完全一致；案例、已批准标准、run manifest、freeze04、输入资料哈希及原 final-v1 reviewed-report 哈希链吻合。
- 用原始正式评分 JSON 离线回放现有 `evaluate_quiz`，十二份 `EvaluationResult` 全字段一致，再经 `validate_evaluation_context` 核对。三十五个学生原文锚点均逐字匹配实际作答区间；四十一个逐例绑定来源均核实际原文件、行号、片段哈希及文件哈希。
- 九份正式最终 `DiagnosisDecision` 通过原契约与业务校验；引用在实际允许集合中。九份 `decide_progress` 纯计算结果与已存守卫完全一致。三个needs_review没有最终Diagnosis或正式守卫，未冒充学生低分。
- 正式评分首份/末份均12/12合法；正式最终Diagnosis首份/末份均9/9合法。另有9次工具选择输出。原report每科first_structurally_valid=6/7混入了01合法的空AIMessage/model_finished工具阶段，不能把它说成最终诊断非法或输出修复。全部真实任务output_repairs=0。
- 六个02/03实际查询当前节点、合法前置历史及完成状态，各工具执行3次，历史均为no_history；最终输入也确实没有历史作答记录。诊断选择当前补弱而不凭完成状态断言前置已掌握/已不会，成立。本套没有“实际取得同源错答再回前置”的正向覆盖，不能夸称已测试该能力。
- 三十次真实请求、三十份响应与usage逐条对应，任务请求≤3、单操作≤12、网络重试/输出修复均0，工具≤2轮/3次。只读打开原运行SQLite，缓存任务结果、计数与报告相同，读取前后DB哈希不变。操作记录status=running是runner未做业务关闭的评估存储状态，不代表本轮还有模型在运行。
- 原始模型为deepseek-flash；Prompt grading=`v3-day13-text-rubric-4`、diagnosis=`v3-day13-diagnosis-6`。原响应usage合计输入111199、输出40937 token；无可靠计价，费用保持不可得。

## 逐例实质审查

### english_holdout_final01

实际：graded / 10.0 / advance；独立判定：supported。

Yesterday置句首，后接did Nora have lunch构成合法一般疑问，did后have原形，主语/事件/时间保留。4/4/2=10与advance成立；接受正确语序变体。

实际绑定依据：
- `materials/v3/english/teaching.md:27-32`，`section_42345187ca25ea362c66e1b1`：“普通实义动词的一般疑问常用 Did + 主语 + 动词原形。”
- `materials/v3/english/teaching.md:33-40`，`section_f267ed980111fd5bf24c140c`：“不同但成立的经历、同义词和句子顺序可以接受。”

raw SHA256 `eb8d3b09d8d029affe0cc07b12d1c7809fb8357af89a57b4041fcb8630764b47`；result SHA256 `5760cc7f98d2b7ebcca5eb5c525f7bd66e02ae14e98c367bc8cc623c47701485`。

### english_holdout_final02

实际：graded / 6.0 / remediate；独立判定：supported_with_nonblocking_note。

Did前置和事件/时间保留分别4与2分；wrote未还原write，且明确宣称did后必须继续过去式，动词项0与冻结critical成立。6分/补弱合理，不重复扣掉其余正确内容。

非阻断：q1_c3摘录为“a note yesterday”，直接覆盖宾语与时间，主语Leo要结合完整学生答案和q1_c1整句引文核对；引用覆盖偏窄，不改变实际得分或行动。

实际绑定依据：
- `materials/v3/english/teaching.md:27-32`，`section_42345187ca25ea362c66e1b1`：“普通实义动词的一般疑问常用 Did + 主语 + 动词原形。”
- `materials/v3/english/assessment_private.md:6-13`，`section_160aa6905dd870aac35d289e`：“did 后再次使用过去式、把过去任务持续写成现在时，应定位实际动词与对应量规。”

raw SHA256 `10a070f9a6b8dc6f28167dbe70396687cbd031f7e111763d3c98b9de833ae9e4`；result SHA256 `7d1b41bd9077ae8e5a17f719f4c3f5395c41be99133b8d2fdcf4a36642508033`。

### english_holdout_final03

实际：graded / 90.0 / remediate；独立判定：supported_with_nonblocking_note。

q1否定句didn't see及原意/last night均正确，36/36/18=90。q2只重复陈述Iris played chess yesterday，未形成Did疑问、未给play原形，冻结三个分项均0。必要o2未达标，remediate成立。

非阻断：q1_c3仅摘录“last night”，单条证据只支持时间，不能独自证明They/the show的原意保留；完整实际答案确实保留原意，故属非阻断的分项引文覆盖不足，不能称每条引文都独立完整支持全部子条件。

实际绑定依据：
- `materials/v3/english/teaching.md:20-26`，`section_eabcaf376f97f0f880a687c1`：“普通实义动词的过去否定用主语加 did not 或 didn't，再加动词原形。”
- `materials/v3/english/teaching.md:27-32`，`section_42345187ca25ea362c66e1b1`：“普通实义动词的一般疑问常用 Did + 主语 + 动词原形。”
- `materials/v3/english/teaching.md:33-40`，`section_f267ed980111fd5bf24c140c`：“题目若明确要求疑问，单给正确肯定句仍没有满足该任务；题面不清时应先澄清。”

raw SHA256 `0aa2c7bd8fc73d5bfcbb275143f8d928819872200e7c538d1febd9e9a8169bcf`；result SHA256 `c4eac24f9d644183cb48474e42845c0a29bb2b8ad421440ec4a60c8795b2cca3`。

### english_holdout_final04

实际：needs_review / 不计分 / assessment_review；独立判定：supported。

绑定规则要求did not后用原形eat，实际附件却明确要求过去式ate/went，学术内容互斥。评分正式输出定位双方原文及暂停规则，needs_review成立；学生正确否定句不应被当作消除资料冲突的理由。

实际绑定依据：
- `materials/v3/english/teaching.md:20-26`，`section_eabcaf376f97f0f880a687c1`：“普通实义动词的过去否定用主语加 did not 或 didn't，再加动词原形。”
- `materials/v3/english/assessment_private.md:21-27`，`section_c0dda34230d367b7a281d295`：“若两份资料对 did 后的动词形式有冲突，应标明资料问题并暂停有效评价。”

实际附件原文（确在本次评分输入，不是只听学生声称冲突）：“普通实义动词过去否定句使用did not以后，后面的行为动词必须继续用过去式ate或went，不能用原形。”

raw SHA256 `5256389a915163d3e75d8a5d7446a2142c9021a5cb490e40a174c0445f5c48fc`；result SHA256 `d7c83eb52d96cf3555e8bf9cf01111559b561cf078f565d138b59b2267dfb1de`。

### mathematics_holdout_final01

实际：graded / 20.0 / advance；独立判定：supported。

5x+2=2x+14解为4；4.000的确定性数值评价独立重算正确。文字另有同减2x、同减2、同除3，以及原式左右22=22；数值没有代替解释证据。10+10=20与两个必要目标通过成立。

实际绑定依据：
- `materials/v3/mathematics/teaching.md:26-32`，`section_18fda0284e3686d0b6dc627d`：“先正确展开括号、合并同类项，再把变量项和常数项分开，最后令变量系数为 1。”
- `materials/v3/mathematics/teaching.md:33-40`，`section_29b51c76a0399abe4ef74bf1`：“若题目还要求解释步骤，只写“4”不足以提供等价变形的证据。”

raw SHA256 `4ade6690d521ca545d84ad1d7db66e68a9c139f3e6ebb2ab526259a9d47835fe`；result SHA256 `36328fc7eff6fb5fd740b63f622b239de32c10e4fd83fb8a043d29df0814c9ea`。

### mathematics_holdout_final02

实际：graded / 0.0 / remediate；独立判定：supported。

-2x=10应得x=-5，-2*(-5)=10；学生x=5及“正数除负数总是正数”均错误且未检验。0分与冻结反向符号规则critical相符。查询无相关历史，不越级臆断先修不会，当前remediate成立。

实际绑定依据：
- `materials/v3/mathematics/teaching.md:19-25`，`section_ce29bd3a859e8b6e11b44adb`：“用于求唯一解的除法必须除以非零数。”
- `materials/v3/mathematics/teaching.md:33-40`，`section_29b51c76a0399abe4ef74bf1`：“求出的数要代回原方程，分别计算左右两边，而不是仅代入已经写错的中间式。”

raw SHA256 `8637dcbaa4f9aef3d1da6751285b8decfac3a076c8a9595848e40ab9f941758c`；result SHA256 `c1c52c7198d0f34c1dc1cc22026833d2cfc1e1ca68e106a71f7dd1bfbc42bfde`。

### mathematics_holdout_final03

实际：graded / 90.0 / remediate；独立判定：supported。

q1同加6→3x=15、同除3→x=5与代回9正确，90分成立。q2认为同除0合法且总保持同解，与非零除数约束相反，0分合理；必要o2=0，因此remediate。不能因多数分来自另一个正确目标而advance。

实际绑定依据：
- `materials/v3/mathematics/teaching.md:12-18`，`section_089ad68bcee8d97ed528c435`：“为保持等式成立，两边同时加上或减去同一个数。”
- `materials/v3/mathematics/teaching.md:19-25`，`section_ce29bd3a859e8b6e11b44adb`：“不能除以 0，也不能把 `3x` 错当作 `x + 3`。”

raw SHA256 `2e81121cf288e841156d02159b75ad737b99cc201d24e165d0cda54456949afc`；result SHA256 `4ea13f3bcf7ff3f8a06d643ad561995919f8c65b3edd3e2d5947aa71c2fd0090`。

### mathematics_holdout_final04

实际：needs_review / 不计分 / assessment_review；独立判定：supported。

本轮实际资料包含“求唯一解的除法必须除以非零数”，同时附件明确禁止同除非零6、声称只改左边等价。6x=18对应两条规则直接互斥。暂停有效评价成立；学生x=3合理也不能消除未决资料冲突。

实际绑定依据：
- `materials/v3/mathematics/teaching.md:19-25`，`section_ce29bd3a859e8b6e11b44adb`：“用于求唯一解的除法必须除以非零数。”
- `materials/v3/mathematics/teaching.md:41-45`，`section_39a84421e8b44d36d5f8c561`：“题面缺少条件或两份材料给出互相矛盾的规则时，先定位矛盾，不能静默选一份评分。”

实际附件原文（确在本次评分输入，不是只听学生声称冲突）：“等式两边同除非零的6会改变解集，不能用来求解6x=18；只改变左边才保证等价。”

raw SHA256 `d9079c0caae4d225bfac003e56eebe8a0326231785b96ba92f2e272a68f04b1c`；result SHA256 `3682b0f2f34af615dbbce8f61d333c52eeadd36aedf8df012e81e1eb75cd7b2f`。

### python_holdout_final01

实际：graded / 10.0 / advance；独立判定：supported。

中文“二、一、零”是2、1、0的等价表述；先减1再打印和n=0后条件假均明确。4/4/2及advance成立，没有因非逐字模板而误拒。

实际绑定依据：
- `materials/v3/python/teaching.md:37-48`，`section_8887e7b0d603470016b9dc7a`：“每次准备进入 `while` 循环体之前都检查条件；第一次就是假时不会进入循环体。”

raw SHA256 `7d72b8853453cf26c961ab4bbf5fa128efff4bd5b4d1bb239b98755b1806bd6a`；result SHA256 `6bd15b2e50b5ad1304111e67b2e77cded8166fc8646a22736323d79955233232`。

### python_holdout_final02

实际：graded / 0.0 / remediate；独立判定：supported。

x=2时2>5为假，实际应B；“有if就执行第一个分支，不需要判断真假”是明确的一般性反向规则。0/0/0与冻结q1_c2关键错误相符，remediate成立；不是仅凭低分升级严重性。

实际绑定依据：
- `materials/v3/python/teaching.md:14-28`，`section_e59af5f25f96c33fd94babe3`：“`if/elif/else` 链从上到下判断，执行第一个条件成立的分支；都不成立时才进入 `else`。”

raw SHA256 `5262dea0424b5ef57771a421561643846e559d629c167965cd6f4af6371d2953`；result SHA256 `9312ea20e260b3979a0c6e2838d825f7047c8b7c07ad2c147d38a2eee0f0e44a`。

### python_holdout_final03

实际：graded / 90.0 / remediate；独立判定：supported。

q1按顺序输出a、b、取元素非下标及耗尽后结束均正确，90分成立。q2明确声称for至少执行一次，和range(3,3)空序列相反，三个分项均0；o2为必要目标，不能被90总分覆盖。冻结未定义本题critical，未任意补标。

实际绑定依据：
- `materials/v3/python/teaching.md:29-36`，`section_7b56cec63c4b922a8f345e34`：“`range(3, 3)` 没有元素，因此循环体执行零次。”
- `materials/v3/python/teaching.md:6-13`，`section_fb774cc20ec9651043300e37`：“`for color in colors` 依次取得元素；如需位置，可以显式遍历 `range(len(colors))`。”

raw SHA256 `4f8cd7d51d924e0299728707cc8a6ec588dab666256a48d7e009428248bdf326`；result SHA256 `d456edf3e698034d5db2f56065817ba656ced2d71e59ee141e4537979ff43101`。

### python_holdout_final04

实际：needs_review / 不计分 / assessment_review；独立判定：supported。

实际传入的while教学规则要求先检查、初始假执行零次；附件却明确声称先执行、至少一次，针对同一语义直接互斥。needs_review/assessment_review成立，未把提出资料问题的学生计作低分；未运行最终Diagnosis。

实际绑定依据：
- `materials/v3/python/teaching.md:37-48`，`section_8887e7b0d603470016b9dc7a`：“每次准备进入 `while` 循环体之前都检查条件；第一次就是假时不会进入循环体。”
- `materials/v3/python/assessment_private.md:21-27`，`section_5f18d5235a8fc8ee1de9a493`：“来源有矛盾或参考答案错误时，保留原因并暂停有效评价，不计作学生失败轮数。”

实际附件原文（确在本次评分输入，不是只听学生声称冲突）：“while总是先执行一次循环体，再检查条件；即使初值使条件为假也至少执行一次。”

raw SHA256 `d88710b856fe52d16761ad804d7cc9d8f9e580697590297dbeee0b82b6c39177`；result SHA256 `55308960801250fcef40e2e03aef2a629c443e96a7b624186e6db0a19c7c8db0`。

## 非阻断事项和边界

英语02与03的部分摘录分别仅覆盖宾语/时间或只覆盖时间；必须与真实完整学生答案及其它证据联合判断。实际评分与行动有依据，但不得宣称每个最短摘录都独立支持分项全部子条件。未来可改进引文完整性；本轮不因这些备注改Prompt、标准或重测此集。
资料包保留的“尚未实装”等历史准备说明不是服务端能力授权。本轮真实服务按冻结版本运行，模型未把该历史句子当作拒绝现有评价的理由。能力、系统换题和工程恢复仍须各自独立证据。
本套使用固定已审题目，不能证明新题生成、Tutor课程或第四主题均通过；这些由对应独立记录负责。已批准标准不是本次AI新造金标准，本复核不替人类批准新参考或发布。

## 完整性标识

- 原run report SHA256：`eb1cd3558d2f2546320f7741ffe00dc88a36cfad9239e2da255bb7f372a2ad5b`。
- 原run manifest SHA256：`af8bacf5e055c2434d8b474754e7b35921426097ed040c6410d11b44e1c83d13`。
- freeze04 SHA256：`91dcea124db6fe36f051c7a19739801e0fb622957365bf74d621944d9a19ddf2`。
- 标准文件 SHA256：`fc82a723f2bf0fe4a91060b68f6ccfa7800124950062910ed5e38ce981d65ce6`。
- 复验来源原reviewed-report SHA256：`ebdc3947b2e4995fbde50220eafa6f29b385461e0f1356474095b2ce8b6055b4`。
- 只读原业务库 SHA256：`21106e352a17beac4a5d95ec428c4b87141526633a064c14e6d9d3fa0bf1607e`。
- 离线机械明细：`work/day13-20261023/final-v2-independent-mechanical.json`，SHA256 `cfaa5f59563ab90f5b438be6f5bbc89cd964081bf709bfcce5f4a7bc6809341a`。
- 本次独立复核没有新增真实模型请求；未改写原report的pending标记，合并结论由主审另行完成。
