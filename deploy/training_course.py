"""Publish a confirmed planner draft and rebuild employee plans from it.

The browser does not supply the knowledge tree. Publication reads a draft the
caller owns, at an explicit revision, and stores source anchors so each
employee project can remap those anchors onto its own chunks.
"""
from __future__ import annotations

import json

from app.v3.capabilities import get_capability, validate_evaluation_policy
from app.v3.contracts import EvaluationPolicy, LearningPlan, LearningProfile
from app.v3.learning_repository import LearningRepository
from app.v3.materials import MaterialService
from app.v3.planner import validate_learnability


KNOWN_PASS_RULES = frozenset({'all_required_nodes'})


def source_anchor(material_id: str, chunk: dict) -> str:
    return f"ref_{material_id}_{int(chunk['line_start'])}_{int(chunk['line_end'])}_{chunk['content_hash'][:12]}"


def teaching_chunks(repo, project_id: str) -> list[dict]:
    """Latest teaching chunks for one project, with source title attached."""
    latest = {}
    for raw in repo.list_sources(project_id, include_private=True):
        if raw.get('visibility') != 'teaching':
            continue
        previous = latest.get(raw['source_id'])
        if previous is None or raw['source_version'] > previous['source_version']:
            latest[raw['source_id']] = raw
    chunks = []
    for source in latest.values():
        rows = repo.list_source_chunks(
            project_id, source['source_id'], source['source_version'], include_private=False)
        for chunk in rows:
            chunks.append({**chunk, 'title': source.get('title') or source['source_id']})
    return chunks


def planner_catalog(chunks: list[dict], project_id: str) -> list[dict]:
    return [{
        'chunk_id': chunk['chunk_id'],
        'project_id': project_id,
        'source_id': chunk['source_id'],
        'source_version': chunk['source_version'],
        'content_hash': chunk['content_hash'],
        'content': chunk['content'],
        'title': chunk.get('title') or chunk['source_id'],
        'heading': chunk.get('heading'),
        'visibility': 'teaching',
    } for chunk in chunks]


def _fail_plan(exc: Exception) -> None:
    text = str(exc)
    if '依赖环' in text or '依赖自己' in text:
        raise ValueError('invalid_course_cycle') from exc
    if '不存在的节点' in text or '不存在' in text:
        raise ValueError('invalid_course_dangling_dependency') from exc
    if '重复' in text:
        raise ValueError('invalid_course_duplicate') from exc
    raise ValueError('invalid_course') from exc


