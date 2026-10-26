# 第四主题 SQL 实际课程与固定参考评价

执行于2026-10-22至23，Asia/Shanghai。全部使用现有通用Planner/Tutor/测评/Diagnosis及Graph；没有SQL执行器、SQL专用Graph或学科分支。参考范围及六例预期已由用户明确批准，课程计划确认由合成验收操作员执行，不冒称用户逐计划批准。

> 更新：下文的“继续/待执行”保留当时阶段记录；已完成结果见末节。候选03的管理配置路线已通过，但普通用户入口缺口随后触发新的通用修复，当前候选须重新验证。

## 两类证据

固定六例novel-v1真实评价：6/6行动/状态符合，5个有分数案例误差0；16次请求，0错误推进。9分但明确“永久删除”的关键错误被拦，未知0分补弱，实际资料冲突needs_review。独立AI逐例核引文，不等于新增人工金标准。原输出与报告在work/day13-20261022/novel-v1，六例内容不等于实际学习过程已通过。

实际课程第一版sql-workflow出现量规过严：3个普通整项全为critical，零分动作虽正确，却把“不会”写成关键错误且形成必须满分的潜在误拒。旧卷、评分、日志完整保留，独立内容审查阻断；不能拿固定六例成绩掩盖它。

## 第二版课程（继续验收）

新隔离项目v3_1117a458471f4259b3ead1ebe85d9120，两节点：node_sql_select_projection → node_sql_where_filter。真实Planner先给4节点，经普通adjust_plan合并为2节点、40分钟；冻结0.8策略及资料版本。首卷8分项均critical=false，未知作答graded0/6、remediate、0完成，无关键错误标签；补弱Tutor使用本轮真实错答。新卷3题9个普通分项，独立审查通过，旧assessment关联正确。首节点正确回答后通过并推进，第二节点仍待完成和审查。

## 私有资料绑定的真实边界

新增curriculum_private.md解释required与critical不同，独立语义预审通过；但普通PreparationService确认只冻结目标引用的teaching片段，未自动把上传的私有资料绑定到assessment/grading。因此本次课程合格新卷不能归因于新增私有文件，不能声称网页已经具备私有标准绑定。现有Repository.freeze_plan(material_links=...)可显式配置用途绑定，若单独演示，必须核实际模型输入，不能只看上传成功。

## 仍待执行

第二节点通过、同项目重启/等待身份不变、干净依赖环境实际启动及隔离恢复继续。最新过程/请求预占/完成记录：work/day13-20261022/sql-workflow-v2/timeline.jsonl；原始模型输入输出raw.jsonl含合成私有内容，仅本地保留。运行时核心未改；没有将模型生成量规保证为永不出错，内容审查仍是边界。


## 显式绑定配置复验（后续执行）

仅有上传不能让私有参考进入模型。新增数据配置configs/v3/novel/sql_material_links.json，使用既有V3Repository.freeze_plan(material_links=...)管理接口；前置检查档案确认hash、当前资料可学习性、revision与pending_input。新项目v3_2673196fa4e6442a9a058be8acbd7d39真实Planner最初给3节点，经普通调整合并成2节点45分钟，再由验收操作员明确管理确认。准备Graph仍保留旧等待checkpoint，不把这条管理调用冒称网页确认完成；后续走独立Learning Graph读取冻结事实。该差异与网页未暴露私有绑定的限制不能省略。

24条私有绑定实际入库（assessment12/grading12），冻结snapshot含sql-curriculum-private正确hash。首卷模型输入每目标包含通用段与SELECT段，Tutor仅teaching，公开视图无私有来源、answer_key或rubric结构。首卷3题12分10分项均critical=false，独立内容审查通过。真实未知作答graded0/12、普通目标不足补弱、0完成；新的重测与第二节点继续实测。证据work/day13-20261023/sql-bound-workflow，不能继承前一课程或固定六例的内容批准。

## 候选03两条完整课程与恢复的最终事实

第二版未绑定根课程最终完成SELECT10/10、WHERE9/9，两节点唯一完成、三轮评价、累计17次预占；内容获独立审查。新私有文件实际未绑定，仍不能把这次随机更好的量规归因于该文件。其隔离恢复分支技术恢复通过，但新WHERE三个普通项再次被标critical，内容仍阻断。两者结论分别保存。

显式绑定根课程最终完成未知0/12→新SELECT12/12→WHERE12/12，两节点唯一完成、三条唯一迁移，累计19次预占（Planner2+逻辑任务17）。其中两个任务各一次APITimeoutError后网络重试，均使用原共享预算；没有输出修复。模型输入真实包含选定私有参考，Tutor与公开投影保持隔离。根课程获独立内容批准。

匹配代码的显式绑定恢复包实际恢复后，原等待SELECT身份、题面、私有快照、任务及累计8次预占不变，读取0模型。恢复后SELECT12/12，新WHERE12/12且12普通分项均非critical，最终两节点各唯一完成、三条唯一迁移，累计8+9=17次预占。来源块/锚点/历史/私有用途与守卫经独立重算审查通过。实际证据：`work/day13-20261023/bound-restored-result.json`、`bound-restored-read-evidence.json`和独立审查报告。原库、原管理课程、恢复包均未被该分支修改。

## 普通用户入口修复后的开发回归

上述管理路线不满足普通网页的完整交互，因此完成`reference_bindings.py`、Preparation正常确认与前端用途选择修复，详见[NORMAL_PRIVATE_BINDING_RESULTS.md](NORMAL_PRIVATE_BINDING_RESULTS.md)。6个真实浏览器Fake场景通过；新的真实SQL开发回归位于`work/day13-20261023/sql-normal-product`，走普通Preparation resume/private_references→Graph冻结到END，不调用freeze_config。当前已完成未知0/12→补弱→新卷12/12→进入依赖WHERE。后续结果另追加。

普通入口回归已完成并获独立内容批准：三卷各一题12分、三个普通项均critical=false，未知0/12补弱→新SELECT12/12→WHERE12/12，两节点各唯一完成、三assessment各唯一transition，16次真实请求（Planner2+learning14），最大单操作4，0网络重试/输出修复。28条private链接（assessment14/grading14）实际进入quiz/grade，准备Graph已正常结束，无管理路径遗留等待点。69来源块、11个原始答案锚点、三个守卫及公开隔离经独立核对。完整依据见独立审查。

本路线没有单独实测所有部分答案、18<=age变体或每条参考子项都完整转录为量规，不能扩大当前证据范围。SQL已用于本轮修复，后续只能称回归主题；不能把它再次算作修复后新候选的未调试主题。V3.0仍待候选04验证和新主题验收。
