"""运行此文件即可启动 SkillTree，并在服务就绪后打开浏览器。"""

from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}/"


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
        from app.main import app
    except ModuleNotFoundError as exc:
        requirements = Path(__file__).resolve().parent / "requirements.txt"
        print(f"缺少依赖：{exc.name}。请先安装项目依赖：", file=sys.stderr)
        print(
            f'& "{sys.executable}" -m pip install -r "{requirements}"',
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=PORT, workers=1))
    print(f"SkillTree 启动后将自动打开：{URL}\n按 Ctrl+C 停止服务。", flush=True)
    threading.Thread(
        target=open_browser_when_ready,
        args=(server,),
        name="skilltree-browser",
        daemon=True,
    ).start()
    server.run()


if __name__ == "__main__":
    main()
