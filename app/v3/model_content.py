"""Provider wire contracts: content out, request authority stays in Python.

The original V3 contracts and business validators still receive complete DTOs.
This adapter changes the model-facing transport, never the persisted format,
score policy, ownership, evidence authorization or logical request budget.
"""
from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Literal

from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, create_model

from .contracts import ContractModel, SkillNode, Text

WIRE_VERSION = 'content-bindings-1'
SUPPORTED = {'LearningPlan', 'TextBatchScore', 'DiagnosisDecision', 'TutorReply', 'QualityReview', 'AssessmentQuiz', 'QuizContent'}
PRIVATE_METADATA = {'project_id', 'assessment_id', 'previous_assessment_id', 'snapshot',
                    'policy_id', 'policy_version', 'profile_version', 'plan_version',
                    'draft_revision', 'contract_version', 'content_hash', 'source_content_hash',
                    'schema', 'output_schema', 'learning_plan_schema', 'tutor_reply_schema'}


def _dump(value):
    return value.model_dump() if hasattr(value, 'model_dump') else value


def _object(text):
    if not isinstance(text, str):
        return None
    start = text.find('{')
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def _payload(messages, name):
    required = {
        'LearningPlan': {'project_id', 'profile', 'teaching_material_catalog', 'policy'},
        'TextBatchScore': {'project_id', 'assessment_id', 'questions', 'answers', 'snapshot'},
        'DiagnosisDecision': {'project_id', 'assessment_id', 'allowed_evidence_ids', 'current_evidence'},
        'TutorReply': {'data_kind', 'teaching_contexts', 'exploration'},
        'QualityReview': {'project_id', 'quiz', 'bound_material', 'student_answers'},
        'AssessmentQuiz': {'project_id', 'node', 'assessment_id', 'snapshot', 'contexts', 'policy'},
        'QuizContent': {'slots', 'supported_numeric_units', 'previous_question_prompts'},
    }[name]
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            data = _object(message.content)
            if data is not None and required <= data.keys():
                return index, deepcopy(data)
    raise ValueError('Missing trusted input for the model content contract')


class Projection:
    """Exact ID fields only; learner prose and quoted source text are untouched."""
    def __init__(self, aliases=None):
        self.aliases = dict(aliases or {})

    def discover(self, value, field=''):
        if isinstance(value, dict):
            for key, item in value.items():
                if key not in PRIVATE_METADATA:
                    self.discover(item, key)
        elif isinstance(value, list):
            for item in value:
                self.discover(item, field)
        elif isinstance(value, str) and len(value) > 16 and (field.endswith('_id') or field.endswith('_ids')):
            if value not in self.aliases:
                self.aliases[value] = 'ref' + str(len(self.aliases) + 1)

    def data(self, value, field=''):
        if isinstance(value, dict):
            return {self.aliases.get(key, key): self.data(item, key) for key, item in value.items()
                    if key not in PRIVATE_METADATA}
        if isinstance(value, list):
            return [self.data(item, field) for item in value]
        if isinstance(value, str) and (field.endswith('_id') or field.endswith('_ids') or field in {'answers', 'allowed_evidence_ids'}):
            return self.aliases.get(value, value)
        return value

    def diagnostic(self, text):
        # Error messages may mention a full ID. These are diagnostics, never
        # learner answers or source quotes, so replace only exact known values.
        for real, short in sorted(self.aliases.items(), key=lambda pair: -len(pair[0])):
            text = text.replace(real, short)
        return text


class PlanContent(ContractModel):
    nodes: list[SkillNode] = Field(min_length=1, max_length=20)


class QuoteContent(ContractModel):
    quote: Text
    occurrence: int = Field(default=1, ge=1, le=4000)


class CriterionContent(ContractModel):
    score: float = Field(ge=0, allow_inf_nan=False)
    anchors: list[QuoteContent] = Field(min_length=1, max_length=10)
    severity: Literal['minor', 'major', 'critical'] | None = None
    subject_tags: list[str] = Field(default_factory=list, max_length=20)


class GradeContent(ContractModel):
    grading_status: Literal['graded', 'needs_review', 'invalid_item']
    uncertainty_reasons: list[Text] = Field(default_factory=list, max_length=20)


