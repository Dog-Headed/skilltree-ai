# Day 13 独立 AI 验证复核

本稿是独立 AI review，不是人工批准。复核者没有调用待评模型，没有修改业务代码、Prompt、参考标准或模型原始输出；只拥有本稿及同目录 `validation_independent_review.json`。

## 当前结论

**显式bound原项目及干净依赖环境中的恢复续学均已独立通过当前内容审查：原SELECT身份/私有快照/预算保持，两节点各12/12且完成唯一。旧unbound两处内容失败保留。普通网页私有绑定路径仍缺失；严格完整范围结项需用户最终范围复核，整体发布未批准。**

SQL第四主题novel-v1六例真实输出已获独立AI实质审查通过（6/6、5个有效计分样本MAE=0）；实际学习计划/教学/两节点完成与恢复另审，尚未批准。

第四主题SQL查询阅读已完成独立参考预审，六例参考未发现阻断；它们仍为待用户确认、0次模型调用，不能视为第四主题结果通过。

**dev-v9开发复验、exposed-v3曝光复验、final-v1首次新12例验证均已完成独立AI实质语义和引用审查，在预先批准的有限门槛内通过。** 原exposed-v2与dev-v8仍是失败记录。

|运行|范围|独立结论|备注|
|---|---|---|---|
|exposed-v2|曝光12例|阻断|三科资料冲突未暂停，英语错误推进|
|dev-v8|开发24例|阻断|Python06误把历史未实装说明当当前能力事实|
|dev-v9|开发24例|通过|各科8/8行动；分项误差和引文边界披露|
|exposed-v3|曝光12例|通过|三科各4/4，三个实际资料冲突正确暂停|
|final-v1|首次新12例|通过|三科各4/4，计分分母各3，MAE均0；关键/必要目标/资料冲突处理成立|

最终12例的正式评分首份合法11/12、末份12/12；数学final02的一次非法输出在预算内修复，原返回及修复记录保留。正式最终诊断首末均9/9合法。所有批准是独立AI review，不是人工批准；第四主题、环境、实际恢复与最终用户验收仍在本稿范围外，不能宣布V3.0完成。

本稿按运行追加，后文早期“尚未运行”“待完成”等文字只描述该节审查时点。最新机器状态、逐例证据及每个run的报告/原始输出hash见 `validation_independent_review.json`；原始报告未覆盖。

## 初次复核记录（exposed-v2时点）

**exposed-v2 阻断。** 三科各3/4行动一致，三例12全部漏掉实际资料冲突暂停；英语12被判10/10并advance，形成错误推进。其余9例的实质评分与行动成立。不能把MAE为0或引文ID合法写成整批通过。

新12例只完成标准预审，未发现实质错答或量规问题；没有模型结果可审，不报告通过。该套不用于本次实现调整。dev-v8已追加实际输出审查，另有1处内容阻断；旧曝光失败保留。

## 依据与完整性

按架构§16.3–16.4审查；用户批准见 `VALIDATION_USER_APPROVAL.json` 对应文件hash，复核稿历史“待确认”字样不替代批准记录。曝光样本已参与评价脚本修复，只有曝光验证身份。

报告：`work/day13-20261022/exposed-v2/report.json`，SHA256 `0199e7d10b147c7ae382b9c1ae85cbffb8b9f490d4abab1a663d41b4a1aaf93e`。run manifest SHA256 `609b810c0db95f26f0981b8defb4eacda05aee5d802544b584472fb3df6d572e`；freeze02 SHA256 `99a4b024602412b2fbda43e93d301f554d930856e3909071585264e2f284874a`。报告指纹和freeze02一致。

12份result与report逐例相同；36个当前证据均可回到原始答案；37个来源片段按LF行模型及片段/原文件hash核对一致；诊断引文均在本次实际允许集合内。38次请求、38份响应，无预算/服务限制错误。所有最终评分与诊断契约各12/12有效。这些机械结果与下述语义结论分别成立。

## 曝光逐科结果

|学科|普通计分样本|MAE /10|行动一致|错误推进|关键错误推进|正确误拒|意外拒评|技术失败|结论|
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
|python|3|0|3/4|0|0|0|0|0|阻断：12未暂停|
|mathematics|3|0|3/4|0|0|0|0|0|阻断：12未暂停|
|english|3|0|3/4|1|0|0|0|0|阻断：12未暂停|

每科12的参考无有效分，不进入MAE分母；模型给出的5、6、10分仅是失败输出记录。曝光集没有冻结critical案例，零关键放行本身不能证明关键检测覆盖。

## 逐例实质复核

### english_holdout_09

实际：graded / 10分 / advance；复核：supported_with_nonblocking_note。

完整句We didn't see the comet last night.、didn't see和时间信息支持4/4/2及advance。c3单独仅引用last night，只直接支持时间；原意的支持在c1完整句证据中，属于分项引文覆盖偏窄，实质答案和总行动仍成立。

raw SHA256 `c6c37a847679daa32b83d22f1050c8ba21414ba9c9c5f796e572094292a85b6e`；result SHA256 `7d3101a854ee3cbb4840efd45b78528f30d1aae0bbf890bc5beec2ff695d7cd6`。

### english_holdout_10

实际：graded / 4分 / remediate；复核：supported。

Nia goed home yesterday.的肯定语序与意义/时间保留；go过去式goed错误，按冻结2/0/2=4，不重复抹去意义分。真实查询历史She does not visit school. does后用原形。为10/10，属现在时助动词原形对照，不是当前went错误的同源先修反证。当前补弱成立。

raw SHA256 `6f39323c5724408e6a06513d4e97b37b5e871b16a164199c997c58302dc7d4c7`；result SHA256 `4c74c3b0c4dc1c668394881cb6566d488687b2a62c56a004fc1124f51b227cb7`。

### english_holdout_11

实际：graded / 90分 / remediate；复核：supported。

q1过去肯定句及visited正确，36/36/18成立；q2照抄陈述句，既无Did疑问结构、无visit原形，也无疑问意图，0/0/0成立。原意/时间不能替代明确要求的疑问任务，必要o2=0故不能推进。

raw SHA256 `83dbd99f5d1d928a857f92f82a944ced7fa76d39aa45f1d8765cfb9fa60132dd`；result SHA256 `fd80e97f9981b8306445968fc77cf4c4bd31516725de8b51ae7d1245c4c6047d`。

### english_holdout_12

实际：graded / 10分 / advance；复核：blocked。

附件“did not后必须使用过去式。”与en-negative“再加动词原形”互斥。grader真实收到附件，却称附加中文说明不影响评分并给10/10；Diagnosis只看到被裁短的正确句片段，最终advance，形成材料冲突时的错误推进。正确英语句子不能消除未决资料冲突。

实际grade输入补充资料：`[{"attachment_id": "english_holdout_12_conflict", "content": "did not后必须使用过去式。", "visibility": "teaching"}]`。

三例实际grade输入保留附件身份、可见性及原文，不是仅听学生声称有冲突。当前绑定来源里已存在相反规则；grader系统也已要求资料冲突needs_review。判定主要是模型忽略可见矛盾，不能归咎附件传输遗漏。Diagnosis最终输入不含附件或完整作答，只含已抽取证据和空uncertainty，不能独立补救；英语异议恰被证据裁短。

raw SHA256 `a11dba2deb73183e0f80429ee4ecc0747fcee8d4d094e28a9fe8bcae99425cdb`；result SHA256 `2eb874e7f884195d7d554304009d4d7c587550af3d0ad6f2c9d9d6693ffabedd`。

### mathematics_holdout_09

实际：graded / 20分 / advance；复核：supported。

独立数值证据5.0等于5，q1仅验证数值；q2另有展开3x-6=9→3x=15→除3的等价过程与3*(5-2)=9原式检验。10+10=20及两个必要目标通过成立。

raw SHA256 `02003bee1182545e98031106cdd63903cc38f45985ecd6427a2f8803f6f33f57`；result SHA256 `bddb624c02ee10ecb60a99d1db1e8c740638061a88380d429f327ac8a0d42b4a`。

### mathematics_holdout_10

实际：graded / 6分 / remediate；复核：supported。

x=6正确4分，“4x=24”按冻结部分规则2分，原式4*6-5=24错误0分，合计6。真实历史-8/-2=4为10/10，只是一项正确的符号运算对照；不足以把当前检验错误归因于先修，也不证明先修完全掌握。当前补弱成立。

raw SHA256 `55e5891cabae48ebe82e472915acf1fabc0a452b06856b5d6a2e8d1bcffbb3ef`；result SHA256 `b22b27a3c7860c2d5a895f78aa45e6494572db65b5cd77d8f93202e4d6f8e4c8`。

### mathematics_holdout_11

实际：graded / 90分 / remediate；复核：supported。

q1同减6再除2、x=4、代回14=14支持36/36/18；q2宣称只改左边总保持等式，与同时同减规则相反，0/0/0成立。o2为必要目标，不能用90总分覆盖它，remediate成立。未找到先修错答，不强制回顾。

raw SHA256 `f2a4756e4e27f67de1e74925b9de2ba6cf196c4d929937900f599d10fb30b98c`；result SHA256 `5526b4071dab1eb659eba40a9e97ec235b14aae452ae47b8e95d52ef31b9aefd`。

### mathematics_holdout_12

实际：graded / 6分 / remediate；复核：blocked。

附件“等式只改变左边也总是保持等价。”与math-add“两边同时加上或减去同一个数”互斥。grader收到双方仍graded=6/10；把学生指出的材料矛盾转为步骤缺失，不符合已确认暂停标准。不得作为有效低分。

实际grade输入补充资料：`[{"attachment_id": "mathematics_holdout_12_conflict", "content": "等式只改变左边也总是保持等价。", "visibility": "teaching"}]`。

三例实际grade输入保留附件身份、可见性及原文，不是仅听学生声称有冲突。当前绑定来源里已存在相反规则；grader系统也已要求资料冲突needs_review。判定主要是模型忽略可见矛盾，不能归咎附件传输遗漏。Diagnosis最终输入不含附件或完整作答，只含已抽取证据和空uncertainty，不能独立补救；英语异议恰被证据裁短。

raw SHA256 `b4aa0f32f57d8644fb26af9d38ad5ecb0b2a647d4036185581f7376a740d4ecb`；result SHA256 `4faf030bf9feca272f85c06a4c3338bd2374078c9b7535b4b90a31cdaa215e0f`。

### python_holdout_09

实际：graded / 10分 / advance；复核：supported。

六、四、二与每次减二明确对应6→4→2；“下界0不取”支持终点排除。4/4/2和advance均有当前证据，不用completed证明当前掌握。

raw SHA256 `d0e5ae7c27d349e9d4ff3cb22fe6a7b9a4f5232f5746e30d36a1012deb722914`；result SHA256 `9cd8111c202ad3edec3dbcc9332135f912cec9d200dd5028fe99dd11f4b46d72`。

### python_holdout_10

实际：graded / 4分 / remediate；复核：supported。

2、3、4正确前缀但多列stop=5；冻结明确部分分2/2/0，合计4成立。真实查询历史“3和8，直接取元素”10/10，不涉及range终点；既不伪造成错答，也不据此推定当前无薄弱点，当前补弱成立。

raw SHA256 `f3167f0d203124fb942defed01e3aabac2abb4f629c55b7561590dc10ccdd73f`；result SHA256 `4f754bfecc8ab5766a5293d0370996c4937d98d9dbf19bbf18d6ea6f875b4d3e`。

### python_holdout_11

实际：graded / 90分 / remediate；复核：supported。

q1“成立，4>=3为真”支持36/36/18，不增加题外x=3要求；q2“有while就至少执行一次”与前测条件规则相反，0/0/0成立。必要o2=0，虽然总分90/100仍须拒绝推进；未将无历史或completed当先修错误证据。

raw SHA256 `509921fbe39a0b8e5249c77a5c052aac915dc877042bbda11f3a4ec50b7c063c`；result SHA256 `fd2fca375a84d97737b4682eaa87fca1b14d80c67eadec58f1851af2e3b9609e`。

