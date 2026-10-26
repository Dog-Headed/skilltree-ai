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
        if self.schema_name == 'StudyNotes':
            messages = [SystemMessage(content=(
                'StudyNotes.content 请用紧凑的中文 Markdown：一个总标题，最多三个小标题；'
                '每节采用连贯段落，不为每个小步骤另起标题。保留已确认范围内的定义、步骤、例子与常见错误，'
                '不要扩大学习范围；通常300至1000汉字即可。这可避免大量标题碎片挤占后续规划上下文。')),*messages]
        if self.schema_name == 'LearningPlan':
            messages = [SystemMessage(content=(
                'LearningPlan 必须覆盖已请求的全部必要评价能力，同时保持节点与目标描述简洁。'
                '每个 source_chunk_ids 引用片段的正文必须与该目标存在具体内容词汇关联，'
                '不能只因片段是章节标题就引用它。逐字复制目录中的片段身份，不能编造。')),*messages]
        if self.schema_name == 'AssessmentQuiz':
            # Pydantic's union schema cannot express these existing conditional
            # validators. Explain them to the provider; never coerce its answer.
            hint = ('AssessmentQuiz 的条件字段规则必须遵守：single_choice 的 answer_key 是单个字符串选项ID，'
                    '例如 "answer_key":"A"，绝不能是 ["A"]；multiple_choice 的 answer_key 是不重复的选项ID数组。'
                    '选择题选项字段为 option_id 和 text，答案ID必须存在于本题选项。'
                    'text 的 answer_key 是非空字符串，并提供满分合计等于 max_score 的 rubric；'
                    'numeric_scalar 必须提供 numeric_rules，其他题型 numeric_rules 为 null。'
                    '原样保留所有项目、节点、测评身份和完整 frozen snapshot，不改变评分标准。')
            messages = [SystemMessage(content=hint), *messages]
        result = self.runnable.invoke(messages, *args, **kwargs)
        error = result.get('parsing_error')
        if error is not None:
            raise OutputParserException(compact_parse_error(error)) from error
        if result.get('parsed') is None:
            raise OutputParserException('A complete schema-valid JSON object is required.')
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
