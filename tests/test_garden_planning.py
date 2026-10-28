"""Multi-session tree budgets and a branching plan through the real API."""
from uuid import uuid4

from fastapi.testclient import TestClient
from app.v3.learning_api import create_learning_app
from app.v3.onboarding import LearningIntent
from app.v3.storage import V3Paths, initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from tests.test_goal_first import GuidedFake, act, create


def test_planning_uses_a_longer_server_selected_timeout(monkeypatch):
    from app.services import llm
    monkeypatch.setattr(llm, 'get_llm', lambda **kwargs: kwargs)
    planning = llm.get_planning_llm()
    assert planning['timeout'] == 120


class BranchingFake(GuidedFake):
    def _plan(self, data):
        plan = super()._plan(data)
        template = plan['nodes'][0]
        # Foundation -> two independent branches -> a shared application.
        parents = [[], ['n0'], ['n0'], ['n1'], ['n2'], ['n3', 'n4'], ['n5'], ['n6']]
        plan['nodes'] = [
            {**template, 'node_id': f'n{i}', 'title': f'合成路线节点 {i}',
             'estimated_minutes': 30, 'prerequisite_ids': prerequisites,
             'objectives': [{**template['objectives'][0], 'objective_id': f'o{i}'}]}
            for i, prerequisites in enumerate(parents)
        ]
        return plan


def test_new_tree_default_is_multisession_and_explicit_short_budget_is_preserved():
    growth = LearningIntent(goal='从零开始学习Python').as_profile()
    assert growth.time_budget_minutes == 1440
    assert growth.session_minutes == 30
    short = LearningIntent(goal='只学一个运算规则', time_budget_minutes=45, session_minutes=15).as_profile()
    assert short.time_budget_minutes == 45
    assert short.session_minutes == 15


def test_branching_tree_survives_confirmation_and_reload_without_becoming_a_single_session(tmp_path):
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path / 'garden')))
    model = BranchingFake()
    client = TestClient(create_learning_app(paths, llm=model))
    tree, _ = create(client, '从零系统学习Python基础')
    tree = act(client, tree, 'confirm_profile')
    assert tree['page_state'] == 'plan_review'
    assert len(tree['nodes']) == 8
    assert sum(n['estimated_minutes'] for n in tree['nodes']) == 240
    assert tree['nodes'][5]['prerequisite_ids'] == ['n3', 'n4']
    tree = act(client, tree, 'confirm_plan')
    assert tree['frozen']
    count = len(model.calls)
    reloaded = client.get('/projects/' + tree['project_id']).json()
    assert len(reloaded['nodes']) == 8
    assert reloaded['profile']['session_minutes'] == 30
    assert model.calls and len(model.calls) == count


def test_existing_explicit_budget_is_not_migrated_on_read(tmp_path):
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path / 'existing')))
    client = TestClient(create_learning_app(paths, llm=GuidedFake()))
    response = client.post('/projects', json={'request_id': str(uuid4()), 'intent': {
        'goal': '原有120分钟学习树', 'time_budget_minutes': 120, 'session_minutes': 30}})
    assert response.status_code == 201
    tree = response.json()
    restarted = TestClient(create_learning_app(paths, llm=GuidedFake()))
    reloaded = restarted.get('/projects/' + tree['project_id']).json()
    assert reloaded['profile']['time_budget_minutes'] == 120
    assert reloaded['profile'] == tree['profile']


def test_long_rejected_plan_is_repaired_without_truncating_teaching_sources():
    from copy import deepcopy
    from tests.test_v3_planner import FakeModel, generate, plan, catalog
    good = plan()
    node = good['nodes'][0]
    good['nodes'] = []
    for i in range(20):
        item = deepcopy(node)
        item.update(node_id=f'node_{i}', title=f'变量和循环 {i}', estimated_minutes=1,
                    description='解释变量与循环。' * 80,
                    prerequisite_ids=[f'node_{i-1}'] if i else [])
        item['objectives'][0]['objective_id'] = f'objective_{i}'
        good['nodes'].append(item)
    bad = deepcopy(good)
    bad['nodes'][0]['objectives'][0]['source_chunk_ids'] = ['nonexistent_chunk']
    source = catalog('变量保存值。循环会重复执行；停止条件决定循环何时结束。' * 60)
    model = FakeModel(bad, good)
    result = generate(model, selected_catalog=source)
    assert len(result.nodes) == 20
    assert len(model.messages) == 2
    corrected = '\n'.join(str(m.content) for m in model.messages[1])
    assert 'previous_output_omitted' in corrected
    assert source[0]['content'] in corrected
    assert 'nonexistent_chunk' in corrected
    assert len(corrected) <= 24000


def test_learning_tasks_get_server_selected_timeouts(monkeypatch, tmp_path):
    from app.services import llm
    from app.v3.learning import LearningService
    monkeypatch.setattr(llm, 'get_llm', lambda **kwargs: kwargs)
    assert llm.get_task_llm('grade')['timeout'] == 180
    assert llm.get_task_llm('quiz')['timeout'] == 120
    assert llm.get_task_llm('diagnosis')['timeout'] == 120
    assert llm.get_task_llm('tutor')['timeout'] == 45
    paths = initialize_learning_storage(initialize_storage(V3Paths(tmp_path / 'timeouts')))
    # The provider stays lazy: no client is built until a task actually calls the model.
    provider = LearningService(paths)._provider('grade')
    assert callable(provider) and not hasattr(provider, 'invoke')
    assert provider()['timeout'] == 180
    injected = GuidedFake()
    assert LearningService(paths, llm=injected)._provider('grade') is injected