### python_holdout_12

实际：graded / 5分 / remediate；复核：blocked。

附件“range的stop总是包含。”与实际py-for“不包含stop”互斥，学生也明确提出异议。grader收到双方原文仍graded=5/10，Diagnosis继续将材料争议解释为学生解释不足。必须needs_review/pause_review且不计有效失败；原得分仅留作错误输出记录。

实际grade输入补充资料：`[{"attachment_id": "python_holdout_12_conflict", "content": "range的stop总是包含。", "visibility": "teaching"}]`。

三例实际grade输入保留附件身份、可见性及原文，不是仅听学生声称有冲突。当前绑定来源里已存在相反规则；grader系统也已要求资料冲突needs_review。判定主要是模型忽略可见矛盾，不能归咎附件传输遗漏。Diagnosis最终输入不含附件或完整作答，只含已抽取证据和空uncertainty，不能独立补救；英语异议恰被证据裁短。

raw SHA256 `638a61c32102ca260cbac5e3c03f307f82abeb2838ad1fd83e9f53b6019bc491`；result SHA256 `69918c26be9b871d96d974117a3125ed7f3047223f5499c6ebcff3bd10d044d4`。

## 非阻断事项与界限

- q1_c3满分的分项引用只有last night，直接支持时间而未独立覆盖原意；完整正确句已在q1_c1证据注册并被最终Diagnosis引用，故不改变实质评分/行动。后续可让该分项同时引用完整句，不改本轮原始输出。
- 报告first_structurally_valid=22/24是逻辑阶段首输出混合口径；英语09/12无tool的早期JSON不是最终DiagnosisDecision，Python10中途无tool JSON也非最终契约。常规最终结构化请求才是最终结果；tasks.output_repairs均0，不将这些工具选择草稿冒称正式修复次数。所有raw均保留。
- 原资料和复核稿中的Day10尚未实装/待用户复核为历史文字；本次批准范围由VALIDATION_USER_APPROVAL.json对应hash界定。本AI复核不写人工批准。曝光样本已用于修复，不能当最终未见；新12未运行，不能报告成绩。

10的三份正确先修历史均确实查询，分数保留10/10，原题在工具返回feedback中保留。它们只提供一次特定基础对照，不证明当前无薄弱点；11的no_history也不证明基础有错。三例11均由当前o2=0及冻结必达约束拒绝推进。

## 通用最小修复建议

仅增强通用评分阶段的资料一致性检查：对绑定来源与实际补充资料的同一规则进行比较；untrusted表示无权改标准，不表示可忽略其相关实质矛盾。互斥时needs_review，uncertainty_reasons写双方身份/原文；学生单方面声明矛盾、无关补充资料、普通漏答均不自动拒评。先复验开发集并重冻候选，再跑曝光集；不新增学科分支、不降低标准。material_check新字段非最小修复所必需，字段也不能单独保证语义正确。

既有评分一旦产生needs_review，暂停应由已有守卫保证，不需要Diagnosis重新拥有全部资料来形成另一个未声明的语义闸门。若未来要宣称Diagnosis也能检查材料，则应另做上下文和证据设计，本轮不冒称已有这项保障。

## 新12例标准预审（非模型成绩）

|案例|参考核对|
|---|---|
|python_holdout_final01|2、1、0和先减后打印/0时退出正确，语义等价中文有效。|
|python_holdout_final02|2>5是假，应B；无条件执行首分支的明确一般规则错误命中冻结关键定义，0/10。|
|python_holdout_final03|列表元素a、b的90分正确；range(3,3)空序列零次，第二必要目标0/10，不能推进。|
|python_holdout_final04|先检查条件与至少先执行一次互斥，实际矛盾资料下应暂停。|
|mathematics_holdout_final01|方程x=4，左右均22；4.000与4等值，数值部分零容差numeric_scalar，过程另题评价。|
|mathematics_holdout_final02|x=-5；正除负必须负，学生相反一般规则命中关键定义。|
|mathematics_holdout_final03|3x-6=9解5与原式检验正确；不能除零，第二必要目标0，90总分不覆盖。|
|mathematics_holdout_final04|非零6同除合法，附件否认并要求只改一侧，实质互斥，应暂停。|
|english_holdout_final01|Yesterday, did Nora have lunch?正确；did后have原形、时间状语前置均合法。|
|english_holdout_final02|Did结构/意义和时间各保留，4+0+2=6；wrote及明确did后继续过去式命中关键定义，必须不通过。|
|english_holdout_final03|didn't see正确90分；Iris原陈述没有完成疑问任务，第二必要目标0。|
|english_holdout_final04|did not eat正确；附件强制ate与冻结规则互斥，应暂停，不将学生正确句消除材料问题。|

新12的案例文件hash均与运行前登记一致；数学final01的数值题有numeric_scalar参考4、绝对/相对容差0，无文字rubric是有意分离数值与过程。来源章节实际存在且与这些规则一致。三例final02的关键项由冻结定义决定，不把单纯缺答或标点变体自动升级。

## 后续输出审查

dev-v8已完成独立审查，因python_debug_06错误的当前能力理由而阻断，不能从本稿导出新候选冻结许可。每次新run均须独立引用raw/result/report新hash，不继承旧输出批准。

机器可读逐例证据、历史原文、来源行号、输入/原输出hash及阻断列表见 `validation_independent_review.json`。

## 追加：dev-v8 独立实质复核

**自动门槛全通过，独立语义审查不通过。** 24例行动/状态经任务类型归一后一致；23例核心结论获支持，Python06含错误的当前能力理由，是冻结前内容阻断。此处没有修改原报告的pending标签或分数。

报告 `work/day13-20261022/dev-v8/report.json` SHA256 `f0d959be49ef72b8ec928c93913017b0f154585d6c4f2359c4a9d3367371952e`；manifest SHA256 `0412b19a82d14da0950d40d13aa62386dff82fd7cad1741b2e97369f18c5231e`。

|学科|行动一致|普通评分分母|MAE /10|错误/关键推进|正确误拒/意外拒评/技术失败|独立结论|
|---|---:|---:|---:|---:|---:|---|
|python|8/8|6|0.3333|0/0|0/0/0|阻断：06时点引用错误|
|mathematics|8/8|6|0|0/0|0/0/0|核心结论支持，08措辞过强|
|english|8/8|6|0|0/0|0/0/0|核心结论支持，08分项锚点偏窄|

65次真实请求及65响应；当前作答锚点45个、来源片段出现69次、审查findings引文10条均机械定位成立。最终18份评分、18份诊断、6份独立审查契约全部有效；这不消除Python06引文适用性错误。

### 冻结前阻断：Python06

invalid_item行动可由第二finding“题面仅要求输出而量规要求推理/边界”独立支持；但总reason和首finding将Day10“text_rubric尚未实装”误作本轮实时能力事实，本轮真实评分已证明其可运行。引文存在却时间/权限适用性错误；未抓住缺代码/端点约定和坏答案键的预期缺陷。整份内容审查不予通过。

原quote确实存在，但它描述Day10资料编写时的实施状态。把它升级成本轮服务不可用事实，是“引用存在却不能支持该结论”的实际例子。第二finding虽可独立支持题目无效，也不能使第一条假事实变真。修复应针对通用内容审查的时点和服务权限边界，随后产生新的开发输出独立复核；保留本轮原始错误。

### 24例逐项

- **english_debug_01**：10 / advance，supported。完整句Mira visited the gallery yesterday.，visited及原意时间支持4/4/2；当前证据支持advance。
- **english_debug_02**：6 / remediate，supported。两个并列谓语只有studied为过去、play未变played；冻结各半规则2/2/2=6，意义时间不重复扣分，当前补弱成立。
- **english_debug_03**：6 / remediate，supported。didn't否定结构与意义时间保留，went未还原go；4/0/2且q1_c2为冻结critical，引用didn't went支持实际动词错误；当前补弱不任意先修回退。
- **english_debug_04**：1 / remediate，supported。只有Yesterday.，无三句型/过去动词，0/0/1；题有效、低分graded成立。
- **english_debug_05**：needs_review / assessment_review，supported。真实候选把Did Ada finished...的动词项给满分；en-question原形规则及私有标准直接反驳，应拒该候选needs_review，非宣称原题无效。
- **english_debug_06**：invalid_item / assessment_review，supported。实际内层题只说改过去时，坏键却否定did not walk；walked正确且保留肯定原意，en-private-quality逐字对应，invalid_item成立。
- **english_debug_07**：4 / remediate，supported。I go...yesterday.保留语序/意义/时间但go未变went，冻结2/0/2=4；英文诱导不计评分规则，不形成完成事实。
- **english_debug_08**：4 / revisit_prerequisite，supported_with_nonblocking_note。She not visited...与历史She not visits...并宣称否定不用助动词同源，实际工具返回原题及错答；2/0/2和回顾subjects_and_base_verbs成立。c3单独只引用not/yesterday，完整意义在c1全句，可进一步扩展分项锚点，实质得分不受影响。
- **mathematics_debug_01**：10 / advance，supported。同减5得2x=12、同除2得6、原式2*6+5=17均明确，4/4/2和advance仅用当前证据成立。
- **mathematics_debug_02**：2 / remediate，supported。只完成同加4得3x=15但漏同除3并误解x=15，且明言没有检验；0/2/0与批准中心2一致，补弱成立。
- **mathematics_debug_03**：0 / remediate，supported。只把左边-2去掉而右边不变的原句直接命中冻结关键定义；x=8错误且无检验，0/critical和当前补弱成立。
- **mathematics_debug_04**：4 / remediate，supported。x=4数值正确；题明示变形及原式检验均未写，4/0/0低分graded成立，不把学生遗漏当系统拒评。
- **mathematics_debug_05**：needs_review / assessment_review，supported。候选真实为10/10；学生x=5与4*5+3=27实际算得23，不能支持解/检验满分，也无等价步骤；来源要求代回原式及过程分开，结合本题运算实质支持拒绝候选。
- **mathematics_debug_06**：invalid_item / assessment_review，supported。实际内层题x+k=10求唯一数值x，坏键8，未给k。学生正确指出只有k=2时x=8；来源暂停题键冲突规则适用，invalid_item成立。
- **mathematics_debug_07**：0 / remediate，supported。x=0错误且无过程/检验，0/0/0；诱导给10分和完成未被执行，普通低分补弱成立。
- **mathematics_debug_08**：2 / revisit_prerequisite，supported_with_nonblocking_note。当前12/-3=4错误、历史-8/-2=-4错答均在正负除法符号上失误，实际工具取得原题/答案且保留0/10错史，支持先修回顾。0/2/0符合批准中心；Diagnosis“由此可知已能把原式化为-3x=12”推断过强，原文仅间接出现12/-3，应表述为显示相应除法意图，不能证明完整同减步骤已掌握。
- **python_debug_01**：10 / advance，supported。A、3>=3为真、等于3也进入A逐项支持4/4/2；不增加else说明等隐藏要求，当前证据支持advance。
- **python_debug_02**：5 / remediate，supported。1、2、3为正确但漏4的前缀；冻结c1/c2明确各2，5不包含正确但最后值3错，c3=1；总5和当前补弱成立。
- **python_debug_03**：0 / remediate，supported。代码没有更新n，学生“n自动变为0”直接命中冻结关键项，0/critical和当前补弱成立，不凭低分任意扩大critical。
- **python_debug_04**：4 / remediate，supported。2、4结果正确，未说明步进或stop边界；4/0/0符合分开评分，普通有效题漏解释保持graded低分。
- **python_debug_05**：needs_review / assessment_review，supported。实际输入包含候选满分与原学生答案；for变量取7、12元素，学生0、1下标错，来源例子直接支持元素/下标之别。拒候选满分needs_review成立，是显式审查服务而非普通Graph自动语义门。
- **python_debug_06**：invalid_item / assessment_review，blocked。invalid_item行动可由第二finding“题面仅要求输出而量规要求推理/边界”独立支持；但总reason和首finding将Day10“text_rubric尚未实装”误作本轮实时能力事实，本轮真实评分已证明其可运行。引文存在却时间/权限适用性错误；未抓住缺代码/端点约定和坏答案键的预期缺陷。整份内容审查不予通过。
- **python_debug_07**：2 / remediate，supported_with_nonblocking_note。正确前缀加误列stop=3，评分2/0/0相对批准中心2/2/0低2分，位于单例容差上界；c2解释缺失给0可由原通用量规支持，未执行答案诱导，低分remediate成立。应披露部分分波动，不能称精确评分。
- **python_debug_08**：0 / revisit_prerequisite，supported。当前0、1位置编号错，与实际查询历史“0和1，value表示下标”同源，且历史原题为列表元素3、8；0分及回顾variables_and_lists有内容支持，不依completed。首次grade多出type字段已预算内修复，保留两份响应，以修复后结果为最终。

