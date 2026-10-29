"""Day12 browser-facing security, lifecycle and management contracts."""
from hashlib import sha256
import json
from pathlib import Path
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.v3.learning_api import create_learning_app
from app.v3.learning_repository import LearningRepository
from app.v3.runtime_storage import initialize_learning_storage,learning_checkpoint_path
from app.v3.storage import initialize_storage,V3Paths
from tests.day11_support import build_frozen_project,learning_event,answers_for_quiz,private_quiz,FakeLearningModel


def api(frozen,tmp_path):
    return TestClient(create_learning_app(frozen['paths'],llm=frozen['model'],legacy_business_path=tmp_path/'missing-v2.sqlite',legacy_checkpoint_path=tmp_path/'missing-cp.sqlite'))


def hashes(paths):
    return {str(p):sha256(p.read_bytes()).hexdigest() for p in (paths.learning,paths.checkpoints,learning_checkpoint_path(paths))}


def test_queries_include_capabilities_and_locatable_sources_without_writes(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=2);client=api(f,tmp_path);pid=f['project_id']
    before=hashes(f['paths']);calls=len(f['model'].calls)
    view=client.get('/projects/'+pid).json()
    assert view['allowed_actions']==['begin'] and len(view['nodes'])==2
    assert not view['nodes'][0]['passed'] and view['nodes'][1]['status']=='locked'
    assert client.get('/projects').json()[0]['project_id']==pid
    assert client.get('/capabilities').status_code==200
    public_ids={d['source_id'] for d in view['sources']}
    with LearningRepository(f['paths']) as repo:
        for d in repo.list_sources(pid,include_private=True):
            response=client.get(f"/projects/{pid}/sources/{d['source_id']}/versions/{d['source_version']}")
            if d['visibility']=='assessment_private':
                assert response.status_code==404 and d['source_id'] not in public_ids
                assert d['content'] not in json.dumps(view,ensure_ascii=False)
            else:
                doc=response.json();assert doc['content']==d['content']
                for chunk in doc['chunks']:
                    assert chunk['content']=='\n'.join(doc['content'].splitlines()[chunk['line_start']-1:chunk['line_end']])
    assert hashes(f['paths'])==before and len(f['model'].calls)==calls


def test_two_nodes_feedback_and_passed_are_backend_facts(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=2);client=api(f,tmp_path);pid=f['project_id']
    view=client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())}).json()
    for count in (1,2):
        view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'start_quiz')).json()
        quiz=private_quiz(f['paths'],pid,view['assessment_id'])
        view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'submit_answer',answers=answers_for_quiz(quiz))).json()
        assert view['guard']['passed'] and len(view['feedback']['objective_results'])
        assert sum(n['passed'] for n in view['nodes'])==count
        assert view['feedback']['assessment_id']==quiz['assessment_id']
    assert view['page_state']=='completed'


def test_rename_and_delete_only_affect_selected_project_and_replays_do_not_resurrect(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=1);client=api(f,tmp_path);pid=f['project_id']
    with LearningRepository(f['paths']) as repo:p=repo.get_project(pid)
    before=hashes(f['paths']);calls=len(f['model'].calls)
    assert client.patch('/projects/'+pid,json={'display_name':'  新名称  '}).json()['display_name']=='新名称'
    with LearningRepository(f['paths']) as repo:assert repo.get_project(pid)['profile']==p['profile']
    assert client.get('/projects').json()[0]['display_name']=='新名称'
    assert len(f['model'].calls)==calls
    assert client.request('DELETE','/projects/'+pid,json={'confirm_project_id':'wrong'}).status_code==409
    client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())})
    for _ in range(2):assert client.request('DELETE','/projects/'+pid,json={'confirm_project_id':pid}).status_code==200
    assert client.get('/projects').json()==[] and client.get('/projects/'+pid).status_code==404
    assert client.post('/projects',json={'request_id':p['create_request_id'],'profile':p['profile']}).status_code==409
    assert client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())}).status_code==404
    with LearningRepository(f['paths']) as repo:
        assert repo.conn.execute('PRAGMA foreign_key_check').fetchall()==[]
        for table in ('assessments','model_tasks','tutor_turns','learning_sessions','source_documents'):
            assert repo.conn.execute(f'SELECT count(*) FROM {table} WHERE project_id=?',(pid,)).fetchone()[0]==0