def _literal(values):
    return Literal[tuple(values)] if values else Literal['__no_authorized_reference__']


def _span(answer, quote, occurrence):
    start = -1
    for _ in range(occurrence):
        start = answer.find(quote, start + 1)
        if start < 0:
            raise ValueError('Quoted evidence does not occur at that occurrence in the actual answer')
    if not quote.strip():
        raise ValueError('Quoted evidence must contain actual answer text')
    return {'quote': quote, 'start': start, 'end': start + len(quote)}


@dataclass
class Binding:
    schema: type
    payload: dict
    assemble: object
    projection: Projection
    instruction: str
    schema_document: dict | None = None


def _plan(payload):
    projection = Projection()
    def assemble(content):
        return {**content, **{key: payload[key] for key in ('project_id', 'draft_revision', 'plan_version')}}
    document = deepcopy(payload['learning_plan_schema'])
    for key in ('project_id', 'draft_revision', 'plan_version'):
        document['properties'].pop(key, None)
    document['required'] = [key for key in document.get('required', []) if key in document['properties']]
    # Preserve the existing planner's source aliases and reference sets. New
    # node/objective symbols describe a DAG; they are not persisted UUIDs.
    return Binding(PlanContent, projection.data(payload), assemble, projection,
        '只输出nodes。用n1、n2及全树唯一o1、o2等短标记表达依赖和目标；项目身份、草稿和计划版本由程序绑定。', document)


def _grade(payload):
    questions = payload['questions']
    aliases = {q['question_id']: 'q' + str(i) for i, q in enumerate(questions, 1)}
    projection = Projection(aliases); projection.discover(payload)
    fields, slots, model_questions = {}, {}, []
    for question in questions:
        key = aliases[question['question_id']]
        criteria = {'r' + str(i): c for i, c in enumerate(question['rubric'], 1)}
        rubric_fields = {}
        for short, criterion in criteria.items():
            bounded = create_model('GradeCriterion' + key + short, __base__=CriterionContent,
                score=(float, Field(ge=0, le=criterion['max_score'], allow_inf_nan=False)))
            rubric_fields[short] = (bounded, ...)
        rubric = create_model('GradeRubric' + key, __base__=ContractModel, **rubric_fields)
        item = create_model('GradeQuestion' + key, __base__=ContractModel,
            criteria=(rubric, ...), feedback=(Text, ...))
        fields[key] = (item | None, None)
        slots[key] = (question, criteria)
        value = projection.data(question)
        value['rubric'] = {short: {k: v for k, v in criterion.items() if k != 'criterion_id'}
                           for short, criterion in criteria.items()}
        model_questions.append(value)
    question_map = create_model('GradeQuestions', __base__=ContractModel, **fields)
    schema = create_model('TextGradeContent', __base__=GradeContent, questions=(question_map, ...))
    wire = projection.data(payload); wire['questions'] = model_questions
    def assemble(content):
        supplied = {k: v for k, v in content['questions'].items() if v is not None}
        if content['grading_status'] == 'graded' and set(supplied) != set(slots):
            raise ValueError('A graded batch must cover every text question exactly once')
        results = []
        for key, item in supplied.items():
            question, criteria = slots[key]
            answer = payload['answers'][question['question_id']]
            rows = []
            for short, scored in item['criteria'].items():
                criterion = criteria[short]
                rows.append({**scored, 'criterion_id': criterion['criterion_id'],
                    'max_score': criterion['max_score'],
                    'anchors': [_span(answer, a['quote'], a['occurrence']) for a in scored['anchors']]})
            results.append({'question_id': question['question_id'], 'evaluator_id': question['evaluator_id'],
                'evaluator_version': question['evaluator_version'], 'max_score': question['max_score'],
                'criteria': rows, 'feedback': item['feedback']})
        return {**{k: payload[k] for k in ('project_id', 'node_id', 'assessment_id', 'snapshot')},
            'grading_status': content['grading_status'], 'questions': results,
            'uncertainty_reasons': content['uncertainty_reasons']}
    return Binding(schema, wire, assemble, projection,
        'questions是q1等槽位的对象，每题criteria是r1等分项的对象。只判断score、severity、subject_tags、feedback及真实答案摘录。'
        'anchors只填写quote和可选occurrence（同一摘录第几次出现，从1开始）；字符位置、满分、评价器、版本和全部长编号由程序填写。'
        'graded必须逐题逐分项完整覆盖；needs_review或invalid_item可少返回题目，但须说明uncertainty_reasons。')


