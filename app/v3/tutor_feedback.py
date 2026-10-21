"""Bounded remediation facts; private quiz standards never become Tutor data."""
import json
import re
from typing import Literal

from pydantic import Field

from .contracts import ContractModel, Identity, EvaluationResult, AssessmentQuiz, EvaluationPolicy


class FeedbackObjective(ContractModel):
    objective_id: Identity
    observable_outcome: str = Field(max_length=300)
    score_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)


class FeedbackAnswer(ContractModel):
    question_id: Identity
    objective_ids: list[Identity] = Field(max_length=5)
    prompt: str = Field(max_length=160)
    student_answer_excerpt: str = Field(max_length=400)
    answer_truncated: bool
    score: float = Field(ge=0, allow_inf_nan=False)
    max_score: float = Field(gt=0, allow_inf_nan=False)
    feedback: str = Field(max_length=200)


class TutorFeedback(ContractModel):
    project_id: Identity
    node_id: Identity
    assessment_id: Identity
    review_node_id: Identity | None = None
    recommended_action: Literal['advance','remediate','revisit_prerequisite','collect_more_evidence']
    diagnosis_reason: str = Field(max_length=600)
    failed_objectives: list[FeedbackObjective] = Field(max_length=5)
    questions: list[FeedbackAnswer] = Field(max_length=10)


class PrivateFeedbackFilter:
    """Conservatively omit feedback quoting known private standards.

    Student-owned answer excerpts and public prompts remain separately typed.
    Long private literals are also checked on model output, without sending
    this deny-list to the model. This does not prove semantic paraphrase safety.
    """
    def __init__(self, fragments, public_text=()):
        self.fragments=tuple(dict.fromkeys(part.strip() for value in fragments if isinstance(value,str)
            for part in [value,*re.split(r'[\r\n。！？!?；;]',value)]
            if part.strip() and not any(part.strip() in text for text in public_text)))

    def public(self,text,fallback,limit):
        if re.search(r'正确答案|参考答案|私有量规|answer\s*key|correct\s*answer',text,re.I) or any(part in text for part in self.fragments):
            return fallback[:limit]
        return text[:limit]

    def validate_reply(self,reply):
        if any(len(part)>=8 and part in reply.text for part in self.fragments):
            raise ValueError('Tutor输出引用了私有答案或评分资料，请仅围绕公开目标与学生作答补弱')


def build_tutor_feedback(repo,project_id,session):
    if session['mode'] not in ('remediate','review'):return None,None
    row=repo.get_assessment(project_id,session['current_assessment_id'])
    if not row or not row['evaluation_json'] or not row['diagnosis_json']:
        raise ValueError('补弱必须有本轮持久化评价与诊断依据')
    quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json']))
    evaluation=EvaluationResult.model_validate(json.loads(row['evaluation_json']))
    diagnosis=json.loads(row['diagnosis_json'])
    node=repo.node(project_id,row['node_id'])
    if quiz.project_id!=project_id or node.node_id!=session['current_node_id'] or evaluation.grading_status!='graded':
        raise ValueError('补弱依据不属于当前项目节点的有效测评')
    # Read exact frozen versions only. Neither the originals nor private quiz
    # fields below are serialized into Tutor input or the public page.
    fragments=[]
    for question in quiz.questions:
        if isinstance(question.answer_key,str):fragments.append(question.answer_key)
        elif question.answer_key:fragments.extend(question.answer_key)
        if question.numeric_rules:fragments.append(str(question.numeric_rules.expected))
        fragments.extend(criterion.description for criterion in question.rubric)
    frozen={(ref.source_id,ref.source_version) for ref in quiz.snapshot.source_manifest}
    public_text=[obj.observable_outcome for obj in node.objectives]
    public_text.extend(question.prompt for question in quiz.questions)
    public_text.extend(option.text for question in quiz.questions for option in question.options)
    for document in repo.list_sources(project_id,include_private=True):
        if document['visibility']=='assessment_private' and (document['source_id'],document['source_version']) in frozen:
            fragments.append(document['content'])
        elif document['visibility']=='teaching' and (document['source_id'],document['source_version']) in frozen:
            public_text.append(document['content'])
    privacy=PrivateFeedbackFilter(fragments,public_text)
    policy=EvaluationPolicy.model_validate(repo.get_project(project_id)['policy'])
    thresholds={rule.objective_id:rule.pass_threshold for rule in policy.objective_rules}
    objectives={obj.objective_id:obj for obj in node.objectives}
    failed=[FeedbackObjective(objective_id=item.objective_id,
        observable_outcome=objectives[item.objective_id].observable_outcome[:300],score_ratio=item.score_ratio)
        for item in evaluation.objective_results if item.score_ratio<thresholds[item.objective_id]]
    failed_ids={item.objective_id for item in failed}
    questions={question.question_id:question for question in quiz.questions}
    answers=json.loads(row['answers_json'])
    responses=[]
    for result in evaluation.question_results:
        question=questions[result.question_id]
        if result.score==result.max_score and failed_ids and not failed_ids.intersection(question.objective_ids):continue
        answer=answers[result.question_id]
        text=answer if isinstance(answer,str) else ', '.join(answer)
        responses.append(FeedbackAnswer(question_id=result.question_id,objective_ids=question.objective_ids,
            prompt=question.prompt[:160],student_answer_excerpt=text[:400],answer_truncated=len(text)>400,
            score=result.score,max_score=result.max_score,
            feedback=privacy.public(result.feedback,'本题未达到所列目标要求，请结合学生原作答进行解释。',200)))
    feedback=TutorFeedback(project_id=project_id,node_id=node.node_id,assessment_id=quiz.assessment_id,
        review_node_id=diagnosis['review_node_id'],recommended_action=diagnosis['action'],
        diagnosis_reason=privacy.public(diagnosis['reason'],'本轮需针对学生作答补弱或收集更完整的目标证据。',600),
        failed_objectives=failed,questions=responses)
    return feedback,privacy.validate_reply
