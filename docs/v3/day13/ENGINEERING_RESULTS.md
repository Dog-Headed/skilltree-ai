# Day13 当前候选工程回归

这份记录只证明Fake/Mock工程行为，不替代真实模型内容评价或最终发布验收。

2026-10-22，当前第三次冻结候选：**892 passed，2 warnings，572.27秒**。Python3.11，原有测试参数和故障超时未放宽。警告为websockets与uvicorn的弃用提示，无失败。

- 完整日志：work/day13-candidate-v9-regression-20261022.log。
- 机器记录：同名.json，保存实际命令、开始/结束时间、退出码、源码逐文件指纹、原V2双库与V3三库main/非空WAL前后指纹。
- 退出码0；运行前后runtime_code_unchanged=true、original_runtime_files_unchanged=true。
- 本轮额外覆盖：显式真实历史评分不被改0分、附件标签隔离、全套输入预检、题号/字段修订拒绝、真实补充资料传入、冲突复核即使候选满分和advance也不推进、当前评价能力由代码提供而非历史资料声明。

旧记录完整保留：早期875项通过；后续891项通过但运行期间有源码调整，runtime_code_unchanged=false，不能把它当当前冻结版本的最终证据；更早872通过/1超时失败及原条件隔离复跑也保留。未删除失败、未只选有利结果。

当前仍需真实最终独立集、第四主题、干净环境与正式恢复演示。工程全通过不能证明模型永远不会误判，不能单独宣布V3.0完成。


## 新主题资料接入后的工程复验

新增第四资料包后，历史 Day10 检查器与离线演示原先枚举全部资料目录，错误地把新主题当成旧三科案例。两处历史工具改为只检查其原有声明的三科；新增回归验证后来的独立资料包不被历史检查器收编，原三包缺失或篡改仍拒绝。没有修改通用学习引擎、Graph或学科路由。

第一次资料回归2失败/102通过，修复检查器后105通过；随后全量发现离线演示同类问题，主动中止并保留部分日志，修复后相关106项通过。最新中间全量为893 passed、2 warnings、596.78秒（work/day13-novel-historical-tools-final-regression-20261022.log）。原V2/V3数据前后不变；期间仅SQL配置的用户批准元数据被写入，故该次runtime_code_unchanged=false，不能声称所有文件在运行期不变。

新的稳定最终全量已启动：work/day13-release-final-regression-20261022.log；结果另行追加，未完成前不计通过。


## 稳定最终全量（已完成）

893 passed、2 warnings、571.04秒，退出码0。机器记录：work/day13-release-final-regression-20261022.json。运行期app/config/根运行脚本指纹不变，原V2双库与V3三库main/非空WAL指纹不变。范围是工程行为；SQL后来补充的课程资料须由实际课程独立复验，不凭全量测试证明内容质量。


## 显式新主题配置后的最终复验

2026-10-23最终全量893 passed、2 warnings、604.74秒，退出码0。work/day13-final-configured-regression-20261023.json确认运行期app/config/根运行脚本与原V2/V3库main/非空WAL均不变。未放宽超时或断言。上述新资料绑定配置已存在于此次运行前；管理配置的实际输入与内容正确性另由真实流程和独立审查证明。

在按requirements重新安装、关闭system/user site的新venv内，另跑恢复工具、通用评价器、学习恢复、Diagnosis四组85项，全部通过（64.23秒，work/day13-20261023/clean-engineering-regression.log）。它们与893有重叠，不相加成978。没有因为仅文档更新而重复整套测试。

## 普通产品绑定修复期间的全量（不能当成最终冻结验证）

`work/day13-normal-binding-full-20261023.json`：909通过、1失败、2警告、661.18秒。失败是旧Day10离线Fake演示没有明确排除私有参考，被新正常契约拒绝；已仅修改演示显式exclude，其隔离测试通过。原失败保留。

`work/day13-normal-binding-final-20261023.json`：913通过、2警告、623.33秒，退出码0；原V2/V3数据前后哈希一致。但运行期间Diagnosis因真实开发集身份错误更新到Prompt v6，`runtime_code_unchanged=false`，变化仅`app/v3/diagnosis.py`。因此这是修复期间工程回归，不能冒称最终匹配冻结候选的稳定全量。最终版本必要全量仍需另记。

## 候选04稳定核心全量（已完成）

`work/day13-candidate04-stable-regression-20261023.json`：913通过、2依赖弃用警告、623.94秒，退出码0。运行期间app/config/根运行脚本指纹完全一致，原V2两库与V3三库main/非空WAL指纹一致。包含普通private确认/隔离/旧输入/超限修正、真实硬退出恢复、明确的独立集复验来源、新身份提示及既有Day6至Day12回归。

这是候选04核心和当时已存在资料配置的工程全量；后续仅新增未调试主题资料/配置/案例时，须另核新材料哈希、能力、契约、正常流程及恢复，不用本次数字冒充其真实内容评价。若通用代码再改，必须重新回归并更新候选，不承继本次稳定结论。


## 最终资料及新环境补充验证（2026-10-24）

仅新增密度资料配置、用户批准元数据及同义资料澄清，冻结04的116个核心指纹仍完全一致。资料相关47项通过（4.48秒）；无需仅因文档变化重复已稳定的913全量。

匹配新包从零安装的新venv运行tests/test_day13_recovery.py、test_v3_evaluators.py、test_v3_learning_recovery.py、test_v3_diagnosis.py、test_v3_reference_bindings.py、test_day13_diagnosis_repair.py，104 passed、1依赖警告、78.73秒（总进程80.516秒），退出0。证据work/day13-20261024/clean-v2-engineering-regression.log/.json；无真实模型配置，Fake/Mock工程行为，不能与913相加。

另在真实恢复完成产品上运行1440/390页面纯GET、双次刷新检查：两后端passed可见、无水平溢出、无私有标识/答案键/量规字段进入DOM，0写请求/0模型。截图经视觉检查；最初动画帧截图保留，稳定截图通过减少动画/回顶采集，产品代码未改。目录work/day13-20261024/final-browser-stable。

最后仅修Git包装属性保留冻结字节（* -text），不改变116核心或实际输入。353文件在新隔离Git中core.autocrlf=true add/checkout-index逐hash相同；新venv从导出代码实际初始化空三库并读四API均200、0模型。原Git index未改，没有commit/push。见git-full-export-final-evidence.json；这项是包装可复现性验证，不能加到pytest数量或真实评价例数。
