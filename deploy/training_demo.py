"""Isolated local training demo: python -m deploy.training_demo.

Only the local launcher enables this surface. The normal app is unchanged.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket

from fastapi.responses import FileResponse
from .asgi import EvaluationGateway
from .auth import AuthStore, csrf_token
from .training_store import TrainingStore
from . import training_learner
from app.v3.storage import PROJECT_ROOT, V3Paths, initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.learning_api import create_learning_app, STATIC


TRAINING_WORK = PROJECT_ROOT / 'work' / 'training-demo'
UNIT_ID = 'demo-qinghe'
ACCOUNTS = (
    ('admin@example.test', '学习管理员', 'admin'),
    ('employee.a@example.test', '员工甲', 'employee'),
    ('employee.b@example.test', '员工乙', 'employee'),
    ('employee.c@example.test', '员工丙', 'employee'),
)
DEMO_PASSWORD = 'SkillTreeDemo2026!'


def isolated_root(value):
    root = Path(value).resolve()
    if not root.is_relative_to(TRAINING_WORK.resolve()) or root == TRAINING_WORK.resolve():
        raise ValueError('演示目录必须是 work/training-demo/ 下的独立子目录。')
    marker = root / 'training-demo.json'
    expected = {'kind': 'skilltree-training-demo-v1'}
    if root.exists() and any(root.iterdir()) and not marker.is_file():
        raise ValueError('目录已有其他数据，请选择新的演示子目录。')
    if marker.exists() and json.loads(marker.read_text(encoding='utf-8')) != expected:
        raise ValueError('演示目录标记不匹配。')
    root.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(expected), encoding='utf-8')
    return root


def seed(auth, store, password=DEMO_PASSWORD):
    # Never reset hashes, sessions, projects or learning progress on restart.
    for login, _, _ in ACCOUNTS:
        with auth.connect() as conn:
            exists = conn.execute('SELECT 1 FROM auth_accounts WHERE login=?', (login,)).fetchone()
        if not exists:
            auth.create_account(login, password)
    with store.connect() as conn:
        conn.execute('INSERT OR IGNORE INTO training_units VALUES (?,?)', (UNIT_ID, '青禾研习社（虚构演示单位）'))
        for login, name, role in ACCOUNTS:
            with auth.connect() as identities:
                account = identities.execute('SELECT account FROM auth_accounts WHERE login=?', (login,)).fetchone()[0]
            conn.execute('INSERT OR IGNORE INTO training_members VALUES (?,?,?,?)', (UNIT_ID, account, name, role))


class TrainingSurface:
    def __init__(self, store, materials):
        self.store = store
        self.materials = materials

    async def identity(self, account, auth):
        member = await asyncio.to_thread(self.store.member, account)
        if member:
            return member
        if not account:
            return None
        if await asyncio.to_thread(auth.is_guest, account):
            # Visitors own personal projects, but are never unit members.
            return {'account': account, 'display_name': '游客', 'role': 'guest',
                    'unit_id': None, 'unit_name': '个人学习空间'}
        # Registered personal account: may learn freely without a unit.
        login = await asyncio.to_thread(auth.login_name, account)
        label = (login.split('@', 1)[0] if isinstance(login, str) and '@' in login else login) or '个人用户'
        return {'account': account, 'display_name': label, 'role': 'personal',
                'unit_id': None, 'unit_name': '个人学习空间'}

    async def handle(self, scope, receive, send, user, token, gateway):
        path, method = scope['path'], scope['method']
        if path == '/login' and method in {'GET', 'HEAD'}:
            await FileResponse(STATIC/'training-login.html', headers={'Cache-Control': 'no-store'})(scope, receive, send)
            return True
        if path not in {'/', '/learn', '/session'} and not path.startswith('/training'):
            return False
        member = await self.identity(user, gateway.auth)
        if not member:
            await gateway.reply(send, 403, {'error': {'code': 'not_a_member', 'message': '请先登录或注册个人账号。'}})
            return True
        admin_path = path.startswith('/training/admin') or path.startswith('/training/api/admin')
        if admin_path and member['role'] != 'admin':
            await gateway.reply(send, 403, {'error': {'code': 'admin_required', 'message': '此入口仅向本单位学习管理员开放。'}})
            return True
        guest = member['role'] == 'guest'
        personal = member['role'] == 'personal'
        unaffiliated = guest or personal
        if unaffiliated and path in {'/training/tasks', '/training/api/my-tasks'}:
            await gateway.reply(send, 403, {'error': {'code': 'member_required',
                'message': '单位学习任务仅向所属成员开放，个人账号可以继续自主学习。'}})
            return True
        if path == '/training/api/admin/members/lookup' and method == 'GET':
            from urllib.parse import parse_qs
            query = parse_qs(scope.get('query_string', b'').decode('latin1'))
            needle = (query.get('q') or query.get('login') or query.get('account') or [''])[0]
            found = await asyncio.to_thread(gateway.auth.resolve_registered, needle)
            if not found:
                await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '未找到该注册账号。请核对完整邮箱或账号 ID。'}})
                return True
            existing = await asyncio.to_thread(self.store.member, found['account'])
            await gateway.reply(send, 200, {
                'account': found['account'], 'login': found['login'],
                'in_this_unit': bool(existing and existing['unit_id'] == member['unit_id']),
                'in_other_unit': bool(existing and existing['unit_id'] != member['unit_id']),
                'role': existing['role'] if existing else None,
            })
            return True
        if path == '/training/api/admin/members' and method == 'POST':
            try:
                payload = json.loads(await gateway.body(receive, 4096))
            except Exception:
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供有效的账号邮箱或 ID。'}})
                return True
            if not isinstance(payload, dict):
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供有效的账号邮箱或 ID。'}})
                return True
            # Ignore client-supplied role/unit_id; only employees can be added here.
            needle = payload.get('login') or payload.get('account') or payload.get('email')
            found = await asyncio.to_thread(gateway.auth.resolve_registered, needle)
            if not found:
                await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '未找到该注册账号，不能把游客直接加入单位。'}})
                return True
            label = payload.get('display_name')
            if not isinstance(label, str) or not label.strip():
                label = found['login'].split('@', 1)[0]
            try:
                result = await asyncio.to_thread(
                    self.store.add_employee, member['unit_id'], found['account'], label)
            except ValueError as err:
                code = str(err)
                if code == 'other_unit':
                    await gateway.reply(send, 409, {'error': {'code': 'other_unit',
                        'message': '该账号已属于其他单位，本版不支持自动转移。'}})
                else:
                    await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '显示名称无效。'}})
                return True
            result = {**result, 'login': found['login'], 'unit_name': member['unit_name']}
            await gateway.reply(send, 200 if not result['created'] else 201, result)
            return True
        if path == '/training/api/admin/members/remove' and method == 'POST':
            try:
                payload = json.loads(await gateway.body(receive, 4096))
            except Exception:
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供要移除的账号。'}})
                return True
            target = payload.get('account') if isinstance(payload, dict) else None
            if not isinstance(target, str) or not target.strip():
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供要移除的账号。'}})
                return True
            try:
                result = await asyncio.to_thread(
                    self.store.remove_employee, member['unit_id'], target.strip())
            except ValueError:
                await gateway.reply(send, 409, {'error': {'code': 'cannot_remove_admin',
                    'message': '不能通过成员管理移除管理员。'}})
                return True
            await gateway.reply(send, 200, result)
            return True
        if path == '/training/api/admin/courses/publish' and method == 'POST':
            try:
                payload = json.loads(await gateway.body(receive, 262144))
            except Exception:
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供有效的发布内容。'}})
                return True
            if not isinstance(payload, dict):
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供有效的发布内容。'}})
                return True
            try:
                result = await asyncio.to_thread(
                    self.store.publish_course, member['unit_id'],
                    request_id=payload.get('request_id'),
                    course_id=payload.get('course_id') or 'course',
                    title=payload.get('title'),
                    tree=payload.get('tree'),
                    required_nodes=payload.get('required_nodes'),
                    pass_rule=payload.get('pass_rule') or {'rule': 'all_required_nodes'},
                    material_version_ids=payload.get('material_version_ids'))
            except KeyError:
                await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '资料版本不存在或不属于本单位。'}})
                return True
            except ValueError:
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '发布参数无效：需要 request_id、title、tree、必学节点和资料版本。'}})
                return True
            await gateway.reply(send, 201 if result.get('created') else 200, result)
            return True
        if path.startswith('/training/api/admin/courses/') and method == 'GET':
            course_id = path[len('/training/api/admin/courses/'):]
            if course_id and '/' not in course_id and course_id != 'publish':
                value = await asyncio.to_thread(self.store.course_version, member['unit_id'], course_id)
                if not value:
                    await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '课程版本不存在。'}})
                    return True
                await gateway.reply(send, 200, value)
                return True
        if path == '/training/api/admin/tasks/assign' and method == 'POST':
            try:
                payload = json.loads(await gateway.body(receive, 4096))
            except Exception:
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供有效的下发内容。'}})
                return True
            if not isinstance(payload, dict):
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供有效的下发内容。'}})
                return True
            try:
                result = await asyncio.to_thread(
                    self.store.assign_task, member['unit_id'],
                    request_id=payload.get('request_id'),
                    course_version_id=payload.get('course_version_id'),
                    title=payload.get('title'),
                    due_at=payload.get('due_at'),
                    created_by=member['account'],
                    accounts=payload.get('accounts'))
            except KeyError:
                await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '课程版本不存在。'}})
                return True
            except PermissionError:
                await gateway.reply(send, 403, {'error': {'code': 'admin_required', 'message': '仅管理员可下发任务。'}})
                return True
            except ValueError as err:
                code = str(err)
                message = '下发参数无效。'
                if code == 'invalid_assignee':
                    message = '只能向本单位员工下发，请先在成员管理中加入账号。'
                await gateway.reply(send, 422, {'error': {'code': code if code.startswith('invalid_') else 'invalid_input', 'message': message}})
                return True
            await gateway.reply(send, 201 if result.get('created') else 200, result)
            return True
        if path == '/training/api/admin/dashboard' and method == 'GET':
            board = await asyncio.to_thread(
                training_learner.unit_dashboard, gateway.paths, self.store, member['unit_id'])
            await gateway.reply(send, 200, board)
            return True
        if path.startswith('/training/api/admin/tasks/') and method == 'GET':
            rest = path[len('/training/api/admin/tasks/'):]
            if rest.endswith('/board') and '/' not in rest[:-len('/board')]:
                task_id = rest[:-len('/board')]
                value = await asyncio.to_thread(
                    training_learner.task_board, gateway.paths, self.store, member['unit_id'], task_id)
                if not value:
                    await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '任务不存在。'}})
                    return True
                await gateway.reply(send, 200, value)
                return True
            if rest and '/' not in rest and rest != 'assign':
                value = await asyncio.to_thread(self.store.task_detail, member['unit_id'], rest)
                if not value:
                    await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '任务不存在。'}})
                    return True
                await gateway.reply(send, 200, value)
                return True

        if path.startswith('/training/api/my-tasks/') and path.endswith('/start') and method == 'POST':
            employee_task_id = path[len('/training/api/my-tasks/'):-len('/start')]
            if not employee_task_id or '/' in employee_task_id:
                await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '任务不存在。'}})
                return True
            if unaffiliated or member['role'] not in {'employee', 'admin'}:
                await gateway.reply(send, 403, {'error': {'code': 'member_required', 'message': '仅单位成员可开始分配给自己的任务。'}})
                return True
            try:
                payload = json.loads(await gateway.body(receive, 4096))
            except Exception:
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供 request_id。'}})
                return True
            if not isinstance(payload, dict):
                await gateway.reply(send, 422, {'error': {'code': 'invalid_input', 'message': '请提供 request_id。'}})
                return True
            try:
                result = await asyncio.to_thread(
                    training_learner.ensure_initialized,
                    gateway.paths, self.materials.root, self.store, gateway.ownership,
                    member['unit_id'], user, employee_task_id, request_id=payload.get('request_id'))
            except KeyError:
                await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '任务不存在或不属于当前账号。'}})
                return True
            except PermissionError:
                await gateway.reply(send, 409, {'error': {'code': 'project_conflict', 'message': '学习项目归属冲突，请联系管理员。'}})
                return True
            except FileNotFoundError:
                await gateway.reply(send, 409, {'error': {'code': 'material_missing', 'message': '课程资料原件缺失，无法开课。'}})
                return True
            except ValueError as err:
                code = str(err)
                await gateway.reply(send, 422, {'error': {'code': code if code.startswith(('invalid_', 'no_')) else 'invalid_input',
                    'message': '无法按已发布课程初始化学习项目，请刷新后重试。'}})
                return True
            except Exception as err:
                # Surface freeze/import contract failures without leaking internals.
                await gateway.reply(send, 500, {'error': {'code': 'start_failed',
                    'message': '开课初始化失败，进度未推进；请稍后重试。'}})
                return True
            await gateway.reply(send, 201 if result.get('created') else 200, result)
            return True

        if await self.materials.handle(scope, receive, send, gateway, member):
            return True
        if method not in {'GET', 'HEAD'}:
            await gateway.reply(send, 405, {'error': {'code': 'not_implemented', 'message': '该写接口尚未开放。'}})
            return True
        if path == '/session':
            await gateway.reply(send, 200, {'account': user, 'login': await asyncio.to_thread(gateway.auth.login_name, user),
                'csrf_token': csrf_token(token), 'guest': guest, 'logout': not guest, 'training': member})
        elif path == '/learn':
            await gateway.application({**scope, 'path': '/', 'raw_path': b'/'}, receive, send)
        elif path == '/':
            # Same original garden for every role. Training hubs stay on /training/*.
            # Fragment selects 我的花园; /learn#/p/... is unchanged because it never hits this branch.
            await gateway.reply(send, 303, {}, [(b'location', b'/learn#/garden')])
        elif path == '/training/api/me':
            await gateway.reply(send, 200, member)
        elif path == '/training/api/admin/overview':
            await gateway.reply(send, 200, await asyncio.to_thread(self.store.overview, member['unit_id']))
        elif path == '/training/api/my-tasks':
            tasks = await asyncio.to_thread(self.store.my_tasks, member['unit_id'], user)
            enriched = []
            for task in tasks:
                item = dict(task)
                item['learning_available'] = True
                if task.get('project_id'):
                    course = await asyncio.to_thread(self.store.course_version, member['unit_id'], task['course_version_id'])
                    bindings = await asyncio.to_thread(self.store.node_bindings, task['id'])
                    progress = await asyncio.to_thread(
                        training_learner.progress_for_project, gateway.paths, task['project_id'],
                        (course or {}).get('required_nodes') or [], bindings)
                    item['progress'] = progress
                    item['status'] = progress['status']
                else:
                    item['progress'] = None
                    item['status'] = 'not_started'
                enriched.append(item)
            await gateway.reply(send, 200, {'tasks': enriched, 'learning_available': True})
        elif path in {'/training/home', '/training/admin', '/training/materials', '/training/tasks',
                      '/training/admin/materials', '/training/admin/courses', '/training/admin/tasks',
                      '/training/admin/dashboard', '/training/admin/members'}:
            await FileResponse(STATIC/'training.html', headers={'Cache-Control': 'no-store'})(scope, receive, send)
        else:
            await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '演示入口不存在。'}})
        return True


class TrainingGateway(EvaluationGateway):
    async def authenticated(self, scope, receive, send):
        if scope['method'] in {'GET', 'HEAD'} and (scope['path'] == '/learn' or scope['path'].startswith('/training/')) and not scope['path'].startswith('/training/api/'):
            # Let the existing boundary perform redirects for signed-out pages.
            headers = dict(scope['headers'])
            from http.cookies import SimpleCookie
            cookies = SimpleCookie()
            try:
                cookies.load(headers.get(b'cookie', b'').decode('latin1'))
                token = cookies[self.cookie_name].value if self.cookie_name in cookies else ''
            except Exception:
                token = ''
            if not await asyncio.to_thread(self.auth.session, token):
                # Root reuses the existing bounded guest-session creation flow.
                await self.reply(send, 303, {}, [(b'location', b'/')])
                return None, token
        user, token = await super().authenticated(scope, receive, send)
        if user and not await self.training.identity(user, self.auth):
            await self.reply(send, 403, {'error': {'code': 'not_a_member', 'message': '请先登录或注册个人账号。'}})
            return None, token
        return user, token


def create_app(*, root=None, port=18780, llm=None, public_origin=None, seed_password=DEMO_PASSWORD):
    if not 18780 <= port <= 18879:
        raise ValueError('演示端口范围为 18780–18879，不能接管原服务端口。')
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT/'.env')
    root = isolated_root(root or os.getenv('SKILLTREE_TRAINING_ROOT', str(TRAINING_WORK/'instance')))
    paths = initialize_learning_storage(initialize_storage(V3Paths(root/'learning')))
    auth, store = AuthStore(root/'auth.sqlite'), TrainingStore(root/'training.sqlite')
    if public_origin and (not public_origin.startswith('https://') or seed_password == DEMO_PASSWORD or len(seed_password) < 16):
        raise ValueError('公网学习必须使用 HTTPS 和独立的至少 16 位初始密码。')
    seed(auth, store, seed_password)
    settings = None
    if llm is None:
        from .model_settings import AccountModel, ModelSettings, ModelScopedApplication, ensure_local_key_file
        settings = ModelSettings(root/'gateway.sqlite', ensure_local_key_file(root/'model-settings.key'))
        llm = AccountModel()
    application = create_learning_app(paths, llm=llm, quiz_generation_mode='content-v1',
        preparation_generation_mode='notes-outline-v1')
    if settings:
        application = ModelScopedApplication(application, settings)
    from .training_materials import TrainingMaterials
    materials = TrainingMaterials(root, root/'gateway.sqlite', store)
    store.material_filename_hint = materials.filename_for
    gateway = TrainingGateway(application, paths, root/'gateway.sqlite', auth_store=auth, queued=True,
        origin=public_origin or f'http://127.0.0.1:{port}', cookie_secure=bool(public_origin), guest_access=True,
        cookie_name='__Host-skilltree_training_session' if public_origin else f'skilltree_training_{port}_session',
        model_settings=settings, training=TrainingSurface(store, materials))
    return gateway


def create_production_app():
    password = os.environ.get('SKILLTREE_TRAINING_PASSWORD', '')
    if len(password) < 16:
        raise ValueError('先在服务器私有配置中设置学习初始密码。')
    return create_app(root=os.getenv('SKILLTREE_TRAINING_ROOT', str(TRAINING_WORK/'production')),
        public_origin=os.getenv('SKILLTREE_PUBLIC_ORIGIN', 'https://skilltree.goutouren.work'), seed_password=password)


def main():
    parser = argparse.ArgumentParser(description='SkillTree 单位学习本地演示（保留已有演示进度）')
    parser.add_argument('--port', type=int, default=18780)
    parser.add_argument('--data-root', type=Path, default=None)
    parser.add_argument('--init-only', action='store_true')
    args = parser.parse_args()
    # .env may still describe the earlier production release; report this checkout.
    import subprocess
    try:
        os.environ['SKILLTREE_COMMIT'] = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=PROJECT_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    if not 18780 <= args.port <= 18879:
        parser.error('请使用 18780–18879 内的独立演示端口。')
    listener = None
    if not args.init_only:
        listener = socket.socket()
        try:
            listener.bind(('127.0.0.1', args.port))
        except OSError:
            listener.close()
            parser.error('演示端口已被占用，请保留原进程并选择另一个演示端口。')
    try:
        application = create_app(root=args.data_root, port=args.port)
        print(f'Training demo: http://127.0.0.1:{args.port}/ | {application.paths.root.parent}', flush=True)
        if not args.init_only:
            import uvicorn
            uvicorn.Server(uvicorn.Config(application, host='127.0.0.1', port=args.port, workers=1)).run(sockets=[listener])
    finally:
        if listener:
            listener.close()


if __name__ == '__main__':
    main()
