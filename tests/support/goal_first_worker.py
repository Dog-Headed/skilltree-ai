"""Real process-exit recovery proof with explicit Fake model, no paid requests."""
import argparse,json,os,sys
from pathlib import Path
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from fastapi.testclient import TestClient
from tests.test_goal_first import GuidedFake
from app.v3.learning_api import create_learning_app
from app.v3.materials import MaterialService
from app.v3.repository import V3Repository
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths,initialize_storage

p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--mode',choices=['notes','plan','recover'],required=True);a=p.parse_args()
a.root.mkdir(parents=True,exist_ok=True);paths=V3Paths(a.root/'data')
class LoggedFake(GuidedFake):
    def _invoke(self,schema,messages):
        result=super()._invoke(schema,messages)
        with (a.root/'calls.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'schema':schema})+'\n')
        return result
model=LoggedFake()
if a.mode!='recover':initialize_learning_storage(initialize_storage(paths))
client=TestClient(create_learning_app(paths,llm=model))
if a.mode!='recover':
    view=client.post('/projects',json={'request_id':str(uuid4()),'intent':{'goal':'从零学习英语基础','prior_knowledge':'零基础'}}).json()
    (a.root/'identity.json').write_text(json.dumps({'project_id':view['project_id']}),encoding='utf-8')
    if a.mode=='notes':
        original=MaterialService.import_text
        def crash(self,*args,**kwargs):
            result=original(self,*args,**kwargs);os._exit(91)
        MaterialService.import_text=crash
    else:
        original=V3Repository.save_candidate_plan
        def crash(self,*args,**kwargs):
            result=original(self,*args,**kwargs)
            (a.root/'candidate-id.json').write_text(json.dumps({'input':self.get_project(view['project_id'])['candidate_input_id']}),encoding='utf-8')
            os._exit(91)
        V3Repository.save_candidate_plan=crash
    client.post('/projects/'+view['project_id']+'/resume',json={'request_id':str(uuid4()),'pending_input_id':view['pending_input_id'],
        'draft_revision':view['draft_revision'],'action':'confirm_profile'})
    raise AssertionError('Expected hard exit was not reached')
else:
    pid=json.loads((a.root/'identity.json').read_text(encoding='utf-8'))['project_id']
    view=client.get('/projects/'+pid).json();assert view['page_state']=='error' and view['recovery_required']
    view=client.post('/projects/'+pid+'/retry',json={'request_id':str(uuid4()),'retry_token':view['retry_token']}).json()
    assert view['page_state']=='plan_review',view
    if (a.root/'candidate-id.json').exists():assert view['pending_input_id']==json.loads((a.root/'candidate-id.json').read_text())['input']
    with V3Repository(paths) as repo:
        assert len(repo.list_sources(pid))==1
        assert repo.conn.execute('SELECT sum(reserved_requests) FROM model_operations').fetchone()[0]==3
    calls=[json.loads(line)['schema'] for line in (a.root/'calls.jsonl').read_text().splitlines()]
    assert calls==['LearningPreparation','StudyNotes','LearningPlan'],calls
    (a.root/'result.json').write_text(json.dumps({'same_project_thread':view['project_id']==view['thread_id'],'requests':3,
        'real_model_requests':0,'page_state':view['page_state'],'calls':calls},indent=2),encoding='utf-8')