def _diagnosis(payload):
    real_evidence = list(payload['allowed_evidence_ids'])
    evidence = {'e' + str(i): real for i, real in enumerate(real_evidence, 1)}
    nodes = {'n' + str(i): real for i, real in enumerate(payload['node']['prerequisite_ids'], 1)}
    aliases = {real: short for short, real in {**evidence, **nodes}.items()}
    projection = Projection(aliases); projection.discover(payload)
    schema = create_model('DiagnosisContent', __base__=ContractModel,
        action=(Literal['advance', 'remediate', 'revisit_prerequisite', 'collect_more_evidence'], ...),
        reason=(Text, ...), evidence_refs=(list[_literal(evidence)], Field(default_factory=list, max_length=min(100, len(evidence)))),
        review_node_ref=(_literal(nodes) | None, None))
    def assemble(content):
        return {**{k: payload[k] for k in ('project_id', 'node_id', 'assessment_id', 'snapshot')},
            'action': content['action'], 'reason': content['reason'],
            'evidence_ids': [evidence[ref] for ref in content['evidence_refs']],
            'review_node_id': nodes[content['review_node_ref']] if content['review_node_ref'] is not None else None}
    wire = projection.data(payload)
    wire['allowed_evidence_refs'] = list(evidence)
    wire['allowed_review_node_refs'] = list(nodes)
    return Binding(schema, wire, assemble, projection,
        '只返回action、reason、evidence_refs及review_node_ref。证据仅从allowed_evidence_refs选择短标记；'
        'review_node_ref仅在revisit_prerequisite时选择合法前置短标记，其余行动必须为null。'
        'reason用自然语言解释，不抄写编号。项目、节点、测评及冻结快照由程序绑定，不能输出这些字段。')


def _tutor(payload):
    citations, aliases = {}, {}
    for context in payload['teaching_contexts']:
        for citation in context['public_citations']:
            identity = tuple(citation[k] for k in ('source_id', 'source_version', 'chunk_id'))
            if identity not in [tuple(v[k] for k in ('source_id', 'source_version', 'chunk_id')) for v in citations.values()]:
                short = 'b' + str(len(citations) + 1)
                citations[short] = {k: citation[k] for k in ('source_id', 'source_version', 'chunk_id')}
                aliases[citation['chunk_id']] = short
    projection = Projection(aliases); projection.discover(payload)
    schema = create_model('TutorContent', __base__=ContractModel, text=(str, Field(min_length=1, max_length=8000)),
        citation_refs=(list[_literal(citations)], Field(default_factory=list, max_length=min(100, len(citations)))))
    def assemble(content):
        return {'text': content['text'], 'citations': [citations[ref] for ref in content['citation_refs']],
                'exploration': payload['exploration']}
    wire = projection.data(payload); wire['allowed_citation_refs'] = list(citations)
    return Binding(schema, wire, assemble, projection,
        '本轮只输出text和citation_refs。引用按allowed_citation_refs选择b1等短标记；'
        '真实来源、版本和探索模式由程序绑定，不要输出citations、exploration、source_id或版本。正式教学必须引用本轮真实资料。')


def _review(payload):
    questions = {q['question_id']: 'q' + str(i) for i, q in enumerate(payload['quiz']['questions'], 1)}
    chunks = {b['citation']['chunk_id'] for ctx in payload['bound_material'].values() for b in ctx['blocks']}
    sources = {real: 'b' + str(i) for i, real in enumerate(sorted(chunks), 1)}
    projection = Projection({**questions, **sources}); projection.discover(payload)
    finding = create_model('ReviewFindingContent', __base__=ContractModel,
        question_ref=(_literal(questions.values()), ...), source_ref=(_literal(sources.values()), ...),
        source_quote=(Text, ...), answer_quote=(str | None, Field(default=None, max_length=4000)), reason=(Text, ...))
    schema = create_model('QualityReviewContent', __base__=ContractModel,
        verdict=(Literal['accepted', 'needs_review', 'invalid_item'], ...), reason=(Text, ...),
        findings=(list[finding], Field(default_factory=list, max_length=20)))
    qreverse = {short: real for real, short in questions.items()}; sreverse = {short: real for real, short in sources.items()}
    def assemble(content):
        findings = []
        for f in content['findings']:
            findings.append({k: v for k, v in f.items() if k not in {'question_ref', 'source_ref'}} |
                {'question_id': qreverse[f['question_ref']], 'source_chunk_id': sreverse[f['source_ref']]})
        return {'project_id': payload['project_id'], 'assessment_id': payload['assessment_id'],
                'verdict': content['verdict'], 'reason': content['reason'], 'findings': findings}
    return Binding(schema, projection.data(payload), assemble, projection,
        '只返回verdict、reason、findings。finding使用question_ref和source_ref对应输入中q1、b1等短标记，'
        '保留真实source_quote和可选answer_quote。项目及测评编号由程序绑定。')


