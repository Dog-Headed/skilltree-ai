"""将已保存的诊断投影为学习者反馈，不修改诊断事实或再次调用模型。"""

import re


_AUDIT = re.compile(
    r"工具(?:执行|查询|调用)|调用(?:预算|次数|上限|轮数)|\d+\s*次调用"
    r"|未查询(?:前置|某个)|本轮(?:仅|未|没有)?.{0,8}查询"
    r"|(?:由|交给)\s*Graph|Graph\s*的确定性规则|Checkpoint"
    r"|evidence_ids|tool_execution_summary|calls\s*(?:为空|=)|pending_input_id",
    re.IGNORECASE,
)
_CODE = re.compile(r"(```[\s\S]*?```|`[^`\n]+`|[A-Za-z_]\w*\([^()\n]*(?:\([^()\n]*\)[^()\n]*)*\))")
_TAG_ANNOTATION = re.compile(
    r"(?<![A-Za-z0-9_.])[（(]\s*(?:error_tags\s*[:：]\s*)?"
    r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?:\s*[,，]\s*[a-z][a-z0-9]*(?:_[a-z0-9]+)+)*\s*[）)]"
)
_UNKNOWN_OBJECTIVE = re.compile(r"(?<![A-Za-z0-9_])(?:obj_[A-Za-z0-9_]+|[A-Za-z0-9_]+_obj_\d+)(?![A-Za-z0-9_])")
_UNKNOWN_QUESTION = re.compile(r"(?<![A-Za-z0-9_])q_[A-Za-z0-9_]+(?![A-Za-z0-9_])")
_TAG_LABELS = {
    "missing_python_extension": "尚未安装或启用 Python 扩展",
    "assignment_confusion": "赋值与比较容易混淆",
    "needs_practice": "需要继续练习",
    "critical_error": "关键知识点需要巩固",
    "critical_misconception": "关键概念需要巩固",
}
_PYTHON_ERRORS = {
    "SyntaxError", "NameError", "TypeError", "IndentationError", "IndexError",
    "KeyError", "ValueError", "ZeroDivisionError", "FileNotFoundError",
    "AttributeError", "ModuleNotFoundError", "ImportError",
}


class LearnerFeedback:
    def __init__(self, nodes, records, current_record):
        self.labels = {}
        self.objectives = {}
        self.node_titles = {}
        for node in nodes:
            self.node_titles[node.id] = node.title
            self.labels[node.id] = f"「{node.title}」"
            for objective in node.objectives:
                self.objectives[objective.id] = objective.description
                self.labels[objective.id] = f"「{objective.description}」"

        # 先登记历史，再覆盖本轮；同名 q1 等编号始终对应当前试卷。
        ordered = [record for record in records if record is not current_record] + [current_record]
        self.tags = dict(_TAG_LABELS)
        self.fallback_weak_points = []
        for record in ordered:
            is_current = record is current_record
            quiz = record.get("quiz") or {}
            questions = {question["id"]: question for question in quiz.get("questions", [])}
            for number, question in enumerate(questions.values(), 1):
                question_label = f"第{number}题" if is_current else f"第{record['round_no']}轮的第{number}题"
                self.labels[f"assessment:{record['id']}:{question['id']}"] = question_label + "的作答"
                self.labels[question["id"]] = question_label
            self.labels[record["id"]] = "本轮测验" if is_current else f"第{record['round_no']}轮测验"
            for result in (record.get("evaluation") or {}).get("question_results", []):
                question = questions.get(result["question_id"], {})
                objective = self.objectives.get(question.get("objective_id"), "当前知识点")
                if is_current and result["score"] < question.get("max_score", 0):
                    self.fallback_weak_points.append("需要巩固：" + objective)
                for tag in result.get("error_tags", []):
                    if tag:
                        self.tags[tag] = _TAG_LABELS.get(tag, "需要巩固：" + objective)
        self.labels.update(self.tags)
        tokens = sorted(self.labels, key=len, reverse=True)
        self.references = re.compile(
            r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(token) for token in tokens) + r")(?![A-Za-z0-9_])"
        ) if tokens else None
        tags = sorted(self.tags, key=len, reverse=True)
        self.tag_annotation = re.compile(
            r"[（(]\s*(?:error_tags\s*[:：]\s*)?(?:"
            + "|".join(re.escape(tag) for tag in tags) + r")[）)]"
        ) if tags else None

    def text(self, value, *, omit_audit=True):
        def plain(text):
            text = _TAG_ANNOTATION.sub("", text)
            if self.tag_annotation:
                text = self.tag_annotation.sub("", text)
            if self.references:
                text = self.references.sub(lambda match: self.labels[match.group()], text)
            text = _UNKNOWN_OBJECTIVE.sub("该学习目标", text)
            text = _UNKNOWN_QUESTION.sub("相关题目", text)
            return text.replace("error_tags", "错误提示")

        # 保留真正的 Python 示例；单独以代码格式显示的内部编号仍转换为中文。
        pieces = _CODE.split(value or "")
        for index, piece in enumerate(pieces):
            if index % 2:
                token = piece[1:-1]
                if token in self.labels:
                    pieces[index] = self.labels[token]
            else:
                sentences = re.findall(r"[^。！？；\n]+[。！？；]?", piece) or [piece]
                pieces[index] = "\n\n".join(
                    plain(sentence) for sentence in sentences
                    if not omit_audit or not _AUDIT.search(sentence)
                )
        return "".join(pieces).strip()

    def diagnosis(self, diagnosis, *, completed=False):
        weak_points = []
        for value in diagnosis.get("weak_points", []):
            text = self.text(value)
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", text) and text not in _PYTHON_ERRORS:
                text = ""
            if text:
                weak_points.append(text)
        if diagnosis.get("weak_points") and not weak_points:
            weak_points = self.fallback_weak_points or ["当前知识点还需要巩固"]
        weak_points = list(dict.fromkeys(weak_points))

        reason = self.text(diagnosis.get("reason", ""))
        if not reason:
            action = diagnosis.get("recommended_action")
            review_title = self.node_titles.get(diagnosis.get("review_node_id"), "相关前置知识")
            reason = {
                "advance": "本轮测评已通过，可以继续学习下一个知识点。" if completed else "建议继续学习，实际完成进度以技能路径为准。",
                "remediate": "根据本轮作答，建议先巩固薄弱知识点，再通过新题验证。",
                "collect_more_evidence": "现有作答还不足以确认掌握情况，接下来通过追加测评进一步判断。",
                "revisit_prerequisite": f"建议先复习「{review_title}」，再回到当前知识点继续练习。",
            }.get(action, "评分已保存，诊断等待恢复。")
        return reason, weak_points
