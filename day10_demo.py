"""Offline Day10 three-pack contract demo; no HTTP or real evaluator grants.

Run in a new directory. The stores are permanently marked demo_only and the
real PreparationService refuses them. Simulated confirmations are not approvals.
Evaluation cases (including holdout) are never loaded into the Planner.
"""
import argparse
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from app.v3 import capabilities, planner, preparation
from app.v3.capabilities import CapabilityCheck
from app.v3.context import ContextBuilder, keyword_overlap_score
from app.v3.contracts import EvaluationPolicy, LearningProfile
from app.v3.materials import MaterialService
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths, initialize_storage

ROOT=Path(__file__).resolve().parent
DEMO_EVALUATORS={'choice_exact','text_rubric','numeric_scalar'}


def fake_check(requested,*,has_material,learning_mode='formal'):
    if isinstance(requested,LearningProfile):
        learning_mode=requested.learning_mode;requested=requested.requested_capabilities
    unavailable=[name for name in requested if name not in DEMO_EVALUATORS]
    status='unsupported' if unavailable else 'needs_material' if not has_material else 'supported'
    return CapabilityCheck(status=status,formal_assessment_allowed=status=='supported',
        requested_capability_ids=list(requested),unavailable_capability_ids=unavailable,
        reasons=['ISOLATED FAKE capability contract; no executable evaluator'])


def fake_policy(policy):
    """Retain server thresholds/round limits while simulating known contracts."""
    policy=EvaluationPolicy.model_validate(policy.model_dump() if hasattr(policy,'model_dump') else policy)
    if any(ref.evaluator_id not in DEMO_EVALUATORS or ref.evaluator_version!='1.0.0' for ref in policy.evaluators):
        raise ValueError('Unknown Fake evaluator')
    surrogate=policy.model_dump()
    surrogate['evaluators']=[{'evaluator_id':'choice_exact','evaluator_version':'1.0.0'}]
    surrogate['allowed_question_types']=['single_choice']
    for rule in surrogate['objective_rules']:rule['evidence_kinds']=['choice']
    capabilities.validate_evaluation_policy(surrogate)
    return policy


class OfflinePlanModel:
    """Build deterministic preview fixtures from pack metadata, never case keys."""
    def __init__(self,fixtures):self.fixtures=fixtures;self.calls=0
    def with_structured_output(self,*args,**kwargs):return self
    def invoke(self,messages):
        self.calls+=1
        data=json.loads(messages[1].content.split('\n',1)[1])
        requested=data['profile']['requested_capabilities']
        kinds={'choice_exact':'choice','text_rubric':'text_excerpt','numeric_scalar':'numeric_result'}
        catalog=data['teaching_material_catalog']
        nodes=[]
        for index,fixture in enumerate(self.fixtures):
            outcome=fixture['outcome']
            # The same algorithm and node IDs are used for all subjects.
            selected=[chunk for chunk in catalog if chunk['heading'] and
                      any(chunk['heading'].startswith(section+' ') for section in fixture['sections'])]
            if len(selected)!=len(fixture['sections']):raise ValueError('Demo section missing')
            nodes.append({'node_id':f'node_{index+1}','title':outcome,'description':'依据当前项目资料分步练习：'+outcome,
                'estimated_minutes':20,'prerequisite_ids':[f'node_{index}'] if index else [],
                'objectives':[{'objective_id':f'objective_{index+1}',
                    'observable_outcome':outcome,
                    'required_capability_ids':requested,'evidence_requirement':[kinds[name] for name in requested],
                    'source_chunk_ids':[chunk['chunk_id'] for chunk in selected]}]})
        return {'project_id':data['project_id'],'draft_revision':data['draft_revision'],
                'plan_version':data['plan_version'],'nodes':nodes}


class _DemoService(preparation.PreparationService):
    def __init__(self,paths):
        # This class lives only in the offline CLI, never in app.v3 or the API.
        self.paths=paths


def command(service,view,action,**payload):
    return service.resume(view['project_id'],{'request_id':str(uuid4()),'pending_input_id':view['pending_input_id'],
        'draft_revision':view['draft_revision'],'action':action,**payload})


