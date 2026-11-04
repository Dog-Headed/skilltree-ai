"""Retired study-time metadata cannot constrain planning or change old records."""
import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.v3.contracts import LearningPlan, LearningProfile
from app.v3.learning_api import create_learning_app
from app.v3.onboarding import LearningIntent, infer_scope
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage
from app.services.llm import ModelCallBudget
from tests.test_goal_first import GuidedFake, act
from tests.test_planner_task_contract import Wire, proposal, generate
from tests.test_v3_preparation_content import Queue, scope_result


def test_new_profiles_and_model_plans_do_not_invent_study_times():
    profile = LearningIntent(goal='比较变量与循环').as_profile()
    assert not {'time_budget_minutes','session_minutes'} & profile.model_dump().keys()
    wire = Wire(proposal())
    plan = generate(wire)
    assert all('estimated_minutes' not in node for node in plan.model_dump()['nodes'])
    schema, payload, _ = wire.calls[0]
    assert 'estimated_minutes' not in schema.model_json_schema()['$defs']['PlanNodeContent']['properties']
    assert 'time_budget_minutes' not in json.dumps(payload)
    assert 'session_minutes' not in json.dumps(payload)


def test_explicit_legacy_short_times_no_longer_reject_generation_or_freezing(tmp_path):
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path/'course')))
    model = GuidedFake()
    with TestClient(create_learning_app(paths,llm=model)) as client:
        p = client.post('/projects',json={'request_id':str(uuid4()),'intent':{
            'goal':'解释变量与循环','time_budget_minutes':1,'session_minutes':30}}).json()
        old_profile = p['profile']
        p = act(client,p,'confirm_profile')
        assert p['page_state']=='plan_review' and p['nodes'][0]['estimated_minutes']>1
        p = act(client,p,'confirm_plan')
        assert p['frozen'] and not p.get('error_type')
        assert p['profile']['time_budget_minutes']==old_profile['time_budget_minutes']==1
        assert p['profile']['session_minutes']==old_profile['session_minutes']==30
        for call in model.inputs:
            messages='\n'.join(call['messages'])
            assert '"time_budget_minutes"' not in messages
            assert '"session_minutes"' not in messages


def test_legacy_profile_and_node_times_roundtrip_without_migration():
    from tests.test_v3_planner import profile,plan
    raw = profile(time_budget_minutes=90,session_minutes=30).model_dump()
    assert LearningProfile.model_validate(raw).model_dump()==raw
    saved = LearningPlan.model_validate(plan()).model_dump()
    assert LearningPlan.model_validate(saved).model_dump()==saved
    assert saved['nodes'][0]['estimated_minutes']==plan()['nodes'][0]['estimated_minutes']


def test_scope_ignores_legacy_numeric_time_but_preserves_user_goal():
    model=Queue(scope_result())
    infer_scope(model,ModelCallBudget(),{'intent':{'goal':'Softmax 数值稳定性',
        'time_budget_minutes':90,'session_minutes':30},'user_material_catalog':[]},generation_mode='content-v1')
    text='\n'.join(str(m.content) for m in model.messages[0])
    assert 'Softmax 数值稳定性' in text
    assert '"time_budget_minutes"' not in text and '"session_minutes"' not in text