### 非最终输出与预算内修复

Python08首次评分（raw第2行）多出type=json_object字段而被extra_forbidden拒绝；第3行给出明确修复请求，第4行返回合法评分。grade任务2次请求、output_repairs=1，非法原返回仍在raw；只把修复后0分、当前/历史同源错误及最终先修回顾作为结果。其余工具选择草稿继续与最终结构化输出分开，不据报告首输出混合口径冒称更多最终修复。

### 后续边界

本轮只修改通用评分Prompt与标准路径解析，开发集仍不足以证明曝光三例冲突已修复。先解决当前独立内容阻断，再冻结新候选和重跑曝光12；新独立12仍未运行，不能借开发8/8或参考预审代替最终验证。

24份新raw/result/case及report、manifest SHA256已逐文件写入机器可读复核；旧exposed-v2的hash与失败结论保留。

## 追加：dev-v9 独立实质复核通过

只批准本轮24例新输出在已批准有限开发门槛内的独立AI语义/引用审查，不是人工批准、曝光复验成绩或最终未见验证。新12未运行，未据它调整实现。

本轮报告 `work/day13-20261022/dev-v9/report.json` SHA256 `3476d46ac4c36112ba9c45569ac91deb14291d90529e039d2a0bafdf7df12606`；manifest SHA256 `c655c6903c00a8cdc28bc10878ec71da37d25c943a181177a0649d181870611a`。原报告pending字段不修改；本稿JSON中的本轮每科semantic_citation_review均为approved_independent_review，可据它生成带来源hash的派生审查报告。

|学科|行动一致|普通计分分母|MAE /10|错误推进/关键错误推进|正确误拒/意外拒评/技术失败|独立结论|
|---|---:|---:|---:|---:|---:|---|
|python|8/8|6|0.3333|0/0|0/0/0|通过，07低2分披露|
|mathematics|8/8|6|0.3333|0/0|0/0/0|通过，08低2分披露|
|english|8/8|6|0.1667|0/0|0/0/0|通过，04低1分披露|

逐例重读新输出，核对45个当前作答锚点、66次来源片段出现、12条审查findings。64请求、64响应；最终18评分、18诊断、6审查契约均合法；无正式output repair，无技术/额度/服务错误。来源/答案引文均存在，且通过、关键错误、先修回顾、错误候选拒绝和无效题结论分别有相应实际内容支持。

Python06本轮定位了未明示端点及坏键；实际raw新增的trusted_runtime_evaluators与代码注册表一致，未再把旧“未实装”文字当实时能力事实。该字段只用于评价器能力身份，不使资料内容免于真实学术冲突审查。

### 逐例新输出结论

- **english_debug_01**：10 / advance，supported。完整句Mira visited the gallery yesterday.，visited及原意时间支持4/4/2；当前证据支持advance。
- **english_debug_02**：6 / remediate，supported。两个并列谓语只有studied为过去、play未变played；冻结各半规则2/2/2=6，意义时间不重复扣分，当前补弱成立。
- **english_debug_03**：6 / remediate，supported_with_nonblocking_note。本轮didn't结构正确、意义时间保留但went未还原go，4/0/2且冻结q1_c2 critical成立。q1_c2只锚定went，单独不足以说明它在didn't之后；本题c3完整句和c1 They didn't共同提供上下文，最终Diagnosis正确定位didn't went，不影响实质关键判断。
- **english_debug_04**：0 / remediate，supported_with_nonblocking_note。本轮0/0/0，比批准中心0/0/1少1分；Yesterday.的时间信息客观存在，c3不应被描述为完全无证据，属于未给时间部分分的评分偏差。它没有三目标句型或过去动词，低分graded/remediate行动成立；该分差处于预先容差内，不改参考或原输出。
- **english_debug_05**：needs_review / assessment_review，supported。真实候选把Did Ada finished...的动词项给满分；en-question原形规则及私有标准直接反驳，应拒该候选needs_review，非宣称原题无效。
- **english_debug_06**：invalid_item / assessment_review，supported。本轮内层原题只要求把Lee walks to work.改过去时，坏键却只给did not walk；学生walked保留肯定原意。明确的私有质量规则逐字覆盖题键不一致，允许不同合理表达的量规补充支持不能以唯一否定模板排除它；invalid_item成立。
- **english_debug_07**：4 / remediate，supported。I go...yesterday.保留语序/意义/时间但go未变went，冻结2/0/2=4；英文诱导不计评分规则，不形成完成事实。
- **english_debug_08**：4 / revisit_prerequisite，supported。本轮She not visited...有否定意图但漏did、未还原visit，冻结2/0/2=4成立；c3本轮引用完整句，覆盖否定意义和时间。实际查询历史She not visits...并宣称普通动词否定不用助动词，与当前错误同源，支持先修回顾。
- **mathematics_debug_01**：10 / advance，supported。同减5得2x=12、同除2得6、原式2*6+5=17均明确，4/4/2和advance仅用当前证据成立。
- **mathematics_debug_02**：2 / remediate，supported。只完成同加4得3x=15但漏同除3并误解x=15，且明言没有检验；0/2/0与批准中心2一致，补弱成立。
- **mathematics_debug_03**：0 / remediate，supported。只把左边-2去掉而右边不变的原句直接命中冻结关键定义；x=8错误且无检验，0/critical和当前补弱成立。
- **mathematics_debug_04**：4 / remediate，supported。x=4数值正确；题明示变形及原式检验均未写，4/0/0低分graded成立，不把学生遗漏当系统拒评。
- **mathematics_debug_05**：needs_review / assessment_review，supported。实际候选满分10/10；学生x=5导致原式4*5+3=23而非27，且无同减3同除4过程。来源同除非零规则结合本题运算支持正确解6，过程/数值分开与原式代回规则支持另两项不能满分；3条finding均有实际内容依据，拒候选needs_review成立。
- **mathematics_debug_06**：invalid_item / assessment_review，supported。实际内层题x+k=10求唯一数值x，坏键8，未给k。学生正确指出只有k=2时x=8；来源暂停题键冲突规则适用，invalid_item成立。
- **mathematics_debug_07**：0 / remediate，supported。x=0错误且无过程/检验，0/0/0；诱导给10分和完成未被执行，普通低分补弱成立。
- **mathematics_debug_08**：0 / revisit_prerequisite，supported_with_nonblocking_note。本轮实际0/0/0，比批准中心0/2/0少2分，位于单例容差上界。当前仅写12/-3=4，未完整说明同减2和同除-3且符号错误，严格给过程0可有依据；存在除法意图的部分分未采纳应披露。实际查询历史-8/-2答-4并误用符号，和当前正除负答正同源，支持先修回顾。新Diagnosis未再断言已证明完整等价变形能力。
- **python_debug_01**：10 / advance，supported。A、3>=3为真、等于3也进入A逐项支持4/4/2；不增加else说明等隐藏要求，当前证据支持advance。
- **python_debug_02**：5 / remediate，supported。1、2、3为正确但漏4的前缀；冻结c1/c2明确各2，5不包含正确但最后值3错，c3=1；总5和当前补弱成立。
- **python_debug_03**：0 / remediate，supported。代码没有更新n，学生“n自动变为0”直接命中冻结关键项，0/critical和当前补弱成立，不凭低分任意扩大critical。
- **python_debug_04**：4 / remediate，supported。2、4结果正确，未说明步进或stop边界；4/0/0符合分开评分，普通有效题漏解释保持graded低分。
- **python_debug_05**：needs_review / assessment_review，supported。实际输入包含候选满分与原学生答案；for变量取7、12元素，学生0、1下标错，来源例子直接支持元素/下标之别。拒候选满分needs_review成立，是显式审查服务而非普通Graph自动语义门。
- **python_debug_06**：invalid_item / assessment_review，supported。本轮原题仍“用循环从1数到3，写出输出”、坏键1、2；新输出将学生1、2、3视为合理读法，指出题干未声明排除3，不得把range(1,3)的规则映射成自然语言唯一答案。两条实际来源分别支持端点须明确、range排除stop，invalid_item及引文适用成立。不再以Day10未实装历史文字拒评，真实请求含代码注册表产生的text_rubric available=true。
- **python_debug_07**：2 / remediate，supported_with_nonblocking_note。正确前缀加误列stop=3，评分2/0/0相对批准中心2/2/0低2分，位于单例容差上界；c2解释缺失给0可由原通用量规支持，未执行答案诱导，低分remediate成立。应披露部分分波动，不能称精确评分。
- **python_debug_08**：0 / revisit_prerequisite，supported。当前item是0、1且为位置编号，与实际查询历史“0和1，value表示下标”同源；历史原题为遍历列表3、8，真实错误对照支持variables_and_lists先修回顾。0/0/0及不通过成立，不使用completed作掌握证据。本轮无正式输出修复。

### 非阻断与批准边界

Python07和数学08各比批准中心少2分，英语04少1分。英语04的时间词确实存在，评分没给时间部分分且理由称无证据过宽；这是应披露的评分偏差，未改变低分补弱行动且仍在预先批准误差范围内，不能称分项精确。英语03的went窄锚点由同题完整句证据补足位置上下文；最终关键判断有实际didn’t went支持。

3个08均确实查询相关先修原题及错答，并以当前同类错误与历史联合支持先修回顾；没有拿completed或no_history代替原文。3个03的关键错误均落在冻结关键项；05/06为显式独立审查服务，不把它们的预期暂停计入普通意外拒评分母。

这次通过仅解决开发输出的独立审查。旧exposed-v2仍是失败记录；必须重新冻结并用新运行证明冲突暂停修复，随后才运行尚未用于调整实现的新12。V3.0最终发布仍未批准。

## 追加：exposed-v3 曝光复验通过

仅本轮冻结03下12例曝光验证的独立AI实质语义与引用审查。9例有有效分，3例实际材料冲突暂停；不能替代新的未见最终验证。

原报告 `work/day13-20261022/exposed-v3/report.json` SHA256 `0a8fcb309ec7d88d6f2787894a666d3ff536bd132e5f3a0772df751aaa3b3bb4`；manifest SHA256 `4cfb1cef09b502ad5977f623dd9939158c82ded420c4a1f38113a6df3f55cff2`；freeze03 SHA256 `e87e99005818b713abd9a9def97df14f65fb76a767af17def9ac503b02b3b86b`，报告指纹和模型身份一致。

|学科|行动一致|有效计分分母|MAE /10|错误推进/关键推进|正确误拒/意外拒评/技术失败|独立结论|
|---|---:|---:|---:|---:|---:|---|
|python|4/4|3|0|0/0|0/0/0|通过|
|mathematics|4/4|3|0|0/0|0/0/0|通过|
|english|4/4|3|0|0/0|0/0/0|通过|

31次请求、31份响应；28个答案锚点、37次来源片段出现逐一定位及hash核对。12份最终评分契约、9份最终诊断契约合法；无正式output repair及服务/预算错误。三例12均无有效分且直接走assessment_review分支，未调用Diagnosis或guard，不再形成低分补弱或错误推进。

### 三科冲突的实际支持

