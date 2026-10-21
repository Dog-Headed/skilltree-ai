"""Actual SQLite constraints, concurrency, immutable references and query purity."""
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from langgraph.graph import StateGraph, START, END

from app.v3.contracts import LearningProfile, LearningPlan
from app.v3.presets import load_evaluation_policy
from app.v3.repository import V3Repository, ConflictError, BudgetExhaustedError
from app.v3.state import V3State
from app.v3.storage import V3Paths, initialize_storage, open_v3_checkpointer


@pytest.fixture
def paths(tmp_path):
    return initialize_storage(V3Paths(tmp_path / "v3"))


def profile(**changes):
    return LearningProfile(subject_label="任何文字主题",topic="识别资料中的事实",goal="依据资料识别事实",
                           bounded_goal="选择符合资料的描述",requested_capabilities=["choice_exact"],**changes)


def source(project_id, source_id="source", version=1, visibility="teaching", content="依据资料选择正确描述。"):
    digest=hashlib.sha256(content.encode()).hexdigest()
    return ({"project_id":project_id,"source_id":source_id,"source_version":version,
             "title":"案例资料","source_description":"用户提供","content":content,"content_hash":digest,"visibility":visibility},
            [{"project_id":project_id,"source_id":source_id,"source_version":version,"chunk_id":f"chunk-{source_id}-{version}",
              "content":content,"content_hash":digest,"line_start":1,"line_end":1}])


def plan(project):
    return LearningPlan(project_id=project["id"],draft_revision=project["draft_revision"],nodes=[{
        "node_id":"common-node","title":"一个可验证的小单元","description":"阅读后选择描述","estimated_minutes":20,
        "objectives":[{"objective_id":"outcome","observable_outcome":"选择与资料相符的描述",
                       "required_capability_ids":["choice_exact"],"evidence_requirement":["choice"],
                       "source_chunk_ids":["chunk-source-1"]}]}])


def policy():
    draft=load_evaluation_policy().model_dump()
    draft["objective_rules"]=[{"objective_id":"outcome","evidence_kinds":["choice"]}]
    return draft


def candidate(repo):
    p=repo.create_project(uuid4(),profile())
    d,c=source(p["id"])
    repo.put_source(d,c,request_id=uuid4())
    p=repo.get_project(p["id"])
    return repo.save_candidate_plan(p["id"],plan(p),expected_revision=p["draft_revision"])


def freeze(repo,p,selected_policy=None):
    return repo.freeze_plan(p["id"],selected_policy or policy(),expected_revision=p["draft_revision"],pending_input_id=p["pending_input_id"])


def test_v2_files_and_unknown_versions_are_rejected_before_any_write(tmp_path):
    root=tmp_path/'legacy';root.mkdir()
    with sqlite3.connect(root/'learning.sqlite') as conn:
        conn.execute('CREATE TABLE learning_projects(id TEXT PRIMARY KEY,goal TEXT)')
    before=(root/'learning.sqlite').read_bytes()
    with pytest.raises(ValueError,match='non-V3'):
        initialize_storage(V3Paths(root))
    assert (root/'learning.sqlite').read_bytes()==before
    assert not (root/'checkpoints.sqlite').exists()
    paths=initialize_storage(V3Paths(tmp_path/'fresh'))
    with sqlite3.connect(paths.learning) as conn:
        conn.execute("UPDATE runtime_metadata SET value='future' WHERE key='contract_version'")
    before=paths.learning.read_bytes()
    with pytest.raises(ValueError,match='migration'):
        initialize_storage(paths)
    assert paths.learning.read_bytes()==before


def test_separate_stores_checkpoint_restarts_with_same_versions(paths):
    assert paths.learning != paths.checkpoints
    for path,kind in ((paths.learning,'business'),(paths.checkpoints,'checkpoint')):
        with sqlite3.connect(path) as conn:
            metadata=dict(conn.execute('SELECT key,value FROM runtime_metadata'))
            assert metadata['store_kind']==kind and metadata['contract_version']=='3.0.0'
            assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    # A tiny identity-only Graph exercises the real saver, not a V3 learning loop.
    config={'configurable':{'thread_id':'v3_demo'},'recursion_limit':30}
    builder=StateGraph(V3State);builder.add_node('identity',lambda s:{});builder.add_edge(START,'identity');builder.add_edge('identity',END)
    with open_v3_checkpointer(paths) as saver:
        graph=builder.compile(checkpointer=saver)
        graph.invoke({'project_id':'v3_demo','thread_id':'v3_demo','contract_version':'3.0.0'},config,durability='sync')
    with open_v3_checkpointer(paths) as saver:
        snapshot=builder.compile(checkpointer=saver).get_state(config)
        assert snapshot.values['project_id']=='v3_demo' and snapshot.values['contract_version']=='3.0.0'
    with sqlite3.connect(paths.learning) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoints'").fetchone()


