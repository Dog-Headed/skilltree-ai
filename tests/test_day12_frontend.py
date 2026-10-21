"""Real page regressions with isolated Edge/Chromium, API, Graph and SQLite.

Requires Node + Playwright (test tooling only). No deployment store or paid
provider is opened. DAY12_FRONTEND_EVIDENCE_DIR retains screenshots and traces.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
from threading import Thread
import time

import pytest
import uvicorn

from day12_demo_server import create_demo
from app.v3.learning_repository import LearningRepository
from app.v3.storage import V3Paths


@pytest.fixture(scope='module')
def frontend_server(tmp_path_factory):
    root=tmp_path_factory.mktemp('day12-frontend')
    app=create_demo(root)
    sock=socket.socket();sock.bind(('127.0.0.1',0))
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    deadline=time.monotonic()+15
    while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
    assert server.started,'Isolated browser server did not start'
    try:yield root,f'http://127.0.0.1:{sock.getsockname()[1]}'
    finally:
        server.should_exit=True;thread.join(timeout=10);sock.close()


@pytest.mark.parametrize('scenario',[
    'completed-new','response-lost-found','response-lost-unreadable','create-not-committed',
    'legacy-request','import-success','import-failure','import-recovery-failure',
])
def test_real_frontend_creation_and_import_recovery(frontend_server,tmp_path,scenario):
    root,url=frontend_server
    node=os.environ.get('SKILLTREE_TEST_NODE') or shutil.which('node')
    if not node:pytest.skip('Install Node and Playwright to run real frontend regressions')
    env=os.environ.copy()
    bundled=Path(node).resolve().parent.parent/'node_modules'
    env['NODE_PATH']=os.pathsep.join(filter(None,[str(bundled),env.get('NODE_PATH','')]))
    probe=subprocess.run([node,'-e',"require.resolve('playwright')"],env=env,capture_output=True,text=True,encoding='utf-8')
    if probe.returncode:pytest.skip('Playwright is required for the real frontend regressions')
    if os.name=='nt':env.setdefault('SKILLTREE_TEST_BROWSER_CHANNEL','msedge')
    evidence=Path(env.get('DAY12_FRONTEND_EVIDENCE_DIR',tmp_path))/scenario
    evidence.mkdir(parents=True,exist_ok=True)
    result=subprocess.run([node,str(Path(__file__).parent/'support'/'day12_frontend.cjs'),
                           url,scenario,str(evidence.resolve())],env=env,capture_output=True,text=True,encoding='utf-8',timeout=120)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    report=json.loads((evidence/'result.json').read_text(encoding='utf-8'))
    assert report['scenario']==scenario and report['passed']
    # Check committed facts as well as the page, including preservation of A.
    with LearningRepository(V3Paths(root)) as repo:
        if scenario=='completed-new':
            old,new=report['project_ids']
            assert old!=new
            assert repo.get_project(old)['lifecycle']=='completed' and len(repo.completed(old))==2
            assert repo.get_project(new)['lifecycle']=='profile_review' and repo.completed(new)==[]
            assert repo.conn.execute('SELECT COUNT(*) FROM assessments WHERE project_id=?',(old,)).fetchone()[0]==2
        else:
            for pid in report['project_ids']:
                assert repo.get_project(pid) is not None

