"""Keep strict schemas while giving the model concise, actionable repair errors."""
import json
import os
import re
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import SystemMessage
from app.services.llm import compact_parse_error
from app.services.json_syntax import complete_json
from app.services.observability import log_event


class _DuplicateContentField(ValueError):
    def __init__(self,key):
        self.key=key if re.fullmatch(r'[A-Za-z0-9_.]{1,80}',key) else 'invalid_field_name'
        super().__init__('Content JSON field requires one unique value')

    def errors(self,**kwargs):
        return [{'loc':(self.key,),'type':'duplicate_field',
                 'msg':'Each declared field requires one unique value. Return it exactly once.'}]


class StructuredReply:
    def __init__(self, runnable, schema_name=None, schema=None):
        self.runnable = runnable
        self.schema_name = schema_name
        self.schema = schema

    def invoke(self, messages, *args, **kwargs):
        from app.services.live_progress import phase_for_schema
        phase_for_schema(self.schema_name)
        if self.schema_name == 'TextBatchScore':
            from deploy.text_evidence import with_text_evidence
            messages = with_text_evidence(messages)
        # Course scope and granularity come from the shared application prompts.
        # Production must not replace long-route notes with a compressed microcourse.
        if self.schema_name == 'AssessmentQuiz':
            # Pydantic's union schema cannot express these existing conditional
            # validators. Explain them to the provider; never coerce its answer.
            hint = ('AssessmentQuiz 的条件字段规则必须遵守：single_choice 的 answer_key 是单个字符串选项ID，'
                    '例如 "answer_key":"A"，绝不能是 ["A"]；multiple_choice 的 answer_key 是不重复的选项ID数组。'
                    '选择题选项字段为 option_id 和 text，答案ID必须存在于本题选项。'
                    'single_choice、multiple_choice 使用 choice_exact 确定性评分，rubric 必须为 []；'
                    'numeric_scalar 的 rubric 也为 []。只有 text 题提供非空 rubric。'
                    'text 的 answer_key 是非空字符串，并提供满分合计等于 max_score 的 rubric；'
                    'numeric_scalar 必须提供 numeric_rules，期望数值写入 numeric_rules.expected，answer_key 为 null，不能填 JSON 数字；其他题型 numeric_rules 为 null。'
                    '每道题都必须包含完整 source_citations 数组，复制本目标上下文的真实来源身份；每个选项都必须有 text。'
                    '按冻结 min_items 与每一种证据满足覆盖；min_items是题数下限，不是允许省略证据类型。'
                    '同一目标同时需要数值结果和文字解释时，必须有数值题和文字题分别覆盖，不能只出一道其中的题型。'
                    'previous_question_prompts 是禁止重用的历史题，换题必须设计不同的新题干与比较实例，不要复述历史题。'
                    '原样保留所有项目、节点、测评身份和完整 frozen snapshot，不改变评分标准。')
            messages = [SystemMessage(content=hint), *messages]
        if self.schema_name in {'TutorReply','TutorContent'}:
            from app.services.live_progress import tutor_callback
            callback=tutor_callback()
            if callback is not None:
                from langchain_core.runnables.config import merge_configs
                kwargs['config']=merge_configs(kwargs.get('config'),{'callbacks':[callback]})
        result = self.runnable.invoke(messages, *args, **kwargs)
        raw = result.get('raw')
        content = getattr(raw, 'content', None)
        if getattr(raw, 'response_metadata', {}).get('finish_reason') == 'length':
            raise OutputParserException('Model output was cut off before completion. Return a concise complete JSON instance covering the entire requested scope.')
        if isinstance(content, str):
            # LangChain can close unfinished JSON and return only the complete
            # leading nodes. A truncated route must never become a smaller tree
            # or an apparently complete grading result.
            text = content.strip()
            if text.startswith('```json\n') and text.endswith('\n```'):
                text = text[8:-4]
            elif text.startswith('```\n') and text.endswith('\n```'):
                text = text[4:-4]
            try:
                def unique_members(pairs):
                    value={}
                    for key,item in pairs:
                        if key in value:raise _DuplicateContentField(key)
                        value[key]=item
                    return value
                punctuation_repair = self.schema_name in {'LearningPlan', 'PlanContent'} and hasattr(self.schema, 'model_validate')
                decoded, repairs = complete_json(text, object_pairs_hook=unique_members, repair_punctuation=punctuation_repair)
                if repairs:
                    # SDK parsing used the original text. Re-validate the whole
                    # recovered object against exactly the requested schema.
                    parsed = self.schema.model_validate(decoded)
                    result = {**result, 'parsed': parsed, 'parsing_error': None}
                    log_event('planner_json_punctuation_recovered', operation=self.schema_name,
                              outcome=','.join(repairs), attempt=len(repairs))
            except json.JSONDecodeError as exc:
                raise OutputParserException(compact_parse_error(exc)) from exc
            except ValueError as exc:
                raise OutputParserException(compact_parse_error(exc)) from exc
        error = result.get('parsing_error')
        if error is not None:
            raise OutputParserException(compact_parse_error(error)) from error
        if result.get('parsed') is None:
            raise OutputParserException('A complete schema-valid JSON object is required.')
        if self.schema_name in {'LearningPlan', 'PlanContent'}:
            for ni, node in enumerate(result['parsed'].nodes):
                for oi, objective in enumerate(node.objectives):
                    if 'text_rubric' not in objective.required_capability_ids and objective.criterion_ids:
                        raise OutputParserException(
                            f'nodes.{ni}.objectives.{oi}.criterion_ids must be [] without text_rubric. '
                            'Deterministic choice/numeric grading has no rubric criteria. Return the complete corrected plan.')
        if self.schema_name == 'AssessmentQuiz':
            for index, question in enumerate(result['parsed'].questions):
                if question.question_type != 'text' and question.rubric:
                    raise OutputParserException(
                        f'questions.{index}.rubric must be [] for deterministic choice/numeric grading. '
                        'Return the complete corrected JSON without changing frozen standards.')
        return result['parsed']


