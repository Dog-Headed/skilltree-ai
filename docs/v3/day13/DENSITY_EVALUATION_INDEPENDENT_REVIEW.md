# 密度六例真实评价独立审查

结论：density-v1六例实质通过，density_reading的semantic_citation_review=approved_independent_review，无内容阻断。此为独立AI审查，非人工新批准或整体发布批准；不背书尚未运行的普通两节点课程、新卷、补弱或恢复。

## 逐例结果

|例|实际分项与状态|实质依据|
|---|---|---|
|01|4+4+2=10，graded/advance|80/20=4、单位体积质量及g/cm³、40/10比值不变均有实际原文。|
|02|4+0+0=4，graded/remediate|只给数字4，其它明确不会，没有从题面或参考答案替学生补分。|
|03|0+0+0=0，c2 severity=critical，remediate|明确反称密度为V/m并以0.25cm³/g为密度，命中预先批准的关键定义；取半密度再减半也错误。普通RubricCriterion.critical仍全false。|
|04|4+4+2=10，graded/advance|每立方厘米四克完整表达数值/单位/含义；总质量和空间各半、比值不变支持取样。没有因缺ρ符号误拒。|
|05|0+0+0=0，graded/remediate，severity全null|不会声明无正确判断，属于有效题正常低分，未强制critical或作废题。|
|06|needs_review/assessment_review，不计分|真实附件反称V/m并否认m/V及4g/cm³，与主资料互斥；输出定位双方真实规则，暂停成立。|

## 原始证据与纯计算核对

独立对六份实际正式grade JSON做离线回放，不调用模型，六份EvaluationResult全字段与原报告一致。30次输入来源块逐行、片段hash及文件hash一致；16个原始评分锚点逐字定位正确，持久化去重证据13个。引用的实际density-ratio、scaling、reference和rubric内容分别支持密度方向、均匀同比取样及4+4+2子项，不只是ID存在。

五份最终Diagnosis契约、身份、实际允许证据通过；五次纯guard重算与记录完全相同。02/03/05实际查当前节点及mass_and_volume历史均no_history，最终输入没有历史作答记录，当前补弱没有虚构先修错答。01/04工具选择未取得新历史，当前充分答案仍允许通过；completed为固定案例预置背景，不冒称真实学习测得。

06原始评分输入完整保留density_reading_novel_06_supplement的实际反向公式，不依赖学生单方面说冲突。正式理由引用density-teaching 9—12行的m/V、私有标准80÷20=4以及实际附件的V/m/0.25cm³/g，双方学术规则直接互斥。没有question/objective结果，也没有最终Diagnosis、guard或正式通过。

## 正式结构、预算与入库范围

6个grade和5个正式Diagnosis首末均11/11结构及业务合法；另5个工具选择阶段输出分列。原自动首份10/11把01工具阶段的JSON草稿（未提供evidence_ids）混入，不能称正式诊断失败；04的代码块草稿同样不是正式返回。全部任务output_repairs=0、network_retries=0，16真实请求/16响应及usage逐条一致。

只读打开原运行SQLite，6项目、11任务缓存逐字段与报告一致，6操作共16预占，最大单操作3≤12、任务≤3，读取前后hash不变。该固定题runner没有创建assessments、learning_progress、learning_transitions，三表均0；它保存评分/诊断任务并计算guard，不冒称普通课程已正式完成或依赖已解锁。操作status=running是该评价runner未关闭的存储状态，实际请求已结束。

原report.md通用页头“05/06是独立审查服务测试”不适用本主题：本轮六例task_type全部ordinary_grading；06实际走text evaluator资料冲突暂停，未调用quality_review服务。保持原文件不改，将其作为模板说明局限。本轮固定题评分/诊断通过不等于新题生成或Tutor通过。

## 批准与冻结溯源

用户批准记录保存直接回复“认可六例标准，继续真实评价”。逐字草稿备份hash吻合，三JSON共九处变化仅review_status，六例正文及答案/量规/门槛未变。批准在2026-10-23 16:32:28.953985 UTC，运行起点16:32:34.121007 UTC在后；新主题选取在前轮final-v2独立批准后，冻结04全部当前指纹及本轮独立输入包匹配。本轮只新增资料/配置/案例，没有密度专用runtime或密度单位numeric_scalar支持宣称。

6/6行动与状态一致，五有分样本MAE0；两个正确/等价答案允许通过，关键错、普通错误和未知不放行，冲突例单独暂停。零误推进、完整正确误拒、意外拒评和技术失败。费用没有可靠计价，仅保留provider usage（输入57746、输出19872 token）。

原报告SHA256：420fe9b4e114b73732f73663f9ac2faec78feda655fbfaf6a1f8d6cd824a5136。只读业务库SHA256：0b3d71223a54e39465e5a276a1c3e2ff24451dab72bba66bef68cb8fa5115134。逐例原始输出/来源/锚点、正式与工具阶段、批准链和hash见density_evaluation_independent_review.json。reviewed-report.json保留原报告数据，仅更新独立语义状态并添加本审查溯源。普通课程须使用后续实际输出另审。
