"""启动 SkillTree V3 学习工作台。"""

from __future__ import annotations

import sys
import os
import threading
import time
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"


def load_application():
    """Use the same product as day12_server; never initialize the V2 runtime."""
    from app.v3.learning_api import create_learning_app

    options={}
    local_auth = os.getenv('SKILLTREE_LOCAL_AUTH', '0') == '1'
    if local_auth:
        from app.v3.storage import V3Paths
        from deploy.model_settings import AccountModel, ModelSettings, ModelScopedApplication, ensure_local_key_file
        paths = V3Paths()
        quota = os.getenv('SKILLTREE_LOCAL_QUOTA_DB', str(paths.root.parent/'local-quota.sqlite'))
        key = ensure_local_key_file(os.getenv('SKILLTREE_LOCAL_MODEL_KEY_FILE', str(paths.root.parent/'local-model-settings.key')))
        settings = ModelSettings(quota, key)
        options['llm'] = AccountModel()
    elif os.getenv('SKILLTREE_LOCAL_RUNTIME')=='production':
        from deploy.provider import create_runtime_model
        options['llm']=create_runtime_model()
    mode=os.getenv('SKILLTREE_QUIZ_GENERATION','legacy')
    if mode!='legacy':options['quiz_generation_mode']=mode
    preparation_mode=os.getenv('SKILLTREE_PREPARATION_GENERATION','legacy')
    if preparation_mode!='legacy':options['preparation_generation_mode']=preparation_mode
    application=create_learning_app(**options)
    if local_auth:
        from deploy.asgi import EvaluationGateway
        from deploy.auth import AuthStore
        from app.v3.storage import V3Paths
        application=EvaluationGateway(ModelScopedApplication(application, settings),paths,quota,model_settings=settings,
            auth_store=AuthStore(os.getenv('SKILLTREE_LOCAL_AUTH_DB',str(paths.root.parent/'local-auth.sqlite'))),
            queued=True,origin='http://127.0.0.1:8765',cookie_secure=False,cookie_name='skilltree_local_session')
    return application


def open_browser_when_ready(server) -> None:
    """等待当前服务启动成功，避免端口被占用时打开其他服务。"""
    deadline = time.monotonic() + 30
    while not server.started:
        if server.should_exit or time.monotonic() >= deadline:
            return
        time.sleep(0.1)

    try:
        opened = webbrowser.open(URL, new=2)
    except webbrowser.Error:
        opened = False
    if not opened:
        print(f"未能自动打开浏览器，请手动访问：{URL}", flush=True)


def main() -> None:
    try:
        import uvicorn
        app = load_application()
    except ModuleNotFoundError as exc:
        requirements = Path(__file__).resolve().parent / "requirements.txt"
        print(f"缺少依赖：{exc.name}。请先安装项目依赖：", file=sys.stderr)
        print(
            f'& "{sys.executable}" -m pip install -r "{requirements}"',
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    except ValueError:
        print(
            "V3 数据尚未初始化或版本不匹配，服务未启动，也不会退回旧版或自动修改数据库。\n"
            "请按 docs/v3/DAY12_API.md 的初始化/迁移说明准备 data/v3 后重新运行。",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, workers=1))
    print(f"SkillTree V3 启动后将自动打开：{URL}\n填写目标和基础，可选上传资料，由 AI 整理学习计划。\n按 Ctrl+C 停止服务。", flush=True)
    threading.Thread(
        target=open_browser_when_ready,
        args=(server,),
        name="skilltree-browser",
        daemon=True,
    ).start()
    server.run()


if __name__ == "__main__":
    main()
