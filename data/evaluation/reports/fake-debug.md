# Day 7 诊断评价报告

模式：fake；分组：debug；模型：fixed_fake_no_api
Prompt：day7-v1；金标准状态：pending_or_fake_not_gold_standard

Fake 报告只检查工具、校验、修复和报告流程。未由用户复核的预期不构成人工金标准。

首次结构合法率：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
最终结构合法率：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
修复案例结构合法率：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
正式行动一致率：None
草案预期一致率（暂定）：{'numerator': 3, 'denominator': 8, 'rate': 0.375}
错误放行数（草案预期、推进守卫模拟）：0

| 案例 | 建议 | 守卫路由 | 首次/最终结构 | 输出修复 | 耗时ms |
|---|---|---|---|---|---|
| advance_01 | remediate | remediate | True/True | 1 | 8.704 |
| advance_02 | remediate | remediate | True/True | 1 | 6.352 |
| critical_01 | remediate | remediate | True/True | 1 | 6.968 |
| insufficient_01 | remediate | remediate | True/True | 1 | 8.498 |
| prerequisite_01 | remediate | remediate | True/True | 1 | 7.525 |
| prerequisite_02 | remediate | remediate | True/True | 1 | 6.346 |
| remediate_01 | remediate | remediate | True/True | 1 | 8.046 |
| remediate_02 | remediate | remediate | True/True | 1 | 7.069 |

完整工具选择、证据引用、每次最终输出的结构/业务结果、请求数及可获得 usage 见同名 JSON。
逐例人工复核：理由是否由答案支持、工具是否合理、证据是否足以支持行动、分歧及下一步修订。
首次结构率按首次收到的模型输出计算（网络失败不构成输出）；最终结构率不等于业务通过率。
