# Day 7 诊断评价报告

模式：real；分组：holdout；模型：deepseek-flash
Prompt：day7-v2-prerequisite-evidence；金标准状态：user_reviewed_after_model_run

真实模型结果；未由用户复核的预期仅用于暂定比较。
未由用户复核的预期不构成人工金标准。

首次结构合法率：{'numerator': 4, 'denominator': 4, 'rate': 1.0}
最终结构合法率：{'numerator': 4, 'denominator': 4, 'rate': 1.0}
修复案例结构合法率：{'numerator': 0, 'denominator': 0, 'rate': None}
正式行动一致率：{'numerator': 4, 'denominator': 4, 'rate': 1.0}
草案预期一致率（暂定）：{'numerator': 4, 'denominator': 4, 'rate': 1.0}
错误放行数（草案预期、推进守卫模拟）：0
指定节点的必要工具查询完成率：{'numerator': 0, 'denominator': 0, 'rate': None}

| 案例 | 建议 | 守卫路由 | 首次/最终结构 | 输出修复 | 耗时ms |
|---|---|---|---|---|---|
| advance_03 | advance | advance | True/True | 0 | 7326.307 |
| critical_02 | remediate | remediate | True/True | 0 | 15379.913 |
| insufficient_02 | collect_more_evidence | collect_more_evidence | True/True | 0 | 17675.057 |
| remediate_03 | remediate | remediate | True/True | 0 | 16475.482 |

完整工具选择、证据引用、每次最终输出的结构/业务结果、请求数及可获得 usage 见同名 JSON。
逐例人工复核：理由是否由答案支持、工具是否合理、证据是否足以支持行动、分歧及下一步修订。
首次结构率按首次收到的模型输出计算（网络失败不构成输出）；最终结构率不等于业务通过率。

用户已确认12例预期（2026-10-11 17:45:24 +08:00）。模型输出生成早于确认；本报告复用原始输出，教学标签未修改，没有再次调用模型。

正式字段表示与用户确认预期的描述性比较，不声称预先登记的盲测。逐例理由/工具/证据的教学合理性仍可由用户继续复核。
