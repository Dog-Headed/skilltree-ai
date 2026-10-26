"""Auditable V3 content evaluation. No expected labels are sent to the model.

Development, candidate freezing, holdout and novel-topic stages are separate
commands. Reports never turn a Fake run into a content-quality measurement.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import subprocess
from threading import Lock
from time import perf_counter
from uuid import NAMESPACE_URL, uuid5

from langchain_core.callbacks import BaseCallbackHandler

from app.v3.assessment import evaluate_quiz
from app.v3.contracts import (AssessmentQuiz, EvaluationPolicy, EvaluationResult,
    LearningProfile, SkillNode)
from app.v3.diagnosis import DiagnosisDecision, diagnose
from app.v3.guard import decide_progress
from app.v3.model_tasks import run_model_task
from app.v3.quality_review import QualityReview, review_assessment
from app.v3.repository import V3Repository, encode
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.storage import V3Paths, initialize_storage

ROOT=Path(__file__).resolve().parent
PROTOCOL=ROOT/'evals/v3/day13/protocol.json'
SUBJECTS=('python','mathematics','english')
BLOCKED_MODEL_FIELDS={'human_expectation','candidate_content_error','agent_reference_check',
    'expected_action','expected_passed','question_score_ranges','scenario_tags','score_center'}


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    temporary.replace(path)


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def assert_no_labels(value):
    if isinstance(value,dict):
        if set(value)&BLOCKED_MODEL_FIELDS:raise ValueError('Expected label crossed model boundary')
        for v in value.values():assert_no_labels(v)
    elif isinstance(value,list):
        for v in value:assert_no_labels(v)


def current_fingerprint():
    # Include executable evaluator/runner code, policies, source packs and all
    # case bytes, but never deserialize held-out case contents to create it.
    paths=[p for folder in ('app','configs/v3/policies')
           for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in {'.py','.json','.md','.js','.css','.html'}]
    paths += [p for s in SUBJECTS for p in (ROOT/'materials/v3'/s).rglob('*') if p.is_file()]
    paths += [ROOT/'configs/v3/subjects'/(s+'.json') for s in (*SUBJECTS,'generic')]
    paths += [p for subject in SUBJECTS for p in (ROOT/'evals/v3'/subject/'cases').glob('*.json')]
    paths += [ROOT/'requirements.txt',Path(__file__),PROTOCOL,PROTOCOL.parent/'development_standards.json']
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(set(paths))}


def model_identity():
    from app.services.llm import get_llm  # loads local configuration, no HTTP
    return {'configured_model':os.getenv('LLM_MODEL'),
            'endpoint_sha256':sha256(os.getenv('LLM_BASE_URL','').encode()).hexdigest(),
            'sdk_retries':0,'timeout_seconds':45}


def _source_blocks(subject,project_id,root=ROOT):
    base=root/'materials/v3'/subject;manifest=read_json(base/'manifest.json')
    blocks={};sources=[]
    for document in manifest['documents']:
        raw=(base/document['filename']).read_bytes()
        if sha256(raw).hexdigest()!=document['content_hash']:raise ValueError('Frozen material hash mismatch')
        lines=raw.decode('utf-8').splitlines()
        sources.append({'source_id':document['source_id'],'source_version':document['source_version'],
                        'content_hash':document['content_hash']})
        for section in document['sections']:
            content='\n'.join(lines[section['line_start']-1:section['line_end']])
            cid='section_'+sha256((document['source_id']+':'+section['section_id']).encode()).hexdigest()[:24]
            blocks[(document['filename'],section['section_id'])]={
                'citation':{'source_id':document['source_id'],'source_version':document['source_version'],
                    'chunk_id':cid,'line_start':section['line_start'],'line_end':section['line_end'],
                    'visibility':document['visibility']},'content':content,
                'content_hash':sha256(content.encode()).hexdigest(),'source_content_hash':document['content_hash']}
    return blocks,sources


def adapt_case(case,*,subject,project_id,standards,root=ROOT):
    """Translate Day10 planned contracts to available handlers, preserving the originals."""
    blocks,sources=_source_blocks(subject,project_id,root)
    lc=case['learning_context'];question_rows=deepcopy(case['questions'])
    edits=standards.get('input_revision',{})
    if set(edits)-{'questions','objectives','history','reason'}:
        raise ValueError('Unsupported case input revision')
    if set(edits.get('questions',{}))-{q['question_id'] for q in question_rows}:
        raise ValueError('Unknown question in input revision')
    if set(edits.get('objectives',{}))-{o['objective_id'] for o in lc['current_objectives']}:
        raise ValueError('Unknown objective in input revision')
    questions=[];contexts={};used_sources={}
    for q in question_rows:
        override=edits.get('questions',{}).get(q['question_id'],{})
        if set(override)-{'prompt','reference_answer','criterion_descriptions','extra_source_refs'}:
            raise ValueError('Unsupported question input revision')
        if set(override.get('criterion_descriptions',{}))-{c['criterion_id'] for c in q.get('rubric',[])}:
            raise ValueError('Unknown criterion in input revision')
        q.update({k:v for k,v in override.items() if k in {'prompt','reference_answer'}})
        rubric=[]
        for r in q.get('rubric',[]):
            description=override.get('criterion_descriptions',{}).get(r['criterion_id'],r['description'])
            guidance=r.get('scoring_guidance',{})
            description+='；分项给分：'+json.dumps(guidance,ensure_ascii=False)
            if r.get('critical_failure_definition'):description+='；关键错误：'+r['critical_failure_definition']
            rubric.append({'criterion_id':r['criterion_id'],'description':description,
                'max_score':r['max_score'],'critical':r['criterion_id'] in case['policy_assumptions'].get('critical_criterion_ids',[])})
        refs=[blocks[(r['document'],r['section_id'])] for r in [*q['source_refs'],*override.get('extra_source_refs',[])]]
        for b in refs:used_sources[(b['citation']['source_id'],b['citation']['source_version'])]=True
        row={k:q[k] for k in ('question_id','objective_ids','question_type','prompt','max_score','evaluator_id')}
        row.update(evaluator_version='1.0.0',source_citations=[{k:b['citation'][k] for k in ('source_id','source_version','chunk_id')} for b in refs])
        if q['question_type']=='text':row.update(answer_key=q['reference_answer'],rubric=rubric)
        else:row['numeric_rules']=q['numeric_rules']
        questions.append(row)
    objectives=[];rules=[]
    for obj in lc['current_objectives']:
        relevant=[q for q in questions if obj['objective_id'] in q['objective_ids']]
        ids=list(dict.fromkeys(q['evaluator_id'] for q in relevant))
        kinds=list(dict.fromkeys('text_excerpt' if q['question_type']=='text' else 'numeric_result' for q in relevant))
        cids=[c['criterion_id'] for q in relevant for c in q.get('rubric',[]) if c['criterion_id'] in obj.get('criterion_ids',[])]
        chunk_ids=list(dict.fromkeys(c['chunk_id'] for q in relevant for c in q['source_citations']))
        objective_edit=edits.get('objectives',{}).get(obj['objective_id'],{})
        if set(objective_edit)-{'observable_outcome'}:
            raise ValueError('Unsupported objective input revision')
        objectives.append({'objective_id':obj['objective_id'],'observable_outcome':objective_edit.get('observable_outcome',obj['observable_outcome']),
            'required':obj.get('required',True),'required_capability_ids':ids,'evidence_requirement':kinds,
            'criterion_ids':cids,'source_chunk_ids':chunk_ids})
        rules.append({'objective_id':obj['objective_id'],'required':obj.get('required',True),
            'pass_threshold':case['policy_assumptions']['objective_pass_threshold'],'evidence_kinds':kinds})
        selected=[b for b in blocks.values() if b['citation']['chunk_id'] in chunk_ids]
        context={'project_id':project_id,'node_id':lc['node_id'],'objective_id':obj['objective_id'],
                 'purpose':'grading','blocks':selected}
        # Conflict attachments are explicitly untrusted source data. Never send
        # scenario tags or a gold conclusion to make the model reject them.
        if case.get('context_anomalies'):
            attachments=[]
            for raw in case['context_anomalies']:
                if not all(isinstance(raw.get(k),str) and raw[k] for k in ('attachment_id','visibility','content')):
                    raise ValueError('Supplement must contain actual source content and identity')
                attachments.append({k:raw[k] for k in ('attachment_id','visibility','content')})
            context['untrusted_supplement']=attachments
        contexts[obj['objective_id']]=context
    evaluator_ids=list(dict.fromkeys(q['evaluator_id'] for q in questions))
    policy=EvaluationPolicy(policy_id='day13_policy',policy_version='1.0.0',
        allowed_question_types=list(dict.fromkeys(q['question_type'] for q in questions)),
        evaluators=[{'evaluator_id':x,'evaluator_version':'1.0.0'} for x in evaluator_ids],
        objective_rules=rules,total_pass_threshold=case['policy_assumptions']['total_pass_threshold'])
    snapshot={'profile_version':1,'plan_version':1,'policy_id':policy.policy_id,'policy_version':policy.policy_version,
        'source_manifest':[s for s in sources if (s['source_id'],s['source_version']) in used_sources],
        'evaluator_manifest':[r.model_dump() for r in policy.evaluators]}
    node=SkillNode(node_id=lc['node_id'],title=case['topic'],description=case['topic'],estimated_minutes=20,
        objectives=objectives,prerequisite_ids=[n['node_id'] for n in lc['prerequisite_nodes']])
    quiz=AssessmentQuiz(project_id=project_id,node_id=node.node_id,
        assessment_id='evaluation_'+sha256((project_id+case['case_id']).encode()).hexdigest()[:24],
        snapshot=snapshot,questions=questions)
    profile=LearningProfile(subject_label=case['subject_label'],topic=case['topic'],goal=case['topic'],
        bounded_goal=case['topic'],requested_capabilities=evaluator_ids)
    assert_no_labels({'quiz':quiz.model_dump(),'contexts':contexts,'node':node.model_dump(),'answers':case['student_answers']})
    return {'quiz':quiz,'node':node,'policy':policy,'profile':profile,'contexts':contexts,
        'completed_node_ids':[n['node_id'] for n in lc['prerequisite_nodes'] if n['completion_status']=='completed']}


def adapt_history(case,adapted,standard):
    result=[]
    observations=standard.get('input_revision',{}).get('history',{})
    if set(observations)-{r['assessment_id'] for r in case.get('available_history',[])}:
        raise ValueError('Unknown historical assessment in input revision')
    for raw in case.get('available_history',[]):
        eid=raw['evidence_id'];answer=raw['student_answer']
        observation=observations.get(raw['assessment_id'])
        if not observation or set(observation)!={'score','max_score','feedback'}:
            raise ValueError('Historical score and feedback must be explicit reviewed input; no invented zero scores')
        score,maximum=observation['score'],observation['max_score']
        if (any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (score,maximum))
                or maximum<=0 or not 0<=score<=maximum or not isinstance(observation['feedback'],str)):
            raise ValueError('Invalid historical score or feedback')
        evidence={'evidence_id':eid,'question_id':'history_question','kind':'text_excerpt','quote':answer,'start':0,'end':len(answer)}
        # Seeded historical evidence is fixture input, not a newly model-graded
        # student fact or a claim that the frozen course passed these answers.
        evaluation=EvaluationResult(project_id=adapted['quiz'].project_id,node_id=raw['node_id'],
            assessment_id=raw['assessment_id'],snapshot=adapted['quiz'].snapshot,grading_status='graded',
            question_results=[{'question_id':'history_question','evaluator_id':'text_rubric','evaluator_version':'1.0.0',
                'score':score,'max_score':maximum,'evidence_ids':[eid],
                'feedback':observation['feedback']+'；原题：'+raw['question']}],
            evidence=[evidence],objective_results=[])
        result.append({'project_id':evaluation.project_id,'node_id':raw['node_id'],
            'assessment_id':raw['assessment_id'],'evaluation':evaluation.model_dump(),
            'answers':{'history_question':answer}})
    return result


class Trace(BaseCallbackHandler):
    def __init__(self,path):self.path=Path(path);self.started={};self.lock=Lock();self.events=[];self.stage=None
    def _append(self,event):
        with self.lock:
            event['logical_stage']=self.stage
            self.events.append(event)
            with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(event,ensure_ascii=False,default=str)+'\n')
    def on_llm_start(self,serialized,prompts,*,run_id,**kwargs):
        self.started[str(run_id)]=perf_counter()
        self._append({'event':'request_started','run_id':str(run_id),'prompts':prompts})
    def on_chat_model_start(self,serialized,messages,*,run_id,**kwargs):
        self.started[str(run_id)]=perf_counter()
        self._append({'event':'request_started','run_id':str(run_id),
            'messages':[[{'role':m.type,'content':m.content} for m in batch] for batch in messages]})
    def on_llm_end(self,response,*,run_id,**kwargs):
        for batch in response.generations:
            for generation in batch:
                message=getattr(generation,'message',None)
                if message is None:continue
                meta=getattr(message,'response_metadata',{}) or {}
                self._append({'event':'response_received','run_id':str(run_id),
                    'elapsed_seconds':round(perf_counter()-self.started.get(str(run_id),perf_counter()),3),
                    'content':message.content,'tool_calls':getattr(message,'tool_calls',[]),
                    'invalid_tool_calls':getattr(message,'invalid_tool_calls',[]),
                    'usage':getattr(message,'usage_metadata',None),'token_usage':meta.get('token_usage'),
                    'model':meta.get('model_name'),'finish_reason':meta.get('finish_reason')})
    def on_llm_error(self,error,*,run_id,**kwargs):
        self._append({'event':'request_failed','run_id':str(run_id),'error_type':type(error).__name__,
            'elapsed_seconds':round(perf_counter()-self.started.get(str(run_id),perf_counter()),3)})


def _candidate(case,adapted):
    raw=deepcopy(case['candidate_question_result']);raw['evaluator_version']='1.0.0'
    # The old fixture's feedback literally calls itself an erroneous grade.
    # Remove that answer-revealing annotation, retaining the disputed claim.
    raw['feedback']='候选评分认为本回答满足全部量规。'
    evidence=deepcopy(case['answer_evidence'])
    from app.v3.contracts import ObjectiveResult
    return EvaluationResult(project_id=adapted['quiz'].project_id,node_id=adapted['node'].node_id,
        assessment_id=adapted['quiz'].assessment_id,snapshot=adapted['quiz'].snapshot,
        grading_status='graded',question_results=[raw],evidence=evidence,
        objective_results=[ObjectiveResult(objective_id=o.objective_id,score_ratio=1.0,
            evidence_ids=raw['evidence_ids'],criterion_ids=o.criterion_ids) for o in adapted['node'].objectives])


def metrics_for(case,standard,result):
    expected=standard
    observed=result.get('effective_action')
    score_errors=[]
    evaluation=result.get('evaluation')
    if evaluation and evaluation['grading_status']=='graded' and expected.get('score_center') is not None:
        total=sum(q['score'] for q in evaluation['question_results'])
        maximum=sum(q['max_score'] for q in evaluation['question_results'])
        score_errors.append(abs(total/maximum-expected['score_center']/expected.get('max_score',maximum)))
    exp_action=expected['effective_action']
    allowed={'pause_review':{'assessment_review'},'replace_or_pause':{'assessment_review'}}.get(exp_action,{exp_action})
    expected_passed=expected.get('passed',False)
    return {'action_matches':observed in allowed,'status_matches':result.get('grading_status')==expected['grading_status'],
        'false_advance':bool(result.get('passed')) and not expected_passed,
        'critical_false_advance':bool(result.get('passed')) and bool(expected.get('critical_error')),
        'false_reject_complete_correct':expected_passed and not result.get('passed',False),
        'unexpected_refusal':expected['task_type']=='ordinary_grading' and expected['grading_status']=='graded'
            and result.get('grading_status') in {'needs_review','invalid_item'},
        'normalized_score_error':score_errors[0] if score_errors else None}


def run_case(path,standard,output,mode,run_uuid,root=ROOT):
    from app.services.llm import get_llm
    case=read_json(path);subject=path.parents[1].name
    cid=case['case_id'];target=output/'cases'/cid;target.mkdir(parents=True,exist_ok=True)
    final=target/'result.json'
    if final.exists():return read_json(final)
    trace=Trace(target/'raw.jsonl');started=perf_counter()
    result={'case_id':cid,'subject':subject,'split':case['split'],'mode':mode,'case_sha256':digest(path),
        'standard_sha256':sha256(encode(standard).encode()).hexdigest(),
        'task_type':standard['task_type'],'human_standard_approved':standard.get('review_status')=='approved_by_user',
        'input_source':'fixed reviewed case adapted to V3; no Planner/Tutor content-quality claim'}
    paths=V3Paths(output/'runtime');request=uuid5(run_uuid,cid)
    project_id='v3_'+request.hex
    adapted=adapt_case(case,subject=subject,project_id=project_id,standards=standard,root=root)
    history=adapt_history(case,adapted,standard)
    with V3Repository(paths) as repo:
        repo.create_project(str(request),adapted['profile'])
        op=repo.create_operation(project_id,str(request),kind='day13_evaluation')
    def factory():
        if mode!='real':
            from tests.day11_support import FakeLearningModel
            return FakeLearningModel()
        model=get_llm();model.callbacks=[trace];return model
    def task(suffix,payload,kind,callback):
        assert_no_labels(payload)
        trace.stage=suffix
        return run_model_task(paths,project_id,op['operation_id'],cid+':'+suffix,payload,kind,callback,llm=factory)
    try:
        payload={'quiz':adapted['quiz'].model_dump(),'node':adapted['node'].model_dump(),
            'policy':adapted['policy'].model_dump(),'contexts':adapted['contexts'],'answers':case['student_answers']}
        if standard['task_type'] in {'candidate_score_audit','item_validity_audit'}:
            candidate=_candidate(case,adapted) if standard['task_type']=='candidate_score_audit' else None
            payload['candidate']=candidate.model_dump() if candidate else None
            review=task('review',payload,QualityReview,lambda model,budget:review_assessment(
                quiz=adapted['quiz'],node=adapted['node'],policy=adapted['policy'],contexts=adapted['contexts'],
                answers=case['student_answers'],candidate=candidate,llm=model,budget=budget))
            result['quality_review']=review.model_dump()
            result['grading_status']='invalid_item' if review.verdict=='invalid_item' else 'needs_review' if review.verdict=='needs_review' else 'graded'
            result['effective_action']='assessment_review' if review.verdict!='accepted' else 'advance'
            result['passed']=review.verdict=='accepted'
            result['review_scope']='explicit separate review service; ordinary Graph does not automatically perform this review'
        else:
            evaluation=task('grade',payload,EvaluationResult,lambda model,budget:evaluate_quiz(
                quiz=adapted['quiz'],answers=case['student_answers'],policy=adapted['policy'],node=adapted['node'],
                contexts=adapted['contexts'],llm=model,budget=budget))
            result['evaluation']=evaluation.model_dump();result['grading_status']=evaluation.grading_status
            if evaluation.grading_status!='graded':
                result.update(passed=False,effective_action='assessment_review')
            else:
                dp={'quiz':adapted['quiz'].model_dump(),'evaluation':evaluation.model_dump(),
                    'node':adapted['node'].model_dump(),'policy':adapted['policy'].model_dump(),
                    'history':history,'completed_node_ids':adapted['completed_node_ids']}
                decision=task('diagnose',dp,DiagnosisDecision,lambda model,budget:diagnose(
                    quiz=adapted['quiz'],evaluation=evaluation,node=adapted['node'],policy=adapted['policy'],
                    history=history,completed_node_ids=adapted['completed_node_ids'],llm=model,budget=budget))
                guard=decide_progress(quiz=adapted['quiz'].model_dump(),evaluation=evaluation.model_dump(),
                    node=adapted['node'].model_dump(),policy=adapted['policy'].model_dump(),
                    profile=adapted['profile'].model_dump(),completed_node_ids=adapted['completed_node_ids'],
                    diagnosis=decision.model_dump(),answers=case['student_answers'])
                result.update(diagnosis=decision.model_dump(),guard=guard.model_dump(),passed=guard.passed,
                    effective_action=guard.effective_action)
        result['metrics']=metrics_for(case,standard,result)
    except Exception as exc:
        result.update(error_type=type(exc).__name__,passed=False,effective_action='technical_failure')
        result.setdefault('grading_status',None)
        result['metrics']=metrics_for(case,standard,result)
    result['elapsed_seconds']=round(perf_counter()-started,3)
    with V3Repository(paths) as repo:
        result['tasks']=[dict(r) for r in repo.conn.execute('SELECT task_key,requests,network_retries,output_repairs,status,error_type FROM model_tasks WHERE project_id=?',(project_id,))]
        result['operation']=repo.get_operation(project_id,op['operation_id'])
    result['requests']=sum(t['requests'] for t in result['tasks'])
    responses=[e for e in trace.events if e['event']=='response_received']
    result['raw_responses']=len(responses)
    result['usage']=[{'model':e['model'],'usage':e['usage'],'token_usage':e['token_usage']} for e in responses]
    from app.v3.evaluators import TextBatchScore
    legality={}
    for stage in ('grade','diagnose','review'):
        items=[e for e in responses if e.get('logical_stage')==stage]
        valid=[]
        for e in items:
            try:
                if e['invalid_tool_calls']:valid.append(False);continue
                if e['tool_calls']:valid.append(True);continue
                raw=json.loads(e['content'])
                kind=TextBatchScore if stage=='grade' else DiagnosisDecision if stage=='diagnose' else QualityReview
                kind.model_validate(raw);valid.append(True)
            except (ValueError,TypeError):
                # A non-JSON no-tool response during the selection phase is an
                # AIMessage, not a failed final DiagnosisDecision.
                valid.append(stage=='diagnose' and bool(e['content']) and not str(e['content']).lstrip().startswith('{'))
        if valid:legality[stage]={'received_outputs':len(valid),'first_structurally_valid':valid[0],
                                'last_structurally_valid':valid[-1]}
    result['structure_legality']=legality
    result['cost']={'actual_currency_amount':None,'reason':'Provider billing/pricing not configured; usage is recorded when returned'}
    result['quality_metrics_official']=mode=='real' and result['human_standard_approved']
    write_json(final,result)
    print(json.dumps({'case':cid,'action':result['effective_action'],'requests':result['requests'],
        'error':result.get('error_type')},ensure_ascii=False),flush=True)
    return result


def report(results,output,metadata):
    protocol=read_json(PROTOCOL);subjects={}
    for subject in sorted({r['subject'] for r in results}):
        rows=[r for r in results if r['subject']==subject]
        errors=[r['metrics']['normalized_score_error'] for r in rows if r['metrics']['normalized_score_error'] is not None]
        gates={
            'no_false_advance':not any(r['metrics']['false_advance'] for r in rows),
            'no_critical_false_advance':not any(r['metrics']['critical_false_advance'] for r in rows),
            'no_correct_reject':not any(r['metrics']['false_reject_complete_correct'] for r in rows),
            'no_unexpected_refusal':not any(r['metrics']['unexpected_refusal'] for r in rows),
            'all_actions_match':all(r['metrics']['action_matches'] for r in rows),
            'all_statuses_match':all(r['metrics']['status_matches'] for r in rows),
            'score_mae':bool(errors) and sum(errors)/len(errors)<=protocol['gates']['normalized_mae_max']+1e-12,
            'score_max':bool(errors) and max(errors)<=protocol['gates']['normalized_individual_error_max']+1e-12,
            'no_technical_failure':not any(r.get('error_type') for r in rows)}
        subjects[subject]={'cases':len(rows),'ordinary_grading_cases':sum(r['task_type']=='ordinary_grading' for r in rows),
            'normalized_mae':sum(errors)/len(errors) if errors else None,'scored_samples':len(errors),
            'action_matches':sum(r['metrics']['action_matches'] for r in rows),
            'false_advances':sum(r['metrics']['false_advance'] for r in rows),
            'false_rejects':sum(r['metrics']['false_reject_complete_correct'] for r in rows),
            'unexpected_refusals':sum(r['metrics']['unexpected_refusal'] for r in rows),
            'technical_failures':sum(bool(r.get('error_type')) for r in rows),
            'requests':sum(r['requests'] for r in rows),'gates':gates,
            'automated_gates_passed':all(gates.values()),'semantic_citation_review':'pending_independent_review'}
        stages=[v for r in rows for v in r.get('structure_legality',{}).values()]
        usage=[u['usage'] for r in rows for u in r.get('usage',[]) if u.get('usage')]
        latencies=sorted(r['elapsed_seconds'] for r in rows)
        subjects[subject].update(
            structure_tasks=len(stages),
            first_structurally_valid=sum(v['first_structurally_valid'] for v in stages),
            final_structurally_valid=sum(v['last_structurally_valid'] for v in stages),
            input_tokens=sum(u.get('input_tokens',0) for u in usage),
            output_tokens=sum(u.get('output_tokens',0) for u in usage),
            usage_responses=len(usage),
            latency_seconds={'mean':sum(latencies)/len(latencies),'max':max(latencies)},
            cost={'amount':None,'reason':'No verified provider billing rate configured'})
    value={'metadata':metadata,'by_subject':subjects,'results':results,
           'release_approved':False,'note':'工程流程、内容质量和人工/独立语义引用复核分别报告。'}
    write_json(output/'report.json',value)
    lines=['# Day 13 '+metadata['split']+' '+metadata['mode']+' 评价结果','',
        '使用固定、经审阅的题目；真实评价器、诊断和守卫。05/06是独立审查服务测试，不宣称普通Graph自动执行审查。',
        'Fake只测管线；结构或ID合法不代表语义正确。费用无可靠定价时保持不可得。','',
        '|学科|例数|行动一致|归一化MAE|错误推进|完整正确误拒|意外拒评|技术失败|请求|自动门槛|',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for s,m in subjects.items():
        lines.append(f"|{s}|{m['cases']}|{m['action_matches']}/{m['cases']}|{m['normalized_mae']}|{m['false_advances']}|{m['false_rejects']}|{m['unexpected_refusals']}|{m['technical_failures']}|{m['requests']}|{'通过' if m['automated_gates_passed'] else '未通过'}|")
    lines+=['','逐例原输出、工具选择、usage和耗时见 cases/*/raw.jsonl 与 result.json；发布结论仍需独立语义审查及其余验收。']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return value


def select_cases(split,subjects,case_root=None):
    base=Path(case_root).resolve() if case_root else ROOT/'evals/v3'
    if not base.is_relative_to(ROOT):raise ValueError('Case suite must be inside the repository')
    if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,60}',s) for s in subjects):raise ValueError('Unsafe subject pack identity')
    selected=[p for subject in subjects for p in sorted((base/subject/'cases').glob('*_'+split+'_*.json'))]
    if any(not p.resolve().is_relative_to(base) for p in selected):raise ValueError('Case suite escaped its directory')
    return selected


def preflight_cases(selected,standards,split):
    expected_count=24 if split=='debug' else 12 if split=='holdout' else len(standards['cases'])
    if len(selected)!=expected_count or {p.stem for p in selected}!=set(standards['cases']):
        raise ValueError('Frozen split cardinality or standard identities mismatch')
    for path in selected:
        case=read_json(path);standard=standards['cases'][path.stem]
        if case['case_id']!=path.stem or case['split']!=split:
            raise ValueError('Case identity or split mismatch')
        if standard.get('review_status')!='approved_by_user':raise ValueError('Each case needs human reference approval')
        prepared=adapt_case(case,subject=path.parents[1].name,project_id='preflight',standards=standard)
        adapt_history(case,prepared,standard)
        from app.v3.assessment import validate_quiz
        validate_quiz(prepared['quiz'],node=prepared['node'],policy=prepared['policy'],contexts=prepared['contexts'])


def revalidation_provenance(previous_report, selected, standard_file):
    """A repeat of an independent suite is never a new first-unseen run."""
    prior = read_json(previous_report)
    metadata = prior['metadata']
    if (metadata['split'] != 'holdout' or metadata['mode'] != 'real'
            or metadata.get('validation_role') != 'unseen_final_holdout'
            or metadata.get('input_cases') != {p.relative_to(ROOT).as_posix(): digest(p) for p in selected}
            or metadata.get('standards_sha256') != digest(standard_file)
            or any(not row['automated_gates_passed'] or row['semantic_citation_review'] not in
                   {'approved_independent_review', 'approved_by_user'} for row in prior['by_subject'].values())):
        raise ValueError('Revalidation requires the same approved independent cases and standards, with reviewed original results')
    return {'previous_report_sha256': digest(previous_report),
            'previous_report': str(Path(previous_report)), 'first_unseen_execution': False,
            'scope': 'Previously independent suite repeated after repair; not a new unseen test'}


def run(split,output,*,mode='real',workers=2,freeze=None,subjects=None,standard_path=None,prior_holdout=None,case_root=None,revalidate=None):
    protocol=read_json(PROTOCOL)
    standard_file=Path(standard_path).resolve() if standard_path else ROOT/'evals/v3/day13'/('development_standards.json' if split=='debug' else 'holdout_standards.json')
    standards=read_json(standard_file)
    if standards.get('review_status')!='approved_by_user':raise ValueError('Human reference approval is required before real evaluation')
    if split in {'holdout','novel'}:
        if freeze is None:raise ValueError('A frozen candidate is required before holdout')
        frozen=read_json(freeze)
        if frozen['fingerprint']!=current_fingerprint():raise ValueError('Candidate changed after freeze')
        if frozen['model_identity']!=model_identity():raise ValueError('Model configuration changed after freeze')
    if split=='novel':
        if prior_holdout is None:raise ValueError('Novel-topic evaluation requires a completed holdout report')
        previous=read_json(prior_holdout)
        if (previous['metadata']['split']!='holdout' or previous['metadata']['mode']!='real'
                or previous['metadata'].get('validation_role') not in {'unseen_final_holdout','independent_final_revalidation'}
                or previous['metadata'].get('fingerprint')!=current_fingerprint()
                or previous['metadata'].get('model_identity')!=model_identity()
                or any(not s['automated_gates_passed'] or s['semantic_citation_review'] not in
                       {'approved_independent_review','approved_by_user'} for s in previous['by_subject'].values())):
            raise ValueError('A matching, reviewed independent final holdout must pass before novel topic')
    selected=select_cases(split,subjects or SUBJECTS,case_root)
    preflight_cases(selected,standards,split)
    validation_role=standards.get('validation_role','development' if split=='debug' else 'novel' if split=='novel' else 'exposed_validation')
    provenance = None
    if revalidate is not None:
        if split != 'holdout' or mode != 'real' or validation_role != 'unseen_final_holdout':
            raise ValueError('Only an independent final holdout can use the revalidation entry')
        provenance = revalidation_provenance(revalidate, selected, standard_file)
        validation_role = 'independent_final_revalidation'
    if split=='holdout' and validation_role=='unseen_final_holdout':
        if case_root is None or Path(case_root).resolve()==ROOT/'evals/v3':
            raise ValueError('Exposed original holdouts cannot be relabeled as unseen final validation')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    paths=initialize_storage(V3Paths(output/'runtime'));initialize_learning_storage(paths)
    run_uuid=uuid5(NAMESPACE_URL,str(output))
    input_paths=[standard_file,*selected]
    for subject in subjects or SUBJECTS:
        input_paths.extend(p for p in (ROOT/'materials/v3'/subject).rglob('*') if p.is_file())
    metadata={'date':datetime.now(timezone.utc).isoformat(),'mode':mode,'split':split,
        'baseline_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'protocol_sha256':digest(PROTOCOL),'standards_sha256':digest(standard_file),
        'fingerprint':current_fingerprint(),'freeze_sha256':digest(freeze) if freeze else None,
        'reference_status':standards['review_status'],'validation_role':validation_role,
        'holdout_used_for_development':validation_role=='exposed_validation','model_identity':model_identity(),
        'runtime_fingerprint_scope':'core runtime, policies, original three source/case packs, development protocol/standards; novel data is hashed separately',
        'input_cases':{p.relative_to(ROOT).as_posix():digest(p) for p in selected},
        'input_bundle_fingerprint':{p.relative_to(ROOT).as_posix():digest(p) for p in input_paths}}
    if provenance is not None:metadata['revalidation_provenance']=provenance
    from app.v3.diagnosis import DIAGNOSIS_PROMPT_VERSION
    from app.v3.evaluators import TEXT_PROMPT_VERSION
    from app.v3.quality_review import REVIEW_PROMPT_VERSION
    metadata['prompt_versions']={'grading':TEXT_PROMPT_VERSION,'diagnosis':DIAGNOSIS_PROMPT_VERSION,'review':REVIEW_PROMPT_VERSION}
    write_json(output/'run_manifest.json',metadata)
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(run_case,p,standards['cases'][p.stem],output,mode,run_uuid) for p in selected]
        for f in as_completed(futures):results.append(f.result())
    return report(sorted(results,key=lambda r:r['case_id']),output,metadata)


def freeze_candidate(report_path,output):
    result=read_json(report_path)
    if result['metadata']['split']!='debug' or result['metadata']['mode']!='real':raise ValueError('Freeze requires real development evaluation')
    if any(not s['automated_gates_passed'] for s in result['by_subject'].values()):raise ValueError('Development gates failed; cannot freeze for holdout')
    if any(s['semantic_citation_review'] not in {'approved_independent_review','approved_by_user'} for s in result['by_subject'].values()):
        raise ValueError('Independent semantic review is required before freezing')
    if set(result['by_subject'])!=set(SUBJECTS) or any(s['cases']!=8 for s in result['by_subject'].values()) or len(result.get('results',[]))!=24:
        raise ValueError('Freeze requires all 24 development cases across three subjects')
    if result['metadata'].get('fingerprint')!=current_fingerprint() or result['metadata'].get('model_identity')!=model_identity():
        raise ValueError('Candidate changed since the reviewed development run')
    value={'frozen_at':datetime.now(timezone.utc).isoformat(),'development_report_sha256':digest(report_path),
        'fingerprint':current_fingerprint(),'model_identity':model_identity(),'stage':'candidate_frozen_before_holdout'}
    if Path(output).exists():raise FileExistsError('Candidate freeze is immutable')
    write_json(output,value);return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('run');p.add_argument('--split',choices=['debug','holdout','novel'],required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--mode',choices=['real','fake'],default='real')
    p.add_argument('--workers',type=int,choices=[1,2,3],default=2);p.add_argument('--freeze',type=Path)
    p.add_argument('--subjects',nargs='+');p.add_argument('--standards',type=Path);p.add_argument('--prior-holdout',type=Path)
    p.add_argument('--case-root',type=Path,help='Separate, versioned case suite; original exposed cases cannot count as unseen')
    p.add_argument('--revalidate',type=Path,help='Original reviewed independent report; repeat identical approved cases without claiming a first-unseen execution')
    p=sub.add_parser('freeze');p.add_argument('--development-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.command=='freeze':print(json.dumps(freeze_candidate(args.development_report,args.output),ensure_ascii=False))
    else:
        result=run(args.split,args.output,mode=args.mode,workers=args.workers,freeze=args.freeze,
                   subjects=args.subjects,standard_path=args.standards,prior_holdout=args.prior_holdout,case_root=args.case_root,revalidate=args.revalidate)
        print(json.dumps(result['by_subject'],ensure_ascii=False))
