# Day 7 诊断评价报告

模式：real；分组：debug；模型：deepseek-flash
Prompt：day7-v1；金标准状态：pending_or_fake_not_gold_standard

Fake 报告只检查工具、校验、修复和报告流程。未由用户复核的预期不构成人工金标准。

首次结构合法率：{'numerator': 7, 'denominator': 8, 'rate': 0.875}
最终结构合法率：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
修复案例结构合法率：{'numerator': 1, 'denominator': 1, 'rate': 1.0}
正式行动一致率：None
草案预期一致率（暂定）：{'numerator': 6, 'denominator': 8, 'rate': 0.75}
错误放行数（草案预期、推进守卫模拟）：0

| 案例 | 建议 | 守卫路由 | 首次/最终结构 | 输出修复 | 耗时ms |
|---|---|---|---|---|---|
| advance_01 | advance | advance | True/True | 0 | 6387.324 |
| advance_02 | advance | advance | True/True | 0 | 8252.783 |
| critical_01 | remediate | remediate | False/True | 1 | 14314.826 |
| insufficient_01 | collect_more_evidence | collect_more_evidence | True/True | 0 | 9920.183 |
| prerequisite_01 | remediate | remediate | True/True | 0 | 13411.367 |
| prerequisite_02 | remediate | remediate | True/True | 0 | 14222.92 |
| remediate_01 | remediate | remediate | True/True | 0 | 13643.007 |
| remediate_02 | remediate | remediate | True/True | 0 | 12218.562 |

完整工具选择、证据引用、每次最终输出的结构/业务结果、请求数及可获得 usage 见同名 JSON。
逐例人工复核：理由是否由答案支持、工具是否合理、证据是否足以支持行动、分歧及下一步修订。
首次结构率按首次收到的模型输出计算（网络失败不构成输出）；最终结构率不等于业务通过率。