def test_concurrent_create_same_request_has_one_stable_identity(paths):
    request=uuid4()
    def create(_):
        with V3Repository(paths) as repo:
            return repo.create_project(request,profile())
    with ThreadPoolExecutor(max_workers=4) as pool:
        projects=list(pool.map(create,range(8)))
    assert len({p['id'] for p in projects})==len({p['pending_input_id'] for p in projects})==1
    assert all(p['thread_id']==p['id'] for p in projects)
    with V3Repository(paths) as repo:
        assert len(repo.list_projects())==1
        changed=profile().model_dump();changed['goal']='不同创建目标'
        with pytest.raises(ConflictError): repo.create_project(request,changed)


def test_queries_do_not_write_or_run_a_model(paths,monkeypatch):
    with V3Repository(paths) as repo:
        p=repo.create_project(uuid4(),profile())
    before={p:p.read_bytes() for p in (paths.learning,paths.checkpoints)}
    monkeypatch.setattr('app.services.llm.get_llm',lambda:pytest.fail('query called model'))
    for _ in range(3):
        with V3Repository(paths) as repo:
            assert repo.get_project(p['id'])['id']==p['id']
            assert len(repo.list_projects())==1
            assert repo.get_progress(p['id'])==repo.list_sources(p['id'])==[]
            assert repo.conn.total_changes==0
    assert all(path.read_bytes()==data for path,data in before.items())


def test_self_report_does_not_mint_assessed_evidence_or_progress(paths):
    with V3Repository(paths) as repo:
        p=repo.create_project(uuid4(),profile(prior_knowledge={'self_reported':['我说我会了']}))
        assert repo.get_progress(p['id'])==[]
        data=profile().model_dump()
        data['prior_knowledge']['assessed_evidence']=[{'project_id':'fake','node_id':'node','assessment_id':'invented','objective_id':'x','summary':'自称测评通过'}]
        with pytest.raises(ValueError,match='verified'):repo.create_project(uuid4(),data)


def test_source_project_isolation_private_permission_and_immutability(paths):
    with V3Repository(paths) as repo:
        p=repo.create_project(uuid4(),profile());other=repo.create_project(uuid4(),profile())
        d,c=source(p['id'],visibility='assessment_private');req=uuid4()
        repo.put_source(d,c,request_id=req);revision=repo.get_project(p['id'])['draft_revision']
        repo.put_source(d,c,request_id=req)
        assert repo.get_project(p['id'])['draft_revision']==revision
        assert repo.list_sources(p['id'])==[] and repo.get_chunk(p['id'],c[0]['chunk_id']) is None
        assert len(repo.list_sources(p['id'],include_private=True))==1
        assert repo.get_chunk(other['id'],c[0]['chunk_id'],include_private=True) is None
        with pytest.raises(ConflictError,match='immutable'):repo.put_source(d,c,request_id=uuid4())
        d2,c2=source(other['id'])
        c2[0]['project_id']=p['id']
        with pytest.raises(ValueError,match='Cross-project'):repo.put_source(d2,c2,request_id=uuid4())


def test_changed_draft_invalidates_candidate_and_old_input(paths):
    with V3Repository(paths) as repo:
        p=candidate(repo)
        d,c=source(p['id'],source_id='new-source')
        repo.put_source(d,c,request_id=uuid4())
        assert repo.get_project(p['id'])['requires_replan']
        with pytest.raises(ConflictError,match='Stale'):freeze(repo,p)
        current=repo.get_project(p['id'])
        changed=current['profile'].copy();changed['topic']='新的范围'
        updated=repo.update_profile(p['id'],changed,expected_revision=current['draft_revision'],pending_input_id=current['pending_input_id'])
        with pytest.raises(ConflictError):repo.update_profile(p['id'],changed,expected_revision=updated['draft_revision'],pending_input_id=current['pending_input_id'])


@pytest.mark.parametrize('attack',['evaluator','future_version','threshold','objective','required','private'])
def test_freeze_rechecks_policy_and_each_objective_permissions(paths,attack):
    with V3Repository(paths) as repo:
        p=candidate(repo);pol=policy()
        if attack=='evaluator': pol['evaluators']=[{'evaluator_id':'code_execution','evaluator_version':'1.0.0'}]
        if attack=='future_version': pol['evaluators']=[{'evaluator_id':'choice_exact','evaluator_version':'future'}]
        if attack=='threshold':pol['total_pass_threshold']=0.1
        if attack=='required':pol['objective_rules'][0]['required']=False
        if attack in ('objective','private'):
            data=p['candidate_plan']
            if attack=='objective':data['nodes'][0]['objectives'][0]['required_capability_ids']=['symbolic_proof']
            else:
                d,c=source(p['id'],'secret',visibility='assessment_private');repo.put_source(d,c,request_id=uuid4())
                p=repo.get_project(p['id']);data['draft_revision']=p['draft_revision']
                data['nodes'][0]['objectives'][0]['source_chunk_ids']=['chunk-secret-1']
            p=repo.save_candidate_plan(p['id'],data,expected_revision=p['draft_revision'])
        with pytest.raises(ValueError):freeze(repo,p,pol)
        assert repo.get_project(p['id'])['frozen_snapshot'] is None
        assert repo.get_progress(p['id'])==[]


