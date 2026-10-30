"""Isolated real browser + gateway + Graph; deliberately synthetic model content."""
import json,os,shutil,socket,subprocess,time
from pathlib import Path
from threading import Thread
import pytest
import uvicorn
from app.services.live_progress import tutor_callback
from app.v3.learning_api import create_learning_app
from deploy.asgi import EvaluationGateway
from deploy.auth import AuthStore
from tests.day11_support import FakeLearningModel,build_frozen_project


class SlowSynthetic(FakeLearningModel):
    def _invoke(self,schema,messages):
        value=super()._invoke(schema,messages)
        if schema=='TutorReply':
            value['text']='这是浏览器回归的合成讲解。<img src=x onerror="window.streamInjected=1">\n\n'+('变量像带标签的盒子，赋值会更新盒子里的内容。\n'*24)
            callback=tutor_callback()
            if callback:
                raw=json.dumps(value,ensure_ascii=False)
                for i in range(0,len(raw),18):callback.on_llm_new_token(raw[i:i+18]);time.sleep(.055)
                time.sleep(1)
        return value


@pytest.mark.parametrize('width',[1440,390])
def test_live_text_reload_final_history_and_polling_fallback(tmp_path,width):
    node=os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:pytest.skip('Browser tooling is optional')
    env=dict(os.environ)
    if subprocess.run([node,'-e',"require.resolve('playwright')"],env=env,capture_output=True).returncode:pytest.skip('Playwright is optional')
    model=SlowSynthetic();frozen=build_frozen_project(tmp_path/'learning',model=model)
    auth=AuthStore(tmp_path/'auth.sqlite');auth.create_account('stream-browser@example.test','test-password-2026')
    sock=socket.socket();sock.bind(('127.0.0.1',0));origin='http://127.0.0.1:'+str(sock.getsockname()[1])
    gateway=EvaluationGateway(create_learning_app(frozen['paths'],llm=model),frozen['paths'],tmp_path/'quota.sqlite',
        auth_store=auth,queued=True,origin=origin,cookie_secure=False)
    gateway.ownership.claim(frozen['project_id'],'stream-browser@example.test')
    server=uvicorn.Server(uvicorn.Config(gateway,log_level='error'));thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    until=time.monotonic()+10
    while not server.started and time.monotonic()<until:time.sleep(.02)
    assert server.started
    evidence=Path(os.getenv('STREAM_BROWSER_EVIDENCE',str(tmp_path)))/str(width);evidence.mkdir(parents=True,exist_ok=True)
    try:
        result=subprocess.run([node,str(Path(__file__).parent/'support/streaming_frontend.cjs'),origin,frozen['project_id'],str(width),str(evidence.resolve())],
            env=env,capture_output=True,text=True,encoding='utf-8',timeout=110)
        assert result.returncode==0,result.stdout+result.stderr
        assert model.call_counts['TutorReply']==3
    finally:server.should_exit=True;thread.join(12);sock.close()
