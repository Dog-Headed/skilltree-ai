"""Paired real-Intern scope/notes pilot; synthetic profiles and no database writes."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true',help='Permit actual configured Intern-S2 API calls.')
parser.add_argument('--output-dir',type=Path)
parser.add_argument('--workers',type=int,choices=(1,2),default=1)
parser.add_argument('--case',action='append',dest='selected')
parser.add_argument('--stage',choices=('scope','notes'),action='append')
parser.add_argument('--mode',choices=('legacy','content-v1','notes-outline-v1'),action='append')
parser.add_argument('--repeat',type=int,choices=(1,2,3),default=1)
args=parser.parse_args()
if not args.live:parser.error('Actual API calls require --live; no model was called.')

from dotenv import load_dotenv
load_dotenv(ROOT/'.env',override=False)
from langchain_core.callbacks import BaseCallbackHandler
from app.services.llm import ModelCallBudget, compact_parse_error
from app.v3.onboarding import infer_scope, generate_notes, LearningIntent, _inferred_profile
from app.v3.onboarding import LearningPreparation, PROMPT_VERSION
from app.v3.notes_outline import PROMPT_VERSION as OUTLINE_PROMPT_VERSION
from deploy.provider import StructuredReply, create_runtime_model

cases=[
    ('sql','零基础学习SQL：SELECT列与别名、WHERE及NULL、排序分页、聚合分组、JOIN连接，最后结合多表查询做综合文字推理。只做文字学习，不执行数据库。',
     ['关系表与查询顺序','SELECT列与别名','WHERE筛选与NULL','ORDER BY排序和LIMIT分页','聚合函数与GROUP BY及HAVING','JOIN连接条件与结果','多表查询综合推理']),
    ('python','从零学习Python变量与类型、条件、循环、列表字典、函数、文件和异常，最后综合阅读一段小程序并解释调试思路；只做文字推理，不声称运行代码。',
     ['变量与基本类型','条件分支','循环与停止条件','列表与字典','函数与参数返回值','文件读写与异常','综合程序阅读和调试']),
    ('arithmetic','零基础学习有理数、四则运算、运算顺序、分配律、等式变形和一元一次方程，最后做文字应用题综合推理。',
     ['有理数与数轴','四则运算规则','括号与运算顺序','分配律和去括号','等式性质与同解变形','一元一次方程与应用题'])]
if args.selected:
    unknown=set(args.selected)-{c[0] for c in cases}
    if unknown:parser.error('Unknown case: '+','.join(sorted(unknown)))
    cases=[c for c in cases if c[0] in args.selected]

if args.repeat>1:cases=[(c[0]+'_'+str(i),*c[1:]) for i in range(1,args.repeat+1) for c in cases]

root=args.output_dir or ROOT/'work'/('preparation-content-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
root.mkdir(parents=True,exist_ok=False)
local=threading.local();original=StructuredReply.invoke


def measured(self,messages,*a,**kw):
    runnable=self.runnable
    class Meter:
        def invoke(inner,messages,*aa,**kk):
            started=time.monotonic();record={'input_characters':sum(len(str(m.content)) for m in messages)}
            class FirstToken(BaseCallbackHandler):
                def on_llm_new_token(inner,token,**kwargs):
                    if token and 'first_token_seconds' not in record:
                        record['first_token_seconds']=round(time.monotonic()-started,3)
            config=dict(kk.pop('config',{}) or {});config['callbacks']=[*(config.get('callbacks') or []),FirstToken()]
            try:
                result=runnable.invoke(messages,*aa,config=config,**kk)
                raw=result.get('raw');usage=getattr(raw,'usage_metadata',None) or {}
                record.update(input_tokens=usage.get('input_tokens'),output_tokens=usage.get('output_tokens'),
                    output_characters=len(str(getattr(raw,'content',''))),
                    synthetic_output_tail=str(getattr(raw,'content',''))[-100:],
                    finish_reason=getattr(raw,'response_metadata',{}).get('finish_reason'))
                parse_error=result.get('parsing_error')
                if parse_error:
                    record['synthetic_parse_error']=str(parse_error).rsplit('Got:',1)[-1][-1400:]
                try:
                    duplicates=[]
                    def pairs(items):
                        data={}
                        for k,v in items:
                            if k in data:duplicates.append(k)
                            data[k]=v
                        return data
                    decoded=json.loads(str(getattr(raw,'content','')),object_pairs_hook=pairs)
                    record['synthetic_top_level_fields']=list(decoded) if isinstance(decoded,dict) else []
                    record['synthetic_duplicate_fields']=duplicates
                except (ValueError,TypeError):pass
                return result
            except Exception as exc:record['error_type']=type(exc).__name__;raise
            finally:record['elapsed_seconds']=round(time.monotonic()-started,3);local.attempts.append(record)
    self.runnable=Meter()
    try:return original(self,messages,*a,**kw)
    except Exception as exc:
        if local.attempts:local.attempts[-1]['diagnostic']=compact_parse_error(exc)
        raise
    finally:self.runnable=runnable


StructuredReply.invoke=measured


def run_case(index,case):
    name,goal,branches=case;rows=[]
    intent=LearningIntent(goal=goal,prior_knowledge='零基础',time_budget_minutes=1440,session_minutes=30)
    scope=LearningPreparation(subject_label=name,topic=goal[:80],bounded_goal=goal,scope_in=branches,
        scope_out=['未支持的实际操作评价'],evaluation_capabilities=['text_rubric'],basis='general_knowledge',
        explanation='独立配对实验固定范围；不操作真实课程。')
    profile=_inferred_profile(scope,intent,intent.as_profile())
    payloads={'scope':{'intent':intent.model_dump(),'user_material_catalog':[],'adjustment':'',
                'prompt_version':PROMPT_VERSION,'available_evaluators':['choice_exact','numeric_scalar','text_rubric']},
              'notes':{'profile':profile.model_dump(),'prompt_version':PROMPT_VERSION}}
    for stage,function in [('scope',infer_scope),('notes',generate_notes)]:
        if args.stage and stage not in args.stage:continue
        modes=args.mode or ['legacy','content-v1']
        for mode in (modes if index%2==0 else list(reversed(modes))):
            provider=create_runtime_model()
            if provider.model_name!='intern-s2' or provider.extra_body!={'thinking_mode':False}:
                raise ValueError('Pilot requires Intern-S2 with thinking disabled')
            budget=ModelCallBudget();local.attempts=[];started=time.monotonic()
            row={'case':name,'stage':stage,'mode':mode,'model':provider.model_name,'temperature':provider.temperature,'thinking_mode':False,
                 'prompt_version':OUTLINE_PROMPT_VERSION if stage=='notes' and mode=='notes-outline-v1' else PROMPT_VERSION}
            try:
                result=function(provider,budget,payloads[stage],generation_mode=mode)
                row['passed']=True
                if stage=='scope':row.update(branches=len(result.scope_in),basis=result.basis)
                else:row.update(content_characters=len(result.content),expected_branches=len(branches))
                (root/f'{name}-{stage}-{mode}.json').write_text(json.dumps(result.model_dump(),ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:row.update(passed=False,error_type=type(exc).__name__,error_detail=str(exc)[:1600])
            row.update(first_pass=row['passed'] and budget.request_count==1,requests=budget.request_count,
                output_repairs=budget.output_repair_count,network_retries=budget.network_retry_count,
                elapsed_seconds=round(time.monotonic()-started,3),attempts=local.attempts)
            for key in ('input_tokens','output_tokens'):
                values=[a.get(key) for a in local.attempts]
                row[key]=sum(values) if values and all(v is not None for v in values) else None
            (root/f'{name}-{stage}-{mode}-metrics.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:v for k,v in row.items() if k!='attempts'},ensure_ascii=True),flush=True);rows.append(row)
    return rows


rows=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
    for result in pool.map(lambda ic:run_case(*ic),enumerate(cases)):rows.extend(result)
summary={}
for stage in ('scope','notes'):
    summary[stage]={}
    for mode in (args.mode or ['legacy','content-v1']):
        group=[r for r in rows if r['stage']==stage and r['mode']==mode]
        if not group:continue
        summary[stage][mode]={'cases':len(group),'first_pass':sum(r['first_pass'] for r in group),
            'final_pass':sum(r['passed'] for r in group),'requests':sum(r['requests'] for r in group),
            'output_repairs':sum(r['output_repairs'] for r in group),
            'median_seconds':statistics.median(r['elapsed_seconds'] for r in group),
            'observed_max_seconds':max(r['elapsed_seconds'] for r in group),
            'content_characters':sum(r.get('content_characters',0) for r in group)}
(root/'summary.json').write_text(json.dumps({'summary':summary,'runs':rows},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'summary':summary}),flush=True)
