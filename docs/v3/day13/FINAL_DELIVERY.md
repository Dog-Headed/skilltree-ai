# V3 候选04：最终交付与复现

用户于2026-10-24直接确认“体验没问题，认可当前边界”。Day 13及V3.0通用文字学习版最终验收通过，范围限本页记录的能力与边界；签收记录见FINAL_USER_ACCEPTANCE.json。详细标准逐项见根目录DAY13_ACCEPTANCE.md。

## 看最终演示

本机隔离演示：http://127.0.0.1:8765/ 。选择“质量、体积与密度入门”，查看两个后端确认通过的依赖节点、逐题反馈、冻结计划与公开来源。可刷新核对保存结果，更多操作支持重命名、删除等原有功能。本次页面数据是合成验收记录，不是用户本人的学习成绩。

演示运行在D:/SkillTree_AI/day13-isolated-20261024/density-restored-v2/code，数据也在该副本；原仓库data/V2/V3不切换、不覆盖。进程与解释器记录在work/day13-20261024/final-demo.json。该演示只供本机使用；未来用户主动操作会产生新的副本事实，不纳入本次已封存的请求统计。日常使用仍按README启动原仓库app.py；端口被演示占用时先结束该演示进程，不要同时启动两个8765服务。

1440/390宽度截图、公开响应、仅GET/刷新检查：work/day13-20261024/final-browser-stable。初次截图捕获抽屉动画中间帧及滚动偏移，已保留；稳定截图启用减少动画并回顶部，未修改产品CSS或源代码。

## 真实评价索引

|目录（均在本机work）|范围|当前结论|
|---|---|---|
|day13-20261023/dev-v13|三科24开发|独立通过；62请求|
|day13-20261023/exposed-v4|原12曝光验证|独立通过；31请求|
|day13-20261023/final-v2|既有独立12例冻结后复验|双独立通过；30请求；不称首次未见|
|day13-20261024/density-v1|新密度六例|独立通过；16请求|
|day13-20261024/density-course-v2|正常确认、补弱、新卷、两依赖节点|内容及事实通过；16请求|
|隔离density-restored-v2/code/work/real-density-recovery|等待点恢复真实继续|独立通过；7+9=16请求|

每个固定评价保留run_manifest、逐例raw/result、原report与不改原报告的reviewed-report。报告记录模型deepseek-flash、评分Prompt4、Diagnosis Prompt6、显式审查Prompt2，以及代码、资料、策略、标准、usage、延迟、工具与有效行动。公开报告不含凭证；详细原输出包含私有答案，留在忽略目录。费用不可得，不估算成实际账单。

本轮对真实样本之外的错误率不作统计保证。原36例由24开发和12曝光验证组成，另12独立案例的原首次与当前复验角色分开；不把重复执行当新样本。资料/期望在模型运行前由用户确认，AI独审明确不是人工批准。

## 第四主题接入文件

- configs/v3/novel/density_reading.json：开放学科档案，现有text_rubric能力。
- materials/v3/density_reading：初始资料与固定六例来源，原字节保留。
- evals/v3/density_reading/cases和evals/v3/day13/density_standards.json：六类预先确认对照。
- materials/v3/density_reading_course_v2：仅资料同义澄清；教学正文不改，普通复合项critical=false，实际反向定义severity=critical。

原课程量规失败保持失败标签，后一个版本是资料修订后复验。没有density专用Graph、工具、单位解析或学科分支。实际课程使用普通Preparation确认和私有参考选择，不借管理员freeze_config。上传新课资料时采用course_v2两正文，在计划预览明确绑定私有参考到两个节点；原六例评价仍使用原资料，不能混换历史依据。

## 可复现运行与恢复

Python3.11；完整安装、初始化、启动命令见README。实际架构见docs/v3/ARCHITECTURE.md；评价CLI见docs/v3/day13/EVALUATION.md；恢复操作见docs/v3/day13/RECOVERY.md。

最终包装检查修正了.gitattributes：冻结文件本来同时含LF/CRLF，强制转换成LF会改变哈希。现在用`* -text`保留版本化原字节，仍可普通文本diff；没有重写任何已评估资料、核心或标准。在隔离新Git目录设置core.autocrlf=true，353文件add/checkout-index全部字节一致，116核心匹配冻结；用新venv加载该导出代码初始化空三库、四HTTP只读入口200、0模型。原仓库Git index未动，无提交或推送。见GIT_BYTE_PRESERVATION_REVIEW.md及work/day13-20261024/git-full-export-final-evidence.json。

最终人工签收源码副本另存work/day13-20261024/accepted-code；签收前匹配副本work/day13-20261024/final-code-preserved-bytes保留原字节；旧final-code及等待点包保留原字节，恢复包内旧Git属性不影响直接复制恢复，核心/资料实际输入一致。清单DELIVERY_FILES.md列当前工作树相对基线的所有改动。

当前私有等待点包：work/day13-20261024/density-v2-waiting-backup，356受控文件。原project/thread保持v3_6f0ca83c78f34effa586cf3cedcabde6；原待答assessment_c3fc2d197d735d5698536b21356841d2、完整试卷和预算7保持。包含匹配代码、三库、资料与环境清单，不含.env/密钥；安装仍需软件源，真实调用需另外配置凭证。请先停全部写入，验证后只恢复到新目录。不要将私有包推到GitHub。

实际新环境：day13-isolated-20261024/clean-install-v2/code/.venv，按requirements安装，pip check通过、四HTTP读取200、0模型。随后用该解释器加载另一个恢复目录的代码继续原卷，保存六个旧任务原样复用，最终两唯一完成。证据density-restored-result.json保持审查前原字节，最终语义批准见density_workflow_independent_review.json；派生批准记录另存，不改原证据hash。

首次strict restore拒绝审阅产生的额外WAL/SHM，四文件已保留隔离，清单内字节未变；当前strict verify通过。以后审阅备份用mode=ro&immutable=1并显式close，不直接以普通SQLite连接打开只读包。此事件与旧普通量规失败均不删除。

V2独立旧环境恢复见V2_RECOVERY_RESULTS.md；真实范围是wait_learning，Fake的wait_answer补充不得改称真实原作答点。不能让V3执行旧Checkpoint。

## 测试、边界与最后人工事项

稳定全量913通过/623.94秒/2依赖警告；新资料47通过/4.48秒；新环境恢复/评分/幂等104通过/78.73秒/1警告；6个私有绑定浏览器场景通过。测试有交集，不相加。Fake证明流程，真实评价证明本次有限内容样本，两者分别报告。

当前没有未解决错误推进、重复事实、私有泄漏或无法恢复的验收阻断。自动生成的内容仍需有依据的资料和审查；普通required不能被误设为整项critical。已保留的窄引用、空查询历史措辞、过度保守隐私匹配是质量边界，不宣称已全局消除。

本地单用户文字系统；当前评价器choice_exact/numeric_scalar/text_rubric。无代码执行、实验、听说、多模态或复杂证明；私有文件按整份绑定，超长资料须拆分；未实现多机分布式锁、离线依赖包或跨平台恢复保证。

最终人工检查已完成：用户直接回复“体验没问题，认可当前边界”，确认最终演示和上述范围。当前状态为“Day 13验收通过，V3.0文字学习版完成”。此次只记录签收、更新文档与归档，核心代码、评分标准、原输出及测试证据均不改。
