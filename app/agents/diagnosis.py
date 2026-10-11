from app.db.repository import repository_for_state, get_assessment_for_state
from app.state import LearningState
import json
from time import perf_counter
from pydantic import ValidationError
from langchain_core.exceptions import OutputParserException
from typing import Any

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.services.llm import (
    get_llm, ModelCallBudget, ModelOutputValidationError, invoke_with_shared_budget,
)
from app.services.observability import log_event, observed_node

from app.tools.executor import (
    LearningHistoryArgs,
    NodeLookupArgs,
    ToolExecutionContext,
    execute_tool_call,
)
from app.models.schemas import (
    DiagnosisResult,
    get_prerequisite_closure,
    validate_diagnosis_against_context,
)


@observed_node
def diagnosis_node(
    state: LearningState,
):
    assessment_id = state.get(
        "assessment_id"
    )

    if not assessment_id:
        raise ValueError(
            "Diagnosis 缺少 assessment_id"
        )

    # ================================================
    # 第一查：有没有已经落库的 Diagnosis
    # ================================================

    with repository_for_state(state) as repo:

        assessment = get_assessment_for_state(repo, state)

        if assessment is None:
            raise ValueError(
                "找不到当前测验"
            )

        existing = assessment[
            "diagnosis"
        ]

        if existing is not None:
            return {
                "diagnosis": existing
            }

    # ================================================
    # 没有才调用真实 Diagnosis Agent
    # ================================================

    diagnosis = run_real_diagnosis(
        state
    )

    diagnosis_dict = (
        diagnosis.model_dump()
    )

    # ================================================
    # 第二步：写库固定
    # ================================================

    with repository_for_state(state) as repo:

        saved = (
            repo.save_diagnosis_if_absent(
                assessment_id=(
                    assessment_id
                ),
                diagnosis=(
                    diagnosis_dict
                ),
            )
        )

    return {
        "diagnosis": (
            saved["diagnosis"]
        )
    }


def fake_diagnosis_node(state: LearningState):
    score_summary = state.get("score_summary", {})
    evaluation = state.get("evaluation", {})

    percentage = score_summary.get(
        "percentage",
        0,
    )

    question_results = evaluation.get(
        "question_results",
        [],
    )

    error_tags = []

    for result in question_results:
        error_tags.extend(
            result.get("error_tags", [])
        )

    # 去重
    error_tags = list(dict.fromkeys(error_tags))

    # =========================
    # 低于 80：补弱
    # =========================

    if percentage < 80:
        return {
            "diagnosis": {
                "weak_points": error_tags or [
                    "当前知识点掌握不充分"
                ],
                "recommended_action": "remediate",
                "reason": (
                    f"当前得分 {percentage:.1f}，"
                    "未达到 80 分通过标准。"
                ),
            }
        }

    # =========================
    # 达到 80：建议通过
    # =========================

    return {
        "diagnosis": {
            "weak_points": [],
            "recommended_action": "advance",
            "reason": (
                f"当前得分 {percentage:.1f}，"
                "建议进入下一学习节点。"
            ),
        }
    }


DIAGNOSIS_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_learning_history",
            "description": (
                "查询指定学习节点最近的学习历史。"
                "当你需要判断当前错误是否反复出现、"
                "是否属于长期薄弱点时使用。"
                "最多查询最近 3 条。"
            ),
            "parameters": (
                LearningHistoryArgs.model_json_schema()
            ),
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_prerequisite_status",
            "description": (
                "查询指定节点直接前置节点的完成状态。"
                "当你怀疑当前问题来自前置知识缺失时使用。"
            ),
            "parameters": (
                NodeLookupArgs.model_json_schema()
            ),
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_node_material",
            "description": (
                "读取指定节点预先登记的短材料和学习目标。"
                "当你需要确认该节点应该掌握什么内容时使用。"
            ),
            "parameters": (
                NodeLookupArgs.model_json_schema()
            ),
        },
    },
]


