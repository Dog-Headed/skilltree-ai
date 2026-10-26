"""Keep strict schemas while giving the model concise, actionable repair errors."""
import json

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import SystemMessage


def compact_parse_error(error):
    current = error
    for _ in range(8):
        if current is None:
            break
        if hasattr(current, 'errors'):
            issues = current.errors(include_input=False, include_url=False)
            return json.dumps({'schema_errors': [
                {'field': '.'.join(map(str, issue['loc'])), 'type': issue['type'], 'message': issue['msg'][:180]}
                for issue in issues[:12]], 'instruction': 'Return the complete corrected JSON. Preserve all supplied identities and frozen values.'}, ensure_ascii=False)
        if isinstance(current, json.JSONDecodeError):
            return json.dumps({'json_error': current.msg, 'line': current.lineno, 'column': current.colno,
                               'instruction': 'Return complete valid JSON with correctly escaped string values and no surrounding commentary.'})
        current = current.__cause__
    return 'Structured JSON did not match the supplied schema. Return one complete JSON object, preserving the supplied identities and frozen values.'


class StructuredReply:
    def __init__(self, runnable, schema_name=None):
        self.runnable = runnable
        self.schema_name = schema_name

    def invoke(self, messages, *args, **kwargs):
        if self.schema_name == 'TextBatchScore':
            from deploy.text_evidence import with_text_evidence
            messages = with_text_evidence(messages)
        if self.schema_name == 'StudyNotes':
            messages = [SystemMessage(content=(
                'StudyNotes.content 请用紧凑的中文 Markdown：一个总标题，最多三个小标题；'
                '每节采用连贯段落，不为每个小步骤另起标题。保留已确认范围内的定义、步骤、例子与常见错误，'
                '不要扩大学习范围；通常300至1000汉字即可。这可避免大量标题碎片挤占后续规划上下文。')),*messages]
        if self.schema_name == 'LearningPlan':
            messages = [SystemMessage(content=(
                'LearningPlan 必须覆盖已请求的全部必要评价能力，同时保持节点与目标描述简洁。'
                '每一个 observable_outcome 都必须使用明确可观察动词，例如选出、辨认、识别、指出、解释、描述或判断。'
                'choice_exact 目标必须写成从给定选项中选出、辨认或判断具体内容，不能写成仅理解、知道、熟悉或口头说出。'
                '每个 source_chunk_ids 引用片段的正文必须与该目标存在具体内容词汇关联，'
                '不能只因片段是章节标题就引用它。逐字复制目录中的片段身份，不能编造。'
                '对全部目标逐项核对这些要求，不能只修复报错的第一个目标。')),*messages]
        if self.schema_name == 'AssessmentQuiz':
            # Pydantic's union schema cannot express these existing conditional
            # validators. Explain them to the provider; never coerce its answer.
            hint = ('AssessmentQuiz 的条件字段规则必须遵守：single_choice 的 answer_key 是单个字符串选项ID，'
                    '例如 "answer_key":"A"，绝不能是 ["A"]；multiple_choice 的 answer_key 是不重复的选项ID数组。'
                    '选择题选项字段为 option_id 和 text，答案ID必须存在于本题选项。'
                    'single_choice、multiple_choice 使用 choice_exact 确定性评分，rubric 必须为 []；'
                    'numeric_scalar 的 rubric 也为 []。只有 text 题提供非空 rubric。'
                    'text 的 answer_key 是非空字符串，并提供满分合计等于 max_score 的 rubric；'
                    'numeric_scalar 必须提供 numeric_rules，其他题型 numeric_rules 为 null。'
                    '每道题都必须包含完整 source_citations 数组，复制本目标上下文的真实来源身份；每个选项都必须有 text。'
                    '按冻结 min_items 与证据种类满足最少覆盖即可，窄目标优先一道完整题，避免无谓扩题。'
                    'previous_question_prompts 是禁止重用的历史题，换题必须设计不同的新题干与比较实例，不要复述历史题。'
                    '原样保留所有项目、节点、测评身份和完整 frozen snapshot，不改变评分标准。')
            messages = [SystemMessage(content=hint), *messages]
        result = self.runnable.invoke(messages, *args, **kwargs)
        error = result.get('parsing_error')
        if error is not None:
            raise OutputParserException(compact_parse_error(error)) from error
        if result.get('parsed') is None:
            raise OutputParserException('A complete schema-valid JSON object is required.')
        if self.schema_name == 'AssessmentQuiz':
            for index, question in enumerate(result['parsed'].questions):
                if question.question_type != 'text' and question.rubric:
                    raise OutputParserException(
                        f'questions.{index}.rubric must be [] for deterministic choice/numeric grading. '
                        'Return the complete corrected JSON without changing frozen standards.')
        return result['parsed']


class StrictProvider:
    def __init__(self, model):
        self.model = model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def invoke(self, *args, **kwargs):
        return self.model.invoke(*args, **kwargs)

    def with_structured_output(self, *args, **kwargs):
        # Parsing and validation remain in LangChain/Pydantic. Raw output is
        # never returned to the business layer or copied into repair prompts.
        kwargs['include_raw'] = True
        schema = args[0] if args else kwargs.get('schema')
        return StructuredReply(self.model.with_structured_output(*args, **kwargs), getattr(schema, '__name__', None))

    def bind_tools(self, *args, **kwargs):
        return self.model.bind_tools(*args, **kwargs)
