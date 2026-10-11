# Day 7 诊断评价报告

模式：real；分组：debug；模型：deepseek-flash
Prompt：day7-v2-prerequisite-evidence；金标准状态：pending_or_fake_not_gold_standard

真实模型结果；未由用户复核的预期仅用于暂定比较。
未由用户复核的预期不构成人工金标准。

首次结构合法率：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
最终结构合法率：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
修复案例结构合法率：{'numerator': 0, 'denominator': 0, 'rate': None}
正式行动一致率：None
草案预期一致率（暂定）：{'numerator': 8, 'denominator': 8, 'rate': 1.0}
错误放行数（草案预期、推进守卫模拟）：0
指定节点的必要工具查询完成率：{'numerator': 2, 'denominator': 2, 'rate': 1.0}

| 案例 | 建议 | 守卫路由 | 首次/最终结构 | 输出修复 | 耗时ms |
|---|---|---|---|---|---|
| advance_01 | advance | advance | True/True | 0 | 7507.666 |
| advance_02 | advance | advance | True/True | 0 | 7561.071 |
| critical_01 | remediate | remediate | True/True | 0 | 10891.404 |
| insufficient_01 | collect_more_evidence | collect_more_evidence | True/True | 0 | 14852.563 |
| prerequisite_01 | revisit_prerequisite | revisit_prerequisite | True/True | 0 | 14268.044 |
| prerequisite_02 | revisit_prerequisite | revisit_prerequisite | True/True | 0 | 12745.258 |
| remediate_01 | remediate | remediate | True/True | 0 | 15921.1 |
| remediate_02 | remediate | remediate | True/True | 0 | 14563.625 |

完整工具选择、证据引用、每次最终输出的结构/业务结果、请求数及可获得 usage 见同名 JSON。
逐例人工复核：理由是否由答案支持、工具是否合理、证据是否足以支持行动、分歧及下一步修订。
首次结构率按首次收到的模型输出计算（网络失败不构成输出）；最终结构率不等于业务通过率。
