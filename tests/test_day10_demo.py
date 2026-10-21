from day10_demo import run_demo
from app.v3.capabilities import check_capabilities, list_capabilities


def test_three_subjects_share_graph_and_remain_isolated_fake_contracts(tmp_path):
    before=list_capabilities()
    report=run_demo(tmp_path/'demo')
    assert report['real_http_requests']==report['real_evaluations']==0
    assert report['real_service_refuses_demo_store']
    assert report['real_registry_unchanged'] and list_capabilities()==before
    assert len(report['plans'])==3
    assert all(p['real_capability_check']['status']=='supported' for p in report['plans'])
    assert not check_capabilities(['code_execution'],has_material=True).formal_assessment_allowed
    assert not check_capabilities(['symbolic_proof'],has_material=True).formal_assessment_allowed
    assert all(p['fake_model_calls']==1 and not p['human_approved'] for p in report['plans'])
    # Identical node names are safe because every chunk and query is project-bound.
    ids=[p['project_id'] for p in report['plans']]
    assert len(set(ids))==3
    assert len({p['preview']['plan']['nodes'][0]['node_id'] for p in report['plans']})==1
    assert report['holdout_cases_read_by_model']==0