def assert_course_publishable(tree, required_nodes, pass_rule, material_version_ids):
    """Reject a course that cannot be learned. Raises before any publish write."""
    if not isinstance(tree, dict) or not isinstance(tree.get('nodes'), list) or not tree['nodes']:
        raise ValueError('invalid_course_empty')
    if not isinstance(required_nodes, list) or not required_nodes:
        raise ValueError('invalid_course_dangling_required')
    if len(set(required_nodes)) != len(required_nodes):
        raise ValueError('invalid_course_duplicate')
    if not isinstance(pass_rule, dict) or pass_rule.get('rule') not in KNOWN_PASS_RULES:
        raise ValueError('invalid_course_unknown_rule')
    if not isinstance(pass_rule.get('policy'), dict):
        raise ValueError('invalid_course_policy')
    nodes = tree['nodes']
    identities = []
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('node_id'), str) or not node['node_id']:
            raise ValueError('invalid_course_empty')
        identities.append(node['node_id'])
        objectives = node.get('objectives')
        if not isinstance(objectives, list) or not objectives:
            raise ValueError('invalid_course_objectives')
        prerequisites = node.get('prerequisite_ids') or []
        if not isinstance(prerequisites, list):
            raise ValueError('invalid_course_dangling_dependency')
    if len(set(identities)) != len(identities):
        raise ValueError('invalid_course_duplicate')
    known = set(identities)
    if any(node_id not in known for node_id in required_nodes):
        raise ValueError('invalid_course_dangling_required')
    for node in nodes:
        if any(item not in known for item in (node.get('prerequisite_ids') or [])):
            raise ValueError('invalid_course_dangling_dependency')
    try:
        plan = LearningPlan.model_validate({
            'project_id': 'published_course',
            'plan_version': int(tree.get('plan_version') or 1),
            'draft_revision': 0,
            'nodes': nodes,
        })
    except Exception as exc:
        _fail_plan(exc)
    index = tree.get('source_index')
    if not isinstance(index, list) or not index:
        raise ValueError('invalid_course_source')
    anchors = {}
    for item in index:
        if not isinstance(item, dict) or not item.get('anchor') or not item.get('material_version_id'):
            raise ValueError('invalid_course_source')
        if item['anchor'] in anchors:
            raise ValueError('invalid_course_source')
        anchors[item['anchor']] = item
    referenced = set()
    for node in plan.nodes:
        for objective in node.objectives:
            if not objective.source_chunk_ids:
                raise ValueError('invalid_course_source')
            for ref in objective.source_chunk_ids:
                item = anchors.get(ref)
                if item is None:
                    raise ValueError('invalid_course_source')
                referenced.add(item['material_version_id'])
    if not isinstance(material_version_ids, list) or set(material_version_ids) != referenced:
        raise ValueError('invalid_course_source')
    try:
        policy = validate_evaluation_policy(pass_rule['policy'])
    except Exception as exc:
        raise ValueError('invalid_course_policy') from exc
    objective_ids = {objective.objective_id for node in plan.nodes for objective in node.objectives}
    rules = {rule.objective_id: rule for rule in policy.objective_rules}
    if set(rules) != objective_ids:
        raise ValueError('invalid_course_policy')
    for node in plan.nodes:
        for objective in node.objectives:
            rule = rules[objective.objective_id]
            if rule.required != objective.required or not set(objective.evidence_requirement) <= set(rule.evidence_kinds):
                raise ValueError('invalid_course_policy')
            for capability_id in objective.required_capability_ids:
                capability = get_capability(capability_id)
                if capability is None or capability.kind != 'evaluation' or not capability.evaluator_id:
                    raise ValueError('invalid_course_policy')
    return plan, policy


def course_executable(course: dict) -> bool:
    tree = course.get('tree') if isinstance(course.get('tree'), dict) else {}
    rule = course.get('pass_rule') if isinstance(course.get('pass_rule'), dict) else {}
    nodes = tree.get('nodes')
    return bool(
        isinstance(nodes, list) and nodes
        and isinstance(tree.get('source_index'), list) and tree['source_index']
        and rule.get('rule') == 'all_required_nodes'
        and isinstance(rule.get('policy'), dict)
        and all(isinstance(node, dict) and node.get('objectives') for node in nodes)
    )


def _closure(nodes: list[dict], required: list) -> list[dict]:
    by_id = {}
    for node in nodes:
        node_id = node.get('node_id') if isinstance(node, dict) else None
        if not isinstance(node_id, str) or node_id in by_id:
            raise ValueError('course_needs_republish')
        by_id[node_id] = node
    if not required or any(node_id not in by_id for node_id in required):
        raise ValueError('course_needs_republish')
    needed = set()
    stack = list(required)
    while stack:
        node_id = stack.pop()
        if node_id in needed:
            continue
        node = by_id.get(node_id)
        if node is None:
            raise ValueError('course_needs_republish')
        needed.add(node_id)
        prerequisites = node.get('prerequisite_ids') or []
        if not isinstance(prerequisites, list):
            raise ValueError('course_needs_republish')
        for item in prerequisites:
            if item not in needed:
                stack.append(item)
    return [node for node in nodes if node.get('node_id') in needed]


def published_capabilities(course: dict) -> list[str]:
    if not course_executable(course):
        raise ValueError('course_needs_republish')
    selected = _closure(course['tree']['nodes'], list(course.get('required_nodes') or []))
    capabilities = []
    for node in selected:
        for objective in node.get('objectives') or []:
            for capability_id in objective.get('required_capability_ids') or []:
                if capability_id not in capabilities:
                    capabilities.append(capability_id)
    if not capabilities:
        raise ValueError('course_needs_republish')
    return capabilities