def _quiz(payload):
    from .contracts import SkillNode, EvaluationPolicy, FrozenSnapshot
    from .quiz_content import build_content_contract, content_payload
    node = SkillNode.model_validate(payload['node']); policy = EvaluationPolicy.model_validate(payload['policy'])
    contract = build_content_contract(node, policy, payload['contexts'])
    inner = _content_quiz(content_payload(contract, node, policy, payload['contexts'], payload['previous_question_prompts']), contract.schema)
    def assemble(content):
        return contract.assemble(inner.assemble(content), **{k: payload[k] for k in
            ('project_id', 'assessment_id', 'previous_assessment_id')}, snapshot=FrozenSnapshot.model_validate(payload['snapshot']), node_id=node.node_id).model_dump()
    return Binding(inner.schema, inner.payload, assemble, inner.projection, inner.instruction, inner.schema_document)


def _content_quiz(payload, original_schema):
    """Closed unit choices on the wire; persisted content-v1 remains compatible."""
    from .quiz_content import NumericContent
    from .evaluators import UNIT_RULES
    from .question_novelty import validate_content_prompts
    units = [None, *sorted(UNIT_RULES)]
    unit_answer = create_model('NumericValueContent', __base__=ContractModel,
        expected=(float, Field(allow_inf_nan=False)),
        unit_index=(int, Field(ge=0, le=len(units)-1, strict=True)))
    fields, numeric = {}, []
    for key, field in original_schema.model_fields.items():
        item = field.annotation
        if issubclass(item, NumericContent):
            item = create_model('NumericSlot' + key, __base__=item, numeric_rules=(unit_answer, ...))
            numeric.append(key)
        fields[key] = (item, ...)
    schema = create_model('QuizContentWire', __base__=ContractModel, **fields)
    history = payload['previous_question_prompts']
    document = schema.model_json_schema()
    # All slots share Text's prompt constraints. Keep the history only once in
    # the schema instead of repeating up to 30 long prompts for every slot.
    if history:
        definitions = document['$defs']
        prompt_rule = None
        for definition in list(definitions.values()):
            properties = definition.get('properties', {})
            if 'prompt' in properties:
                if prompt_rule is None:
                    prompt_rule = deepcopy(properties['prompt'])
                    prompt_rule['not'] = {'enum': list(dict.fromkeys(history))}
                properties['prompt'] = {'$ref': '#/$defs/UnusedQuestionPrompt'}
        definitions['UnusedQuestionPrompt'] = prompt_rule
    def assemble(content):
        validate_content_prompts(content, history)
        result = deepcopy(content)
        for key in numeric:
            item = result[key]['numeric_rules']
            item['unit'] = units[item.pop('unit_index')]
        return original_schema.model_validate(result)
    projection = Projection()
    wire = projection.data(payload)
    wire.pop('supported_numeric_units', None)
    wire['unit_choices'] = {str(i): value for i, value in enumerate(units)}
    return Binding(schema, wire, assemble, projection,
        '只生成给定q1等槽位的内容。numeric_rules只输出expected与整数unit_index，禁止输出unit字符串。'
        'unit_index从unit_choices中按含义选择，0表示无机器单位（只接受数值）。'
        '资料中的单位若不在选项内，应在题干说明原单位并明确只填写数值，选择0；不要声称系统支持额外单位换算。'
        '不能改变已提供的题型、目标、评分项或来源范围；所有固定编号和单位字符串由程序回填。'
        'previous_question_prompts是禁止复用的历史题，数组下标从0开始。输出前逐槽位比对历史及本卷其他题。'
        '重测须改变实际考查任务或实例，优先用资料中未使用的例子，或用资料支持的规则设计新的假设练习数据；'
        '假设数据须在题干给全，不得冒充资料原文或引入资料之外的新知识。同步核对选项、答案与量规。'
        '只改措辞、标点、空白或编号不算新题。修复错误中的q1.prompt等路径就是要替换的槽位，返回完整新卷。', document)


