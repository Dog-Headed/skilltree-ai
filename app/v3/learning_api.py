"""Local V3 product API. Public reads never invoke Graphs or model providers."""
from pathlib import Path
from uuid import UUID
import base64
import binascii
import json
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, field_validator
from .contracts import ContractModel, Identity
from .execution import project_execution
from .learning import LearningService, LearningInput
from .learning_repository import LearningRepository
from .materials import ContextBudgetExceeded, MaterialService
from .preparation import PreparationService
from .preparation_api import CreateDraft, PreparationInput, SourceUpload, RetryInput
from .repository import ConflictError
from .storage import V3Paths, PROJECT_ROOT
from .public_view import project_view, source_detail
from . import project_management
from .reference_bindings import reference_id

logger=logging.getLogger(__name__)
STATIC=Path(__file__).resolve().parents[1]/'static'


class BeginInput(ContractModel):
    request_id: UUID = Field(strict=False)


class RenameInput(ContractModel):
    display_name: str = Field(min_length=1,max_length=80)

    @field_validator('display_name')
    @classmethod
    def clean_name(cls,value):
        value=value.strip()
        if not value or any(ord(c)<32 for c in value):raise ValueError('Invalid name')
        return value


class DeleteInput(ContractModel):
    confirm_project_id: Identity


class LegacyWriteError(Exception):
    pass