def employee_plan(project_id: str, draft_revision: int, course: dict, chunks: list[dict]) -> LearningPlan:
    """Keep the published DAG, objectives and per-objective source anchors."""
    if not course_executable(course):
        raise ValueError('course_needs_republish')
    selected = _closure(course['tree']['nodes'], list(course.get('required_nodes') or []))
    by_anchor = {source_anchor(chunk['source_id'], chunk): chunk['chunk_id'] for chunk in chunks}
    rewritten = []
    for node in selected:
        raw = json.loads(json.dumps(node, ensure_ascii=False))
        raw['prerequisite_ids'] = list(raw.get('prerequisite_ids') or [])
        for objective in raw.get('objectives') or []:
            mapped = []
            for ref in objective.get('source_chunk_ids') or []:
                chunk_id = by_anchor.get(ref)
                if not chunk_id:
                    raise ValueError('source_mapping_failed')
                mapped.append(chunk_id)
            if not mapped or len(mapped) != len(set(mapped)):
                raise ValueError('source_mapping_failed')
            objective['source_chunk_ids'] = mapped
        rewritten.append(raw)
    try:
        return LearningPlan.model_validate({
            'project_id': project_id,
            'plan_version': int(course['tree'].get('plan_version') or 1),
            'draft_revision': draft_revision,
            'nodes': rewritten,
        })
    except Exception as exc:
        raise ValueError('course_needs_republish') from exc


def employee_policy(course: dict, plan: LearningPlan) -> EvaluationPolicy:
    """Use the published thresholds. Do not substitute the choice-foundation 0.8 default."""
    if not course_executable(course):
        raise ValueError('course_needs_republish')
    data = json.loads(json.dumps(course['pass_rule']['policy'], ensure_ascii=False))
    wanted = {objective.objective_id for node in plan.nodes for objective in node.objectives}
    rules = [rule for rule in data.get('objective_rules') or [] if rule.get('objective_id') in wanted]
    if {rule.get('objective_id') for rule in rules} != wanted:
        raise ValueError('course_needs_republish')
    data['objective_rules'] = rules
    try:
        return validate_evaluation_policy(data)
    except Exception as exc:
        raise ValueError('course_needs_republish') from exc


def _policy_preview(policy: dict | None) -> dict | None:
    if not isinstance(policy, dict):
        return None
    rules = []
    for rule in policy.get('objective_rules') or []:
        if not isinstance(rule, dict):
            continue
        rules.append({
            'objective_id': rule.get('objective_id'),
            'required': rule.get('required'),
            'pass_threshold': rule.get('pass_threshold'),
            'evidence_kinds': rule.get('evidence_kinds'),
        })
    return {
        'policy_id': policy.get('policy_id'),
        'total_pass_threshold': policy.get('total_pass_threshold'),
        'objective_rules': rules,
    }


def _node_preview(plan: LearningPlan) -> list[dict]:
    preview = []
    for node in plan.nodes:
        preview.append({
            'node_id': node.node_id,
            'title': node.title,
            'prerequisite_ids': list(node.prerequisite_ids),
            'objectives': [{
                'objective_id': objective.objective_id,
                'observable_outcome': objective.observable_outcome,
                'required_capability_ids': list(objective.required_capability_ids),
                'criterion_ids': list(objective.criterion_ids),
                'source_chunk_ids': list(objective.source_chunk_ids),
                'assessment_tasks': [task.model_dump(mode='json') for task in objective.assessment_tasks],
            } for objective in node.objectives],
        })
    return preview


def list_drafts(paths, store, ownership, unit_id: str, account: str) -> dict:
    drafts = []
    with LearningRepository(paths) as repo:
        for project_id in sorted(ownership.owned(account)):
            project = repo.get_project(project_id)
            if not project or not project.get('candidate_plan'):
                continue
            try:
                plan = LearningPlan.model_validate(project['candidate_plan'])
            except Exception:
                continue
            policy = None
            if project.get('candidate_policy_json'):
                try:
                    policy = json.loads(project['candidate_policy_json'])
                except Exception:
                    policy = None
            try:
                chunks = teaching_chunks(repo, project_id)
            except Exception:
                chunks = []
            materials = sorted({chunk['source_id'] for chunk in chunks})
            materials_ok = bool(materials) and all(store.material_version(unit_id, material_id) for material_id in materials)
            reason = None
            if project.get('requires_replan') or project.get('candidate_revision') != project.get('draft_revision'):
                reason = '资料已变化，请重新生成草稿。'
            elif not policy:
                reason = '草稿还没有可执行的评价配置。'
            elif not materials_ok:
                reason = '草稿引用的资料不属于本单位。'
            drafts.append({
                'project_id': project_id,
                'draft_revision': project.get('draft_revision'),
                'title': (project.get('profile') or {}).get('topic') or project.get('goal') or project_id,
                'publishable': reason is None,
                'reason': reason,
                'nodes': _node_preview(plan),
                'policy': _policy_preview(policy),
                'material_version_ids': materials,
            })
    return {'drafts': drafts}