def build_tool_execution_context(
    state: dict[str, Any],
) -> ToolExecutionContext:

    project_id = state.get("project_id")

    if not isinstance(project_id, str) or not project_id:
        raise ValueError(
            "Diagnosis Tool Loop 缺少合法 project_id"
        )

    tree = state.get("tree")

    if not isinstance(tree, list) or not tree:
        raise ValueError(
            "Diagnosis Tool Loop 缺少合法 tree"
        )

    allowed_node_ids = set()

    for node in tree:
        if not isinstance(node, dict):
            raise ValueError(
                "tree 中的节点必须是字典"
            )

        node_id = node.get("id")

        if not isinstance(node_id, str) or not node_id:
            raise ValueError(
                "tree 中存在非法 node_id"
            )

        allowed_node_ids.add(node_id)

    return ToolExecutionContext(
        project_id=project_id,
        allowed_node_ids=allowed_node_ids,
        current_assessment_id=(
            state.get(
                "assessment_id"
            )
        ),
        learning_db_path=state.get("learning_db_path"),
    )


DIAGNOSIS_TOOL_SYSTEM_PROMPT = """
你是学习诊断系统中的“证据收集 Agent”。

你当前的任务不是直接输出最终 DiagnosisResult，
而是判断现有测评证据是否足够，
并在必要时自主选择工具获取额外证据。

可用工具：

1. get_learning_history
用于确认类似错误过去是否反复出现，可以查询当前节点或合法前置节点。

2. get_prerequisite_status
用于确认当前问题是否可能来自未掌握的前置节点。

3. get_node_material
用于确认节点学习目标和人工登记的核心材料。

要求：

- 不要机械调用全部工具。
- 只在确实需要更多证据时调用。
- 已有证据足够时，可以不调用任何工具。
- 先对照当前节点与前置节点的目标，判断错误属于当前技能还是前置概念。
- 若答案暴露赋值与比较、元素与下标等前置概念混淆，优先查询对应前置节点的学习历史；只查当前节点历史不能排除前置问题。
- 前置完成状态仅表示过去通过某次测评，不能证明当前没有薄弱点，不能用 completed 排除前置知识问题。
- 工具预算有限时，优先查询与具体错误相关的节点，避免先把额度用在当前节点的历史、状态和材料全套查询上。
- 工具失败并不代表“没有数据”，必须区分失败和空结果。
- 不得猜测工具返回内容。
- 不得伪造 evidence_id。
- 不得请求未提供的工具。
- 不要试图提供 project_id。
- 工具阶段最多 2 轮，总调用预算最多 3 次。
"""


MAX_TOOL_ROUNDS = 2
MAX_TOOL_CALLS = 3


