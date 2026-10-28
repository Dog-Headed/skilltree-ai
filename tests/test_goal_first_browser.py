"""Actual browser/API/Graph/SQLite with explicit Fake content, no deployment DB."""
import json,os,shutil,socket,subprocess,time
from pathlib import Path
from threading import Thread
import pytest
import uvicorn
from app.v3.learning_api import create_learning_app
from app.v3.storage import V3Paths,initialize_storage
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.repository import V3Repository
from tests.test_goal_first import GuidedFake


@pytest.fixture(scope='module')
def goal_server(tmp_path_factory):
    paths=initialize_learning_storage(initialize_storage(V3Paths(tmp_path_factory.mktemp('goal-browser'))))
    model=GuidedFake();app=create_learning_app(paths,llm=model)
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+15
    while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
    assert server.started
    try:yield paths,model,f'http://127.0.0.1:{sock.getsockname()[1]}'
    finally:server.should_exit=True;thread.join(timeout=10);sock.close()


@pytest.mark.parametrize('width',[1440,390])
def test_two_fields_optional_file_and_old_legacy_selection(goal_server,tmp_path,width):
    paths,model,url=goal_server;node=shutil.which('node')
    if not node:pytest.skip('Node/Playwright required for actual browser checks')
    env=dict(os.environ);bundled=Path(node).resolve().parent.parent/'node_modules'
    env['NODE_PATH']=os.pathsep.join(filter(None,[str(bundled),env.get('NODE_PATH','')]))
    if subprocess.run([node,'-e',"require.resolve('playwright')"],env=env,capture_output=True).returncode:pytest.skip('Playwright required')
    evidence=Path(os.environ.get('GOAL_FIRST_BROWSER_EVIDENCE',tmp_path))/str(width);evidence.mkdir(parents=True)
    result=subprocess.run([node,str(Path(__file__).parent/'support/goal_first_frontend.cjs'),url,str(width),str(evidence.resolve())],
        env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    report=json.loads((evidence/'result.json').read_text(encoding='utf-8'))
    assert report['passed'] and not report['legacy_requests']
    with V3Repository(paths) as repo:
        general,provided=report['project_ids']
        assert repo.get_project(general)['lifecycle']=='completed'
        assert repo.conn.execute('SELECT count(*) FROM learning_progress WHERE project_id=? AND completed_at IS NOT NULL',(general,)).fetchone()[0]==1
        source=repo.list_sources(provided)
        assert len(source)==1 and '每周五' in source[0]['content'] and 'AI生成' not in source[0]['trust_note']


@pytest.mark.parametrize('width', [1440, 390])
def test_disconnected_write_follows_readonly_status_until_terminal_or_navigation(goal_server, tmp_path, width):
    _, _, url = goal_server
    node = os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:
        pytest.skip('Node/Playwright required for actual browser checks')
    env = dict(os.environ)
    bundled = Path(node).resolve().parent.parent / 'node_modules'
    env['NODE_PATH'] = os.pathsep.join(filter(None, [str(bundled), env.get('NODE_PATH', '')]))
    if subprocess.run([node, '-e', "require.resolve('playwright')"], env=env, capture_output=True).returncode:
        pytest.skip('Playwright required')
    evidence = tmp_path / str(width)
    evidence.mkdir()
    result = subprocess.run([node, str(Path(__file__).parent / 'support/status_recovery_frontend.cjs'),
        url, str(width), str(evidence)], env=env, capture_output=True, text=True, encoding='utf-8', timeout=120)
    assert result.returncode == 0, result.stdout + '\n' + result.stderr
    report = json.loads((evidence / 'result.json').read_text(encoding='utf-8'))
    assert report['passed'] and report['cases'] == ['failed', 'completed', 'navigation']


@pytest.mark.parametrize('width', [1440, 390])
def test_replacement_modal_dismisses_without_cancelling_or_replaying_request(goal_server, tmp_path, width):
    _, _, url = goal_server
    node = os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:pytest.skip('Node/Playwright required')
    env=dict(os.environ)
    env['NODE_PATH']=str(Path(node).resolve().parent.parent/'node_modules')
    if subprocess.run([node,'-e',"require.resolve('playwright')"],env=env,capture_output=True).returncode:
        pytest.skip('Playwright required')
    evidence=tmp_path/str(width);evidence.mkdir()
    result=subprocess.run([node,str(Path(__file__).parent/'support/replacement_modal_frontend.cjs'),url,str(width),str(evidence)],
        env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    report=json.loads((evidence/'result.json').read_text())
    assert report['passed'] and report['writes']==1 and not report['errors']


@pytest.mark.parametrize('width',[1440,390])
def test_silent_write_response_recovers_from_committed_state_without_reposting(goal_server,tmp_path,width):
    _,_,url=goal_server;node=os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:pytest.skip('Node/Playwright required')
    env=dict(os.environ);env['NODE_PATH']=str(Path(node).resolve().parent.parent/'node_modules')
    if subprocess.run([node,'-e',"require.resolve('playwright')"],env=env,capture_output=True).returncode:pytest.skip('Playwright required')
    evidence=tmp_path/str(width);evidence.mkdir()
    result=subprocess.run([node,str(Path(__file__).parent/'support/silent_write_frontend.cjs'),url,str(width),str(evidence)],
        env=env,capture_output=True,text=True,encoding='utf-8',timeout=90)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    report=json.loads((evidence/'result.json').read_text());assert report['passed'] and report['writes']==1