class StrictProvider:
    def __init__(self, model, *, structured_model=None, tools_model=None):
        self.model = model
        self._structured_model = structured_model
        self._tools_model = tools_model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def invoke(self, *args, **kwargs):
        return self.model.invoke(*args, **kwargs)

    def with_structured_output(self, *args, **kwargs):
        # Parsing and validation remain in LangChain/Pydantic. Raw output is
        # never returned to the business layer or copied into repair prompts.
        kwargs['include_raw'] = True
        schema = args[0] if args else kwargs.get('schema')
        model = self._structured_model(schema) if self._structured_model else self.model
        return StructuredReply(model.with_structured_output(*args, **kwargs), getattr(schema, '__name__', None), schema)

    def bind_tools(self, *args, **kwargs):
        model = self._tools_model() if self._tools_model else self.model
        return model.bind_tools(*args, **kwargs)


def create_runtime_model(*, model=None, thinking=None, extra_body_override=None):
    from langchain_openai import ChatOpenAI
    from app.services.llm import get_llm, TASK_TIMEOUTS
    from app.v3.model_content import content_model
    model = model if model is not None else get_llm()
    seconds = float(os.environ.get('SKILLTREE_MODEL_TIMEOUT', '150'))
    if not 45 <= seconds <= 180:
        raise ValueError('Deployment model timeout must be 45..180 seconds')
    thinking = thinking if thinking is not None else os.environ.get('SKILLTREE_THINKING_MODE', 'auto').lower()
    if thinking not in {'auto', 'true', 'false'}:
        raise ValueError('Thinking mode must be auto, true, or false')
    extra_body = extra_body_override if extra_body_override is not None else (None if thinking == 'auto' else {'thinking_mode': thinking == 'true'})
    # Construct the SDK client with the timeout. Changing a Pydantic field
    # on an already-built model leaves its underlying HTTP client unchanged.
    clients = {}
    def client(timeout, streaming=False):
        key = (timeout, streaming)
        if key not in clients:
            clients[key] = ChatOpenAI(model=model.model_name, api_key=model.openai_api_key,
                base_url=model.openai_api_base, temperature=model.temperature,
                timeout=timeout, max_retries=0, extra_body=extra_body, streaming=streaming,
                max_tokens=model.max_tokens)
        return clients[key]
    def structured_model(schema):
        name = getattr(schema, '__name__', '')
        kind = {'TextBatchScore': 'grade', 'TextGradeContent': 'grade', 'AssessmentQuiz': 'quiz', 'QuizContent': 'quiz', 'QuizContentWire': 'quiz',
                'DiagnosisDecision': 'diagnosis', 'DiagnosisContent': 'diagnosis', 'TutorReply': 'tutor', 'TutorContent': 'tutor'}.get(name)
        timeout = TASK_TIMEOUTS.get(kind, 45) if kind else 120 if name in {
            'LearningPlan', 'PlanContent', 'LearningPreparation', 'StudyNotes', 'StudyNotesContent'} else seconds
        # Aggregate the provider stream into one strictly checked result.
        # Receiving chunks avoids retrying a still-generating preparation
        # merely because its non-streaming HTTP response stayed silent.
        return client(timeout, streaming=name in {'LearningPlan', 'PlanContent', 'LearningPreparation', 'StudyNotes', 'StudyNotesContent','TutorReply','TutorContent'})
    # Core injection remains an actual model. Route at the structured schema
    # boundary so its task-specific transports and strict adapters both apply.
    return content_model(StrictProvider(client(seconds), structured_model=structured_model,
                          tools_model=lambda: client(TASK_TIMEOUTS['diagnosis'])))