@observed_node
def run_diagnosis_tool_loop(
    state: dict[str, Any],
    *,
    llm=None,
) -> dict[str, Any]:
    """
    Diagnosis 的有界 Tool Calling 循环。

    本函数只负责收集证据。
    暂时不生成最终 DiagnosisResult。
    """

    context = build_tool_execution_context(
        state
    )

    base_llm = llm or get_llm()

    tool_llm = base_llm.bind_tools(
        DIAGNOSIS_TOOL_SCHEMAS
    )

    current_node_id = state.get(
        "current_node_id"
    )

    evaluation = state.get(
        "evaluation",
        {}
    )

    score_summary = state.get(
        "score_summary",
        {}
    )

    # ========================================================
    # Diagnosis 使用自己的局部消息列表
    # 不写入 tutor_messages
    # ========================================================

    messages = [
        SystemMessage(
            content=DIAGNOSIS_TOOL_SYSTEM_PROMPT
        ),

        HumanMessage(
            content=(
                "请根据下面的当前测评信息判断是否需要"
                "额外查询证据。\n\n"
                f"当前节点：{current_node_id}\n\n"
                "当前节点目标与依赖：\n"
                f"{json.dumps(next((node for node in state['tree'] if node['id'] == current_node_id), {}), ensure_ascii=False)}\n\n"
                "可查询的前置节点及目标：\n"
                f"{json.dumps([node for node in state['tree'] if node['id'] in get_prerequisite_closure(state['tree'], current_node_id)], ensure_ascii=False)}\n\n"
                "当前评分汇总：\n"
                f"{json.dumps(score_summary, ensure_ascii=False)}"
                "\n\n"
                "当前逐题评价：\n"
                f"{json.dumps(evaluation, ensure_ascii=False)}"
            )
        ),
    ]

    tool_logs = []

    tool_call_count = 0
    tool_round_count = 0

    stopped_reason = "model_finished"

    # ========================================================
    # 最多两轮 Tool Calling
    # ========================================================

    for round_index in range(
        MAX_TOOL_ROUNDS
    ):
        def select_tools(repair_context):
            request_messages = list(messages)
            if repair_context is not None:
                request_messages.append(HumanMessage(content=(
                    "工具选择输出未通过校验：" + repair_context.error_message
                    + "。请返回合法的工具调用消息。"
                )))
            try:
                return tool_llm.invoke(request_messages)
            except (ValidationError, OutputParserException) as exc:
                raise ModelOutputValidationError(f"工具选择输出解析失败：{exc}") from exc

        def validate_selection(raw):
            if not isinstance(raw, AIMessage):
                raise ModelOutputValidationError("Diagnosis 模型必须返回 AIMessage")
            if raw.invalid_tool_calls:
                # 适配器会把无法解析的 arguments 放到这里，tool_calls 可能是空列表。
                # 整条候选消息先拒绝，避免漏掉查询或执行其中部分合法调用。
                raise ModelOutputValidationError(
                    "工具调用参数 JSON 解析失败：invalid_tool_calls 中存在 "
                    f"{len(raw.invalid_tool_calls)} 个损坏调用。"
                    "请用完整合法的 JSON 对象重新生成工具参数并返回完整工具调用。"
                )
            if any(not call.get("id") for call in raw.tool_calls):
                raise ModelOutputValidationError("tool_call 缺少 id")
            return raw

        # 一次工具选择有自己的 HTTP 预算；它不增加工具轮数或执行次数。
        ai_message = invoke_with_shared_budget(
            invoke_fn=select_tools, validate_fn=validate_selection,
            operation="diagnosis_tool_selection",
        )

        messages.append(ai_message)

        tool_calls = (
            ai_message.tool_calls or []
        )

        # 模型认为证据已经够了
        if not tool_calls:
            stopped_reason = (
                "model_finished"
            )
            break

        tool_round_count += 1

        # ====================================================
        # 逐个处理模型提出的调用申请
        # ====================================================

        for tool_call in tool_calls:
            tool_started = perf_counter()
            tool_name = tool_call.get(
                "name"
            )

            tool_args = tool_call.get(
                "args",
                {},
            )

            tool_call_id = tool_call.get(
                "id"
            )

            if not tool_call_id:
                raise ValueError(
                    "tool_call 缺少 id"
                )

            # ================================================
            # 调用预算已经耗尽
            # ================================================

            if (
                tool_call_count
                >= MAX_TOOL_CALLS
            ):
                result = {
                    "ok": False,
                    "tool": tool_name,
                    "error_type": (
                        "tool_limit_exceeded"
                    ),
                    "error": (
                        "Diagnosis 工具调用总数"
                        "不能超过 3 次"
                    ),
                }

                executed = False

            else:
                # ============================================
                # 每一个调用申请都会消耗预算
                #
                # 即使是非法调用也消耗，
                # 防止模型靠错误请求无限尝试。
                # ============================================

                tool_call_count += 1

                result = execute_tool_call(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    context=context,
                )

                executed = True

            log_event("tool_execution", state=state,
                      tool=tool_name if tool_name in {s["function"]["name"] for s in DIAGNOSIS_TOOL_SCHEMAS} else "unknown",
                      elapsed_ms=round((perf_counter() - tool_started) * 1000, 3),
                      error_type=result.get("error_type"),
                      outcome="executed" if executed else "blocked")

            # ================================================
            # 关键：
            # 用同一个 tool_call_id 返回结果
            # ================================================

            tool_message = ToolMessage(
                content=json.dumps(
                    result,
                    ensure_ascii=False,
                ),
                tool_call_id=tool_call_id,
            )

            messages.append(
                tool_message
            )

            tool_logs.append(
                {
                    "round": (
                        round_index + 1
                    ),
                    "tool_call_id": (
                        tool_call_id
                    ),
                    "tool_name": (
                        tool_name
                    ),
                    "tool_args": (
                        tool_args
                    ),
                    "result": result,
                    "executed": executed,
                }
            )

        # 第二轮 Tool 已经处理完
        if (
            tool_round_count
            >= MAX_TOOL_ROUNDS
        ):
            stopped_reason = (
                "max_tool_rounds"
            )

    return {
        "messages": messages,
        "tool_logs": tool_logs,
        "tool_call_count": (
            tool_call_count
        ),
        "tool_round_count": (
            tool_round_count
        ),
        "stopped_reason": (
            stopped_reason
        ),
    }