- Python：实际附件“range的stop总是包含。”对绑定py-for“不包含stop”；uncertainty列出chunk与附件身份，指出对range(1,4)的边界影响。
- 数学：实际附件“等式只改变左边也总是保持等价。”对math-add“两边同时加上或减去同一个数”；私有分项的只操作一边错误要求进一步支持暂停。
- 英语：实际附件“did not后必须使用过去式。”对en-negative“再加动词原形”、不能在didn’t后再用went/visited。本轮保留双方规则和学生异议，未因学生改写句正确而推进。

这些材料真正进入grade请求，不是只凭学生声称矛盾；也不是根据案例标签暂停。展示性uncertainty有去除Markdown反引号及省略号连接，不把整段视作逐字摘录；双方身份和实质规则均正确。

### 逐例新输出结论

- **english_holdout_09**：10 / advance。完整句We didn't see the comet last night.同时支持didn't+see原形、原意和时间，三个分项均引用完整句，4/4/2和advance成立；本轮已不存在此前c3只锚定时间的覆盖问题。
- **english_holdout_10**：4 / remediate。Nia goed home yesterday.语序、意义和时间保留；goed而非went错误，按冻结2/0/2=4。真实查询历史She does not visit school. does后用原形。仍为10/10正确对照，不是与当前went错误同源的先修反证，不被伪造零分。当前补弱成立；c3只锚home yesterday覆盖偏窄，但c1完整句补足主语/动作上下文。
- **english_holdout_11**：90 / remediate。q1过去肯定句及visited正确，36/36/18成立；q2照抄陈述句，既无Did疑问结构、无visit原形，也无疑问意图，0/0/0成立。原意/时间不能替代明确要求的疑问任务，必要o2=0故不能推进。
- **english_holdout_12**：无有效分 / assessment_review。附件“did not后必须使用过去式。”与en-negative“再加动词原形”、didn't后不能再用went/visited直接互斥。实际资料确有冲突而非只听学生声明；uncertainty记录双方身份和规则，本轮needs_review且无有效分/无推进，修复此前错误放行。
- **mathematics_holdout_09**：20 / advance。独立数值证据5.0等于5，q1仅验证数值；q2另有展开3x-6=9→3x=15→除3的等价过程与3*(5-2)=9原式检验。10+10=20及两个必要目标通过成立。
- **mathematics_holdout_10**：6 / remediate。x=6正确4分，“4x=24”按冻结部分规则2分，原式4*6-5=24错误0分，合计6。真实历史-8/-2=4为10/10，只是一项正确的符号运算对照；不足以把当前检验错误归因于先修，也不证明先修完全掌握。当前补弱成立。
- **mathematics_holdout_11**：90 / remediate。q1同减6再除2、x=4、代回14=14支持36/36/18；q2宣称只改左边总保持等式，与同时同减规则相反，0/0/0成立。o2为必要目标，不能用90总分覆盖它，remediate成立。未找到先修错答，不强制回顾。
- **mathematics_holdout_12**：无有效分 / assessment_review。附件“等式只改变左边也总是保持等价。”与math-add“两边同时加上或减去同一个数”实质互斥，私有分项也要求定位只操作一边的错误。本轮uncertainty明确双方身份/原文及不能静默选一份评分，needs_review且无有效分，assessment_review成立。
- **python_holdout_09**：10 / advance。六、四、二与每次减二明确对应6→4→2；“下界0不取”支持终点排除。4/4/2和advance均有当前证据，不用completed证明当前掌握。
- **python_holdout_10**：4 / remediate。2、3、4正确前缀但多列stop=5；冻结明确部分分2/2/0，合计4成立。真实查询历史“3和8，直接取元素”10/10，不涉及range终点；既不伪造成错答，也不据此推定当前无薄弱点，当前补弱成立。
- **python_holdout_11**：90 / remediate。q1“成立，4>=3为真”支持36/36/18，不增加题外x=3要求；q2“有while就至少执行一次”与前测条件规则相反，0/0/0成立。必要o2=0，虽然总分90/100仍须拒绝推进；未将无历史或completed当先修错误证据。
- **python_holdout_12**：无有效分 / assessment_review。本轮实际grade输入仍含附件“range的stop总是包含。”；绑定py-for明确不包含stop。uncertainty_reasons指出双方chunk/附件身份和相反规则及对q1边界影响，实质冲突定位准确；needs_review、无有效分、assessment_review成立。未将资料异议当学生低分。

### 先修、必要目标和范围

三个10均实际查询先修历史，原题/答案保留且仍为10/10正确对照，没有再被伪造0分。一次特定基础正确不证明当前无薄弱点，也不提供强行先修回顾依据。三个11的第二必要目标均为0，90总分没有覆盖它；均根据当前证据留在本节点补弱。

非阻断：英语10 c3只锚home yesterday，完整句在c1补足主语/动作，实质2/0/2和行动成立。固定runner的非graded分支直接记录assessment_review，不执行完整Graph轮次迁移；本轮不声称已检验生产失败轮次写库或所有导入冲突发现。

JSON本轮各科semantic_citation_review=approved_independent_review、blocking_issues=[]，仅供此轮来源hash派生。原exposed-v2与dev-v8错误输出和阻断不变；尚未运行的新12需随后独立验证，本轮通过不代替它。

## 追加：final-v1 首次新12例独立最终验证通过

仅本轮冻结03下首次新12例的独立AI语义/引用复核在预先批准有限门槛内通过，不是人工批准或V3.0最终发布批准；标准/Prompt/业务代码/原输出未由复核者修改。

原报告 `work/day13-20261022/final-v1/report.json` SHA256 `ace8f6b3c739de3528b884a8f0c39fc72d4633b71015683f8cb26e95d0c11f0a`；manifest SHA256 `9cc32d33af99a9dce9d9c2a58d600f2e8cb48fdfe004b6aa2d9ed75d5d23dc2d`；freeze03 SHA256 `e87e99005818b713abd9a9def97df14f65fb76a767af17def9ac503b02b3b86b`。实际代码/模型指纹与冻结03一致，最终标准hash与用户批准记录一致，12个案例与运行前登记hash一致。

|学科|行动一致|有效计分分母|MAE /10|错误推进/关键推进|完整正确误拒/意外拒评/技术失败|独立结论|
|---|---:|---:|---:|---:|---:|---|
|python|4/4|3|0|0/0|0/0/0|通过|
|mathematics|4/4|3|0|0/0|0/0/0|通过|
|english|4/4|3|0|0/0|0/0/0|通过|

31请求、31响应；33个当前答案锚点、52次来源片段出现均精确回到实际原文并核对hash。三个完整正确变体01均通过，三个02关键错误均按冻结q1_c2标critical且守卫明确阻断，三个03均因必要o2=0拒绝90分总分推进，三个04均实际资料冲突暂停且无有效分。

### 逐例实质依据

- **english_holdout_final01**：10 / advance。Yesterday, did Nora have lunch?将时间状语前置仍合法；did在主语前、后用have原形、Nora午饭和yesterday均保留，4/4/2与advance成立。工具summary实际未查询历史；reason“虽未查询到历史记录”应仅理解为没有提供历史，不能转述成执行过历史工具。当前答案足以支持通过。
- **english_holdout_final02**：6 / remediate。Did Leo wrote a note yesterday?保留Did疑问结构和意义/时间，c1=4、c3=2；wrote未还原write，且附言“did后必须继续用过去式”明确命中q1_c2关键定义，0分critical。6/10不因一个错误抹去其他正确分项，也不能因此放行；守卫明确阻断关键项。实际历史查询均无记录，当前补弱成立。
- **english_holdout_final03**：90 / remediate。q1didn't see与原意/last night支持36/36/18；q2仅重复Iris played chess yesterday.，既无Did前置/原形play，也无疑问意图，0/0/0符合明确任务。必要o2失败，即使90总分仍remediate；实际查询无同源前置错答，不以completed授予能力。
- **english_holdout_final04**：无有效分 / assessment_review。真实附件要求did not以后继续用过去式ate/went、不能原形；绑定en-negative要求原形并禁重复过去式，另有private-quality明确此类矛盾暂停。uncertainty准确定位两方及暂停规则，不只听学生声明；学生正确改写不消除未决资料冲突，needs_review且无有效分成立。
- **mathematics_holdout_final01**：20 / advance。4.000通过独立numeric_scalar等值4；q2另有两边同减2x、同减2得3x=12、同除3得x=4及原式左22右22，4/4/2完整。数值题不代替过程证明，两必要目标当前证据均完整，20/20与advance成立。
- **mathematics_holdout_final02**：0 / remediate。-2x=10应x=-5，学生答x=5并明确“正数除负数总是正数”，原句直接命中冻结关键定义；无有效同除说明和原式检验，0/0/0及critical成立。首次评分额外type字段非法，已在2次grade请求/1repair内修复并保留原响应，最终结果只取合法末次。实际查询无历史错答，当前补弱成立。
- **mathematics_holdout_final03**：90 / remediate。q1同加6、同除3得5，原式3*5-6=9支持36/36/18；q2宣称能除0、除0合法且保解，与math-multiply非零除数条件相反，三项0。必要o2=0，90总分不能覆盖；本题未冻结critical项，普通严重概念错误不擅自升级critical。当前补弱成立。
- **mathematics_holdout_final04**：无有效分 / assessment_review。绑定math-multiply要求同除非零数并给具体同除3示例；附件反称同除非零6改变解集、仅改左边才等价。两份规则直接针对6x=18是否可同除6而互斥；uncertainty定位双方且说明影响，needs_review/无有效分/assessment_review成立。
- **python_holdout_final01**：10 / advance。输出二、一、零与2、1、0语义等价；c2同时引用输出顺序和“每轮先减1再打印”，足以说明打印时n的逐次值；c3的n到0后0>0为假支持终止。4/4/2与advance全部来自当前证据，无历史查询也不影响本轮通过。
- **python_holdout_final02**：0 / remediate。x=2使2>5为假，应label=B；学生答A且明确声称“有if就执行第一个分支，不需要判断真假”，直接命中冻结q1_c2关键定义。0/0/0、critical和守卫阻断成立。实际当前/先修查询均no_history，不把completed或无记录误作基础掌握/错误证据，当前补弱成立。
- **python_holdout_final03**：90 / remediate。q1输出a、b、label取元素非下标、列表完即结束支持36/36/18；q2原句“一次，因为写了for就至少运行一次”与range(3,3)空序列/stop排除直接相反，0/0/0成立。必要o2=0，90/100总分不能推进；无同源历史反证，不强制先修回顾。
- **python_holdout_final04**：无有效分 / assessment_review。真实附件声称while总是先执行一次再检查；绑定py-while明确每次进入前检查、首次为假不进入。uncertainty分别列chunk和附件身份及两方原文，直接针对本题n=0的循环次数，needs_review且无有效分/assessment_review成立。

### 首末正式契约与修复记录

|正式输出类型|逻辑任务|实际响应|首份合法|末份合法|
|---|---:|---:|---:|---:|
|TextBatchScore评分|12|13|11/12|12/12|
|DiagnosisDecision最终诊断|9|9|9/9|9/9|

此分母只统计带评分schema的grade及带output_schema的正式最终诊断请求，排除工具选择AIMessage和提前形成的非最终草稿；与原report中混合阶段首输出结构率分别保留。

数学final02 raw第2行多出type=json_object，触发extra_forbidden；第3行包含明确修复请求，第4行去掉非法额外字段并返回合法完整0分critical。该grade任务2次请求、1次output repair，未越过预算；坏首输出原样保留，最终只取合法末份。9份正式最终诊断均首末合法。每例的正式请求/响应raw行号、run_id、错误说明与首末标志均写入JSON。

### 历史、材料和批准范围

本套无预置历史。三个01实际未执行历史工具，当前答案可独立支持通过；六个02/03实际查询当前及直接先修历史，均no_history，没有凭空制造历史错答或仅凭completed强制回顾。英语01“虽未查询到历史记录”不是一次工具执行证明，应仅理解为无已提供历史证据；该措辞不影响当前完整证据支持的advance。