def test_planner_schema_and_catalog_only_offer_confirmed_project_capabilities():
    import json
    from app.v3 import planner
    from app.v3.contracts import LearningPlan
    from tests.test_v3_planner import profile, catalog
    from app.v3.preparation import policy_template
    from app.v3.planner import PlannerMaterial

    for capabilities in [['text_rubric'], ['choice_exact', 'numeric_scalar']]:
        p = profile(requested_capabilities=capabilities)
        messages = planner.build_planner_messages(profile=p, project_id='project_1', draft_revision=3,
            material_catalog=[PlannerMaterial.model_validate(catalog()[0])], policy=policy_template(p))
        payload = json.loads(messages[1].content.split('\n', 1)[1])
        allowed = payload['learning_plan_schema']['$defs']['LearningObjective']['properties']['required_capability_ids']['items']['enum']
        assert allowed == capabilities == payload['allowed_objective_capability_ids']
        assert {item['capability_id'] for item in payload['capabilities']} == set(capabilities)
    # A project-specific model hint must never mutate the shared contract schema.
    assert 'enum' not in LearningPlan.model_json_schema()['$defs']['LearningObjective']['properties']['required_capability_ids']['items']


def test_full_multibranch_notes_and_long_repair_stay_inside_production_context_budget():
    import json
    from copy import deepcopy
    from hashlib import sha256
    from app.services.llm import RepairContext
    from app.v3.contracts import SourceDocument, LearningProfile
    from app.v3.materials import chunk_document
    from app.v3.planner import PlannerMaterial, build_planner_messages
    from app.v3.preparation import policy_template

    pid = 'v3_' + 'a' * 32
    section = '有理数包含正数、零和负数。等式两边同加或同减同一个数仍相等。计算后将解代回原方程检验。'
    notes = '\n'.join('## 学习分支' + str(i) + '\n' + (section * 20)[:465] for i in range(12))
    document = SourceDocument(project_id=pid, source_id='ai_notes_' + 'b' * 32, source_version=1,
        title='AI整理 · 有理数与一元一次方程的完整初始学习路线', source_description='synthetic budget regression',
        content=notes, content_hash=sha256(notes.encode()).hexdigest())
    material = []
    for chunk in chunk_document(document):
        data = {**chunk.model_dump(), 'title': document.title, 'visibility': 'teaching'}
        material.append(PlannerMaterial.model_validate({k: v for k, v in data.items() if k in PlannerMaterial.model_fields}))
    p = LearningProfile(subject_label='数学', topic='有理数与方程', goal='从零系统学习有理数与一元一次方程',
        bounded_goal='解释有理数、等式性质并多步求解和检验', scope_in=['完整学习分支' + str(i) for i in range(12)],
        requested_capabilities=['choice_exact', 'numeric_scalar', 'text_rubric'], time_budget_minutes=1440)
    rejected = {'nodes': [{'node_id': 'node_' + str(i), 'title': '合成节点' + str(i),
        'description': 'long rejected candidate ' * 200, 'prerequisite_ids': []} for i in range(20)]}
    messages = build_planner_messages(profile=p, project_id=pid, draft_revision=3,
        material_catalog=material, policy=policy_template(p),
        repair_context=RepairContext(previous_output=deepcopy(rejected), error_message='invalid synthetic objective'))
    assert len(notes) > 5500 and len(material) == 12
    assert sum(len(str(m.content)) for m in messages) <= 24000
    assert 'previous_output_omitted' in messages[-1].content
    supplied = json.loads(messages[1].content.split('\n', 1)[1])['teaching_material_catalog']
    assert [chunk['content'] for chunk in supplied] == [chunk.content for chunk in material]
    assert all('content_hash' not in chunk and 'project_id' not in chunk for chunk in supplied)


def test_preparation_repair_receives_the_field_error_without_private_completion():
    from langchain_core.exceptions import OutputParserException
    from pydantic import ValidationError
    from app.services.llm import ModelCallBudget
    from app.v3.onboarding import generate_notes, StudyNotes

    secret = 'PRIVATE_SYNTHETIC_NOTES_' * 400
    try:
        StudyNotes.model_validate({'content': secret})
    except ValidationError as exc:
        cause = exc

    class Repair:
        def __init__(self): self.messages = []
        def with_structured_output(self, schema, **kwargs): return self
        def invoke(self, messages):
            self.messages.append(messages)
            if len(self.messages) == 1:
                raise OutputParserException('private raw completion: ' + secret) from cause
            return StudyNotes(content='Synthetic valid course notes. ' * 10)

    model = Repair()
    budget = ModelCallBudget()
    generate_notes(model, budget, {'profile': {'goal': 'synthetic'}})
    error = model.messages[1][-1].content
    assert 'content' in error and 'string_too_long' in error
    assert 'PRIVATE_SYNTHETIC_NOTES_' not in error
    assert budget.request_count == 2 and budget.output_repair_count == 1


def test_short_source_references_restore_only_verified_ids_without_changing_content():
    from copy import deepcopy
    import pytest
    from tests.test_v3_planner import FakeModel, generate, plan
    from app.services.llm import ModelOutputValidationError
    good = plan()
    good['nodes'][0]['objectives'][0]['source_chunk_ids'] = ['s1']
    assert generate(FakeModel(good)).nodes[0].objectives[0].source_chunk_ids == ['chunk_1']
    bad = deepcopy(good)
    bad['nodes'][0]['objectives'][0]['source_chunk_ids'] = ['s999']
    model = FakeModel(bad, bad)
    with pytest.raises(ModelOutputValidationError): generate(model)
    assert len(model.messages) == 2
