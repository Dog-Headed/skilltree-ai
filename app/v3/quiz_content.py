"""Model-only quiz content; request identities and frozen mappings stay in code.

The assembled result must still pass the original AssessmentQuiz and business
validators. This module neither publishes a quiz nor changes learning state.
"""
from dataclasses import dataclass
from hashlib import sha256
from math import fsum
from typing import Literal

from pydantic import Field, create_model, field_validator, model_validator

from .config import SERVER_LIMITS
from .contracts import ContractModel, Text, NumericRules, AssessmentQuiz, SourceCitation
from .evaluators import UNIT_RULES, data

CONTENT_MODE = 'content-v1'
GENERATION_MODES = {'legacy', CONTENT_MODE}
TYPE_EVALUATOR = {'single_choice':'choice_exact', 'multiple_choice':'choice_exact',
                  'numeric_scalar':'numeric_scalar', 'text':'text_rubric'}
EVIDENCE_TYPES = {'choice':('single_choice','multiple_choice'),
                  'numeric_result':('numeric_scalar',), 'text_excerpt':('text',)}


class QuestionContent(ContractModel):
    prompt: Text
    source_refs: list[str] = Field(min_length=1, max_length=20)

    @field_validator('source_refs')
    @classmethod
    def unique_refs(cls, value):
        if len(value)!=len(set(value)):raise ValueError('source_refs must contain unique references')
        return value


class SingleChoiceContent(QuestionContent):
    options: list[Text] = Field(min_length=2, max_length=20)
    correct_option: int = Field(ge=1, le=20, description='1-based index into options')
    max_score: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def answer_exists(self):
        if self.correct_option>len(self.options):raise ValueError('correct_option must select an existing option')
        return self


class MultipleChoiceContent(QuestionContent):
    options: list[Text] = Field(min_length=2, max_length=20)
    correct_options: list[int] = Field(min_length=1, max_length=20)
    max_score: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode='after')
    def answers_exist(self):
        ids=self.correct_options
        if len(ids)!=len(set(ids)) or any(i<1 or i>len(self.options) for i in ids):
            raise ValueError('correct_options must be unique 1-based indices into options')
        return self


class NumericAnswerContent(ContractModel):
    expected: float = Field(allow_inf_nan=False)
    unit: Literal[tuple(UNIT_RULES)] | None = None


class NumericContent(QuestionContent):
    numeric_rules: NumericAnswerContent
    max_score: float = Field(gt=0, allow_inf_nan=False)


class CriterionContent(ContractModel):
    description: Text
    max_score: float = Field(gt=0, allow_inf_nan=False)
    acceptable_alternatives: list[Text] = Field(default_factory=list,max_length=20)
    critical: bool = False


@dataclass(frozen=True)
class QuestionSlot:
    key: str
    question_type: str
    objective_ids: tuple[str,...]
    criterion_ids: tuple[str,...]
    citations: tuple[SourceCitation,...]


@dataclass(frozen=True)
class QuizContentContract:
    schema: type[ContractModel]
    slots: tuple[QuestionSlot,...]
    numeric_abs_tolerance: float
    numeric_rel_tolerance: float

    def assemble(self, raw, *, project_id, node_id, assessment_id, snapshot, previous_assessment_id):
        content=self.schema.model_validate(data(raw));questions=[]
        versions={r.evaluator_id:r.evaluator_version for r in snapshot.evaluator_manifest}
        for slot in self.slots:
            item=getattr(content,slot.key)
            qid='question_'+sha256((assessment_id+':'+slot.key).encode()).hexdigest()[:24]
            evaluator=TYPE_EVALUATOR[slot.question_type]
            q={'question_id':qid,'objective_ids':list(slot.objective_ids),'question_type':slot.question_type,
               'prompt':item.prompt,'evaluator_id':evaluator,'evaluator_version':versions[evaluator],
               'source_citations':[slot.citations[int(ref[1:])-1].model_dump() for ref in item.source_refs]}
            if slot.question_type in {'single_choice','multiple_choice'}:
                q['options']=[{'option_id':'option_'+str(i),'text':text} for i,text in enumerate(item.options,1)]
                q['answer_key']='option_'+str(item.correct_option) if slot.question_type=='single_choice' else [
                    'option_'+str(i) for i in item.correct_options]
                q['max_score']=item.max_score
            elif slot.question_type=='numeric_scalar':
                unit=item.numeric_rules.unit
                allowed=[] if unit is None else ([unit] if UNIT_RULES[unit][0]=='scalar' else [
                    name for name,rule in UNIT_RULES.items() if rule[0]==UNIT_RULES[unit][0]])
                q.update(numeric_rules=NumericRules(expected=item.numeric_rules.expected,unit=unit,
                    allowed_units=allowed,abs_tolerance=self.numeric_abs_tolerance,
                    rel_tolerance=self.numeric_rel_tolerance).model_dump(),answer_key=None,max_score=item.max_score)
            else:
                q['answer_key']=item.reference_answer
                q['rubric']=[{'criterion_id':identity,**getattr(item.rubric,'r'+str(i)).model_dump()}
                    for i,identity in enumerate(slot.criterion_ids,1)]
                # This total is derived, not a model field silently overwritten.
                q['max_score']=fsum(c['max_score'] for c in q['rubric'])
            questions.append(q)
        return AssessmentQuiz(project_id=project_id,node_id=node_id,assessment_id=assessment_id,
            snapshot=snapshot,previous_assessment_id=previous_assessment_id,questions=questions)