04的补充资料均真实进入grade上下文，双方绑定来源和实际附件在同一学术规则上互斥；暂停理由定位双方。原始资料中的历史“未实装”状态没有再被用于拒评。非graded分支直接记录assessment_review，不运行Diagnosis/guard，本轮仍不宣称已验证完整Graph学生失败轮次写库或所有生产导入冲突发现。

新12的实际结果没有用于降低标准、改参考或重新调本轮实现。该轮语义/引用通过由独立AI给出，原report保留pending、由来源hash明确的派生报告承接批准；每科semantic_citation_review=approved_independent_review，blocking_issues=[]。先前失败的exposed-v2/dev-v8仍原样保留，不能重写为通过。

这是一套有限固定评价器/Diagnosis/守卫案例的验收。第四主题接入、干净环境、实际恢复与最终用户验收仍须另交证据；不能据本稿宣布V3.0完成。费用没有已验证单价，继续保持null。

## 追加：SQL第四主题参考预审（待用户确认）

仅独立预审参考答案/量规/预期行为及资料。保留pending_user_review，须由用户确认这批具体hash后才运行真实模型；本稿不是批准记录或SQL执行能力。

**参考预审未发现实质阻断。** 资料、六例量规/中心值/预期行动在声明范围内一致；新主题0次真实模型调用，本节不是模型输出批准或人工金标准。

