from app.state import LearningState


def diagnosis_node(state: LearningState):
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