def create_learning_app(paths=V3Paths(), *, llm=None, legacy_business_path=None, legacy_checkpoint_path=None, quiz_generation_mode='legacy', preparation_generation_mode='legacy'):
    """No automatic business/schema migration or legacy checkpoint execution."""
    from .legacy import LegacyHistory
    learning=LearningService(paths,llm=llm,quiz_generation_mode=quiz_generation_mode)
    preparation=PreparationService(paths,llm=llm,quiz_generation_mode=quiz_generation_mode,preparation_generation_mode=preparation_generation_mode)
    legacy=LegacyHistory(legacy_business_path or PROJECT_ROOT/'data'/'learning.sqlite',
                         legacy_checkpoint_path or PROJECT_ROOT/'data'/'checkpoints.sqlite')
    app=FastAPI(title='SkillTree V3',version='3.0.0-day12')

    def visible(pid):
        if legacy.contains(pid):raise LegacyWriteError()
        with LearningRepository(paths) as repo:project_management.require_visible(repo,pid)

    def has_session(pid):
        with LearningRepository(paths) as repo:
            return bool(repo.session(pid) or repo.conn.execute('SELECT 1 FROM learning_execution WHERE project_id=?',(pid,)).fetchone())

    def read(pid):
        with LearningRepository(paths) as repo:project_management.require_visible(repo,pid)
        base=learning.read(pid) if has_session(pid) else preparation.read(pid)
        with LearningRepository(paths) as repo:return project_view(repo,base)

    @app.middleware('http')
    async def local_origin(request:Request,call_next):
        origin=request.headers.get('origin')
        if request.method in {'POST','PATCH','DELETE'} and origin and origin!=str(request.base_url).rstrip('/'):
            return JSONResponse(status_code=403,content={'error':{'code':'invalid_origin','message':'请从当前学习页面提交操作。'}})
        response=await call_next(request)
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response

    @app.exception_handler(LegacyWriteError)
    async def old_version(request,exc):
        return JSONResponse(status_code=409,content={'error':{'code':'legacy_readonly','message':'V2 历史仅供查看，请在 V3 创建新项目。'}})

    @app.exception_handler(ConflictError)
    async def conflict(request,exc):
        return JSONResponse(status_code=409,content={'error':{'code':'state_conflict','message':'状态或输入身份已变化，请读取最新状态。'}})

    @app.exception_handler(KeyError)
    async def missing(request,exc):
        return JSONResponse(status_code=404,content={'error':{'code':'not_found','message':'项目或记录不存在。'}})

    @app.exception_handler(ContextBudgetExceeded)
    async def context_limit(request,exc):
        return JSONResponse(status_code=422,content={'error':{'code':'context_limit',
            'message':'所选资料超过上下文上限，计划尚未冻结。请排除较大评价参考，或导入精简参考后重新规划。'}})

    @app.exception_handler(ValueError)
    async def invalid(request,exc):
        return JSONResponse(status_code=422,content={'error':{'code':'invalid_input','message':'当前状态或输入不允许此操作。'}})

    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):
        return JSONResponse(status_code=422,content={'error':{'code':'invalid_input','message':'请检查输入字段与当前操作。'}})

    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        logger.error('V3 API failure error_type=%s',type(exc).__name__)
        return JSONResponse(status_code=500,content={'error':{'code':'service_error','message':'本次响应未完成，请先刷新状态查看已保存的结果。'}})

    @app.get('/',include_in_schema=False)
    def home():return FileResponse(STATIC/'v3.html')

    @app.get('/login',include_in_schema=False)
    def login_page():return FileResponse(STATIC/'login.html')

    @app.get('/session')
    def local_session():
        # Production's authenticated gateway supplies the actual account.
        return {'account':None}

    @app.get('/assets/{filename}',include_in_schema=False)
    def asset(filename:str):
        if filename not in {'v3.js','v3.css','garden.js','garden.css','botanical.js','botanical.css','fonts.css','controls.css','controls.js','login.html','login.css','login.js'}:raise KeyError(filename)
        return FileResponse(STATIC/filename)

    @app.get('/assets/fonts/{filename}',include_in_schema=False)
    def font(filename:str):
        import re
        if not re.fullmatch(r'design-[0-9]{3}\.(?:woff2|ttf)',filename):raise KeyError(filename)
        path=STATIC/'fonts'/filename
        if not path.is_file():raise KeyError(filename)
        return FileResponse(path)

    @app.get('/projects')
    def projects(request:Request):
        allowed_ids=getattr(request.state,'allowed_project_ids',None)
        with LearningRepository(paths) as repo:
            ids=[p['id'] for p in repo.list_projects() if (allowed_ids is None or p['id'] in allowed_ids) and not project_management.metadata(repo,p['id']).get('deleted_at')]
        result=[]
        for pid in reversed(ids):
            try:view=read(pid)
            except KeyError:continue
            result.append({key:view.get(key) for key in ('project_id','version','read_only','display_name','profile','page_state','current_node_id','completed_node_ids','nodes')})
        return result

    @app.post('/projects',status_code=201)
    def create(payload:CreateDraft):
        pid='v3_'+payload.request_id.hex
        with project_execution(pid,paths),LearningRepository(paths) as repo:
            if project_management.metadata(repo,pid).get('deleted_at'):raise ConflictError('Deleted creation request')
            preparation.create(str(payload.request_id),payload.resolved_profile(),
                guided_intent=payload.intent.model_dump() if payload.intent else None)
            return read(pid)

    @app.get('/projects/{project_id}')
    def get_project(project_id:str):return read(project_id)

    @app.post('/projects/{project_id}/begin')
    def begin(project_id:str,payload:BeginInput):
        with project_execution(project_id,paths):
            visible(project_id);learning.start(project_id,str(payload.request_id));return read(project_id)

    @app.post('/projects/{project_id}/resume')
    def resume(project_id:str,payload:LearningInput | PreparationInput):
        with project_execution(project_id,paths):
            visible(project_id)
            data=payload.model_dump(mode='json',exclude_none=True)
            if has_session(project_id):learning.resume(project_id,data)
            else:preparation.resume(project_id,PreparationInput.model_validate(data).model_dump(mode='json',exclude_none=True))
            return read(project_id)

    @app.post('/projects/{project_id}/retry')
    def retry(project_id:str,payload:RetryInput):
        with project_execution(project_id,paths):
            visible(project_id)
            service=learning if has_session(project_id) else preparation
            service.retry(project_id,retry_token=payload.retry_token,request_id=str(payload.request_id),continue_budget=payload.action=='continue_with_new_budget')
            return read(project_id)

    @app.patch('/projects/{project_id}')
    def rename(project_id:str,payload:RenameInput):
        with project_execution(project_id,paths),LearningRepository(paths) as repo:
            visible(project_id);project_management.rename(repo,project_id,payload.display_name)
            return read(project_id)

    @app.delete('/projects/{project_id}')
    def delete(project_id:str,payload:DeleteInput):
        with project_execution(project_id,paths),LearningRepository(paths) as repo:
            if legacy.contains(project_id):raise LegacyWriteError()
            if payload.confirm_project_id!=project_id:raise ConflictError('Deletion identity mismatch')
            project_management.delete(repo,project_id)
            return {'deleted':True,'project_id':project_id}

    @app.post('/projects/{project_id}/sources')
    def upload(project_id:str,payload:SourceUpload):
        if payload.source_id and payload.source_id.startswith('ai_notes_'):raise ValueError('Generated source identity is server-owned')
        data=payload.model_dump(mode='json',exclude_none=True);data.pop('filename',None);raw=data.pop('data_base64',None)
        with project_execution(project_id,paths),LearningRepository(paths) as repo:
            visible(project_id)
            if repo.session(project_id) or repo.conn.execute('SELECT 1 FROM learning_execution WHERE project_id=?',(project_id,)).fetchone() or repo.conn.execute('SELECT 1 FROM preparation_execution WHERE project_id=?',(project_id,)).fetchone():
                raise ConflictError('Frozen learning or interrupted preparation cannot import material')
            materials=MaterialService(repo)
            if raw is not None:
                try:decoded=base64.b64decode(raw,validate=True)
                except binascii.Error as exc:raise ValueError('Invalid encoding') from exc
                result=materials.import_upload(project_id,data=decoded,filename=payload.filename,**data)
            else:result=materials.import_text(project_id,**data)
        response={'imported':True,'reused':result.reused,'draft_revision':result.draft_revision}
        if result.document.visibility=='assessment_private':response['private_reference_id']=reference_id(result.document.model_dump())
        return response

    @app.get('/projects/{project_id}/sources')
    def sources(project_id:str):return read(project_id)['sources']

    @app.get('/projects/{project_id}/sources/{source_id}/versions/{version}')
    def source(project_id:str,source_id:str,version:int):
        with LearningRepository(paths) as repo:return source_detail(repo,project_id,source_id,version)

    @app.get('/capabilities')
    def capabilities():
        from .capabilities import list_capabilities
        return list_capabilities()

    @app.get('/material-packs')
    def packs():return [{'subject':s,'title':t} for s,t in [('python','Python 条件与循环'),('mathematics','数学：一元一次方程'),('english','英语：一般过去时')]]

    @app.get('/material-packs/{subject}')
    def pack(subject:str):
        if subject not in {'python','mathematics','english'}:raise KeyError(subject)
        root=PROJECT_ROOT/'materials'/'v3'/subject
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        scope=manifest['scope_in'];goal='、'.join(scope)
        return {'subject':subject,'title':manifest['topic'],'review_status':manifest['review_status'],
            'profile':{'subject_label':manifest['subject_label'],'topic':manifest['topic'],'goal':goal,'bounded_goal':goal,
                       'scope_in':scope,'scope_out':manifest['scope_out'],'requested_capabilities':manifest['suggested_plan']['full_goal_required_evaluators']},
            'documents':[{'source_id':d['source_id'],'title':d['title'],'source_description':d['trust_note'],
                          'visibility':'teaching','content':(root/d['filename']).read_text(encoding='utf-8')}
                         for d in manifest['documents'] if d['visibility']=='teaching']}

    @app.get('/legacy/projects')
    def old_projects():return legacy.list_projects()

    @app.get('/legacy/projects/{project_id}')
    def old_project(project_id:str):return legacy.get_project(project_id)

    return app