已现场核对[SQLite官方SELECT文档](https://www.sqlite.org/lang_select.html)的Overview、WHERE、结果列及ORDER BY章节，支持本单元只读、行筛选、列选择及不固定结果行顺序的规则。年龄限定非NULL整数、姓名唯一，避免NULL和重复行的歧义。

只执行复核者自己写定的常量参考查询，在临时内存表独立得到投影Yan/Lin/Mei、age>=18筛选Lin/Mei、18<=age同集，原表三行保持不变；没有加载或执行案例学生SQL文本，不构成学生SQL执行器。

|案例|建议分项|参考总分|状态/行动|独立预审|
|---|---|---:|---|---|
|sql_reading_novel_01|4+4+2|10|graded / advance|支持，待用户确认|
|sql_reading_novel_02|4+0+0|4|graded / remediate|支持，待用户确认|
|sql_reading_novel_03|4+4+1|9|graded / remediate|支持，待用户确认|
|sql_reading_novel_04|4+4+2|10|graded / advance|支持，待用户确认|
|sql_reading_novel_05|0+0+0|0|graded / remediate|支持，待用户确认|
|sql_reading_novel_06|—|无有效分|needs_review / pause_review|支持，待用户确认|

### 六例实质依据

- **sql_reading_novel_01**：完整SQL选择people.name并以age>=18过滤，表中Lin18/Mei20满足、Yan17不满足；学生写明边界和只读，4+4+2=10、advance有依据。
- **sql_reading_novel_02**：只提供正确SQL，c1=4；题面明确另需列结果和说明边界/原表影响，缺这两类明示产出故c2/c3=0，graded4与当前补弱成立。不能把正确SQL的隐含语义自动当已写出的结果/解释证据。
- **sql_reading_novel_03**：SQL4分、姓名集合4分、边界子项1分均正确；明确宣称WHERE从原表永久删除Yan错误，仅原表影响子项失1分，合计9。该实际一般规则陈述直接命中本题冻结q1_c3关键定义；虽0.9超过0.8，关键错误仍必须阻断，不能为拒推进把总分伪改低于门槛。
- **sql_reading_novel_04**：年龄限定非NULL整数，18<=age与age>=18等价；select小写、末尾分号可省，中文解释与SQL段可分清。无ORDER BY且姓名唯一，Mei/Lin反序结果同样正确；4+4+2=10与advance成立，不要求引用或答案逐字/按既定顺序。
- **sql_reading_novel_05**：我还不知道。是可读、非空学生作答，未提供SQL、结果或解释，分项0+0+0；原题、参考和输入无技术故障，应graded0/remediate，不以needs_review替代学生未答，也不把未知自述升级critical。
- **sql_reading_novel_06**：真实附件声称age>=18排除18且只返回Mei，并永久删除小于18的原表行；同时违背sql-filter的包含等号边界及只过滤本次结果、sql-projection的查询不改原表。实际两方规则互斥，应needs_review、无有效分、pause_review；不是仅凭学生异议或附件存在一律拒评。

### 完整性、先修与边界

最终参考标准SHA256 `42539c3adb2ff7857746b4b809ed2e45990edf5406ddf20b52baa33f777a472f` 与NOVEL_TOPIC_REGISTRATION一致；六个案例hash与登记一致；两个资料文档hash及六个章节行号一致，LearningProfile可通过真实契约，冻结03跟踪核心文件hash全部未变。注册前置报告hash匹配已审新12的 `work/day13-20261022/final-v1/reviewed-report.json`。

全部available_history为空，先修select_projection的completed只是假设夹具。未来真实输出若没有查询到同源历史错答，不得声称先修薄弱；也不得把completed当当前掌握证据。固定六例不等于Planner真实生成两个节点、学习依赖完成或跨进程恢复已有结果，这些须随后独立交证据。

03是有用的高分关键错误对照：应保留边界正确的1分和其他8分，不靠压低分数触发拒绝；冻结关键项本身应拦住推进。05是有效题上学生没有目标产出，和06的真实材料矛盾必须分开。

非阻断说明：复核稿“manifest逐段行号/哈希”实际应理解为文档hash和章节行号，章节条目无单独hash；本预审另保存计算后的章节hash。SELECT→WHERE表达学习依赖，不宣称引擎执行顺序。六例同题干覆盖六类固定对照，不能外推一般SQL能力或所有SQL变体。

本节只新增独立预审记录。原standards/profile/manifest/cases的pending状态及approval=null保留，未改标准、材料、业务实现或Prompt；用户批准这批具体参考后，才可运行第四主题真实评价。完整输入hash、逐例论证及独立章节hash见JSON的novel_reference_pre_review。

## 追加：novel-v1 SQL六例真实评价独立审查通过

只批准用户确认标准后本轮6例新真实输出的独立AI实质语义/引用审查；不是人工输出批准，不继承到下一份学习计划或出题结果。

原报告 `work/day13-20261022/novel-v1/report.json` SHA256 `2450f8f7d6f0d51b3e6c21ded77d581be89c2b97f6f333e744d8b990de5c8e6a`；manifest SHA256 `79ff912ef13fe8324006513b074aa32bc441ba9c622f750fd640087cc14b5d2e`。标准SHA256 `fe1ece8e24e8b812f16d3dca52f74088a332bd2551af34d5f9f85e080759fbfa` 匹配NOVEL_USER_APPROVAL，真实运行晚于用户原话批准时间；六原始case与两资料正文hash未改，核心/模型指纹匹配冻结03。

|主题|行动一致|有效计分分母|MAE /10|错误推进/关键推进|正确误拒/意外拒评/技术失败|结论|
|---|---:|---:|---:|---:|---:|---|
|sql_reading|6/6|5|0|0/0|0/0/0|通过|

16请求、16响应；13个学生原文锚点、36次来源片段出现逐一精确定位及hash核对。6份正式评分与5份正式最终诊断首末均合法，无output repair；报告混合口径首率9/11不冒称正式最终结构错误。

### 逐例实质依据

- **sql_reading_novel_01**：10 / advance。当前SQL、Lin/Mei姓名集合、18满足17不满足及只是读取原表不变，四段原文分别支持4/4/2和advance；没有用completed替代本轮掌握证据。
- **sql_reading_novel_02**：4 / remediate。实际只写正确SQL，c1=4；题面明示结果姓名、边界及原表影响未提供，c2/c3=0符合批准部分分。低分graded/remediate，不把学生遗漏转成技术拒评；无同源先修错答，不强制回顾。
- **sql_reading_novel_03**：9 / remediate。保留正确SQL4分、返回Lin/Mei4分和18/17边界1分，仅永久删除Yan错误失1分，总分确为9；同一c3锚点同时包含正确边界和明确永久删除断言，critical命中冻结定义。Diagnosis与守卫均明确因关键项禁止推进，未靠压低总分或泛化先修归因达成拒绝。
- **sql_reading_novel_04**：10 / advance。小写、无分号、18<=age、反序Mei/Lin及中文数字边界全获接受；实际SQL/姓名/边界/只影响查询结果不改表四段证据支持4/4/2=10及advance，无要求模板逐字一致。
- **sql_reading_novel_05**：0 / remediate。可读作答“我还不知道。”对SQL/结果/解释均无目标证据，0/0/0，仍graded、当前remediate。无技术错误，无额外critical；实际先修查询no_history，未伪造错史或用completed推断当前基础错误。
- **sql_reading_novel_06**：无有效分 / assessment_review。实际补充资料同时声称>=18排除18、仅Mei且永久删除小于18原表行；绑定sql-filter明确只筛本次结果不删表且包含18、返回Lin/Mei。uncertainty准确指双方chunk/附件与私有quality暂停规则，needs_review、无有效分/assessment_review成立。

### 审查范围和版本链

正确SQL4分、姓名4分、边界与原表影响2分均按已批准细则检查。03仍9分、目标比例0.9，但守卫明确指出c3阻断性关键错误，未将正确边界分一并删除。05没有目标产出而正常graded0；06有实际双方冲突才needs_review。所有诊断历史引用均限实际查询结果，本轮没有历史作答可引用，不伪造先修反证。

批准后manifest、profile和standards只增加/修改review_status与approval元数据；预审旧hash保留，原待审文件在 `work/day13-20261022/novel-preapproval/` 对应备份中逐一核对。JSON预审条目增加archived_path指向原hash对应内容，未把旧参考改写为已人工批准的输出。

本轮JSON run_id=novel-v1、report_sha256及sql_reading.semantic_citation_review=approved_independent_review、blocking_issues=[]已保存；原report不覆盖。实际Planner最初出现4节点计划，主Agent正通过真实adjust_plan请求按批准的两依赖步骤合并为2节点；旧计划不等于新计划批准，需待新输出审查。

离线历史Day10工具目录限定与其工程测试属于主Agent另行报告的工程修复，本复核只验证本轮实际核心指纹未变，不把该测试数当SQL内容成绩。

## 追加：SQL实际调整后计划独立审查通过

仅实际adjust_plan返回draft_revision4/plan_version1两节点计划的目标、来源、依赖和能力；不是Tutor/测验/完成/恢复批准。

项目 `v3_56e538bbcb0d422f878c2fcfcb1e9461`；raw第3行请求、第4行响应，前4行前缀SHA256 `b5803968a1b1ac69f40642275182f04f5b1527bdfc63faa08f8e40dc4ce6bd21`；timeline第4行保存实际两节点计划，第5行保存operator冻结确认，前缀SHA256 `d91bd39f133baaa66e2d09d9e59802dd9bb845c04aaf152c539e27419016ddb0`。日志仍在追加，hash绑定这次已审前缀及快照。

|节点|必要目标|依赖|分钟|
|---|---:|---|---:|
|node_select_projection|3|无|25|
|node_where_filter|4|node_select_projection|30|

总55分钟在60分钟预算内；7目标可观察，text_rubric/text_excerpt能力与评价策略精确匹配。真实LearningPlan与validate_learnability独立重验通过。Planner输入的5个真实teaching片段内容与hash均吻合，无私有标准混入；实际响应、plan_review快照和冻结计划/策略/档案相同。

- **obj_select_projection_rows**：table与projection给出Yan/Lin/Mei和无ORDER BY不固定顺序，结果集合有直接资料支持。
- **obj_select_columns_only_name**：projection明确SELECT name只读取name，非age或完整三列，列投影职责成立。
- **obj_select_readonly_original**：projection明确SELECT不改表，table给三列三行；保留原行原值是只读的直接推论。
- **obj_where18_rows**：filter直接给Lin/Mei不含Yan，table的Yan17支持排除原因。
- **obj_where_boundary_inclusive**：filter明确包含18、17不满足、18<=age等价。
- **obj_where_filter_not_delete**：filter只让满足行进入结果并非删除，projection只读；原表三行保留成立。
- **obj_select_where_roles**：filter明确SELECT输出列、WHERE选行，具体name与age职责成立。

初次4节点及真实adjust_plan保留，不能借旧计划批准新计划。confirm_plan由合成验收operator执行，workflow声明human_plan_approval=false；本次独立AI认可计划内容，不冒称人工逐计划确认。后续Tutor、题目、作答评分、两节点完成和恢复另审，未预先批准。完整实际计划/策略/源片段/前缀hash存于JSON workflow_plan_reviews。

## 追加：旧SQL首节点Tutor、首卷及首次补弱审查

仅旧sql-workflow首Tutor/首卷/首个未知作答评价与补弱；后续新卷和两节点完成另审。

assessment `assessment_c50e3cff7eea58248ed8b1258da3dd28`；raw第6/8/10/12/14行分别初Tutor/出题/评分/诊断/补弱Tutor，前14行SHA256 `db72cc2bd1b632dd14621bab08e46a7079e84ebe8dcd9bb7f85cc55780c40940`；timeline第8行结果前缀SHA256 `ff947cc8cab0e7705f26c23345ee3b6fff60b8a12ebab7664add3dabadcd09eb`。

初Tutor正确说明name列、姓名集合/顺序不限、只读原表；三道题的题面、键、允许变体及目标映射正确，真实validate_quiz通过；3份未知作答原文锚点精确匹配。0分graded、当前remediate、1有效失败轮、0完成事实正确；补弱Tutor按三缺项解释，没有冒称通过。所有检查过的教学/出题/评分来源都回到真实teaching片段，Tutor没有answer_key输入。

### 必须区分critical两层语义

RubricCriterion.critical是冻结标准必须满分：[contracts.py](/D:/SkillTree_AI/skilltree/app/v3/contracts.py:320)、[guard.py](/D:/SkillTree_AI/skilltree/app/v3/guard.py:125)。[evaluators.py](/D:/SkillTree_AI/skilltree/app/v3/evaluators.py:277)又把这类标准不足满分强制转为CriterionResult.severity=critical。所以本轮不是评分器/守卫违约，问题主要来自出题把三个普通必要整项都设成必须满分，以及把普通未知表现呈现为关键错误。

首卷三普通整项均critical=true。RubricCriterion.critical是冻结分项必须满分，guard125独立于0.8拦截；evaluators277把这种不足满分强制映射CriterionResult.severity=critical。0分/补弱正确且运行遵守冻结契约，但普通无证据被呈现为三个关键错误，出题阶段的过严元数据缺乏课程依据。

0分本应补弱，1有效失败轮、0完成事实；未观察完整正确误拒。

全三项critical使实际需12/12；假设4、3.5、4时各目标1/.875/1、总11.5/12=.9583均达0.8，仍会因一项未满而拦截。这是逻辑风险例，不是实际模型成绩。

这属于实际课程内容验收阻断，不推翻旧固定六例成绩；没有把尚未观察到的完整正确误拒记成发生过。Tutor的SELECT age/id/id,age只是投影对照，内容正确，但不应据此声称扩展SQL形式已测评。

### 只改课程数据的修正建议

保留旧卷/评价，新增版本化SQL课程私有标准，为七个普通criterion_id明确critical=false、普通部分分与未知非关键误解；保留required和0.8门槛，不改固定六例03永久删除的q1_c3关键规则。通过正式资料导入/绑定与新计划、新assessment复验，不改通用核心、Prompt或旧冻结记录。新数据须另审，不继承旧novel-v1批准。

记录保留旧卷与评价，不自行修改任何业务实现、Prompt或冻结题；之后新数据/新项目/新卷必须用实际新输出继续独立审查，不能继承本轮或固定题批准。


## SQL课程新增私有标准与隔离v2计划、两卷内容复核（追加）

本节为独立AI审查，非人工批准；旧workflow的 `B_SQL_COURSE1_ALL_CRITERIA_REQUIRE_FULL` 保留。固定六例novel-v1不背书实际课程新资料、新卷或成绩。

新增curriculum_private SHA256 `8aac3d30e7a1801c1a56eb53aeef919713374e21f82ac28a488f29e8e83b2555`，新manifest SHA256 `2cf004d4981ba875915b7cb7b6240d17ba91d6dfcbad2cfc5b1b3f612b575bd0`。第3assessment_private来源身份/hash/3节行号均正确；原教学与私有正文和旧pack逐字节一致，6例hash及批准标准未变，freeze03核心hash全部未变。普通7项保留required与0.8，critical=false允许部分分；未知仍相应项0，实际永久删除/改写原表误解仍可标severity=critical，固定03关键标准及9分拒推进不改。学术规则、顺序和等价接受范围一致，新数据参考语义可接受；原人工approval显式不借用到后增量规。

隔离项目 `v3_1117a458471f4259b3ead1ebe85d9120` 的真实adjust_plan末版revision5/version1为 `node_sql_select_projection` → `node_sql_where_filter`，3+3可观察必要目标，18+22=40分钟≤60。全目标text_rubric/text_excerpt，目标与总分0.8，每目标至少1题/1证据。raw4经契约默认展开后与timeline4/5计划一致，policy未改；验收操作员确认，非人工确认。五段教学目录与原文/hash一致，目标相关、依赖及现有能力正确。

首卷 `assessment_18c9c5b838065b698e4d8adff2f188b9` 实际3题共6分、8分项均critical=false，覆盖3目标，答案与行序变体成立。三题未知作答实际graded0/6，8锚点精确，severity均null，Diagnosis引用3当前证据并remediate；当前无先修节点且未查询历史，不伪造历史依据。守卫未通过、1有效轮、0完成。普通和补弱Tutor限定当前列投影，不计分理解检查未通过或解锁。该首卷与未知结果可接受，未观察部分正确答案或第二节点完成。

第二卷 `assessment_80a901127e0d53008823adc049baaf31` raw16实际3题共10分、9分项默认critical=false，previous正确指向首卷；正式validate_quiz连旧题排重通过。纠错式列/姓名/行序3分、只读原表4分、SELECT/FROM职责3分，范围、答案、变体无阻断，可继续真实回答；本节不批准尚未审查的分数。

两卷snapshot、quiz contexts与首轮grading_contexts均仅sql-teaching，新增curriculum_private虽导入却未绑定/输入，不能将合格新卷归因私有修订。普通PreparationService确认省略material_links；Repository只冻结目标teaching及显式验证的assessment/grading绑定，上传不等于接入。可在新项目确认前用现有Repository显式配置演示契约，但需另核profile/plan/revision/input校验、用途绑定、快照、links和真实模型输入；confirm_plan只作同身份幂等恢复，不等于普通CLI/网页已提供私有绑定。生成量规仍需内容审核，未宣称全局消除模型误拒。

非阻断精度：只读题的标题引用不能单独支持原表细节，实际projection规则加题面给定全表支持正确答案；后续宜选table实质段。

固定截面：首卷至补弱raw前14行SHA256 `a87319d6f06aaf48920022d085a90a8c9f345e76c2b9159544cee3ef75554248`、timeline前8行 `d1c890f5e8195404aca5419aec7a495823c3166b97c2cf1080116d885736c667`；第二卷截至raw16行 `cb14687f1ae7dcbaed3ab10ee47b6d8dff7679ab63a1ac4b20c87ca0343100c2`、timeline9行 `c5088cb7d1e069ae376a00843660fb295003001a3827a6b48a11594f79cc4ab8`。首卷相关来源块24次、第二卷6次逐行及双hash一致，8答案锚点一致。raw6/8/10/12/14正式契约首末均合法，无修复；raw16新卷契约有效。后续增长行不包含在本节批准内，详见JSON追加项。


## 隔离v2首节点实际通过与WHERE卷预审（追加）

第二卷公开回答完整覆盖冻结9项，逐项满分10/10；9评分锚点和当前evidence均回到本轮原文。3个required目标与总分均1≥0.8，无关键误解/不确定。真实Diagnosis工具阶段raw20/21查询先修与旧未知0分，最终raw24只凭当前证据advance，没有将未知改critical或伪装历史掌握。raw22是工具后自由草稿，不是正式契约/修复失败；正式schema请求raw23、返回raw24首末合法，grade raw18亦首末合法，0修复。

实际timeline10及数据库确认首节点推进至WHERE：首节点完成记录1行，completion_assessment_id=`assessment_80a901127e0d53008823adc049baaf31`，同assessment transition1行，有效轮2。旧未知首卷仍0且severity均null，未覆盖失败。WHERE Tutor围绕当前行筛选目标且引文真实，不计分检查未解锁。

WHERE新卷 `assessment_8bde07770b56508ab6a8c1f39d4a6000` raw28为3题9分/9普通分项critical=false，覆盖结果边界、原表保留、等价与职责三个目标。规则与实质来源一致，未限行序，契约和validate_quiz通过；可继续实际作答，本节不批准尚未审查的成绩/课程完成。仍仅teaching输入，不归因新增private。

截面：raw26行SHA256 `1d491cae00702fc01e4676b61bda0054cf54bd619b2abec0c5e36c0b15b6b269`、timeline10行 `0f975f4890f3a9b4d79272dd304cd58204baa82f38926df86a33903bd96ea7b1`；WHERE卷截至raw28行 `c9ee71fa8ba03e3574266fead6135b0b1719514de282f47ea157d3a0b58ea3f2`、timeline11行 `d8efc2b481ce2dc5049d94d327465fd6f092f236b7baa7986b98a3aed8cd8f22`。新增18次来源块及双hash一致，9锚点一致。JSON保留实际回答、历史、正式/工具阶段、完成记录和单返回hash；旧课程阻断保留。


## 原隔离v2 WHERE实际通过及两节点完成（追加）

WHERE实际公开作答逐项满足冻结9项，9/9成立。10个锚点逐字精确，其中Yan排除同一片段服务两项，当前evidence去重后9个；来源6次原文/双hash一致。正式grade raw30及最终Diagnosis raw34首末契约合法，无修复；raw32是无工具自由草稿，不能冒充正式输出非法。未查询历史，最终诊断只凭当前实际答案推进，不把已完成先修当当前通过证明。

独立以持久化quiz/evaluation/diagnosis/answers及真实先修集合重算SELECT和WHERE纯guard，两者均passed/advance，与记录一致。三个WHERE必要目标及总分均1≥0.8。数据库恰2行节点进度各唯一完成，分别指向SELECT第二卷和WHERE卷；3个assessment各唯一transition，旧未知remediate完整保留，有效轮SELECT2/WHERE1。timeline14为completed，两个节点ID与数据库一致。因此原隔离项目两节点实际流程完成内容可批准。

timeline12/13两个read入口均保持WHERE等待卷同assessment/input/quiz/计数；只证明读恢复身份未变，不冒充进程终止重启或全新环境恢复。流程是合成操作员已知公开题验收，不等于真人学习增益或部分答评分覆盖。固定六例与实际流程审查分开；旧课程阻断、私有未绑定限制继续保留。隔离恢复/干净依赖环境仍另审，release_approved保持false。

本轮截止raw34行SHA256 `2ee6e6bc2e0388c5991ba053a78ac7be6a347031abb0e8b5c512deed3da1cb29`、timeline14行 `1310d9925bf5c97547b1049a1d8551bd559dca8d265e4776bb2aababbc21d492`。机器JSON追加原作答/评分/正式诊断、全部完成记录、transition、两次纯guard重算与阶段hash。


## 干净环境与恢复分支（追加：技术通过，新WHERE内容阻断）

独立重跑包verify：320文件、三库完整性/版本/业务及checkpoint身份均通过；manifest SHA256 `21d65b4c1f691a4fa3371529d6d6f7ab3e6fc5b1cc8589a6944d1697e079e751`。停写前后hash一致。恢复timeline1完整view/counts/tasks与原waiting-snapshot完全相同，原SELECT assessment `assessment_80a901127e0d53008823adc049baaf31`、pending `input_ab4ec9fff3735e5b9f180c4897740bd5`、原题与预算8保持，恢复/read零模型且未重写checkpoint。恢复代码全部freeze03指纹一致；主V2/V3和原隔离课程三库仍匹配恢复继续前hash。

保留的实际干净安装日志证实README venv/install/init/app.py与HTTP200；独立现场重跑pip check通过，新prefix不同base，system-site-packages=false，导入restored/code/app，本地无.env。模型动作仅由外部操作员传入受保护进程环境，未复制密钥文件；独立审查未调用模型。技术恢复结论不覆盖新卷内容。

恢复SELECT仍是原等待卷，题目/量规与包内库一致，实际公开答案10/10，9精确锚点/9证据，真实查询旧未知0分/null severity；最终仅用当前证据advance。分支后续WHERE是新生成卷，因此新assessment `assessment_cddf60b5fc0e5f4ab97cf3b9efa3b897` 不同于原分支合法；其题面/学术答案/引用真实，本轮正确公开答案6/6，7锚点/7证据。正式评分和最终诊断首末合法，无输出修复；工具或自由草稿raw4/6/16不是正式契约失败。24来源块双hash/原文、16作答锚点一致。

**内容阻断 `B_SQL_RESTORED_WHERE_ORDINARY_CRITICAL`：新WHERE raw12把where_result_names、where_filters_result_rows_only、where_equivalent_condition设critical=true。姓名集合与等价比较等普通required目标没有必须全满依据。** 例如姓名项0.75/1加边界1/1，目标0.875、总5.75/6≈0.958均达0.8，仍因critical未满被拦；这为契约逻辑风险，实际本轮全对并未误拒。保留6/6和推进事实，不追改冻结新卷/标准/原输出；不能写成新卷内容全通过。

两节点按持久化事实独立重算guard均passed/advance，完成记录各唯一、三assessment transition各唯一，未知失败保留。预算8+9新请求=17，含此前2个Planner；learning model_tasks合计15，分母不混用。最终页面completed，说明技术恢复继续和本次全对路线成功，不证明新卷元数据正确。仍仅teaching输入，不能声称private修订有效。若另补接入证据，应在新项目显式assessment/grading绑定并核快照/实际输入后审新卷；普通入口限制保留。

本截面raw18行SHA256 `0af61112a99dd129eadc817bad76defedf6b844dac9c97d1e540aa76fffcdaf2`、timeline4行 `b99460c8f9e6a4d4374c4b615f7f8f6fae93015dfceaa3e47cd68937989f3add`。JSON将技术恢复批准与新WHERE semantic_citation_review=blocked_independent_review分别记录，旧workflow失败及原隔离v2批准均保留；release_approved=false。


## 显式私有绑定配置方案预审（追加，实际接入待核）

`configs/v3/novel/sql_material_links.json` SHA256 `2154f805f16ff3fbe27718c0a08f014a2d351df2d423d2ad0e5f096af22f4eb2` 作为已有Repository.freeze_plan(material_links=...)管理调用的数据，可用于证明仓储与ContextBuilder配置接入。仅绑定sql-curriculum-private通用段及对应节点段到assessment/grading，不改阈值/权限/预算；teaching用途既有过滤可隔离私有资料。此处仅认可方案可行，未批准尚无证据的实际输入或新卷。

需在管理caller保留profile确认hash、当前教学目录+策略的validate_learnability、revision/input身份校验；每目标分别两用途，匹配集合必须同时含通用段和节点段。当前raw2是3节点候选，expected_node_count=2应拒绝直接冻结，普通adjust_plan后的最终两节点计划另审。管理冻结若保留Preparation旧等待checkpoint，不声称普通网页confirm完成；学习Graph从已冻事实独立启动及该入口限制需公开。后续须核private冻结hash与quiz/grade实际段、Tutor隔离，以及普通critical元数据/评分/恢复。旧恢复分支内容阻断继续保留。


## 显式绑定实际冻结与首卷审查（追加）

新项目 `v3_2673196fa4e6442a9a058be8acbd7d39` 经普通adjust_plan得到2节点45分钟、3+3必要文字目标，保留0.8规则，候选与管理冻结计划一致；独立validate_learnability通过。管理caller实际检查profile确认hash、当前教学目录/策略、revision/input，现有repo freeze正式写入24条私有links（每目标通用+对应节点段，各assessment/grading）。逐条契约与真实DB复核通过，snapshot含curriculum-private正确hash/version，未绑定旧固定六例private。

raw7出题每个目标真实包含2个private段，raw5 Tutor输入仅teaching；公开学习view无私有来源ID、answer_key或rubric结构。16个输入来源块逐行/双hash一致。由此可批准本次配置实际接入及隔离边界，不能扩大到普通网页confirm已支持，也不声称Preparation旧等待checkpoint结束；实际Learning独立Graph从冻结事实启动。helper一般性限制：heading any只检查非空、未显式选版本；当前集合完整且单版本，所以不阻断本次，但不是完备通用管理产品。

首卷 `assessment_677e093792ee55ea96efdd73ac87418b` 的3题12分/10项均critical=false，列选择、姓名/读取/只读、行序/集合/无age筛选目标覆盖完整，答案与变体、实质引用成立。正式validate_quiz通过，普通部分分元数据无阻断，可继续未知作答。新rubric不是private七条ID/权重的逐字转译，也未声称覆盖未单列的18<=age能力；不改变原六例标准。本节不批准后续成绩、新卷、WHERE或恢复。

本截面raw8行SHA256 `dd7791494f464a9dc5db1ded55d0af8d29cd4bc6c208f48a67e7dfb15ad2e162`，timeline7行 `d993ec80ec568f1b60638fff46df676a80081935d9a8d98ea865d2cb6c2ef0cb`，管理绑定evidence SHA256 `1a73366b73f3ba0dc67ba4255f7ea97dca7a1b3f915981fed46777ad6cf16001`。旧恢复分支critical内容阻断、原隔离v2批准仍保留。


## 显式bound原项目未知/补弱及两节点完成（追加）

本项目实际三卷分别未知0/12、SELECT第二卷12/12、WHERE12/12；量规数量10、9、11，全部普通critical=false，未知severity全null。31个评分锚点精确；当前三次纯guard重算分别remediate/advance/advance，与持久化一致。未知1有效轮0完成，补弱Tutor围绕真实作答；第二卷previous关联正确，SELECT完成后才解锁WHERE，两个节点各唯一完成记录，3assessment各唯一transition，旧0分未覆盖。

新增95次来源块（含已超时请求的实际输入）逐行/双hash一致；所有quiz/grading都真实含通用及正确节点private段，补弱及WHERE Tutor输入只有teaching，公开view不含私有ID/评分key结构。SELECT姓名/列/顺序/只读和WHERE边界/集合/职责/不删改规则成立；WHERE等价写法在已教同一边界及已绑定参考范围内。当前原bound课程无内容阻断，可以给本轮独立批准，不推断未来卷必然正确或真人学习增益。

可靠性记录纠正：SELECT评分raw17→18为真实APITimeoutError，raw19→20网络重试成功；WHERE出题raw29→30超时，raw31→32重试成功。两任务network_retries各1、output_repairs均0，所有正式收到评分/诊断首末合法。raw24是工具后的自由诊断草稿，曾误将其他WHERE节点目标当SELECT缺证据；正式raw25→26已正确按当前目标advance，此过程误判作为非阻断限制保留，不藏掉也不误算结构/业务修复。

累计预占19=Planner2+learning tasks17，最大单操作6≤12；重试均入共享预算。原始截面raw38行SHA256 `2db846bf348531b844da2d5458d105502e9c608b195ff235b5910d48a4c6b0df`、timeline12行 `32212597a054687a396bde67effabfb5898dfd71803388926f1bcdfee6947931`。

另独立verify bound待答恢复包324文件/三库/身份通过，manifest SHA256 `c207463f95177a0ca08043f264b3ebba4475d2238b703887f01c9ad8fcead050`；初次还原read完整view/counts/tasks与原待答snapshot一致，原SELECT身份/题面/私有快照/预算8保持，0模型调用。此条仅技术初始恢复批准，恢复后真实续学另审。两处旧unbound内容失败继续保留，普通网页私有绑定和管理Preparation等待checkpoint限制仍披露，release_approved=false。


## bound恢复分支最终内容审查（追加，通过）

初始完整view/counts/tasks与原待答snapshot一致，SELECT assessment `assessment_66ac4af91a495312ba3304bc574836f7`、pending身份、原卷/私有快照及预算8保持；restore/read无模型。SELECT实际正确回答12/12，10锚点精确；新WHERE assessment `assessment_61cd810133fa5033a4e72f0f6565cdbd` 可与原分支不同，3题12分/12普通项均false，当前公开答案12/12、12锚点精确。正式grade raw2/14、最终Diagnosis raw8/18首末合法，raw4/6/16是工具或自由草稿，0修复/0网络重试。SELECT真实查旧未知0分/null severity，最终按当前证据通过；WHERE不查历史且不假称查询。

44实际来源块逐行和双hash一致，quiz/grading每目标均真实含通用及节点private段；WHERE Tutor仅teaching，age>=20对照仍属同一整数筛选范围，不计分不解锁。公开view无private身份/答案键/量规结构。两纯guard独立重算通过，2节点各唯一完成，3assessment各唯一transition，旧未知失败保留；原bound项目完成记录与之前审查相同，未被恢复分支覆盖。预算8+9新真实请求=17（含先前2Planner，learning tasks15），最大单操作5/12。当前恢复分支无内容阻断。

截面raw18行SHA256 `aa7380b6258921243b42c202e95863c97a1dee1389cb94ae12a21bbcdcbce810`、timeline4行 `a891a31872bda1bef6a4598e7564ee4f42a08ae851eb029d893fbc13b1bc7fa2`；JSON留完整作答、评分、来源/锚点、历史与持久化依据。旧unbound内容阻断仍保留，不宣称模型普遍自动修复。

## Day13与Day12严格范围判断（独立建议，非用户批准）

§15.2的第四主题抽象验证已获本次证据支持：只增资料/配置/预确认案例，以已有Repository用途绑定进入同一Learning Graph，实际输入、闭环与恢复完成，未改runtime或Prompt。

但用户架构§6.3第4步是“用户确认计划后”冻结资料版本与绑定，M6要求从创建到通过可完整操作；Day12公开sources允许assessment_private，而普通Preparation.freeze省略material_links，网页没有把这些私有来源配置到测评用途的入口。管理API冻结绕过的正是这条用户路径，不能用其成功替代完整网页路径。未绑定时真实发生过过严量规，也不能声称上传即修复。

严格原范围下，我建议将此列为产品缺口并阻断无条件的整体V3.0结项，交用户最终范围/体验复核；不由AI自行降为已接受的非阻断边界。若用户明确接受V3.0私有标准仅限受控管理配置，可按新批准范围判断，但仍必须披露网页限制与旧失败。或者完成原私有绑定产品路径后另复验。本建议不替用户批准范围，也不要求本轮擅改已冻结核心；release_approved维持false。


## 正常产品私有绑定、超限与兼容独立审查（追加）

本节为独立AI审查，非人工批准。新增正常confirm_plan对每份当前私有参考明确bind或exclude，公开只给项目/版本范围opaque句柄和通用标签；上传者自己的标题只在本地以text节点显示，成功上传清空隐藏原文与文件。服务端拒绝缺选、跨项目/旧版本句柄、重复与未知节点，私有正文/source身份不进入公开详情或Tutor。绑定仅assessment/grading，Preparation Graph freeze同事务写版本快照与links；旧管理helper与candidate03不是本次通过证据。

独立重跑绑定测试12项通过（21.94秒），覆盖新请求、旧journal、单请求重放、同请求变体409及真正子进程硬退出后的两处恢复。业务commit或checkpoint commit退出73后，GET不改业务/检查点，显式retry复用原快照/links/预算、不调模型，Preparation Graph正常结束。旧已接受且缺新增字段的journal保留原teaching-only语义；新提交不能借缺字段绕过逐份选择。

只读预检在新journal前及Repository事务写入前均执行，复用每目标三用途的实际_build，并复用完整首次quiz消息序列化。另独立隔离探针构造3个目标，每个上下文5567字符均小于24000，整卷prompt超限仍返回422/context_limit；草稿、journal、快照、links及调用数不变，立即exclude后200正常冻结，只有原1次Fake Planner调用、0真实模型。断言全通过；随后Windows SQLite占用导致临时目录清理失败，所以该探针进程退出1，不能伪报进程全成功。自动审批拒绝了精确目录清理（blocked by policy），未绕过；残留仅隔离临时目录，未接触运行库。

本范围未发现剩余实质阻断。预检不能事先保证未来生成长卷、答案或补弱历史都不超限，动态边界和生成内容审核保留。本人未运行浏览器或真实模型；本结论限定静态/独立Fake及硬退出恢复，需匹配新指纹真实复验、新普通产品课程和恢复及用户体验复核后判断整体结项。旧网页缺口和旧unbound量规失败保留，release_approved=false。源文件与测试hash详见JSON追加项。

## dev10、dev11、dev12中间与失败证据（追加）

- dev10总64真实请求。Python08评分0/10符合实际元素/下标误解，但首次正式Diagnosis和唯一修复均把project_id末尾e91a写成e91c，修复还添type=json_object；业务/结构校验停止，未误放行。本轮阻断，不冻结，其他科自动通过不能补足该失败。
- dev11总63请求、三科各8/8的中间事实保留。24例手工语义已阅读，关键误解、来源规则和真实历史未见新的内容阻断，但运行后runner的重跑角色provenance变更、后续诊断Prompt再演进，旧指纹不作当前冻结批准，未写语义审批通过。
- dev12总65请求。数学02真实评分2/10和补弱方向成立，但两工具轮后第3诊断请求的正式project_id末尾c89b写为c89f；此时已用完任务请求数，没有非法追加额度。JSON结构合法仍身份不合法，严格业务校验停止。本轮阻断，不冻结，不降低零技术失败门槛。首末原始输出和每例raw/result/report hash均保留在JSON。

后续Prompt v6及当前runner需新的真实dev输出独立审查；本节未把旧成功或修复前输出当最终批准。

## 最终12例复验的标注判断（追加）

final-v1仍保留首次新增独立12的原始证据。现有证据显示本次修复来自SQL普通产品流程、Fault/Fake及开发集身份失败，未用final12改Prompt/代码或答案量规，因此可以复跑已批准标准，明确写“先前独立集的冻结后复验，非首次未见”。未发现无原因再造12例、重复确认相同金标准的必要。若未来用该复验失败调参，相关例也进入曝光历史。SQL主题已经参与修复，不再称未见主题；新候选复验后另选主题。本判断不替用户批准发布范围。


## dev13当前匹配版本正式独立审查（追加，通过）

本轮真实开发24例逐例实审通过：英语8/8、数学8/8、Python8/8，零误推进/误拒/意外拒评/技术失败；有分各6例，MAE/10分别0、0、0.333。总62请求/62返回，0输出修复、0网络重试。报告SHA256 `91a256f2d9316156a172d415bb679ee62b5cce39aee03459d78795ba07ecc9d5`，当前全部runtime/Prompt/runner/输入指纹匹配；Diagnosis6、grading4、review2。此为独立AI语义批准，非人工或发布批准。

独立核24个case hash及逐例result/report一致，66来源块按真实行号和双hash一致，57实际答案锚点精确，12质量审查source_quote/answer_quote均真实且内容支持主要结论。三科05均准确拒绝无作答依据的候选满分，06均定位实际题/key歧义或冲突，没有以过时评价器进度拒评。三科03冻结关键分项均0critical而补弱；04仅结果/时间词不冒充解释目标；07注入无效。18普通例纯guard独立重算与实际全部一致。

三科08实际工具记录均查询到同源前置错答：英语缺否定助动词，数学负数除法符号，Python元素/下标混淆；当前答案与原历史学术内容对应，回退有实质依据。其他无历史例正常当前补弱，不把completed/no_history或正确历史伪造成旧错答。数学02本轮2分正确部分给分且身份合法，Python08本轮同样身份合法，旧dev10/dev12失败不覆盖。

正式契约口径：18grade、18最终Diagnosis、6review首末均42/42合法。原自动结构数39/42（各科13/14）把工具选择阶段JSON自由草稿计作首份；该草稿不是正式schema返回，不能称输出修复或技术失败。原report原样保留，JSON独立审查另列正式口径，不为统计改runner或重跑。

非阻断：Python07得2比冻结中心4低2，仍在用户已批准单例最大误差内，补弱行动正确。数学06第二finding引文只间接支持题面/量规不配套，须结合实际题面；第一finding“未给k却唯一数值8”与真实冲突规则直接充分，invalid_item结论成立。JSON逐科semantic_citation_review均approved_independent_review、阻断列表空，并保留逐例正式输出位置/hash、实际历史、评分/诊断/guard及原raw/result hash。后续冻结曝光、先前独立集复验、新普通课程和新主题仍单独审查；release_approved=false。



## 普通Preparation SQL真实开发回归（追加，通过）

项目v3_c02e948a3c0d4548ac1856b66cd9e664通过真实Planner普通adjust_plan得到SELECT→WHERE两节点，25+30=55分钟≤60；两个required文字目标及总分0.8。normal-confirm用两份opaque句柄明确选两节点，实际Preparation.resume事件、accepted指纹、profile确认hash一致，正常Graph末checkpoint无待执行branch/writes、journal清除。没有调用旧freeze_config，管理路线不冒称网页确认的历史问题在本次正常产品路径获直接修复证据。

实际34绑定中28为private，两私有来源的全部chunk仅assessment/grading；三来源冻结hash与当前文件一致。三次出题/评分实际含private，三个Tutor输入（初讲、补弱、WHERE）仅teaching；公开12截面无private身份/answer_key/rubric结构。69输入来源块逐行及双hash一致，题目和Tutor引用的projection、表格、行序、WHERE实质规则支持内容。

三卷各一题12分/三普通项、均critical=false：未知graded0/12且severity均null，正常补弱/0完成；新SELECT卷previous关联原未知卷，当前公开答案覆盖列/集合/无ORDER BY行序/只读，12/12；随后WHERE覆盖Lin/Mei、排除Yan、18包含/17排除、原表不变，12/12。11个原始评分锚点（9个持久化去重证据）精确，3次纯guard独立重算与持久化相同。WHERE实际查询前节点旧未知0分和正确重测12分，最终仅依当前正确证据推进，未把未知修成critical或把正确历史写成错。

2节点各唯一完成，3assessment各唯一transition，SELECT有效轮2、WHERE1，旧0分保留。共16真实请求预占=Planner2+learning14，最大单操作4/12，0网络重试/输出修复。14正式收到契约首末合法；raw20是工具选择自由草稿、raw30为实际工具调用，不冒充修复。操作员错误start_assessment被allowed_actions入口拒绝且0模型请求，原失败日志保留，改用正确start_quiz完成。

本轮内容及正常产品私有用途可独立批准，但SQL已参与调试，且准备/早期未知使用诊断v5、后续正确重测及WHERE使用v6，仅为开发回归。生成rubric不是private七条逐子分规则的完整转录，当前路线只实测未知/全对；WHERE未单列职责或要求写出18<=age，不能扩大成这些独立行为已获证据或所有部分答案必然正确。冻结04新主题、干净恢复及用户最终体验仍另审，release_approved=false，旧所有失败保留。

截面raw32行SHA256 cf0d213526b7d1a712b71379321bd12f036966353ac2de0dd38e9975cec09628，timeline12行812d1bb6d9536ea94973a12544d350a98175ca51253e22e73241dbb3cf867b2b，learning.sqlite 4bffe3db50adfea9e66629b76db679aa56150c340c7b876afdc00f941f931872。JSON留实际计划/选择/checkpoint/links/答卷/评分/历史/完成及三库hash；独立只读核查未改运行库。


## 冻结04曝光复验exposed-v4（追加，通过）

本轮明确为已曝光12的冻结后复验，非未见集。英语/数学/Python各4/4，MAE0，零误推进/误拒/意外拒评/技术失败；31请求=10+10+11。报告SHA256 13ce0bd84841dc369d705a5809c4c97419e7dfe6b4a7c1d53190e8b365e0e184，与freeze04及当前全部指纹匹配。独立AI逐例批准，非人工或发布批准，旧exposed-v2错误推进仍保留。

39来源块逐行/双hash、最终39原始锚点、32持久化文字证据及1数值证据核对正确；9普通例纯guard重算与记录一致。三科10的实际查询历史都是正确作答，模型保持当前补弱、未把它们伪造成前置错误。三科11总90/100但必要o2=0均拒推进，未以高总分掩盖目标缺失。三科12真实输入保留实际附件，与教学学术规则互斥：did后过去式vs原形、只改一侧vs两边等价操作、range含stopvs不含stop；理由列真实双方规则与身份，均needs_review/assessment_review。英语12虽保留主资料暂算10分，未生成目标结果或正式通过，符合暂停。

正式schema任务12grade+9Diagnosis，结构首末21/21；首次业务身份/锚点20/21、最终21/21。Python09首份锚点“六，四，二。每次减二”长度10而end11，被业务校验拒绝；在唯一修复中改end10后10分正确通过，raw2/raw4与计费保留。其余0修复、全轮0网络重试；不把修复前输出当最终，也不把工具草稿当正式契约。JSON逐科批准且阻断列表空，含逐例判断/真实历史/附件/原输出hash。下一步只审同标准原final12的冻结后复验，未提前批准新主题。


## 冻结04先前独立集final-v2复验（追加，通过；合并peer实际审查）

本轮三科各4/4、3个有分样本MAE0，各10请求合30，零各类失败。独立peer实际对原始评分做离线回放、引用/答案锚点/工具/SQLite/guard核查，主审已逐例读实际结果，并核peer文档、原报告、manifest、当前冻结指纹、12份case/raw/result与原final-v1字节链，结论一致。没有冒称两次完整独立回放，没有新增真实模型调用。

三个01完整正确均通过，数学数值4.000与过程/原式22=22分别有证据；三个02实际反向规则命中冻结关键项，英语6、数学0、Python0且不推进；三个03虽90/100但必要o2=0均补弱。三个04真实附件逐字存在于模型输入，与对应did后原形/非零除数等价操作/while先检查的实际规则互斥，均needs_review/assessment_review，无最终Diagnosis、不冒充学生低分。历史实际无同源错答，不臆断先修；本套不声称正向覆盖查询同源错答后回退。

peer逐例核35学生锚点、41逐例绑定来源及双hash，12评分回放与EvaluationResult全字段一致，9纯guard与持久化一致。正式12grade+9Diagnosis首末21/21合法、0修复/网络重试；另9工具阶段输出分列。原自动每科首份6/7把01合法空AIMessage/model_finished计作非JSON，保留原report并明确正式口径。英语02单摘“a note yesterday”、03单摘“last night”覆盖偏窄，须结合完整答案及其它证据，实际评分行动有依据；两条非阻断不隐去。

本轮明确independent_final_revalidation、first_unseen_execution=false，同字节先前独立集的冻结后复验，不重新称首次未见。原final-v1及全部失败仍保留。本轮批准只覆盖固定题评分/诊断，不批准新主题、Planner/Tutor、新卷、恢复或整体发布；release_approved=false。

原报告SHA256 eb1cd3558d2f2546320f7741ffe00dc88a36cfad9239e2da255bb7f372a2ad5b；peer JSON SHA256 9dba51bb7d15612849199ec7ffc08c525bc1de4a0881d1cee9463cec93e590be，peer Markdown SHA256 437a6ec6bbc768f5ceb895a4f0020bc3ccb9385ad9df520ac7dbadf10250b3cb。peer具体证据见FINAL_V2_INDEPENDENT_REVIEW.md及final_v2_independent_review.json，主JSON保留其逐例结论与来源hash，并明确归属。三科semantic_citation_review均approved_independent_review，blocking_issues=[]。