def bind(schema, messages):
    name = schema.__name__; index, payload = _payload(messages, name)
    if name == 'QuizContent':
        binding = _content_quiz(payload, schema)
    else:
        builder = {'LearningPlan': _plan, 'TextBatchScore': _grade, 'DiagnosisDecision': _diagnosis,
                   'TutorReply': _tutor, 'QualityReview': _review, 'AssessmentQuiz': _quiz}[name]
        binding = builder(payload)
    projected = binding.payload
    extras = []
    for i, message in enumerate(messages):
        if i == index or not isinstance(message, HumanMessage):
            continue
        obj = _object(message.content)
        if obj is not None and set(obj) <= {'project_id', 'node_id', 'assessment_id'}:
            continue
        extras.append(binding.projection.data(obj) if obj is not None else binding.projection.diagnostic(str(message.content)))
    if extras:
        projected = {**projected, 'supplemental_data': extras}
    document = binding.schema_document or binding.schema.model_json_schema()
    rules = [message for message in messages if isinstance(message, SystemMessage)]
    instruction = (f'模型内容协议 {WIRE_VERSION}。业务约束沿用上述规则，输出字段以本段为准。'
        '固定身份和冻结元数据不由模型生成或回填，即使此前说明提及完整内部DTO也不能输出这些字段。'
        + binding.instruction + '\n只返回以下结构的数据实例JSON，不返回schema定义：\n')
    def render(document):
        override = instruction + json.dumps(document, ensure_ascii=False, separators=(',', ':'))
        return [SystemMessage(content='\n\n'.join([*(str(rule.content) for rule in rules), override])),
                HumanMessage(content=json.dumps(projected, ensure_ascii=False, separators=(',', ':')))]
    result = render(document)
    from .config import SERVER_LIMITS
    if sum(len(str(m.content)) for m in result) > SERVER_LIMITS.max_context_characters:
        # The enum is a redundant generation hint, not the validator. Omit
        # only that copy if needed; keep all history and repair data intact.
        prompt_rule = document.get('$defs', {}).get('UnusedQuestionPrompt', {})
        if name in {'AssessmentQuiz', 'QuizContent'} and 'not' in prompt_rule:
            document = deepcopy(document)
            document['$defs']['UnusedQuestionPrompt'].pop('not')
            result = render(document)
    if sum(len(str(m.content)) for m in result) > SERVER_LIMITS.max_context_characters:
        raise ValueError('Content contract context exceeds the unchanged server limit')
    return binding, result


class ContentModel:
    """Every real model entry point uses this adapter; isolated test doubles may bypass it."""
    def __init__(self, model):
        self.model = model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def invoke(self, *args, **kwargs):
        return self.model.invoke(*args, **kwargs)

    def bind_tools(self, *args, **kwargs):
        return self.model.bind_tools(*args, **kwargs)

    def with_structured_output(self, schema, **kwargs):
        if getattr(schema, '__name__', '') not in SUPPORTED:
            return self.model.with_structured_output(schema, **kwargs)
        parent = self
        class Bound:
            def invoke(self, messages, *args, **invoke_kwargs):
                try:
                    binding, projected = bind(schema, messages)
                    raw = parent.model.with_structured_output(binding.schema, **kwargs).invoke(projected, *args, **invoke_kwargs)
                    content = binding.schema.model_validate(_dump(raw)).model_dump()
                    return schema.model_validate(binding.assemble(content))
                except (ValueError, KeyError, TypeError) as exc:
                    raise OutputParserException('Content binding validation failed: ' + str(exc)) from exc
        return Bound()


def content_model(model):
    return model if isinstance(model, ContentModel) else ContentModel(model)