def run_demo(destination):
    registry_before=capabilities.list_capabilities()
    destination=Path(destination).resolve()
    if (destination/'learning.sqlite').exists() or (destination/'checkpoints.sqlite').exists():
        raise ValueError('Use a new demo directory; never overwrite a runtime')
    paths=initialize_storage(V3Paths(destination))
    with V3Repository(paths) as repo:
        with repo.transaction():repo.conn.execute("INSERT INTO runtime_metadata VALUES ('demo_only','day10-isolated-fake-contract')")
    service=_DemoService(paths)
    results=[]
    # Historical three-pack demo: later packs have their own validation protocol.
    from day10_check_fixtures import SUBJECTS
    for subject in sorted(SUBJECTS):
        manifest_path=ROOT/'materials'/'v3'/subject/'manifest.json'
        manifest=json.loads(manifest_path.read_text(encoding='utf8'))
        suggested=manifest['suggested_plan']
        profile=LearningProfile(subject_label=manifest['subject_label'],topic=manifest['topic'],
            goal=suggested['bounded_goal'],bounded_goal=suggested['bounded_goal'],scope_in=manifest['scope_in'],scope_out=manifest['scope_out'],
            requested_capabilities=suggested['full_goal_required_evaluators'])
        view=service.create(str(uuid4()),profile)
        with V3Repository(paths) as repo:
            materials=MaterialService(repo)
            for document in manifest['documents']:
                raw=(manifest_path.parent/document['filename']).read_bytes()
                assert sha256(raw).hexdigest()==document['content_hash']
                materials.import_upload(view['project_id'],request_id=uuid4(),data=raw,filename=document['filename'],
                    source_id=document['source_id'],title=document['title'],visibility=document['visibility'],
                    source_description='Agent原创、待用户复核；规则依据：'+' ; '.join(document['source_urls']))
        view=service.read(view['project_id'])
        real_gate=capabilities.check_capabilities(profile,has_material=True).model_dump()
        fixtures=json.loads((ROOT/'docs/v3/day10_demo_plans.json').read_text(encoding='utf8'))
        model=OfflinePlanModel(fixtures[manifest_path.parent.name])
        with ExitStack() as stack:
            for module in (capabilities,planner,preparation):stack.enter_context(patch.object(module,'check_capabilities',fake_check))
            for module in (capabilities,planner):stack.enter_context(patch.object(module,'validate_policy',fake_policy))
            stack.enter_context(patch.object(planner,'get_llm',lambda:model))
            preview=command(service,view,'confirm_profile')
            if preview['page_state']!='plan_review':raise AssertionError(preview)
            frozen=command(service,preview,'confirm_plan',private_references=[
                {'reference_id':item['reference_id'],'action':'exclude','node_ids':[]}
                for item in preview['private_references']])
            if not frozen['frozen']:raise AssertionError(frozen)
        citations=[]
        with V3Repository(paths) as repo:
            for node in preview['plan']['nodes']:
                for objective in node['objectives']:
                    context=ContextBuilder(repo).for_teaching(view['project_id'],node['node_id'],objective['objective_id'])
                    assert all(c['visibility']=='teaching' for c in context.citations)
                    citations.append({'node_id':node['node_id'],'objective_id':objective['objective_id'],
                                      'citations':list(context.public_citations)})
            snapshot=repo.get_project(view['project_id'])['frozen_snapshot']
        results.append({'subject':manifest['subject_label'],'profile':profile.model_dump(),'project_id':view['project_id'],
            'real_capability_check':real_gate,'simulated_user_confirmation':True,'human_approved':False,
            'fake_model_calls':model.calls,'preview':preview,'frozen_snapshot':snapshot,'teaching_citations':citations})
    try:preparation.PreparationService(paths)
    except ValueError:real_service_refused=True
    else:raise AssertionError('Real service accepted Fake stores')
    registry_unchanged=capabilities.list_capabilities()==registry_before
    assert registry_unchanged,'Offline Fake overrides changed the real capability registry'
    report={'mode':'ISOLATED_FAKE_CONTRACT_ONLY','real_http_requests':0,'real_evaluations':0,
        'real_service_refuses_demo_store':real_service_refused,'real_registry_unchanged':registry_unchanged,'human_review':'pending_user_review',
        'holdout_cases_read_by_model':0,'plans':results}
    (destination/'plans.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    lines=['# Day10 三科计划复核稿','',
        '这是隔离 Fake 契约演示，模拟了确认与冻结；尚未获得用户确认，也不证明真实规划或评分质量。',
        '真实能力检查按当前服务端注册表记录；演示不会执行或安装真实评价器，也不会改变注册表。演示库始终不能被真实服务打开。','']
    for result in results:
        profile=result['profile'];lines.extend(['## '+result['subject'],'',profile['bounded_goal'],'',
            '正式评价所需能力：'+', '.join(profile['requested_capabilities'])+'；真实检查：'+result['real_capability_check']['status']+'。','',
            '| 节点 | 可观察目标 | 先修 | 资料定位 |','|---|---|---|---|'])
        for node,entry in zip(result['preview']['plan']['nodes'],result['teaching_citations']):
            locations=[c['source_id']+' v'+str(c['source_version'])+' 行'+str(c['line_start'])+'–'+str(c['line_end']) for c in entry['citations']]
            lines.append('| '+node['title']+' | '+node['objectives'][0]['observable_outcome']+' | '+(', '.join(node['prerequisite_ids']) or '无')+
                ' | '+'；'.join(locations)+' |')
        lines.extend(['','默认标准：总分与各必要目标均至少 0.8；critical 阻断；3 轮，可主动追加一次 3 轮；系统换题最多 2 次。',
            '计划已在演示库冻结 profile/plan/policy/source/evaluator 版本；没有出题、评分或完成记录。',''])
    (destination/'三科计划复核稿.md').write_text('\n'.join(lines),encoding='utf8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=run_demo(args.output)
    print(json.dumps({'mode':report['mode'],'plans':len(report['plans']),
        'real_service_refuses_demo_store':report['real_service_refuses_demo_store'],'output':str(args.output.resolve())},ensure_ascii=False))
