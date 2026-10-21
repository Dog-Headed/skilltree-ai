"""Real-adapter technical smoke on isolated checked fixture plans, NOT a quality eval.

The model's own private reference answers are used as synthetic submissions.
No developer/holdout evaluation cases are loaded or labelled as human gold.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from app.services.llm import get_llm
from app.services.observability import configure_logging
from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from tests.day11_support import build_frozen_project, learning_event, answers_for_quiz


class UsageCollector(BaseCallbackHandler):
    def __init__(self):self.responses=[]
    def on_llm_end(self,response,**kwargs):
        for row in response.generations:
            for generation in row:
                message=getattr(generation,'message',None)
                metadata=getattr(message,'response_metadata',{}) or {}
                self.responses.append({'usage':getattr(message,'usage_metadata',None),
                    'token_usage':metadata.get('token_usage'),'model':metadata.get('model_name')})


def run_subject(root,subject,case):
    started=perf_counter();record={'subject':subject,'kind':'real_adapter_technical_smoke',
        'plan_source':'checked fixed fixture through real preparation contracts; Fake planner',
        'submission_source':'synthetic: model-generated private reference answers',
        'quality_evaluation':False,'human_expected_status':'pending_user_review','states':[]}
    try:
        usage=UsageCollector();model=get_llm();model.callbacks=[usage]
        record['model']=model.model_name
        service=LearningService(case['paths'],llm=model)
        view=service.start(case['project_id'],str(uuid4()));record['states'].append(view)
        if view['page_state']=='learning':
            view=service.resume(view['project_id'],learning_event(view,'start_quiz'));record['states'].append(view)
        if view['page_state']=='quiz':
            with LearningRepository(case['paths']) as repo:
                quiz=json.loads(repo.get_assessment(view['project_id'],view['assessment_id'])['quiz_json'])
            view=service.resume(view['project_id'],learning_event(view,'submit_answer',answers=answers_for_quiz(quiz)))
            record['states'].append(view)
        record['final_state']=view['page_state'];record['completed_node_ids']=view['completed_node_ids']
        record['usage']=usage.responses
        with LearningRepository(case['paths']) as repo:
            record['logical_tasks']=[dict(r) for r in repo.conn.execute(
                'SELECT task_key,requests,network_retries,output_repairs,status,error_type FROM model_tasks WHERE project_id=?',(case['project_id'],))]
    except Exception as exc: record['error_type']=type(exc).__name__
    record['elapsed_seconds']=round(perf_counter()-started,3)
    (root/(subject+'.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record


def run(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    configure_logging(output/'events.jsonl')
    # Fixture preparation uses a scoped planner replacement; keep it sequential.
    # Only independent real adapter calls are allowed to run concurrently.
    subjects=['python','mathematics','english']
    cases={subject:build_frozen_project(output/subject,subject,node_count=1) for subject in subjects}
    with ThreadPoolExecutor(max_workers=3) as pool: records=list(pool.map(lambda s:run_subject(output,s,cases[s]),subjects))
    (output/'report.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Day 11 真实适配器技术冒烟','',
           '隔离库、固定且已做契约检查的 Fake 规划；真实模型执行教学、出题、文字评分与诊断。',
           '**作答来自同一模型生成的私有参考答案，仅证明接口和状态可运行，不是独立评分质量评价。**',
           '未加载36例评价案例或保留集，人工预期仍待用户复核。','',
           '|主题|最终状态|完成节点数|HTTP预占数|耗时秒|','|---|---|---:|---:|---:|']
    for r in records:
        lines.append(f"|{r['subject']}|{r.get('final_state',r.get('error_type'))}|{len(r.get('completed_node_ids',[]))}|{sum(t['requests'] for t in r.get('logical_tasks',[]))}|{r['elapsed_seconds']}|")
    lines.extend(['','逐次 usage（提供者返回时）、模型名称、请求与修复次数见同目录 JSON。',
                  '首次/修复后内容正确率、行动准确率与错误放行率：本技术冒烟不测，须在人工标准复核后独立评价。'])
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return [{'subject':r['subject'],'state':r.get('final_state',r.get('error_type')),'elapsed_seconds':r['elapsed_seconds']} for r in records]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(run(args.output),ensure_ascii=False))
