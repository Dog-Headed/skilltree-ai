"""Real Planner smoke previews for three explicitly reduced choice-only goals.

Uses configured local credentials, never logs secrets. No evaluation cases or
private answer files enter the model. Does not confirm/freeze the returned plan.
This is not a full-topic evaluation, nor a Day11 teaching runtime.
"""
import argparse
import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4
from unittest.mock import patch

from app.v3.contracts import LearningProfile
from app.v3.materials import MaterialService
from app.v3.planner import PLANNER_PROMPT_VERSION
from app.v3 import planner
from app.v3.preparation import PreparationService
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths, initialize_storage

ROOT=Path(__file__).resolve().parent


class _RecordingModel:
    def __init__(self,model,outputs):self.model,self.outputs=model,outputs
    def with_structured_output(self,*args,**kwargs):
        return _RecordingModel(self.model.with_structured_output(*args,**kwargs),self.outputs)
    def invoke(self,messages):
        result=self.model.invoke(messages)
        self.outputs.append(result.model_dump() if hasattr(result,'model_dump') else result)
        return result


def preview(destination):
    destination=Path(destination).resolve()
    if (destination/'learning.sqlite').exists() or (destination/'checkpoints.sqlite').exists():
        raise ValueError('Use a new isolated directory')
    paths=initialize_storage(V3Paths(destination));service=PreparationService(paths);rows=[]
    for manifest_path in sorted((ROOT/'materials/v3').glob('*/manifest.json')):
        manifest=json.loads(manifest_path.read_text(encoding='utf8'))
        goal='仅通过选择题辨认'+manifest['suggested_plan']['bounded_goal']+'的规则和结果；不测文字解释或数值求解过程。'
        profile=LearningProfile(subject_label=manifest['subject_label'],topic=manifest['topic'],goal=goal,bounded_goal=goal,
            requested_capabilities=['choice_exact'],scope_in=manifest['scope_in'],scope_out=manifest['scope_out'])
        view=service.create(str(uuid4()),profile)
        with V3Repository(paths) as repo:
            for document in manifest['documents']:
                if document['visibility']!='teaching':continue
                MaterialService(repo).import_upload(view['project_id'],request_id=uuid4(),
                    data=(manifest_path.parent/document['filename']).read_bytes(),filename=document['filename'],
                    source_id=document['source_id'],title=document['title'],visibility='teaching',
                    source_description='Agent原创、待复核；规则来源：'+' ; '.join(document['source_urls']))
        view=service.read(view['project_id']);started=perf_counter()
        outputs=[];adapter=_RecordingModel(planner.get_llm(),outputs)
        with patch.object(planner,'get_llm',lambda:adapter):
            result=service.resume(view['project_id'],{'request_id':str(uuid4()),'pending_input_id':view['pending_input_id'],
                'draft_revision':view['draft_revision'],'action':'confirm_profile'})
        with V3Repository(paths) as repo:
            calls=repo.conn.execute('SELECT COALESCE(SUM(reserved_requests),0) FROM model_operations WHERE project_id=?',(view['project_id'],)).fetchone()[0]
        rows.append({'subject':manifest['subject_label'],'simulated_profile_confirmation':True,'plan_user_confirmed':False,
            'elapsed_seconds':round(perf_counter()-started,3),'reserved_http_requests':calls,'usage':None,
            'usage_unavailable_reason':'Existing structured adapter returns parsed plan only','result':result})
        (destination/(manifest_path.parent.name+'-planner-outputs.json')).write_text(json.dumps(outputs,ensure_ascii=False,indent=2),encoding='utf8')
        (destination/'real-previews.json').write_text(json.dumps({'model':os.getenv('LLM_MODEL'),
            'prompt_version':PLANNER_PROMPT_VERSION,'scope':'reduced_choice_only','case_evaluation_runs':0,'plans':rows},ensure_ascii=False,indent=2),encoding='utf8')
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    rows=preview(parser.parse_args().output)
    print(json.dumps([{'subject':r['subject'],'stage':r['result']['page_state'],
        'reserved_http_requests':r['reserved_http_requests'],'elapsed_seconds':r['elapsed_seconds']} for r in rows],ensure_ascii=False))
