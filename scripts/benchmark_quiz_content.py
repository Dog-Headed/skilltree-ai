"""Small paired real-Intern pilot. Synthetic sources; no production database writes."""
import argparse,concurrent.futures,hashlib,json,os,statistics,sys,threading,time
from pathlib import Path
from datetime import datetime,timezone
REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO))
parser=argparse.ArgumentParser(description='Compare legacy/content-v1 using real Intern-S2 and synthetic sources.')
parser.add_argument('--live',action='store_true',help='Explicitly permit actual model API calls.')
parser.add_argument('--output-dir',type=Path)
parser.add_argument('--workers',type=int,choices=(1,2),default=2)
parser.add_argument('--case',action='append',dest='selected_cases')
args=parser.parse_args()
if not args.live:parser.error('Actual API calls require --live; no model was called.')
from dotenv import load_dotenv
load_dotenv(REPO/'.env',override=False)
from app.v3.contracts import SkillNode,EvaluationPolicy,FrozenSnapshot
from app.v3.assessment import generate_quiz
from app.services.llm import ModelCallBudget,compact_parse_error
from app.services.observability import configure_logging
from deploy.provider import StructuredReply,create_runtime_model

root=args.output_dir or REPO/'work'/('quiz-content-benchmark-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));root.mkdir(mode=0o700,parents=True,exist_ok=False)
configure_logging(root/'events.jsonl');local=threading.local();original=StructuredReply.invoke
def measured(self,messages,*args,**kwargs):
    runnable=self.runnable
    class Meter:
        def invoke(inner,messages,*a,**kw):
            started=time.monotonic()
            record={'input_characters':sum(len(str(m.content)) for m in messages)}
            try:
                result=runnable.invoke(messages,*a,**kw);raw=result.get('raw');usage=getattr(raw,'usage_metadata',None) or {}
                record.update(input_tokens=usage.get('input_tokens'),output_tokens=usage.get('output_tokens'),
                    output_characters=len(str(getattr(raw,'content',''))),finish_reason=getattr(raw,'response_metadata',{}).get('finish_reason'))
                return result
            except Exception as e:record['error_type']=type(e).__name__;raise
            finally:record['elapsed_seconds']=round(time.monotonic()-started,3);local.attempts.append(record)
    self.runnable=Meter()
    try:return original(self,messages,*args,**kwargs)
    except Exception as exc:
        local.attempts[-1]['schema_diagnostics']=compact_parse_error(exc);raise
    finally:self.runnable=runnable
StructuredReply.invoke=measured

cases=[
 ('sql_single','SQL表由行和列组成。行是一条记录，列是一类字段；WHERE 用于按条件筛选行。', [('text','解释表的行与列，以及WHERE筛选行的作用',['c1'])]),
 ('money_mixed','虚构交易算术：金额=单价乘数量。单价10、数量100，金额1000；单价8、数量200，金额1600。不能把单价和数量相加。金额单位在题干说明，答案只写数值。',
  [('choice','判断金额计算方法',[]),('numeric','计算给定单价与数量的金额',[]),('text','解释为何使用乘法而非相加',['c1'])]),
 ('python_rubric','变量可以保存值。赋值语句x=3把3保存到变量x，随后x=5使x的新值为5。赋值不是数学恒等式。',
  [('choice','辨别变量与赋值',[]),('text','解释变量更新并给出资料中的例子',['concept','example'])]),
 ('length_numeric','长度换算：1米等于100厘米；2米等于200厘米；0.5米等于50厘米。只考长度换算，可使用m和cm，题干必须说明答题单位。', [('numeric','完成一次长度换算',[])]),
 ('multi_choice','关系数据库基本术语：表中行表示记录，列表示字段；WHERE按条件筛选行，ORDER BY排序。SELECT不等同于删除。', [('multiple','从多个选项辨别正确的数据库术语',[])]),
 ('dag_texts','DAG是有向无环图。边A到B表示B依赖A；有向环不允许。独立分支可以在前置完成后分别学习；汇合节点需满足全部前置。',
  [('text','解释有向边的依赖方向',['direction']),('text','解释无环的含义',['acyclic']),('text','解释分支与汇合的前置要求',['branches'])]),
 ('unmapped_text','学习记录保存当前节点、已完成节点和历史答卷。刷新是读取状态，不应重复交卷；恢复后应核对原答卷身份。', [('text','解释刷新状态为何不应重复交卷',[])]),
 ('dual_evidence','Python的if条件为真时执行对应分支，为假时不执行。缩进决定分支内的语句。循环用于重复操作，条件分支用于选择。',
  [('both','解释条件真假对分支执行的影响',['c1']),('both','辨别选择与重复并解释缩进',['c2'])]),
]

def fixture(case):
    name,source,goals=case;pid='pilot_'+name;chunk='chunk_'+name;sid='source_'+name;digest=hashlib.sha256(source.encode()).hexdigest()
    mapping={'choice':(['choice_exact'],['choice']), 'multiple':(['choice_exact'],['choice']),
        'numeric':(['numeric_scalar'],['numeric_result']),'text':(['text_rubric'],['text_excerpt']),
        'both':(['choice_exact','text_rubric'],['choice','text_excerpt'])}
    objectives=[];allowed=[];evaluators=[]
    for i,(kind,outcome,criteria) in enumerate(goals,1):
        caps,evidence=mapping[kind]
        objectives.append({'objective_id':'o'+str(i),'observable_outcome':outcome,'required_capability_ids':caps,
            'evidence_requirement':evidence,'source_chunk_ids':[chunk],'criterion_ids':criteria})
        for cap in caps:
            if cap not in evaluators:evaluators.append(cap)
        for qtype in {'choice':['single_choice'],'multiple':['multiple_choice'],'numeric':['numeric_scalar'],
                      'text':['text'],'both':['single_choice','text']}[kind]:
            if qtype not in allowed:allowed.append(qtype)
    node=SkillNode(node_id='n1',title=name,description='基于给定资料完成有限学习目标',estimated_minutes=20,objectives=objectives)
    policy=EvaluationPolicy(policy_id='policy_'+name,policy_version='1.0.0',allowed_question_types=allowed,
        evaluators=[{'evaluator_id':k,'evaluator_version':'1.0.0'} for k in evaluators],
        objective_rules=[{'objective_id':o.objective_id,'evidence_kinds':o.evidence_requirement} for o in node.objectives])
    snapshot=FrozenSnapshot(profile_version=1,plan_version=1,policy_id=policy.policy_id,policy_version=policy.policy_version,
        source_manifest=[{'source_id':sid,'source_version':1,'content_hash':digest}],evaluator_manifest=policy.evaluators)
    contexts={o.objective_id:{'project_id':pid,'node_id':'n1','objective_id':o.objective_id,'purpose':'assessment','blocks':[{
        'citation':{'source_id':sid,'source_version':1,'chunk_id':chunk,'visibility':'teaching'},'content':source,
        'content_hash':digest,'source_content_hash':digest}]} for o in node.objectives}
    return dict(project_id=pid,node=node,assessment_id='assessment_'+name,snapshot=snapshot,policy=policy,contexts=contexts)

cases.append(('mixed_text_numeric','模拟成交金额=单价×数量。单价12元、数量5个时为60元。乘法是把单价按数量重复累加。不含费用，答案只填写数值。', [('text','识别单价、数量与金额单位，并写出成交金额计算列式',['formula']),('text','解释为何把单价按数量累加可用乘法计算',['principle']),('numeric','给定单价12元、数量5个时计算成交金额并写出结果',[])]))

def run_case(index,case):
    name=case[0];records=[]
    for mode in (['legacy','content-v1'] if index%2==0 else ['content-v1','legacy']):
        budget=ModelCallBudget();provider=create_runtime_model();assert provider.model_name=='intern-s2'
        assert provider.extra_body=={'thinking_mode':False};local.attempts=[];started=time.monotonic()
        record={'case':name,'mode':mode,'model':provider.model_name,'thinking_mode':False,'temperature':provider.temperature}
        try:
            quiz=generate_quiz(**fixture(case),llm=provider,budget=budget,generation_mode=mode)
            record.update(passed=True,questions=len(quiz.questions),question_types=[q.question_type for q in quiz.questions])
            (root/(name+'-'+mode+'.json')).write_text(json.dumps(quiz.model_dump(),ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception as e:record.update(passed=False,error_type=type(e).__name__,error_detail=str(e)[:1800])
        record.update(first_pass=record['passed'] and budget.output_repair_count==0 and budget.network_retry_count==0,
            requests=budget.request_count,output_repairs=budget.output_repair_count,network_retries=budget.network_retry_count,
            elapsed_seconds=round(time.monotonic()-started,3),attempts=local.attempts)
        for key in ('input_tokens','output_tokens'):
            values=[a.get(key) for a in local.attempts];record[key]=sum(values) if values and all(v is not None for v in values) else None
        (root/(name+'-'+mode+'-metrics.json')).write_text(json.dumps(record,indent=2));records.append(record)
        print(json.dumps({k:v for k,v in record.items() if k!='attempts'}),flush=True)
    return records

if args.selected_cases:
    unknown=set(args.selected_cases)-{c[0] for c in cases}
    if unknown:parser.error('Unknown cases: '+', '.join(sorted(unknown)))
    cases=[c for c in cases if c[0] in args.selected_cases]

records=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
    futures=[pool.submit(run_case,i,c) for i,c in enumerate(cases)]
    for future in concurrent.futures.as_completed(futures):records.extend(future.result())
summary={}
for mode in ('legacy','content-v1'):
    rows=[r for r in records if r['mode']==mode];latency=sorted(r['elapsed_seconds'] for r in rows)
    summary[mode]={'cases':len(rows),'first_pass':sum(r['first_pass'] for r in rows),'final_pass':sum(r['passed'] for r in rows),
        'requests':sum(r['requests'] for r in rows),'output_repairs':sum(r['output_repairs'] for r in rows),
        'median_seconds':statistics.median(latency),'observed_max_seconds':max(latency),
        'questions':sum(r.get('questions',0) for r in rows),'input_tokens':sum(r['input_tokens'] for r in rows) if all(r['input_tokens'] is not None for r in rows) else None,
        'output_tokens':sum(r['output_tokens'] for r in rows) if all(r['output_tokens'] is not None for r in rows) else None}
(root/'summary.json').write_text(json.dumps({'summary':summary,'runs':records},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'summary':summary}),flush=True)
