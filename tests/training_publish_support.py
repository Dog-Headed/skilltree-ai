"""Build a server-side course draft the way a confirmed Planner result is stored."""
import json
from uuid import uuid4

from app.v3.contracts import EvaluationPolicy, LearningPlan
from app.v3.learning_repository import LearningRepository
from app.v3.materials import MaterialService


def learning_profile(title, capabilities):
    return {
        'subject_label': '单位制度',
        'topic': title[:256],
        'goal': f'完成《{title}》中的已确认要点',
        'bounded_goal': f'掌握《{title}》里已经写明的规则、范围和作答要求',
        'target_level': '入门',
        'learning_mode': 'formal',
        'requested_capabilities': list(capabilities),
        'scope_in': [title[:80] or '单位课程'],
        'scope_out': ['未写入本课程的内容'],
        'prior_knowledge': {'self_reported': ['已阅读单位资料']},
    }


def choice_objective(objective_id, chunk_ref, outcome):
    return {
        'objective_id': objective_id,
        'observable_outcome': outcome,
        'required_capability_ids': ['choice_exact'],
        'evidence_requirement': ['choice'],
        'required': True,
        'source_chunk_ids': [chunk_ref],
        'assessment_tasks': [{
            'task_form': 'choice',
            'submission': '选项作答',
            'requirements': ['根据资料判断正确表述'],
            'criteria': ['选项必须能被资料原文支持'],
        }],
    }


def chain_nodes(chunk_ref='$0'):
    specs = [
        ('n1', '时限要求', [], '从给定选项中判断新员工完成基础制度学习的时限'),
        ('n2', '适用范围', ['n1'], '从给定选项中判断基础制度的适用范围'),
        ('n3', '常见问题', ['n2'], '从给定选项中判断基础制度学习的常见要求'),
    ]
    return [{
        'node_id': node_id,
        'title': title,
        'description': f'学习「{title}」，并按资料做出选择。',
        'prerequisite_ids': prerequisites,
        'objectives': [choice_objective(f'obj_{node_id}', chunk_ref, outcome)],
    } for node_id, title, prerequisites, outcome in specs]


def policy_for(objectives, capabilities, threshold=0.8):
    evaluators = []
    types = []
    if 'choice_exact' in capabilities:
        evaluators.append({'evaluator_id': 'choice_exact', 'evaluator_version': '1.0.0'})
        types.extend(['single_choice', 'multiple_choice'])
    if 'text_rubric' in capabilities:
        evaluators.append({'evaluator_id': 'text_rubric', 'evaluator_version': '1.0.0'})
        types.append('text')
    return EvaluationPolicy.model_validate({
        'policy_id': 'policy_unit_course',
        'policy_version': '1.0.0',
        'allowed_question_types': types,
        'evaluators': evaluators,
        'objective_rules': [{
            'objective_id': item['objective_id'],
            'required': item.get('required', True),
            'evidence_kinds': list(item['evidence_requirement']),
            'min_items': 1,
            'min_evidence': 1,
            'weight': 1.0,
            'pass_threshold': threshold,
        } for item in objectives],
        'total_pass_threshold': threshold,
        'critical_severities': ['critical'],
        'uncertain_handling': 'pause_review',
        'missing_evidence_handling': 'collect_more_evidence',
        'invalid_item_handling': 'replace_or_pause',
    })


def confirm_draft(client, gateway, admin, material_id, title, nodes, capabilities):
    """Attach a unit material and save a candidate plan at the current revision."""
    created = client.post('/projects', headers=admin, json={
        'request_id': str(uuid4()),
        'profile': learning_profile(title, capabilities),
    })
    assert created.status_code in {200, 201}, created.text
    project_id = created.json()['project_id']
    attached = client.post(
        '/training/api/admin/materials/' + material_id + '/attach', headers=admin,
        json={'project_id': project_id, 'request_id': str(uuid4())})
    assert attached.status_code == 200, attached.text
    objectives = [objective for node in nodes for objective in node['objectives']]
    with LearningRepository(gateway.paths) as repo:
        project = repo.get_project(project_id)
        catalog = MaterialService(repo).catalog(project_id)
        assert catalog, 'attached material produced no teaching chunks'
        resolved = json.loads(json.dumps(nodes))
        cited = []
        for node in resolved:
            for objective in node['objectives']:
                mapped = []
                for ref in objective['source_chunk_ids']:
                    if isinstance(ref, str) and ref.startswith('$'):
                        item = catalog[int(ref[1:])]
                    else:
                        item = next(chunk for chunk in catalog if chunk['chunk_id'] == ref)
                    mapped.append(item['chunk_id'])
                    cited.append(item['source_id'])
                objective['source_chunk_ids'] = mapped
        plan = LearningPlan.model_validate({
            'project_id': project_id,
            'draft_revision': project['draft_revision'],
            'plan_version': 1,
            'nodes': resolved,
        })
        policy = policy_for(objectives, capabilities, threshold=objectives[0].get('pass_threshold', 0.8))
        # Objectives carry an optional test-only threshold; the policy builder reads evidence fields.
        repo.save_candidate_plan(
            project_id, plan, expected_revision=project['draft_revision'], policy=policy)
        saved = repo.get_project(project_id)
    return {
        'project_id': project_id,
        'draft_revision': saved['draft_revision'],
        'material_version_ids': sorted(set(cited)),
        'node_ids': [node['node_id'] for node in resolved],
        'policy': policy.model_dump(mode='json'),
    }


def confirm_draft_with_policy(client, gateway, admin, material_id, title, nodes, capabilities, policy):
    draft = confirm_draft(client, gateway, admin, material_id, title, nodes, capabilities)
    with LearningRepository(gateway.paths) as repo:
        project = repo.get_project(draft['project_id'])
        plan = LearningPlan.model_validate(project['candidate_plan'])
        repo.save_candidate_plan(
            draft['project_id'], plan, expected_revision=project['draft_revision'], policy=policy)
        saved = repo.get_project(draft['project_id'])
    draft['draft_revision'] = saved['draft_revision']
    draft['policy'] = policy.model_dump(mode='json')
    return draft


def publish_payload(draft, *, title, course_id=None, request_id=None, required_nodes=None,
                    material_version_ids=None):
    payload = {
        'request_id': request_id or str(uuid4()),
        'title': title,
        'draft_project_id': draft['project_id'],
        'draft_revision': draft['draft_revision'],
        'required_nodes': required_nodes or draft['node_ids'],
        'material_version_ids': draft['material_version_ids'] if material_version_ids is None else material_version_ids,
    }
    if course_id:
        payload['course_id'] = course_id
    return payload