def build_content_contract(node, policy, bound):
    """Allocate coverage before generation; merge only when the 10-item cap requires it."""
    objectives={o.objective_id:o for o in node.objectives}
    rules={r.objective_id:r for r in policy.objective_rules}
    selected=[o for o in node.objectives if o.required] or list(node.objectives)
    groups=[]
    for objective in selected:
        types=[]
        for evidence in objective.evidence_requirement:
            available=[t for t in EVIDENCE_TYPES[evidence] if t in policy.allowed_question_types
                       and TYPE_EVALUATOR[t] in objective.required_capability_ids]
            if not available:raise ValueError('Frozen objective has no executable question type')
            types.append(available[0])
        for index in range(max(len(types),rules[objective.objective_id].min_items)):
            groups.append((types[index%len(types)],(objective.objective_id,)))
    # Merging preserves each objective's item count and evidence kind. Unmapped
    # text objectives cannot be merged under the existing business contract.
    while len(groups)>SERVER_LIMITS.max_questions_per_assessment:
        merged=False
        for kind in ('single_choice','multiple_choice','text','numeric_scalar'):
            for i,(left_type,left) in enumerate(groups):
                if left_type!=kind:continue
                for j in range(i+1,len(groups)):
                    right_type,right=groups[j]
                    if right_type!=kind or set(left)&set(right) or len(left)+len(right)>5:continue
                    combined=left+right
                    if kind=='text' and (any(not objectives[k].criterion_ids for k in combined)
                        or len({c for k in combined for c in objectives[k].criterion_ids})>20):continue
                    groups[i]=(kind,combined);groups.pop(j);merged=True;break
                if merged:break
            if merged:break
        if not merged:raise ValueError('Frozen coverage cannot fit the question limit; no objective was dropped')
    fields={};slots=[];models={};rubric_models={}
    for index,(kind,goal_ids) in enumerate(groups,1):
        key='q'+str(index);citations=[];seen=set()
        for goal_id in goal_ids:
            for block in bound[goal_id]['blocks']:
                raw=block['citation'];identity=(raw['source_id'],raw['source_version'],raw['chunk_id'])
                if identity in seen:continue
                seen.add(identity);citations.append(SourceCitation(source_id=identity[0],source_version=identity[1],chunk_id=identity[2]))
        criteria=tuple(dict.fromkeys(c for goal_id in goal_ids for c in objectives[goal_id].criterion_ids)) if kind=='text' else ()
        if kind=='text' and not criteria:
            # Only previously unmapped objectives receive a new draft criterion.
            criteria=('criterion_'+key+'_1',)
        signature=(kind,len(citations),len(criteria))
        if signature not in models:
            refs=tuple('b'+str(i) for i in range(1,len(citations)+1))
            base={'single_choice':SingleChoiceContent,'multiple_choice':MultipleChoiceContent,
                  'numeric_scalar':NumericContent,'text':QuestionContent}[kind]
            extra={'source_refs':(list[Literal[refs]],Field(min_length=1,max_length=20))}
            if kind=='text':
                size=len(criteria)
                if size not in rubric_models:
                    rubric_models[size]=create_model('RubricContent'+str(size),__base__=ContractModel,
                        **{'r'+str(i):(CriterionContent,...) for i in range(1,size+1)})
                extra.update(reference_answer=(Text,...),rubric=(rubric_models[size],...))
            models[signature]=create_model(kind.title().replace('_','')+'Content'+str(len(models)+1),__base__=base,**extra)
        fields[key]=(models[signature],...)
        slots.append(QuestionSlot(key,kind,goal_ids,criteria,tuple(citations)))
    return QuizContentContract(create_model('QuizContent',__base__=ContractModel,**fields),tuple(slots),
        policy.numeric_abs_tolerance,policy.numeric_rel_tolerance)


def content_payload(contract,node,policy,bound,previous_question_prompts):
    """Only content and slot references are sent back by the model."""
    objectives={o.objective_id:o for o in node.objectives};slots={}
    for slot in contract.slots:
        lookup={(c.source_id,c.source_version,c.chunk_id):'b'+str(i) for i,c in enumerate(slot.citations,1)}
        blocks={};goals=[]
        for goal_id in slot.objective_ids:
            refs=[]
            for block in bound[goal_id]['blocks']:
                c=block['citation'];ref=lookup[(c['source_id'],c['source_version'],c['chunk_id'])]
                refs.append(ref);blocks[ref]=block['content']
            goals.append({'outcome':objectives[goal_id].observable_outcome,'source_refs':refs})
        slots[slot.key]={'question_type':slot.question_type,'goals':goals,'source_blocks':blocks,
            'output_fields':list(contract.schema.model_fields[slot.key].annotation.model_fields)}
        if slot.criterion_ids:
            slots[slot.key]['rubric_slots']={'r'+str(i):{'frozen_standard_label':identity,
                'goals':[objectives[k].observable_outcome for k in slot.objective_ids
                         if not objectives[k].criterion_ids or identity in objectives[k].criterion_ids]}
                for i,identity in enumerate(slot.criterion_ids,1)}
    return {'slots':slots,'previous_question_prompts':list(previous_question_prompts),
        'numeric_tolerance_ceiling':{'absolute':policy.numeric_abs_tolerance,'relative':policy.numeric_rel_tolerance},
        'supported_numeric_units':sorted(UNIT_RULES),'schema':contract.schema.model_json_schema()}
