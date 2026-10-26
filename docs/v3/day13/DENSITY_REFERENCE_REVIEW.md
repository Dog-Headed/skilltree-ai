# 候选04新主题参考复核：物理密度入门

状态：**待用户复核，不是人工金标准；尚未运行此主题模型。** 原SQL已参与修复，不能再次称未调试主题。本主题在候选04三科冻结后复验获得独立实质批准后选择；不修改通用代码、Prompt或服务端能力。

## 范围与能力

两个依赖节点：①区分质量/体积及g、cm³；②密度m/V、g/cm³含义、理想同温均匀材料同比取样。只用已有text_rubric评估文字解释和简单计算；不声称已新增密度单位numeric_scalar解析、实验或复杂证明能力。资料按正常网页途径导入，计划预览显式选择私有参考节点，正常确认冻结。

规则依据已查OpenStax《College Physics 2e》11.2 Density、NIST Density词条和SI Guide Chapter4。讲义、题目和数字为本次原创合成，不复制原书题；ρ=m/V、每单位体积的质量和SI单位kg/m³有原始依据。同温均匀材料同比取样不变是按比值定义作的数学推论，明确排除状态变化、孔隙和损耗等现实条件。

## 共同题目与量规（先于模型输出确定）

题目：均匀材料80g、20cm³，计算并解释密度；同温同物态、无损耗取半后怎样变化？

标准：4g/cm³，即每立方厘米4克；ρ=m/V。取半后40g、10cm³，质量与体积同比减半，密度仍4。

10分分项：结果数值4占4分；质量/体积或单位体积质量2分、g/cm³等价单位2分；取半密度不变1分、同比变化理由1分。每项只按明确子项评分，不新增隐形要求。普通项critical=false；明确反称ρ=V/m并据此判0.25cm³/g是预定义关键概念错误，评分应标critical；普通不会/漏项不标critical。

## 六例预期

|例|学生答案要点|预期分/状态|预期行动|
|---|---|---|---|
|01正确|4g/cm³、m/V、单位体积质量、40/10仍4|10/10 graded|advance|
|02部分正确|只给数值4，其它明确不会|4/10 graded|remediate|
|03关键错误|反称V/m=0.25cm³/g，取半密度再减半|0/10 graded，反向定义项critical|remediate，不通过|
|04替代表达|每立方厘米四克，总质量/空间各半，每立方厘米仍四克|10/10 graded，不强求ρ符号|advance|
|05无掌握证据|“我还不知道怎样计算，也没有给出物理判断。”|0/10 graded，severity不应critical|remediate；是有效题上不会，不是技术拒评|
|06实际资料冲突|正确答案，但实际补充资料说V/m并否定m/V|needs_review，无正式分与通过|assessment_review/暂停，引用双方实际规则|

逐字答案、三分项与原文引用见evals/v3/density_reading/cases六个JSON；预期与评分中心单独放在density_standards.json，不进入模型输入。第五例不是空白API提交，不宣称覆盖所有缺证路径；第六例必须有真实附件，不能凭“冲突”标签触发。

沿用已批准质量门槛：该主题独立MAE≤1/10、单例误差≤2/10，关键/普通错误放行、完整正确误拒、无理由拒评及技术失败均0，行动/状态全部匹配。低分、关键错和缺证三例不算正确答案分母；正确/等价两例必须允许通过，不能全部拒评凑零错误。

## 审批范围和下一步

请确认本稿的两节点范围、六例答案、分项和预期；此前SQL批准不自动覆盖此主题。依据用户指定《SkillTree_通用学习Agent架构_V3.0.md》§16.3：“先人工确认预期行为、答案与量规，再运行模型”。确认后先跑六例，再运行普通两节点/补弱/重启流程与匹配代码恢复，按实际结果报告；失败不宣布V3.0完成。

来源：[OpenStax Density](https://openstax.org/books/college-physics-2e/pages/11-2-density)、[NIST Density](https://www.nist.gov/glossary-term/21726)、[NIST SI units](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-4-two-classes-si-units-and-si-prefixes)。

## 待复核字节摘要

- `materials/v3/density_reading/manifest.json` SHA256 `b3e2e3a1d317e7dca4a41025ad5e53b3cff0ed14f4ed1249fc9a4bd59168d72d`
- `evals/v3/day13/density_standards.json` SHA256 `20b88451565959f78a2e3d3b8ec10f2c0ef9e50629cc3961ae99ff383957bbc3`
- `configs/v3/novel/density_reading.json` SHA256 `2449422c65e98cf65bae0de4525e1285c1c2ddd1653165b9d073ca614bc7f174`
- `evals/v3/density_reading/cases/density_reading_novel_01.json` SHA256 `ccd4a50fc58744975abb73592e53e258944c234353ee4a687f0d22a89fd74e85`
- `evals/v3/density_reading/cases/density_reading_novel_02.json` SHA256 `b5d83d991d0e8db245a9377005a88018ce02b84a2c0839527342d65eb5d615b8`
- `evals/v3/density_reading/cases/density_reading_novel_03.json` SHA256 `0ecd9d80e6da400216fdaba1f16bcaaddc5e8467974123e28da1a1ae258ca2a3`
- `evals/v3/density_reading/cases/density_reading_novel_04.json` SHA256 `ae2cf85eb1000308e8f4b680a8a3564c7ec7001568e74f11c46e71667de2f5f8`
- `evals/v3/density_reading/cases/density_reading_novel_05.json` SHA256 `eccfd7ba249a0c211b22bc03b828d1ff1d1750fcc50c49f2d3021d70b1b191ae`
- `evals/v3/density_reading/cases/density_reading_novel_06.json` SHA256 `0afaced11a56005efd4b9ecff8f323c82ee0a7b314153ecae68d3c376f5ae93b`