def build_current_assessment_evidence(
    state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """
    把当前 Assessment 的逐题结果注册成可引用证据。

    返回：
    {
        evidence_id: evidence_content
    }
    """

    evaluation = state.get(
        "evaluation",
        {}
    )

    assessment_id = evaluation.get(
        "assessment_id"
    )

    if not assessment_id:
        assessment_id = state.get(
            "assessment_id"
        )

    if not assessment_id:
        raise ValueError(
            "当前测评缺少 assessment_id"
        )

    question_results = evaluation.get(
        "question_results",
        [],
    )

    evidence_registry = {}

    for result in question_results:
        question_id = result.get(
            "question_id"
        )

        if not question_id:
            raise ValueError(
                "评分结果缺少 question_id"
            )

        evidence_id = (
            f"assessment:"
            f"{assessment_id}:"
            f"{question_id}"
        )

        evidence_registry[evidence_id] = {
            "source": "current_assessment",
            "assessment_id": assessment_id,
            "question_id": question_id,
            "score": result.get("score"),
            "error_tags": result.get(
                "error_tags",
                [],
            ),
            "evidence": result.get(
                "evidence",
                "",
            ),
            "feedback": result.get(
                "feedback",
                "",
            ),
        }

    return evidence_registry


def collect_tool_evidence(
    tool_logs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """
    从成功执行的 Tool 结果中收集可引用证据。
    """

    evidence_registry = {}

    for log in tool_logs:
        result = log.get(
            "result",
            {}
        )

        if not result.get("ok"):
            # 工具失败不算有效证据
            continue

        tool_name = log.get(
            "tool_name"
        )

        # ====================================================
        # learning history
        # ====================================================

        if tool_name == "get_learning_history":
            records = result.get(
                "records",
                [],
            )

            for record in records:
                for item in record.get("evidence_items", []):
                    evidence_id = item["evidence_id"]
                    evidence_registry[
                        evidence_id
                    ] = {
                        "source": (
                            "learning_history"
                        ),
                        "node_id": (
                            result.get("node_id")
                        ),
                        "assessment_id": record["assessment_id"],
                        "percentage": record["percentage"],
                        "question_id": item["question_id"],
                        "score": item["score"],
                        "error_tags": item["error_tags"],
                        "evidence": item["evidence"],
                        "feedback": item["feedback"],
                    }

        # ====================================================
        # node material
        # ====================================================

        elif tool_name == "get_node_material":
            material = result.get(
                "material",
                {}
            ) or {}

            material_id = material.get(
                "material_id"
            )

            if material_id:
                evidence_registry[
                    material_id
                ] = {
                    "source": "node_material",
                    "node_id": (
                        result.get("node_id")
                    ),
                    "title": (
                        material.get("title")
                    ),
                    "content": (
                        material.get("content")
                    ),
                    "objectives": (
                        material.get(
                            "objectives",
                            [],
                        )
                    ),
                }

        # ====================================================
        # prerequisite status
        #
        # 原始 Tool 没有自己的 evidence_id，
        # 所以由程序生成一个稳定 ID。
        # ====================================================

        elif (
            tool_name
            == "get_prerequisite_status"
        ):
            node_id = result.get(
                "node_id"
            )

            evidence_id = (
                f"prerequisite_status:"
                f"{node_id}"
            )

            evidence_registry[
                evidence_id
            ] = {
                "source": (
                    "prerequisite_status"
                ),
                "node_id": node_id,
                "prerequisites": (
                    result.get(
                        "prerequisites",
                        [],
                    )
                ),
                "all_completed": (
                    result.get(
                        "all_completed"
                    )
                ),
            }

    return evidence_registry


def build_diagnosis_evidence_registry(
    state: dict[str, Any],
    tool_logs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:

    evidence_registry = {}

    evidence_registry.update(
        collect_tool_evidence(
            tool_logs
        )
    )
    # 当前评分始终优先，避免重复历史结果覆盖本轮证据。
    evidence_registry.update(build_current_assessment_evidence(state))

    return evidence_registry


def build_tool_execution_summary(tool_loop_result: dict[str, Any]) -> dict[str, Any]:
    """保留查询状态和预算信息；这些信息不注册为学习证据。"""
    calls = []
    for log in tool_loop_result["tool_logs"]:
        result = log["result"]
        tool_name = log["tool_name"]
        item = {
            "round": log["round"],
            "tool_call_id": log["tool_call_id"],
            "tool_name": tool_name,
            "tool_args": log["tool_args"],
            "executed": log["executed"],
            "ok": result.get("ok", False),
        }
        if result.get("status"):
            item["query_status"] = result["status"]
        if not item["ok"]:
            item["status"] = (
                "limit_exceeded" if result.get("error_type") == "tool_limit_exceeded"
                else "failed"
            )
            item["error_type"] = result.get("error_type")
            item["error"] = result.get("error", "")
        else:
            result_field = {
                "get_learning_history": "records",
                "get_prerequisite_status": "prerequisites",
                "get_node_material": "material",
            }.get(tool_name)
            payload = result.get(result_field) if result_field else None
            item["status"] = "empty" if result_field and not payload else "success"
            if result_field in {"records", "prerequisites"}:
                item["result_count"] = len(payload or [])
        if result.get("message"):
            item["message"] = result["message"]
        calls.append(item)

    return {
        "calls": calls,
        "tool_call_count": tool_loop_result["tool_call_count"],
        "tool_round_count": tool_loop_result["tool_round_count"],
        "max_tool_calls": MAX_TOOL_CALLS,
        "max_tool_rounds": MAX_TOOL_ROUNDS,
        "call_limit_reached": tool_loop_result["tool_call_count"] >= MAX_TOOL_CALLS,
        "round_limit_reached": tool_loop_result["tool_round_count"] >= MAX_TOOL_ROUNDS,
        "stopped_reason": tool_loop_result["stopped_reason"],
    }


DIAGNOSIS_PROMPT_VERSION = "day7-v2-prerequisite-evidence"
FINAL_DIAGNOSIS_SYSTEM_PROMPT = """
你是学习诊断 Agent。

你已经结束本轮有预算限制的证据查询，部分查询可能为空或失败。

现在你的任务是根据：
1. 当前测评结果；
2. 工具返回的真实证据；
3. 当前技能树关系；
4. 工具执行摘要中的查询状态与调用上限；

生成最终结构化 DiagnosisResult。

四种 recommended_action：

advance
表示现有证据支持进入下一学习节点。

remediate
表示当前节点仍需要针对性补弱。

collect_more_evidence
表示现有证据不足，需要追加测评。

revisit_prerequisite
表示问题根源来自前置知识，需要回退复习。

重要规则：

- evidence_ids 只能引用提供给你的证据 ID。
- 不得创造或猜测 evidence_id。
- weak_points 必须能由证据支持。
- 工具执行摘要只表示查询可用性，不是可引用的学习证据。
- empty 表示查询成功但结果为空；failed 表示查询失败，不能据此断言没有历史或学生未掌握。
- limit_exceeded 和达到调用或轮数上限表示查询受到预算限制，不能推断未查询到的数据不存在。
- 未提供工具执行摘要时，查询状态未知，不能假设查询成功或历史为空。
- revisit_prerequisite 时必须给出 review_node_id。
- review_node_id 必须是真实前置节点。
- 其他行动的 review_node_id 必须为 null。
- 不要因为单纯低分就机械选择某个行动，要结合证据。
- 前置节点 completed 只证明过去通过过一次测评，不能推出当前无薄弱点，也不能据此排除前置知识问题。
- 当前节点历史为空不代表前置节点历史为空；未查询某个前置节点时，不要声称已排除它的薄弱点。
- 对照当前目标与前置目标定位概念来源。若当前答案与对应前置历史都呈现同一基础概念错误，应优先考虑 revisit_prerequisite，并引用该前置历史和当前答案的证据。
- 若只有当前操作错误、没有证据支持前置根因，可以选择 remediate；查询失败或受预算限制时应明确说明证据边界，不得伪造确定结论。
- 最终是否真的允许 advance 仍由 Graph 的确定性规则决定。
- 只输出符合给定 JSON Schema 的 JSON，不要输出 Markdown 或额外说明。
"""


@observed_node
def generate_final_diagnosis(
    state: dict[str, Any],
    *,
    evidence_registry: dict[
        str,
        dict[str, Any],
    ],
    tool_execution_summary: dict[str, Any] | None = None,
    llm=None,
    budget: ModelCallBudget | None = None,
    attempt_records: list[dict] | None = None,
) -> DiagnosisResult:

    base_llm = llm or get_llm()

    structured_llm = (
        base_llm.with_structured_output(
            DiagnosisResult,
            method="json_mode",
        )
    )

    current_node_id = state.get(
        "current_node_id"
    )

    tree = state.get(
        "tree",
        [],
    )

    prerequisite_closure = (
        get_prerequisite_closure(
            tree,
            current_node_id,
        )
    )

    prompt = (
        "当前节点：\n"
        f"{current_node_id}\n\n"

        "当前节点的目标与依赖：\n"
        f"{json.dumps(next((node for node in tree if node['id'] == current_node_id), {}), ensure_ascii=False)}\n\n"

        "当前试卷的目标覆盖：\n"
        f"{json.dumps([{'question_id': q['id'], 'objective_id': q['objective_id']} for q in state.get('quiz', {}).get('questions', [])], ensure_ascii=False)}\n\n"

        "当前得分：\n"
        f"{json.dumps(state.get('score_summary', {}),ensure_ascii=False,)}\n\n"

        "当前 Assessment：\n"
        f"{json.dumps(state.get('evaluation', {}),ensure_ascii=False,)}\n\n"

        "当前节点的前置闭包：\n"
        f"{json.dumps(sorted(prerequisite_closure),ensure_ascii=False,)}\n\n"

        "工具执行摘要（查询状态，不是学习证据）：\n"
        f"{json.dumps(tool_execution_summary, ensure_ascii=False)}\n\n"

        "本轮允许引用的证据：\n"
        f"{json.dumps(evidence_registry,ensure_ascii=False,)}\n\n"

        "DiagnosisResult 的 JSON Schema：\n"
        f"{json.dumps(DiagnosisResult.model_json_schema(), ensure_ascii=False)}"
    )

    budget = budget if budget is not None else ModelCallBudget()
    attempts = attempt_records if attempt_records is not None else []

    def invoke_once(repair_context):
        messages = [SystemMessage(content=FINAL_DIAGNOSIS_SYSTEM_PROMPT), HumanMessage(content=prompt)]
        if repair_context is not None:
            messages.append(HumanMessage(content=(
                "上一次诊断未通过系统校验：\n" + repair_context.error_message
                + "\n请仅引用提供的 evidence_id 和前置节点，返回完整修正版 DiagnosisResult JSON。"
            )))
        try:
            return structured_llm.invoke(messages)
        except (ValidationError, OutputParserException) as exc:
            attempts.append({"request_number": budget.request_count, "structure_valid": False,
                             "business_valid": False, "error_type": type(exc).__name__})
            raise ModelOutputValidationError(f"Diagnosis 结构化输出失败：{exc}") from exc
        except Exception as exc:
            attempts.append({"request_number": budget.request_count, "structure_valid": None,
                             "business_valid": None, "error_type": type(exc).__name__})
            raise

    def validate_once(raw):
        record = {"request_number": budget.request_count, "structure_valid": False,
                  "business_valid": False, "error_type": None}
        attempts.append(record)
        try:
            diagnosis = DiagnosisResult.model_validate(
                raw.model_dump() if isinstance(raw, DiagnosisResult) else raw
            )
        except ValidationError as exc:
            record["error_type"] = type(exc).__name__
            raise ModelOutputValidationError(f"Diagnosis 结构校验失败：{exc}") from exc
        record["structure_valid"] = True
        try:
            validate_diagnosis_against_context(
                diagnosis, valid_evidence_ids=set(evidence_registry),
                prerequisite_closure=prerequisite_closure,
            )
        except ValueError as exc:
            record["error_type"] = "business_validation"
            raise ModelOutputValidationError(f"Diagnosis 业务校验失败：{exc}") from exc
        record["business_valid"] = True
        return diagnosis

    return invoke_with_shared_budget(
        invoke_fn=invoke_once, validate_fn=validate_once, budget=budget,
        operation="final_diagnosis",
    )


def run_real_diagnosis(
    state: dict[str, Any],
    *,
    tool_llm=None,
    final_llm=None,
) -> DiagnosisResult:

    tool_loop_result = run_diagnosis_tool_loop(
        state,
        llm=tool_llm,
    )

    evidence_registry = (
        build_diagnosis_evidence_registry(
            state,
            tool_loop_result["tool_logs"],
        )
    )

    diagnosis = generate_final_diagnosis(
        state,
        evidence_registry=evidence_registry,
        tool_execution_summary=build_tool_execution_summary(tool_loop_result),
        llm=final_llm,
    )

    return diagnosis
