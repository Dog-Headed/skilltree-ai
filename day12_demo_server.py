"""Isolated browser workflow demonstration with an explicitly Fake provider.

Never opens deployment data; no real HTTP model calls or held-out cases.
"""
import argparse
import json
from pathlib import Path
from tests.day11_support import FakeLearningModel
from app.v3.storage import V3Paths,initialize_storage,PROJECT_ROOT
from app.v3.runtime_storage import initialize_learning_storage
from app.v3.learning_api import create_learning_app


class BrowserFake(FakeLearningModel):
    def _invoke(self,schema,messages):
        result=super()._invoke(schema,messages)
        with (self.root/'fake-calls.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(self.calls[-1],ensure_ascii=False)+'\n')
        return result

    def _plan(self,data):
        subject=data['profile']['subject_label'].lower()
        key='python' if 'python' in subject else 'mathematics' if subject in ('数学','mathematics') else 'english'
        fixtures=json.loads((PROJECT_ROOT/'docs'/'v3'/'day10_demo_plans.json').read_text(encoding='utf-8'))
        local=FakeLearningModel();local.node_specs=fixtures[key][:2];local.numeric_problems=self.numeric_problems
        return local._plan(data)


def create_demo(root):
    paths=initialize_storage(V3Paths(root));initialize_learning_storage(paths)
    model=BrowserFake();model.root=paths.root
    model.numeric_problems={'node_1':('计算-3-2',-5.0),'node_2':('求解x+5=12的x',7.0)}
    app=create_learning_app(paths,llm=model,legacy_business_path=paths.root/'legacy.sqlite',legacy_checkpoint_path=paths.root/'legacy-checkpoints.sqlite')
    @app.middleware('http')
    async def observed_demo_requests(request,call_next):
        from fastapi.responses import Response
        response=await call_next(request)
        marker=paths.root/'drop-response-once.json';dropped=False
        if marker.exists():
            instruction=json.loads(marker.read_text(encoding='utf-8'))
            if (request.method,request.url.path)==(instruction['method'],instruction['path']):
                marker.unlink();dropped=True
                # Test-only truncated response after the real command commits.
                response=Response('{',media_type='application/json')
        with (paths.root/'browser-requests.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(json.dumps({'method':request.method,'path':request.url.path,
                                     'status':response.status_code,'truncated':dropped})+'\n')
        return response
    return app


if __name__=='__main__':
    import uvicorn
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18120)
    args=parser.parse_args()
    root=args.root.resolve()
    if not root.is_relative_to((PROJECT_ROOT/'work').resolve()):raise SystemExit('Demo root must be under work/')
    uvicorn.run(create_demo(root),host='127.0.0.1',port=args.port)
