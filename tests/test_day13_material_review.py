"""Fake protocol/guard regressions, separate from real material-quality evidence."""
import json

import pytest

from app.v3.assessment import evaluate_quiz
from app.v3.contracts import LearningProfile
from app.v3.guard import decide_progress
from tests.test_v3_evaluators import FakeModel, setup, text_batch


@pytest.mark.parametrize('conflicting',[False,True])
def test_actual_supplement_reaches_grader_and_uncertainty_cannot_unlock_even_with_full_score(conflicting):
    quiz,answers,node,policy,contexts=setup()
    content='过去事件改写只能持续使用现在时。' if conflicting else 'Yesterday说明事情发生在过去。'
    attachment={'attachment_id':'supplement_1','visibility':'teaching','content':content}
    contexts['objective_0']['untrusted_supplement']=[attachment]
    batch=text_batch(quiz,answers)
    if conflicting:
        batch.update(grading_status='needs_review',uncertainty_reasons=[
            'chunk说明过去事件用一般过去时，但supplement_1写“'+content+'”，需要核对。'])
    model=FakeModel(batch)
    evaluation=evaluate_quiz(quiz=quiz,answers=answers,node=node,policy=policy,contexts=contexts,llm=model)
    payload=json.loads(model.calls[0][1].content.split('\n',1)[1])
    assert payload['grading_contexts']['objective_0']['untrusted_supplement']==[attachment]
    assert len(model.calls)==1
    # Deliberately propose advance even on a full numerical score with system
    # uncertainty. The deterministic guard must still send it to review.
    decision=decide_progress(quiz=quiz,evaluation=evaluation,node=node,policy=policy,
        profile=LearningProfile(subject_label='文字',topic='过去事件',goal='解释过去事件',bounded_goal='完成文字改写'),
        completed_node_ids=[],answers=answers,diagnosis={
            'project_id':quiz.project_id,'node_id':quiz.node_id,'assessment_id':quiz.assessment_id,
            'snapshot':quiz.snapshot.model_dump(),'action':'advance','reason':'Fake建议，用于验证程序仍审查状态。',
            'evidence_ids':[item.evidence_id for item in evaluation.evidence],'review_node_id':None})
    assert sum(q.score for q in evaluation.question_results)==10
    assert evaluation.grading_status==('needs_review' if conflicting else 'graded')
    assert decision.passed is (not conflicting)
    assert decision.effective_action==('assessment_review' if conflicting else 'advance')
