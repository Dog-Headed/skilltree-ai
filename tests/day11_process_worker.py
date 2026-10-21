"""Uncatchable process-death fixture; never opens the user's data directory."""
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from app.v3.storage import V3Paths
from tests.day11_support import FakeLearningModel


if __name__=='__main__':
    root,pid,hook,event_file=sys.argv[1:]
    event=json.loads(Path(event_file).read_text(encoding='utf-8'))
    model=FakeLearningModel()
    if hook=='before_initialize':
        def start_session(self,*args,**kwargs):os._exit(71)
        LearningRepository.start_session=start_session
    elif hook in ('tutor_http','quiz_http'):
        original=model._invoke
        def invoke(schema,messages):
            if schema==('TutorReply' if hook=='tutor_http' else 'AssessmentQuiz'): os._exit(71)
            return original(schema,messages)
        model._invoke=invoke
    else:
        owner=LearningService if hook=='finish' else LearningRepository
        name={'quiz_saved':'save_quiz','evaluation_saved':'save_evaluation','completion_saved':'apply_transition',
              'finish':'_finish'}[hook]
        original=getattr(owner,name)
        def saved(self,*args,**kwargs):
            result=original(self,*args,**kwargs)
            # For the last-wait test leave the execution marker behind.
            if hook=='finish': raise AssertionError('finish hook is handled separately')
            os._exit(71)
        if hook=='finish':
            def saved(self,*args,**kwargs): os._exit(71)
        setattr(owner,name,saved)
    service=LearningService(V3Paths(root),llm=model)
    if event['action']=='begin_learning': service.start(pid,event['request_id'])
    else: service.resume(pid,event)
    raise AssertionError('Expected hard exit')
