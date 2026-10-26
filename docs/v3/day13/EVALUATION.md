# Day 13 评价的边界与复现方法

评价入口是仓库根目录的 `day13_evaluate.py`。真实模型测试与 Fake 工程测试分开保存；没有真实调用、人工参考批准或独立语义审查的项目，不能标为内容质量通过。

## 数据和人工标准

Day 10 三科原始资料、manifest 和 36 个案例保留原版本。Day 13 在 `evals/v3/day13/development_standards.json` 保存经用户批准的开发标准与输入修订，不覆盖原案例的 `pending_user_review` 历史元数据。批准范围和原话见 `USER_REVIEW_RECORD.md`，原始独立审阅见 `DEV_REFERENCE_REVIEW.md`。

模型只能接收档案、当前题目、冻结量规、真实资料片段、学生实际作答及授权历史。`human_expectation`、`scenario_tags`、期望行动和得分中心不能跨过模型输入边界。参考答案属于评分所需的冻结标准；期望学生得分、行动标签不是评分输入。案例中的历史是明确标注的人工构造夹具，不冒充真实用户数据。

每科开发 8 例分为 6 个普通评分案例、1 个候选评分审查和 1 个原题有效性审查。学生在有效题上漏步骤属于 graded 低分；不能通过全部拒评来取得零错误推进。05 的错误候选必须作为候选输入接受审查，06 的原无效题与坏答案键必须和题外审查说明分开。

**候选/原题审查是显式独立服务 `app/v3/quality_review.py`，普通学习 Graph 不自动运行该服务。** 这些案例不能被描述成生产 Graph 多了一层自动语义保障。普通模型评分仍可能误判，确定性守卫验证的是身份、分数、证据、目标与策略约束。

## 顺序和命令

使用 Python 3.11，并按 `requirements.txt` 安装依赖。真实调用需要单独配置 `.env` 中的模型三项参数，不能提交密钥。每次输出目录必须是新目录，以保留失败运行及原输出。

```powershell
.\.venv\Scripts\python.exe day13_evaluate.py run --split debug --mode real --workers 3 --output work/day13/dev-001
.\.venv\Scripts\python.exe day13_evaluate.py freeze --development-report work/day13/dev-001/report.json --output work/day13/candidate.json
```

冻结只接受完整24例的真实开发报告、每科自动门槛通过且独立语义审查或用户复核通过，报告对应的实际代码和模型配置必须仍然一致。原报告不覆盖；派生reviewed-report另记原报告与审阅文件哈希。保留标准需另行人工批准，不能借用开发集批准。

本轮原12例在预检和真实失败后已降为曝光验证；新12例登记在独立目录。两者分别运行，不能把原12例重新改名当未见集：

```powershell
.\.venv\Scripts\python.exe day13_evaluate.py run --split holdout --standards evals/v3/day13/exposed_standards.json --freeze work/day13/candidate.json --output work/day13/exposed-001
.\.venv\Scripts\python.exe day13_evaluate.py run --split holdout --case-root evals/v3/day13/final_suite --standards evals/v3/day13/final_standards.json --freeze work/day13/candidate.json --output work/day13/final-001
```

保留集后才选择第四主题，先编写资料、配置和至少六类参考案例并完成标准复核；通用 runner 支持额外资料包目录和独立标准文件：

```powershell
.\.venv\Scripts\python.exe day13_evaluate.py run --split novel --subjects TOPIC_PACK --standards PATH_TO_APPROVED_STANDARDS --freeze work/day13/candidate.json --prior-holdout work/day13/final-001/reviewed-report.json --output work/day13/novel-001
```

上面第四主题命令是参数说明，不代表已有主题通过。若保留集用于修复，它不再是未见集；需要另建独立案例。第四主题促使核心代码变化时同样需要复验，再换未调试主题。

## 每科独立报告

### 修复后复跑原独立集

如果修复来自其它开发/工程数据，没有用该独立集调参，已批准的相同案例与量规可以用于冻结后复验；它不是新的首次未见结果。命令使用`--revalidate PATH_TO_ORIGINAL_REVIEWED_REPORT`，逐字校验原案例哈希、标准哈希和已完成独立审查。新报告角色为`independent_final_revalidation`，附原报告哈希及`first_unseen_execution=false`。之后新主题入口接受这一明确标注且通过分科门槛/独立审查的匹配候选复验。原首次独立报告不覆盖；若据复验失败修改实现，案例转为曝光历史，最终验证必须新增独立案例。

这一入口不允许把原exposed12重新标为独立，不改变答案、量规或质量门槛，也不替用户批准新的主题参考。

预先批准的门槛：10 分制平均绝对误差不超过 1 分，单例不超过 2 分；错误推进、关键错误推进、完整正确误拒、普通可评分题的意外拒评、技术失败均为 0，行动和状态全部符合标准。小样本只说明有限案例，不能外推总体准确率或掌握概率。

运行目录保存：

- `run_manifest.json`：代码、协议、策略/资料/案例哈希，模型身份、Prompt 版本、基线 commit；实际工作树摘要比只记 HEAD 更精确。
- `cases/*/raw.jsonl`：真实请求输入、原返回、工具选择及损坏调用、provider usage、延迟和错误类型；不保存 API 密钥。
- `cases/*/result.json`：经过验证的评分、诊断和有效行动，持久化逻辑任务/请求预占、结构合法情况、得分误差和拒评分母。
- `runtime/`：隔离业务库及 Checkpoint，普通重试不会返还或刷新额度。
- `report.json`、`report.md`：分科结果。独立语义审查需另附逐例依据；仅“引文确实存在”不足以批准。

`structure_legality` 描述每个逻辑阶段首个/最后收到的输出是否符合其协议。汇总分母混合了工具选择AIMessage与最终评分/诊断/审查；一次工具选择草稿JSON不等于最终诊断JSON，不能把其首次不符记成最终输出修复。正式契约首末合法数和持久化output_repairs需分别核对raw及tasks。结构合法与内容正确率分开；预算耗尽而未完成任务仍计技术失败。每个逻辑任务最多3次请求，单个评价操作默认最多12次；工具执行数单独限制。

费用只记录提供者实际返回的 usage。未配置并验证价格来源时，金额为 null 并说明原因，不根据猜测单价估算账单。原始评价材料含私有题库和学生记录，应保留在已忽略的本机 `work/`，发布报告只摘录必要的合成案例证据。

## 与最终交付的关系

本 runner 测固定、经审阅案例的真实评价器、Diagnosis 和守卫。它不证明 Planner/Tutor 内容质量、完整浏览器学习体验、第四主题两节点重启或恢复包实际可用。这些须在对应后续阶段另行运行并提供证据。恢复工具见 `RECOVERY.md`。未完成全部关键门槛前，不宣布 V3.0 完成。
