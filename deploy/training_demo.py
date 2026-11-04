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
from app.v3.storage import PROJECT_ROOT, V3Paths, initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.learning_api import create_learning_app, STATIC


TRAINING_WORK = PROJECT_ROOT / 'work' / 'training-demo'
UNIT_ID = 'demo-qinghe'
ACCOUNTS = (
    ('admin@example.test', '培训管理员', 'admin'),
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
    def __init__(self, store):
        self.store = store

    async def handle(self, scope, receive, send, user, token, gateway):
        path, method = scope['path'], scope['method']
        if path == '/login' and method in {'GET', 'HEAD'}:
            await FileResponse(STATIC/'training-login.html', headers={'Cache-Control': 'no-store'})(scope, receive, send)
            return True
        if path not in {'/', '/learn', '/session'} and not path.startswith('/training'):
            return False
        member = await asyncio.to_thread(self.store.member, user)
        if not member:
            await gateway.reply(send, 403, {'error': {'code': 'not_a_member', 'message': '请使用预置演示账号登录。'}})
            return True
        admin_path = path.startswith('/training/admin') or path.startswith('/training/api/admin')
        if admin_path and member['role'] != 'admin':
            await gateway.reply(send, 403, {'error': {'code': 'admin_required', 'message': '此入口仅向本单位培训管理员开放。'}})
            return True
        if method not in {'GET', 'HEAD'}:
            await gateway.reply(send, 405, {'error': {'code': 'not_implemented', 'message': 'Day 1 尚未开放发布和下发操作。'}})
            return True
        if path == '/session':
            await gateway.reply(send, 200, {'account': user, 'login': await asyncio.to_thread(gateway.auth.login_name, user),
                'csrf_token': csrf_token(token), 'guest': False, 'logout': True, 'training': member})
        elif path == '/learn':
            await gateway.application({**scope, 'path': '/', 'raw_path': b'/'}, receive, send)
        elif path == '/':
            await gateway.reply(send, 303, {}, [(b'location', b'/training/admin' if member['role'] == 'admin' else b'/training/home')])
        elif path == '/training/api/me':
            await gateway.reply(send, 200, member)
        elif path == '/training/api/admin/overview':
            await gateway.reply(send, 200, await asyncio.to_thread(self.store.overview, member['unit_id']))
        elif path == '/training/api/my-tasks':
            await gateway.reply(send, 200, {'tasks': await asyncio.to_thread(self.store.my_tasks, member['unit_id'], user),
                'learning_available': False})
        elif path in {'/training/home', '/training/admin', '/training/materials', '/training/tasks',
                      '/training/admin/materials', '/training/admin/courses', '/training/admin/tasks', '/training/admin/dashboard'}:
            await FileResponse(STATIC/'training.html', headers={'Cache-Control': 'no-store'})(scope, receive, send)
        else:
            await gateway.reply(send, 404, {'error': {'code': 'not_found', 'message': '演示入口不存在。'}})
        return True


class TrainingGateway(EvaluationGateway):
    async def authenticated(self, scope, receive, send):
        if scope['path'] == '/auth/register':
            await self.reply(send, 403, {'error': {'code': 'demo_registration_closed', 'message': '本地演示使用四个预置账号，不开放注册。'}})
            return None, ''
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
                await self.reply(send, 303, {}, [(b'location', b'/login')])
                return None, token
        user, token = await super().authenticated(scope, receive, send)
        if user and not await asyncio.to_thread(self.training.store.member, user):
            await self.reply(send, 403, {'error': {'code': 'not_a_member', 'message': '请使用预置演示账号。'}})
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
        raise ValueError('公网培训必须使用 HTTPS 和独立的至少 16 位初始密码。')
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
    gateway = TrainingGateway(application, paths, root/'gateway.sqlite', auth_store=auth, queued=True,
        origin=public_origin or f'http://127.0.0.1:{port}', cookie_secure=bool(public_origin), guest_access=False,
        cookie_name='__Host-skilltree_training_session' if public_origin else f'skilltree_training_{port}_session',
        model_settings=settings, training=TrainingSurface(store))
    return gateway


def create_production_app():
    password = os.environ.get('SKILLTREE_TRAINING_PASSWORD', '')
    if len(password) < 16:
        raise ValueError('先在服务器私有配置中设置培训初始密码。')
    return create_app(root=os.getenv('SKILLTREE_TRAINING_ROOT', str(TRAINING_WORK/'production')),
        public_origin=os.getenv('SKILLTREE_PUBLIC_ORIGIN', 'https://skilltree.goutouren.work'), seed_password=password)


def main():
    parser = argparse.ArgumentParser(description='SkillTree 单位培训本地演示（保留已有演示进度）')
    parser.add_argument('--port', type=int, default=18780)
    parser.add_argument('--data-root', type=Path, default=None)
    parser.add_argument('--init-only', action='store_true')
    args = parser.parse_args()
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
