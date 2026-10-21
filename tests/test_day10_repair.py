"""Independent-review regressions, including actual uncatchable process death."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from uuid import UUID,uuid4

import pytest
from fastapi.testclient import TestClient
from app.v3 import planner
from app.v3.contracts import LearningProfile
from app.v3.materials import MaterialService
from app.v3.preparation import PreparationService
from app.v3.preparation_api import create_preparation_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths,initialize_storage
from test_v3_preparation import Model,create,upload,resume,preview,web

WORKER=Path(__file__).with_name('day10_process_worker.py')
ROOT=WORKER.parents[1]


@pytest.mark.parametrize('mode',['inflight','candidate_commit','freeze_commit','before_command','after_wait'])
def test_hard_exit_recovers_original_command_and_never_regenerates_saved_plan(tmp_path,monkeypatch,mode):
    directory=tmp_path/mode
    process=subprocess.run([sys.executable,'-B','-X','utf8',str(WORKER),str(directory),mode],cwd=ROOT,
                           capture_output=True,text=True,encoding='utf8',timeout=55)
    assert process.returncode==73,process.stderr
    paths=V3Paths(directory);p=json.loads((directory/'identity.json').read_text(encoding='utf8'));pid=p['project_id']
    model=Model();monkeypatch.setattr(planner,'get_llm',lambda:model)
    client=TestClient(create_preparation_app(paths));before=[f.read_bytes() for f in (paths.learning,paths.checkpoints)]
    view=client.get('/projects/'+pid).json()
    assert view['recovery_required'] and view['execution_status']=='interrupted' and 'retry' in view['allowed_actions']
    assert before==[f.read_bytes() for f in (paths.learning,paths.checkpoints)]
    with V3Repository(paths) as repo:
        saved=repo.get_project(pid);operation=saved['operation_id'];candidate=saved['candidate_input_id']
        charged=repo.get_operation(pid,operation)['reserved_requests']
    body={'request_id':str(uuid4()),'retry_token':view['retry_token']}
    recovered=client.post('/projects/'+pid+'/retry',json=body)
    assert recovered.status_code==200,recovered.text
    result=recovered.json();assert not result['recovery_required'] and result['execution_status']=='idle'
    assert result['page_state']==('learning' if mode=='freeze_commit' else 'plan_review')
    expected=1 if mode in ('inflight','before_command') else 0
    assert len(model.messages)==expected
    with V3Repository(paths) as repo:
        current=repo.get_project(pid)
        assert current['operation_id']==operation
        assert repo.get_operation(pid,operation)['reserved_requests']==charged+expected
        if candidate:assert current['candidate_input_id']==candidate
    # Same recovery request is a read, including after it has converged.
    assert client.post('/projects/'+pid+'/retry',json=body).json()==result
    if mode!='freeze_commit':assert resume(client,result,'confirm_plan').json()['frozen']
    with V3Repository(paths) as repo:
        assert len(repo.get_progress(pid))==1
        assert repo.conn.execute('SELECT COUNT(*) FROM knowledge_nodes WHERE project_id=?',(pid,)).fetchone()[0]==1


def test_live_executor_is_not_treated_as_abandoned_or_reentered(tmp_path):
    directory=tmp_path/'active'
    process=subprocess.Popen([sys.executable,'-B','-X','utf8',str(WORKER),str(directory),'active'],cwd=ROOT,
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf8')
    try:
        # The model blocks after durable precharge; timeout bounds the handshake.
        with ThreadPoolExecutor(1) as pool:assert pool.submit(process.stdout.readline).result(timeout=40).strip()=='READY'
        p=json.loads((directory/'identity.json').read_text(encoding='utf8'));pid=p['project_id']
        client=TestClient(create_preparation_app(V3Paths(directory)))
        view=client.get('/projects/'+pid).json()
        assert view['execution_status']=='active' and not view['recovery_required'] and view['allowed_actions']==[]
        attempted=client.post('/projects/'+pid+'/retry',json={'request_id':str(uuid4()),'retry_token':view['retry_token']})
        assert attempted.status_code==409 and attempted.json()['error']['code']=='execution_active'
        process.communicate(input='\n',timeout=45)
        assert process.returncode==0
        assert client.get('/projects/'+pid).json()['page_state']=='plan_review'
        assert len((directory/'calls.jsonl').read_text().splitlines())==1
    finally:
        if process.poll() is None:process.kill();process.communicate(timeout=10)


def test_retry_request_is_idempotent_sequential_concurrent_and_across_processes(web):
    client,paths,model=web;model.failure=True;p=upload(client,create(client));failed=resume(client,p,'confirm_profile').json()
    body={'request_id':str(uuid4()),'retry_token':failed['retry_token']};url='/projects/'+p['project_id']+'/retry'
    with ThreadPoolExecutor(8) as workers:responses=list(workers.map(lambda _:client.post(url,json=body),range(8)))
    assert all(r.status_code==200 for r in responses)
    assert len(model.messages)==2
    first=client.post(url,json=body).json();assert len(model.messages)==2
    with V3Repository(paths) as repo:assert repo.conn.execute('SELECT SUM(reserved_requests) FROM model_operations').fetchone()[0]==2
    assert client.post(url,json={**body,'retry_token':'changed-token'}).status_code==409
    (paths.root/'retry.json').write_text(json.dumps({'url':url,'body':body}),encoding='utf8')
    replay=subprocess.run([sys.executable,'-B','-X','utf8',str(WORKER),str(paths.root),'replay_retry'],cwd=ROOT,
                          capture_output=True,text=True,encoding='utf8',timeout=45)
    assert replay.returncode==0,replay.stderr
    assert json.loads((paths.root/'replayed.json').read_text(encoding='utf8'))['body']==first
    assert client.post(url,json={**body,'request_id':str(uuid4())}).status_code==200
    assert len(model.messages)==3


def test_original_line_order_is_identical_on_every_import_path(tmp_path):
    paths=initialize_storage(V3Paths(tmp_path/'ordered'))
    with V3Repository(paths) as repo:
        p=repo.create_project(UUID('b1ffd7b9-e983-40dc-b054-0c9e5a2fc0fd'),LearningProfile(subject_label='历史',topic='资料阅读',goal='辨认资料中的事实',
            bounded_goal='选择与资料相符的描述',requested_capabilities=['choice_exact']))
        args={'content':'# 第一节\n资料中的事实需要依据。\n\n# 第二节\n选择符合资料的描述。',
              'title':'课程摘录','source_description':'用户整理的课程资料','source_id':'source'}
        service=MaterialService(repo);request=UUID('00000000-0000-0000-0000-000000000001')
        first=service.import_text(p['id'],request_id=request,**args)
        assert [c.line_start for c in sorted(first.chunks,key=lambda c:c.chunk_id)]==[4,1]
        for next_request in (request,uuid4()):
            actual=service.import_text(p['id'],request_id=next_request,**args)
            assert [c.line_start for c in actual.chunks]==[1,4]
            assert actual.chunks==first.chunks and actual.draft_revision==first.draft_revision
        assert [c['line_start'] for c in repo.list_source_chunks(p['id'],'source',1)]==[1,4]


@pytest.mark.parametrize('size',[2200,1350])
def test_oversized_catalog_or_complete_prompt_can_be_corrected_via_public_actions(web,size):
    client,paths,model=web;p=upload(client,create(client),content='# 变量与循环\n'+('变量的值与循环停止条件。\n'*size))
    old=resume(client,p,'confirm_profile').json()
    assert old['page_state']=='materials_required' and old['error_type']=='ContextBudgetExceeded'
    assert {'import_material','adjust_scope','replan'}<=set(old['allowed_actions']) and not model.messages
    restarted=TestClient(create_preparation_app(paths))
    assert restarted.get('/projects/'+p['project_id']).json()==old
    if size==1350:
        # Catalog itself fits: this exercises schema+policy+prompt overhead.
        with V3Repository(paths) as repo:assert MaterialService(repo).catalog(p['project_id'])
        corrected=resume(restarted,old,'adjust_scope',profile={**old['profile'],'bounded_goal':'选择变量的值与循环停止条件'}).json()
        assert corrected['page_state']=='profile_review'
    else:corrected=old
    new=upload(restarted,corrected,content='# 变量与循环\n变量保存值，循环停止条件决定何时结束。')
    planned=resume(restarted,new,'confirm_profile' if size==1350 else 'replan').json()
    assert planned['page_state']=='plan_review' and len(model.messages)==1
    assert planned['pending_input_id']!=old['pending_input_id'] and planned['draft_revision']>old['draft_revision']
    assert resume(restarted,old,'confirm_plan').status_code==409
    assert resume(restarted,planned,'confirm_plan').json()['frozen']


@pytest.mark.parametrize('metadata_committed',[False,True])
def test_day10_v1_interrupted_store_migrates_without_losing_checkpoints(tmp_path,monkeypatch,metadata_committed):
    import sqlite3
    from app.v3.storage import migrate_day9_storage,DB_SCHEMA_VERSION
    directory=tmp_path/'old-day10'
    process=subprocess.run([sys.executable,'-B','-X','utf8',str(WORKER),str(directory),'candidate_commit'],cwd=ROOT,
        capture_output=True,text=True,encoding='utf8',timeout=55)
    assert process.returncode==73,process.stderr
    paths=V3Paths(directory);p=json.loads((directory/'identity.json').read_text(encoding='utf8'));pid=p['project_id']
    with sqlite3.connect(paths.learning) as conn:
        conn.execute('DELETE FROM preparation_execution')
        conn.execute("DELETE FROM runtime_metadata WHERE key='preparation_recovery_seeded'")
        if not metadata_committed:
            conn.execute('DROP TABLE preparation_execution');conn.execute('DROP TABLE preparation_retries')
    snapshots=[]
    for path in (paths.learning,paths.checkpoints):
        with sqlite3.connect(path) as conn:
            if not metadata_committed:conn.execute("UPDATE runtime_metadata SET value='v3-day10-1' WHERE key='db_schema_version'")
            if path==paths.checkpoints:snapshots=conn.execute('SELECT * FROM checkpoints ORDER BY thread_id,checkpoint_ns,checkpoint_id').fetchall()
    migrate_day9_storage(paths)
    with sqlite3.connect(paths.checkpoints) as conn:
        assert conn.execute('SELECT * FROM checkpoints ORDER BY thread_id,checkpoint_ns,checkpoint_id').fetchall()==snapshots
        assert dict(conn.execute('SELECT key,value FROM runtime_metadata'))['db_schema_version']==DB_SCHEMA_VERSION
    model=Model();monkeypatch.setattr(planner,'get_llm',lambda:model)
    client=TestClient(create_preparation_app(paths));view=client.get('/projects/'+pid).json();assert view['recovery_required']
    recovered=client.post('/projects/'+pid+'/retry',json={'request_id':str(uuid4()),'retry_token':view['retry_token']}).json()
    assert recovered['page_state']=='plan_review' and not model.messages
    before=[f.read_bytes() for f in (paths.learning,paths.checkpoints)]
    migrate_day9_storage(paths)
    assert before==[f.read_bytes() for f in (paths.learning,paths.checkpoints)]


def test_exit_after_budget_extension_reuses_one_child_and_retry_journal(tmp_path,monkeypatch):
    directory=tmp_path/'continuation'
    process=subprocess.run([sys.executable,'-B','-X','utf8',str(WORKER),str(directory),'continuation_commit'],cwd=ROOT,
        capture_output=True,text=True,encoding='utf8',timeout=55)
    assert process.returncode==73,process.stderr
    paths=V3Paths(directory);pid=json.loads((directory/'identity.json').read_text(encoding='utf8'))['project_id']
    client=TestClient(create_preparation_app(paths));view=client.get('/projects/'+pid).json()
    assert view['recovery_required']
    original_payload=json.loads((directory/'continuation.json').read_text(encoding='utf8'))
    model=Model();monkeypatch.setattr(planner,'get_llm',lambda:model)
    # A retransmission of the accepted continuation does not execute it again.
    assert client.post('/projects/'+pid+'/retry',json=original_payload).json()['recovery_required']
    assert not model.messages
    recovered=client.post('/projects/'+pid+'/retry',json={'request_id':str(uuid4()),'retry_token':view['retry_token']}).json()
    assert recovered['page_state']=='plan_review' and len(model.messages)==1
    with V3Repository(paths) as repo:
        operations=repo.conn.execute('SELECT * FROM model_operations').fetchall()
        assert len(operations)==2 and sum(op['reserved_requests'] for op in operations)==13
    assert client.post('/projects/'+pid+'/retry',json=original_payload).json()==recovered
    assert len(model.messages)==1


@pytest.mark.parametrize('planned',[False,True])
def test_rest_never_creates_unfinished_execution_or_changes_checkpoints(web,planned):
    client,paths,model=web;p=preview(client) if planned else create(client)
    before=[f.read_bytes() for f in (paths.learning,paths.checkpoints)];calls=len(model.messages)
    assert resume(client,p,'rest').json()==p
    assert [f.read_bytes() for f in (paths.learning,paths.checkpoints)]==before
    assert len(model.messages)==calls
