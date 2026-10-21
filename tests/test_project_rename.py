from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.repository import LearningRepository
from app.main import create_app
from app.services.learning_session import LearningSession


@pytest.fixture
def web(tmp_path):
    paths={'learning_db_path':tmp_path/'learning.sqlite','checkpoint_db_path':tmp_path/'checkpoints.sqlite'}
    return TestClient(create_app(**paths)),paths


def create(client,goal='原始学习目标'):
    return client.post('/projects',json={'goal':goal,'request_id':str(uuid4())}).json()


def test_rename_changes_only_display_label_and_survives_restart_without_model_or_checkpoint_write(web,monkeypatch):
    client,paths=web;p=create(client);other=create(client,'另一项目')
    before_checkpoint=paths['checkpoint_db_path'].read_bytes()
    with LearningRepository(paths['learning_db_path']) as repo:
        original=repo.get_project(p['project_id']);tree=repo.get_tree(p['project_id'])
    monkeypatch.setattr(LearningSession,'snapshot',lambda *args:pytest.fail('重命名不能运行Graph或模型'))
    result=client.patch('/projects/'+p['project_id'],json={'display_name':'  Python 入门  '})
    assert result.status_code==200 and result.json()['display_name']=='Python 入门'
    assert paths['checkpoint_db_path'].read_bytes()==before_checkpoint
    monkeypatch.undo()
    restarted=TestClient(create_app(**paths));read=restarted.get('/projects/'+p['project_id']).json()
    assert read['goal']==p['goal'] and read['display_name']=='Python 入门'
    assert read['pending_input_id']==p['pending_input_id'] and read['nodes']==p['nodes']
    assert next(x for x in restarted.get('/projects').json() if x['project_id']==p['project_id'])['display_name']=='Python 入门'
    assert restarted.get('/projects/'+other['project_id']).json()==other
    with LearningRepository(paths['learning_db_path']) as repo:
        assert repo.get_project(p['project_id'])==original and repo.get_tree(p['project_id'])==tree


@pytest.mark.parametrize('name',['','   ','x'*81,'line\nbreak','nul\x00name'])
def test_invalid_name_never_changes_label(web,name):
    client,paths=web;p=create(client)
    assert client.patch('/projects/'+p['project_id'],json={'display_name':name}).status_code==422
    assert client.get('/projects/'+p['project_id']).json()==p


def test_name_is_plain_data_and_cannot_change_goal_or_restore_a_deleted_record(web):
    client,paths=web;p=create(client);url='/projects/'+p['project_id']
    name='<script>alert("name")</script>'
    assert client.patch(url,json={'display_name':name}).json()['display_name']==name
    assert client.get(url).json()['goal']==p['goal']
    assert client.patch(url,json={'display_name':'合法名称','goal':'恶意改学习目标'}).status_code==422
    assert client.patch(url,json={'display_name':'来源外修改'},headers={'Origin':'https://other.invalid'}).status_code==403
    assert client.request('DELETE',url,json={'confirm_project_id':p['project_id']}).status_code==200
    assert client.patch(url,json={'display_name':'不能复活'}).status_code==404
    with LearningRepository(paths['learning_db_path']) as repo:
        assert repo.conn.execute('SELECT COUNT(*) FROM project_labels').fetchone()[0]==0


def test_busy_project_cannot_be_renamed_and_unknown_id_does_not_create_record(web,monkeypatch):
    from app.agents import tutor
    client,paths=web;p=create(client);entered=Event();release=Event()
    def paused(*args):
        entered.set();assert release.wait(10);return '一次问答'
    monkeypatch.setattr(tutor,'generate_tutor_content',paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task=pool.submit(client.post,'/projects/'+p['project_id']+'/resume',json={'pending_input_id':p['pending_input_id'],'action':'ask','message':'简单解释'})
        assert entered.wait(10)
        try:assert client.patch('/projects/'+p['project_id'],json={'display_name':'忙时名称'}).status_code==409
        finally:release.set()
        assert task.result().status_code==200
    assert client.patch('/projects/missing',json={'display_name':'不存在'}).status_code==404