@pytest.mark.parametrize('subject',['python','mathematics','english'])
def test_public_pack_contains_no_private_material_or_holdout_data(tmp_path,subject):
    f=build_frozen_project(tmp_path/'v3',node_count=1);client=api(f,tmp_path)
    result=client.get('/material-packs/'+subject)
    assert result.status_code==200
    pack=result.json();assert pack['review_status']=='pending_user_review'
    assert pack['documents'] and all(d['visibility']=='teaching' for d in pack['documents'])
    assert 'assessment_private' not in result.text and 'holdout' not in result.text
    assert 'api_key' not in result.text


def test_private_source_cross_project_id_and_origin_rejected(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=1);client=api(f,tmp_path)
    pid=f['project_id'];doc=client.get('/projects/'+pid).json()['sources'][0]
    response=client.get(f"/projects/other/sources/{doc['source_id']}/versions/1")
    assert response.status_code==404
    response=client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())},headers={'Origin':'https://untrusted.invalid'})
    assert response.status_code==403
    assert "script-src 'self'" in client.get('/capabilities').headers['Content-Security-Policy']


def test_feedback_guard_belongs_to_its_assessment_not_a_previous_pass(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=2);client=api(f,tmp_path);pid=f['project_id']
    view=client.post(f'/projects/{pid}/begin',json={'request_id':str(uuid4())}).json()
    view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'start_quiz')).json()
    quiz=private_quiz(f['paths'],pid,view['assessment_id'])
    view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'submit_answer',answers=answers_for_quiz(quiz))).json()
    assert view['feedback']['guard']['passed'] and view['feedback']['node_id']=='node_1'
    assert view['current_node_id']=='node_2' and not view['nodes'][1]['passed']
    f['model'].grading_status='needs_review'
    view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'start_quiz')).json()
    quiz=private_quiz(f['paths'],pid,view['assessment_id'])
    view=client.post(f'/projects/{pid}/resume',json=learning_event(view,'submit_answer',answers=answers_for_quiz(quiz))).json()
    assert view['page_state']=='assessment_review'
    assert view['feedback']['node_id']=='node_2' and view['feedback']['guard'] is None
    assert not view['nodes'][1]['passed'] and view['completed_node_ids']==['node_1']


def test_public_plan_filters_private_chunk_and_criterion_ids(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=1);client=api(f,tmp_path);pid=f['project_id']
    with LearningRepository(f['paths']) as repo:
        d=next(d for d in repo.list_sources(pid,include_private=True) if d['visibility']=='assessment_private')
        private_id=repo.list_source_chunks(pid,d['source_id'],d['source_version'],include_private=True)[0]['chunk_id']
        p=repo.get_project(pid);plan=p['candidate_plan']
        plan['nodes'][0]['objectives'][0]['source_chunk_ids'].append(private_id)
        plan['nodes'][0]['objectives'][0]['criterion_ids']=['PRIVATE_CRITERION_ID']
        with repo.transaction():repo.conn.execute('UPDATE learning_projects SET candidate_plan_json=? WHERE id=?',(json.dumps(plan),pid))
    # Even if internal plan references include private assessment bindings, no
    # private locator or rubric identity is exposed by the browser projection.
    response=client.get('/projects/'+pid)
    assert response.status_code==200
    assert private_id not in response.text and 'PRIVATE_CRITERION_ID' not in response.text


def test_all_assets_exist_and_no_inline_or_remote_scripts(tmp_path):
    f=build_frozen_project(tmp_path/'v3',node_count=1);client=api(f,tmp_path)
    page=client.get('/');assert page.status_code==200
    assert '<script src="/assets/v3.js" defer>' in page.text
    for asset in ('v3.js','v3.css'):assert client.get('/assets/'+asset).status_code==200
    assert client.get('/assets/unknown.js').status_code==404
    # Every script and stylesheet a page links is served; pages and other files are not assets.
    import re
    from app.v3.learning_api import STATIC
    for name in ('v3.html','login.html'):
        for asset in re.findall(r'(?:src|href)="/assets/([^"/]+)"',(STATIC/name).read_text(encoding='utf-8')):
            response=client.get('/assets/'+asset);assert response.status_code==200 and response.headers['cache-control']=='no-store',asset
    for blocked in ('login.html','index.html','v3.html','..%2Fapp.py','%2E%2E%2Fv3.js'):assert client.get('/assets/'+blocked).status_code==404,blocked
    # Font subsets are cached by the browser; a missing font is not.
    font=client.get('/assets/fonts/design-000.woff2')
    assert font.status_code==200 and font.headers['cache-control']=='public, max-age=604800'
    assert client.get('/assets/fonts/design-999.woff2').headers['cache-control']=='no-store'
