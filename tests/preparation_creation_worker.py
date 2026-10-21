"""Real hard exits around initial preparation; all stores belong to the test."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

import dotenv
dotenv.load_dotenv=lambda *a,**k:False

from app.v3 import preparation
from app.v3.preparation import PreparationService
from app.v3.repository import V3Repository
from app.v3.storage import V3Paths,initialize_storage


if __name__=='__main__':
    directory=Path(sys.argv[1]);mode=sys.argv[2]
    paths=initialize_storage(V3Paths(directory))
    request={'request_id':str(uuid4()),'profile':{'subject_label':'历史','topic':'事实阅读','goal':'辨认事实',
        'bounded_goal':'选择资料中的事实','requested_capabilities':['choice_exact']}}
    (directory/'request.json').write_text(json.dumps(request),encoding='utf-8')
    if mode=='project_inserted':
        original=V3Repository.create_project
        def die(self,*args,**kwargs):original(self,*args,**kwargs);os._exit(73)
        with patch.object(V3Repository,'create_project',die):PreparationService(paths).create(request['request_id'],request['profile'])
    elif mode=='before_wait':
        with patch.object(preparation,'interrupt',lambda *a,**k:os._exit(73)):
            PreparationService(paths).create(request['request_id'],request['profile'])
    elif mode=='wait_committed':
        with patch.object(PreparationService,'_finish_execution',lambda *a,**k:os._exit(73)):
            PreparationService(paths).create(request['request_id'],request['profile'])
    elif mode=='legacy':
        service=PreparationService(paths)
        with V3Repository(paths) as repo:p=repo.create_project(request['request_id'],request['profile'])
        with service._graph() as graph,patch.object(preparation,'interrupt',lambda *a,**k:os._exit(73)):
            graph.invoke({'project_id':p['id'],'thread_id':p['id']},service._config(p['id']),durability='sync')
    raise AssertionError('Expected hard exit')