def publish_from_draft(paths, store, ownership, unit_id: str, account: str, *, request_id,
                       course_id, title, draft_project_id, draft_revision, required_nodes,
                       material_version_ids):
    """Load the server draft and publish that revision, ignoring any client tree."""
    if not isinstance(draft_project_id, str) or not draft_project_id.startswith('v3_') or draft_revision is None:
        raise ValueError('draft_required')
    if type(draft_revision) is not int or draft_revision < 1:
        raise ValueError('draft_stale')
    if not isinstance(required_nodes, list) or not required_nodes:
        raise ValueError('invalid_course_dangling_required')
    if draft_project_id not in set(ownership.owned(account)):
        raise ValueError('draft_not_found')
    with LearningRepository(paths) as repo:
        project = repo.get_project(draft_project_id)
        if not project or not project.get('candidate_plan'):
            raise ValueError('draft_not_ready')
        if (project.get('requires_replan') or project.get('candidate_revision') != draft_revision
                or project.get('draft_revision') != draft_revision):
            raise ValueError('draft_stale')
        if not project.get('candidate_policy_json'):
            raise ValueError('invalid_course_policy')
        try:
            policy = EvaluationPolicy.model_validate(json.loads(project['candidate_policy_json']))
            profile = LearningProfile.model_validate(project['profile'])
            plan = LearningPlan.model_validate(project['candidate_plan'])
        except Exception as exc:
            raise ValueError('invalid_course') from exc
        if plan.project_id != draft_project_id or plan.draft_revision != draft_revision:
            raise ValueError('draft_stale')
        chunks = teaching_chunks(repo, draft_project_id)
        by_id = {chunk['chunk_id']: chunk for chunk in chunks}
        try:
            validate_learnability(plan, profile, planner_catalog(chunks, draft_project_id), policy)
        except Exception as exc:
            raise ValueError('invalid_course') from exc
        rewritten = []
        referenced = []
        for node in plan.nodes:
            raw = node.model_dump(mode='json')
            for objective in raw['objectives']:
                anchors = []
                for chunk_id in objective.get('source_chunk_ids') or []:
                    chunk = by_id.get(chunk_id)
                    if chunk is None:
                        raise ValueError('invalid_course_source')
                    anchor = source_anchor(chunk['source_id'], chunk)
                    anchors.append(anchor)
                    referenced.append((anchor, chunk))
                objective['source_chunk_ids'] = anchors
            rewritten.append(raw)
    index = []
    seen = set()
    materials = []
    for anchor, chunk in referenced:
        if anchor in seen:
            continue
        seen.add(anchor)
        index.append({
            'anchor': anchor,
            'material_version_id': chunk['source_id'],
            'content_hash': chunk['content_hash'],
            'line_start': chunk['line_start'],
            'line_end': chunk['line_end'],
        })
        materials.append(chunk['source_id'])
    materials = sorted(set(materials))
    if material_version_ids is not None and set(material_version_ids) != set(materials):
        raise ValueError('material_mismatch')
    tree = {
        'plan_version': plan.plan_version,
        'nodes': rewritten,
        'source_index': index,
        'published_from': {'project_id': draft_project_id, 'draft_revision': draft_revision},
    }
    pass_rule = {'rule': 'all_required_nodes', 'policy': policy.model_dump(mode='json')}
    return store.publish_course(
        unit_id, request_id=request_id, course_id=course_id, title=title, tree=tree,
        required_nodes=list(required_nodes), pass_rule=pass_rule, material_version_ids=materials)