def test_snapshot_prepare_assessment_and_progress_are_idempotent(paths):
    with V3Repository(paths) as repo:
        p=freeze(repo,candidate(repo));request=uuid4()
        first=repo.prepare_assessment(p['id'],'common-node',request_id=request)
        assert repo.prepare_assessment(p['id'],'common-node',request_id=request)==first
        assert repo.get_assessment('other-project',first['id']) is None
        assert json.loads(first['snapshot_json'])==p['frozen_snapshot']
        repo.mark_node_started(p['id'],'common-node');before=repo.get_progress(p['id'])
        repo.mark_node_started(p['id'],'common-node');assert repo.get_progress(p['id'])==before
        assert before[0]['completed_at'] is None
        d,c=source(p['id'],'revision')
        with pytest.raises(ConflictError,match='Frozen'):repo.put_source(d,c,request_id=uuid4())
        with pytest.raises(sqlite3.IntegrityError):
            with repo.transaction():
                repo.conn.execute("UPDATE learning_progress SET completed_at='now',completion_assessment_id='wrong-node' WHERE project_id=?",(p['id'],))


def test_operation_reservation_survives_reopen_and_one_idempotent_extension(paths):
    with V3Repository(paths) as repo:
        p=repo.create_project(uuid4(),profile());request=uuid4()
        op=repo.create_operation(p['id'],request,kind='planning')
        assert repo.create_operation(p['id'],request,kind='planning')==op
        assert repo.reserve_model_request(p['id'],op['operation_id'])==1
    # A restarted connection sees reservations committed before hypothetical HTTP.
    with V3Repository(paths) as repo:
        for i in range(2,13):assert repo.reserve_model_request(p['id'],op['operation_id'])==i
        with pytest.raises(BudgetExhaustedError):repo.reserve_model_request(p['id'],op['operation_id'])
        with pytest.raises(ConflictError):repo.create_operation(p['id'],uuid4(),kind='planning',parent_operation_id=op['operation_id'],retry_token='stale')
        continuation_request=uuid4()
        child=repo.create_operation(p['id'],continuation_request,kind='planning',parent_operation_id=op['operation_id'],retry_token=op['retry_token'])
        assert repo.create_operation(p['id'],continuation_request,kind='planning',parent_operation_id=op['operation_id'],retry_token=op['retry_token'])==child
        with pytest.raises(ConflictError):repo.create_operation(p['id'],uuid4(),kind='planning',parent_operation_id=op['operation_id'],retry_token=op['retry_token'])
        for i in range(1,13):assert repo.reserve_model_request(p['id'],child['operation_id'])==i
        with pytest.raises(BudgetExhaustedError):repo.reserve_model_request(p['id'],child['operation_id'])
        with pytest.raises(ConflictError):repo.create_operation(p['id'],uuid4(),kind='planning',parent_operation_id=child['operation_id'],retry_token=child['retry_token'])
        assert repo.conn.execute('SELECT SUM(reserved_requests) FROM model_operations').fetchone()[0]==24


def test_same_node_and_chunk_ids_in_two_projects_keep_distinct_facts(paths):
    with V3Repository(paths) as repo:
        projects=[]
        for content in ('项目甲的课程事实。','项目乙的课程事实。'):
            p=repo.create_project(uuid4(),profile())
            d,c=source(p['id'],content=content)
            repo.put_source(d,c,request_id=uuid4())
            p=repo.get_project(p['id']);p=repo.save_candidate_plan(p['id'],plan(p),expected_revision=p['draft_revision'])
            projects.append(freeze(repo,p))
        assert repo.get_chunk(projects[0]['id'],'chunk-source-1')['content']=='项目甲的课程事实。'
        assert repo.get_chunk(projects[1]['id'],'chunk-source-1')['content']=='项目乙的课程事实。'
        assert len(repo.get_progress(projects[0]['id']))==len(repo.get_progress(projects[1]['id']))==1
        a=repo.prepare_assessment(projects[0]['id'],'common-node',request_id=uuid4())
        assert repo.get_assessment(projects[1]['id'],a['id']) is None


def test_concurrent_requests_cannot_overdraw_the_last_slot(paths):
    with V3Repository(paths) as repo:
        p=repo.create_project(uuid4(),profile());op=repo.create_operation(p['id'],uuid4(),kind='planning')
        for _ in range(11):repo.reserve_model_request(p['id'],op['operation_id'])
    def reserve(_):
        with V3Repository(paths) as repo:
            try:return repo.reserve_model_request(p['id'],op['operation_id'])
            except BudgetExhaustedError:return None
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(reserve,range(6)))
    assert results.count(12)==1 and results.count(None)==5
    with V3Repository(paths) as repo:assert repo.get_operation(p['id'],op['operation_id'])['reserved_requests']==12
