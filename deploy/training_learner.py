"""Initialize an independent learning project from a published unit course.

Published dependencies, objectives, criterion ids, assessment tasks and pass
thresholds stay fixed. SourceChunk identities are created for the employee
project and substituted from the published source anchors. Checkpoints and
assessments are never copied. A historical course that lacks this configuration
is left unchanged and must be republished.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
from uuid import NAMESPACE_URL, UUID, uuid5

from app.v3.contracts import LearningProfile
from app.v3.execution import project_execution
from app.v3.learning_repository import LearningRepository
from app.v3.materials import MaterialService
from app.v3.planner import validate_learnability
from app.v3.repository import ConflictError
from deploy.training_course import (
    course_executable, employee_plan, employee_policy, planner_catalog, published_capabilities,
    teaching_chunks,
)


def _creation_request_id(employee_task_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, 'skilltree.training.start:' + employee_task_id)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


_START_GUARD = threading.Lock()
_START_LOCKS: dict[tuple[str, str], threading.Lock] = {}


def _start_lock(unit_id: str, employee_task_id: str) -> threading.Lock:
    key = (unit_id, employee_task_id)
    with _START_GUARD:
        lock = _START_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _START_LOCKS[key] = lock
        return lock


def ensure_initialized(paths, materials_root: Path, store, ownership, unit_id: str, account: str,
                       employee_task_id: str, *, request_id: str):
    """Create or resume the employee's independent project for a unit task."""
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValueError('invalid_request_id')
    request_id = request_id.strip()
    try:
        UUID(request_id)
    except Exception as exc:
        raise ValueError('invalid_request_id') from exc

    row = store.employee_task(unit_id, employee_task_id)
    if not row or row['account'] != account:
        raise KeyError('unknown_employee_task')
    with _start_lock(unit_id, employee_task_id):
        return _initialize_authorized(
            paths, materials_root, store, ownership, unit_id, account, employee_task_id, request_id)


def _initialize_authorized(paths, materials_root, store, ownership, unit_id, account, employee_task_id, request_id):
    """Caller already proved this account owns the target task."""
    row = store.employee_task(unit_id, employee_task_id)
    if not row or row['account'] != account:
        raise KeyError('unknown_employee_task')
    prior = store.start_request_row(unit_id, request_id)
    if prior:
        if not store.start_binding_matches(prior, account, 'start', employee_task_id):
            raise ValueError('request_target_mismatch')
        value = store.employee_task_public(unit_id, employee_task_id)
        value['created'] = False
        return value
    if row.get('project_id'):
        store.record_start_request(
            unit_id, request_id, employee_task_id, row['project_id'], account, 'start')
        value = store.employee_task_public(unit_id, employee_task_id)
        value['created'] = False
        return value

    course = store.course_version(unit_id, row['course_version_id'])
    if not course:
        raise KeyError('unknown_course')
    if not course_executable(course):
        # Historical rows stay in place. Starting them would invent a chain and a 0.8 policy.
        raise ValueError('course_needs_republish')
    material_ids = list(course.get('material_version_ids') or [])
    if not material_ids:
        raise ValueError('no_materials')
    capabilities = published_capabilities(course)

    create_key = _creation_request_id(employee_task_id)
    project_id = 'v3_' + create_key.hex
    goal = course['title']
    profile = LearningProfile(
        subject_label='单位学习',
        topic=goal[:256],
        goal=f'完成单位课程《{goal}》的必学节点',
        bounded_goal=f'掌握《{goal}》中已发布必学节点的要点，并通过测评',
        prior_knowledge={'self_reported': ['单位任务学习者']},
        target_level='入门',
        learning_mode='formal',
        requested_capabilities=capabilities,
        profile_version=1,
        scope_in=[goal],
        scope_out=['未写入本课程版本的内容'],
    )

    with project_execution(project_id, paths), LearningRepository(paths) as repo:
        project = repo.create_project(create_key, profile)
        if not ownership.claim(project_id, account):
            raise PermissionError('project_owned_elsewhere')
        for material_id in material_ids:
            meta = store.material_version(unit_id, material_id)
            if not meta:
                raise KeyError('unknown_material')
            original = Path(meta['original_path'])
            if not original.is_file():
                fallback = Path(materials_root) / material_id / 'original'
                if fallback.is_file():
                    original = fallback
                else:
                    raise FileNotFoundError('material_original_missing')
            filename = Path(meta.get('title') or material_id).name
            hint = getattr(store, 'material_filename_hint', None)
            asset_name = hint(material_id) if callable(hint) else None
            if asset_name:
                filename = asset_name
            raw = original.read_bytes()
            MaterialService(repo).import_upload(
                project_id,
                data=raw,
                filename=filename if '.' in filename else filename + '.bin',
                title=meta['title'],
                source_description='单位发布课程资料：' + meta['title'],
                request_id=uuid5(NAMESPACE_URL, f'{employee_task_id}:{material_id}:import'),
                source_id=material_id,
            )

        project = repo.get_project(project_id)
        if not project['frozen_snapshot']:
            chunks = teaching_chunks(repo, project_id)
            if not chunks:
                raise ValueError('no_chunks')
            plan = employee_plan(project_id, project['draft_revision'], course, chunks)
            policy = employee_policy(course, plan)
            profile = LearningProfile.model_validate(project['profile'])
            plan = validate_learnability(plan, profile, planner_catalog(chunks, project_id), policy)
            project = repo.save_candidate_plan(project_id, plan, expected_revision=project['draft_revision'])
            project = repo.get_project(project_id)
            try:
                repo.freeze_plan(
                    project_id, policy,
                    expected_revision=project['draft_revision'],
                    pending_input_id=project['pending_input_id'],
                )
            except ConflictError:
                project = repo.get_project(project_id)
                if not project or not project['frozen_snapshot']:
                    raise

    # Bind every node kept on the employee plan, including prerequisites that
    # are not themselves required. Progress still counts required_nodes only.
    with LearningRepository(paths) as repo:
        frozen = repo.get_project(project_id)
        node_ids = [node['node_id'] for node in (frozen.get('candidate_plan') or {}).get('nodes') or []]
    if not node_ids:
        node_ids = list(course['required_nodes'])
    bindings = [(node_id, node_id) for node_id in node_ids]
    linked = store.link_employee_project(
        unit_id, employee_task_id, project_id, bindings, started_at=_utc_now())
    store.record_start_request(unit_id, request_id, employee_task_id, project_id, account, 'start')
    value = store.employee_task_public(unit_id, employee_task_id)
    value['created'] = linked.get('created', True)
    return value


