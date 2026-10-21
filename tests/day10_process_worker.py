"""Fault-injection worker: real process death, real SQLite/Graph, Fake model."""
import json
import os
from pathlib import Path
import runpy
import sys
from unittest.mock import patch
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import dotenv
dotenv.load_dotenv=lambda *args,**kwargs:False
from fastapi.testclient import TestClient
from app.v3 import planner
from app.v3.preparation import PreparationService
from app.v3.preparation_api import create_preparation_app
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths,initialize_storage


def main(directory,mode):
    if mode=='replay_retry':
        data=json.loads((directory/'retry.json').read_text(encoding='utf8'))
        with patch.object(planner,'get_llm',lambda:os._exit(99)):
            result=TestClient(create_preparation_app(V3Paths(directory))).post(data['url'],json=data['body'])
        (directory/'replayed.json').write_text(json.dumps({'code':result.status_code,'body':result.json()}),encoding='utf8')
        return
    helpers=runpy.run_path(str(ROOT/'tests/test_v3_preparation.py'))
    model=helpers['Model']();paths=initialize_storage(V3Paths(directory))
    if mode=='continuation_commit':model.failure=True
    invoke=model.invoke
    def recorded(messages):
        with (directory/'calls.jsonl').open('a',encoding='utf8') as stream:stream.write('{}\n')
        if mode in ('inflight','active'):
            if mode=='inflight':os._exit(73)
            print('READY',flush=True)
            sys.stdin.readline()
        return invoke(messages)
    model.invoke=recorded
    with patch.object(planner,'get_llm',lambda:model):
        client=TestClient(create_preparation_app(paths))
        p=helpers['preview'](client) if mode=='freeze_commit' else helpers['upload'](client,helpers['create'](client))
        (directory/'identity.json').write_text(json.dumps(p),encoding='utf8')
        if mode=='continuation_commit':
            failed=helpers['resume'](client,p,'confirm_profile').json()
            for _ in range(12):
                failed=client.post('/projects/'+p['project_id']+'/retry',json={'request_id':str(uuid4()),'retry_token':failed['retry_token']}).json()
            assert failed['page_state']=='budget_exhausted'
            payload={'request_id':str(uuid4()),'retry_token':failed['retry_token'],'action':'continue_with_new_budget'}
            (directory/'continuation.json').write_text(json.dumps(payload),encoding='utf8')
            original=PreparationService._ensure_continuation
            def die_after_child(self,*args):original(self,*args);os._exit(73)
            with patch.object(PreparationService,'_ensure_continuation',die_after_child):
                client.post('/projects/'+p['project_id']+'/retry',json=payload)
            return
        action='confirm_plan' if mode=='freeze_commit' else 'confirm_profile'
        body={'request_id':str(uuid4()),'pending_input_id':p['pending_input_id'],'draft_revision':p['draft_revision'],'action':action}
        if mode in ('candidate_commit','freeze_commit'):
            method='save_candidate_plan' if mode=='candidate_commit' else 'freeze_plan'
            original=getattr(V3Repository,method)
            def die_after_commit(self,*args,**kwargs):
                original(self,*args,**kwargs);os._exit(73)
            with patch.object(V3Repository,method,die_after_commit):client.post('/projects/'+p['project_id']+'/resume',json=body)
        elif mode=='before_command':
            # Interrupt remains persisted; crash immediately after journaling.
            original_transaction=V3Repository.transaction
            from contextlib import contextmanager
            @contextmanager
            def die_after_marker(self):
                with original_transaction(self):yield
                if self.conn.execute('SELECT 1 FROM preparation_execution').fetchone():os._exit(73)
            with patch.object(V3Repository,'transaction',die_after_marker):client.post('/projects/'+p['project_id']+'/resume',json=body)
        elif mode=='after_wait':
            with patch.object(PreparationService,'_finish_execution',lambda *args:os._exit(73)):
                client.post('/projects/'+p['project_id']+'/resume',json=body)
        else:client.post('/projects/'+p['project_id']+'/resume',json=body)


if __name__=='__main__':main(Path(sys.argv[1]),sys.argv[2])
