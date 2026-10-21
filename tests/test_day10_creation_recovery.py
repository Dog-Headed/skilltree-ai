import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID,uuid4

from fastapi.testclient import TestClient
import pytest

from app.v3.preparation import PreparationService
from app.v3.preparation_api import create_preparation_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths
from tests.test_v3_preparation import web,preview,resume


@pytest.mark.parametrize('mode',['project_inserted','before_wait','wait_committed','legacy'])
@pytest.mark.parametrize('route',['replay_create','retry'])
def test_initial_creation_hard_exit_is_recoverable_with_stable_identity_and_no_model(tmp_path,mode,route):
    directory=tmp_path/'v3'
    child=subprocess.run([sys.executable,'-m','tests.preparation_creation_worker',str(directory),mode],
                         cwd=Path(__file__).resolve().parents[1],capture_output=True,timeout=40)
    assert child.returncode==73,child.stderr
    body=json.loads((directory/'request.json').read_text(encoding='utf-8'))
    pid='v3_'+UUID(body['request_id']).hex;paths=V3Paths(directory)
    client=TestClient(create_preparation_app(paths));service=PreparationService(paths)
    before=[p.read_bytes() for p in (paths.learning,paths.checkpoints)]
    view=client.get('/projects/'+pid).json()
    assert view['page_state']=='error' and view['recovery_required'] and view['retry_token']
    assert 'confirm_profile' not in view['allowed_actions'] and 'retry' in view['allowed_actions']
    assert before==[p.read_bytes() for p in (paths.learning,paths.checkpoints)]
    with V3Repository(paths) as repo:original=repo.get_project(pid)
    if route=='replay_create':response=client.post('/projects',json=body)
    else:
        payload={'request_id':str(uuid4()),'retry_token':view['retry_token']}
        response=client.post('/projects/'+pid+'/retry',json=payload)
    assert response.status_code in (200,201),response.text
    ready=response.json()
    assert ready['project_id']==ready['thread_id']==pid and ready['page_state']=='profile_review'
    assert not ready['recovery_required'] and ready['draft_revision']==original['draft_revision']
    assert ready['pending_input_id']==original['pending_input_id']
    with service._graph() as graph:assert graph.get_state(service._config(pid)).interrupts
    clean=[p.read_bytes() for p in (paths.learning,paths.checkpoints)]
    assert client.post('/projects',json=body).json()==ready
    if route=='retry':assert client.post('/projects/'+pid+'/retry',json=payload).json()==ready
    assert clean==[p.read_bytes() for p in (paths.learning,paths.checkpoints)]
    result=client.post('/projects/'+pid+'/resume',json={'request_id':str(uuid4()),'action':'confirm_profile',
        'pending_input_id':ready['pending_input_id'],'draft_revision':ready['draft_revision']})
    assert result.status_code==200 and result.json()['page_state']=='materials_required'
    with V3Repository(paths) as repo:
        assert len(repo.list_projects())==1
        assert repo.conn.execute('SELECT COALESCE(SUM(reserved_requests),0) FROM model_operations').fetchone()[0]==0
        assert repo.conn.execute('SELECT COUNT(*) FROM preparation_execution').fetchone()[0]==0
    assert client.post('/projects',json=body).json()==result.json()


def test_creation_replay_never_resets_an_existing_frozen_project_when_its_checkpoint_is_missing(web):
    from langgraph.checkpoint.sqlite import SqliteSaver
    client,paths,model=web
    ready=resume(client,preview(client),'confirm_plan').json()
    pid=ready['project_id']
    with V3Repository(paths) as repo:before=repo.get_project(pid)
    with SqliteSaver.from_conn_string(str(paths.checkpoints)) as saver:saver.delete_thread(pid)
    response=client.post('/projects',json={'request_id':str(UUID(before['create_request_id'])),'profile':before['profile']})
    assert response.status_code==409
    with V3Repository(paths) as repo:assert repo.get_project(pid)==before