def progress_for_project(paths, project_id: str, required_nodes: list[str], bindings: dict[str, str]):
    """Compute required-node progress from real learning facts only."""
    if not required_nodes:
        return {
            'required_total': 0,
            'required_passed': 0,
            'ratio': None,
            'passed_course_nodes': [],
            'status': 'not_started',
            'completed': False,
        }
    if not project_id:
        return {
            'required_total': len(required_nodes),
            'required_passed': 0,
            'ratio': 0.0,
            'passed_course_nodes': [],
            'status': 'not_started',
            'completed': False,
        }
    with LearningRepository(paths) as repo:
        project = repo.get_project(project_id)
        if not project:
            return {
                'required_total': len(required_nodes),
                'required_passed': 0,
                'ratio': 0.0,
                'passed_course_nodes': [],
                'status': 'error',
                'completed': False,
            }
        completed = set(repo.completed(project_id))
    # Map project node ids back to course node ids.
    reverse = {project_node: course_node for course_node, project_node in bindings.items()}
    passed = []
    for course_node in required_nodes:
        project_node = bindings.get(course_node, course_node)
        if project_node in completed:
            passed.append(course_node)
    total = len(required_nodes)
    count = len(passed)
    done = count == total and total > 0
    status = 'completed' if done else 'in_progress'
    return {
        'required_total': total,
        'required_passed': count,
        'ratio': (count / total) if total else None,
        'passed_course_nodes': passed,
        'status': status,
        'completed': done,
        'project_lifecycle': project.get('lifecycle'),
    }


def _parse_due(due_at: str | None):
    if not due_at:
        return None
    text = due_at.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        # Naive deadlines are interpreted as Asia/Shanghai wall time.
        try:
            from zoneinfo import ZoneInfo
            value = value.replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        except Exception:
            value = value.replace(tzinfo=timezone.utc)
    return value


def overdue_flag(due_at: str | None, *, now: datetime | None = None) -> dict:
    due = _parse_due(due_at)
    if due is None:
        return {'overdue': False, 'due_at': due_at, 'due_timezone': None}
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return {
        'overdue': current > due,
        'due_at': due.isoformat(),
        'due_timezone': str(due.tzinfo),
    }


def employee_learning_detail(paths, store, unit_id: str, assignee: dict, course: dict | None):
    """Build one assignee row for the admin board from real learning facts."""
    required = list((course or {}).get('required_nodes') or [])
    project_id = assignee.get('project_id')
    bindings = store.node_bindings(assignee['id']) if assignee.get('id') else {}
    progress = progress_for_project(paths, project_id, required, bindings)
    due = overdue_flag(assignee.get('due_at') if 'due_at' in assignee else None)
    # due_at lives on the task; callers may pass it separately.
    detail = {
        'employee_task_id': assignee.get('id'),
        'account': assignee.get('account'),
        'project_id': project_id,
        'started_at': assignee.get('started_at'),
        'status': progress['status'] if project_id else 'not_started',
        'progress': {
            'required_passed': progress['required_passed'],
            'required_total': progress['required_total'],
            'ratio': progress['ratio'],
            'passed_course_nodes': progress['passed_course_nodes'],
        },
        'completed': bool(progress.get('completed')),
        'overdue': False,
        'recent_assessment': None,
        'remediation_targets': [],
        'updated_at': assignee.get('started_at'),
        'mode': None,
    }
    if not project_id:
        return detail
    with LearningRepository(paths) as repo:
        project = repo.get_project(project_id)
        session = repo.session(project_id)
        progress_rows = repo.get_progress(project_id)
    updated = None
    for row in progress_rows:
        for key in ('completed_at', 'started_at'):
            if row.get(key) and (updated is None or row[key] > updated):
                updated = row[key]
    if session:
        detail['mode'] = session.get('mode')
        if session.get('last_guard_json'):
            import json
            try:
                guard = json.loads(session['last_guard_json']) if isinstance(session['last_guard_json'], str) else session['last_guard_json']
            except Exception:
                guard = None
            if isinstance(guard, dict):
                detail['recent_assessment'] = {
                    'passed': bool(guard.get('passed')),
                    'effective_action': guard.get('effective_action'),
                    'assessment_id': session.get('current_assessment_id'),
                    'node_id': session.get('current_node_id') or session.get('review_node_id'),
                }
                if guard.get('effective_action') in {'remediate', 'revisit_prerequisite'} or session.get('mode') in {'remediate', 'review'}:
                    target = session.get('review_node_id') or session.get('current_node_id')
                    if target:
                        detail['remediation_targets'] = [target]
        if session.get('tutor_request_id') and not updated:
            updated = assignee.get('started_at')
    if project and project.get('frozen_at') and (updated is None or project['frozen_at'] > updated):
        updated = project['frozen_at']
    detail['updated_at'] = updated or assignee.get('started_at')
    return detail


def task_board(paths, store, unit_id: str, task_id: str, *, now: datetime | None = None):
    detail = store.task_dashboard(unit_id, task_id)
    if not detail:
        return None
    course = detail.get('course')
    due_meta = overdue_flag(detail.get('due_at'), now=now)
    employees = []
    started = completed = 0
    for assignee in detail.get('assignees') or []:
        row = employee_learning_detail(paths, store, unit_id, {**assignee, 'due_at': detail.get('due_at')}, course)
        row_due = overdue_flag(detail.get('due_at'), now=now)
        row['overdue'] = row_due['overdue'] and not row['completed']
        employees.append(row)
        if assignee.get('project_id'):
            started += 1
        if row['completed']:
            completed += 1
    total = len(employees)
    return {
        'id': detail['id'],
        'title': detail['title'],
        'course_version_id': detail['course_version_id'],
        'course': course,
        'due_at': detail.get('due_at'),
        'due_timezone': due_meta['due_timezone'],
        'overdue': due_meta['overdue'],
        'counts': {
            'assigned': total,
            'started': started,
            'completed': completed,
            'not_started': total - started,
            'in_progress': started - completed,
        },
        'employees': employees,
        'progress_definition': 'required_passed / required_total from real learning_progress completions via node bindings',
    }


def unit_dashboard(paths, store, unit_id: str, *, now: datetime | None = None):
    overview = store.overview(unit_id)
    tasks = []
    for task in overview.get('tasks') or []:
        board = task_board(paths, store, unit_id, task['id'], now=now)
        if board:
            tasks.append({
                'id': board['id'],
                'title': board['title'],
                'course_version_id': board['course_version_id'],
                'due_at': board['due_at'],
                'overdue': board['overdue'],
                'counts': board['counts'],
            })
    return {
        'unit_id': unit_id,
        'tasks': tasks,
        'members': overview.get('members') or [],
        'courses': overview.get('courses') or [],
        'dashboard_available': True,
        'empty': not tasks,
    }
