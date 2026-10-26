"""Day10 preparation-only API. V2 UI and learning endpoints remain unchanged."""
import base64
import binascii
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator

from .contracts import ContractModel, Identity, LearningProfile
from .materials import ContextBudgetExceeded, MaterialService
from .preparation import PreparationService, project_execution
from .execution import ExecutionActiveError
from .repository import V3Repository, ConflictError
from .storage import V3Paths
from .reference_bindings import PrivateReferenceChoice, reference_id
from .onboarding import LearningIntent


class CreateDraft(ContractModel):
    request_id: UUID = Field(strict=False)
    profile: LearningProfile | None = None
    intent: LearningIntent | None = None

    @model_validator(mode='after')
    def one_creation(self):
        if (self.profile is None)==(self.intent is None):raise ValueError('Provide a goal intent or a complete profile')
        if self.intent:self.intent.as_profile()
        return self

    def resolved_profile(self):
        return self.intent.as_profile() if self.intent else self.profile


class PreparationInput(ContractModel):
    request_id: UUID = Field(strict=False)
    pending_input_id: Identity
    draft_revision: int = Field(ge=1)
    action: Literal['confirm_profile','update_profile','adjust_scope','replan','adjust_plan','confirm_plan','choose_exploration','rest']
    profile: LearningProfile | None = None
    feedback: str | None = Field(default=None,min_length=1,max_length=2000)
    private_references: list[PrivateReferenceChoice] | None = None

    @model_validator(mode='after')
    def payload_for_action(self):
        if (self.action in ('update_profile','adjust_scope')) != (self.profile is not None):raise ValueError('Wrong profile payload')
        if (self.action=='adjust_plan') != (self.feedback is not None):raise ValueError('Wrong feedback payload')
        if self.private_references is not None and self.action!='confirm_plan':raise ValueError('Reference choices require plan confirmation')
        return self


class SourceUpload(ContractModel):
    request_id: UUID = Field(strict=False)
    source_id: Identity | None = None
    title: str = Field(min_length=1,max_length=256)
    source_description: str = Field(min_length=1,max_length=4000)
    visibility: Literal['teaching','assessment_private'] = 'teaching'
    content: str | None = Field(default=None,max_length=131072)
    filename: str | None = Field(default=None,max_length=255)
    data_base64: str | None = Field(default=None,max_length=174764)

    @model_validator(mode='after')
    def one_source(self):
        if (self.content is None)==(self.data_base64 is None):raise ValueError('Provide text or upload bytes')
        if (self.filename is not None)!=(self.data_base64 is not None):raise ValueError('Upload filename missing')
        return self


class RetryInput(ContractModel):
    request_id: UUID = Field(strict=False)
    retry_token: Identity
    action: Literal['retry','continue_with_new_budget']='retry'


def create_preparation_app(paths=V3Paths()):
    service=PreparationService(paths)
    app=FastAPI(title='SkillTree V3 preparation only')

    @app.exception_handler(ConflictError)
    async def conflict(request,exc):
        stale='requires_replan' in str(exc)
        return JSONResponse(status_code=409,content={'error':{'code':'execution_active' if isinstance(exc,ExecutionActiveError) else 'requires_replan' if stale else 'stale_input',
            'message':'配置或资料已变化，请重新读取并明确重新规划。' if stale else '输入身份已过期，请读取最新状态。'},'requires_replan':stale})

    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse(status_code=404,content={'error':{'code':'not_found','message':'项目或资料不存在。'}})

    @app.exception_handler(ContextBudgetExceeded)
    async def context_limit(request,exc):
        return JSONResponse(status_code=422,content={'error':{'code':'context_limit',
            'message':'所选资料超过上下文上限，计划尚未冻结。请排除较大评价参考，或导入精简参考后重新规划。'}})

    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse(status_code=422,content={'error':{'code':'invalid_input','message':'输入不合法或当前能力不支持此操作。'}})

    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):return JSONResponse(status_code=422,content={'error':{'code':'invalid_input','message':'请检查输入字段与当前操作。'}})

    @app.post('/projects',status_code=201)
    def create(payload: CreateDraft):return service.create(str(payload.request_id),payload.resolved_profile(),
        guided_intent=payload.intent.model_dump() if payload.intent else None)

    @app.get('/projects/{project_id}')
    def read(project_id: str):return service.read(project_id)

    @app.post('/projects/{project_id}/resume')
    def resume(project_id: str,payload: PreparationInput):return service.resume(project_id,payload.model_dump(mode='json',exclude_none=True))

    @app.post('/projects/{project_id}/retry')
    def retry(project_id: str,payload: RetryInput):
        return service.retry(project_id,retry_token=payload.retry_token,request_id=str(payload.request_id),continue_budget=payload.action=='continue_with_new_budget')

    @app.post('/projects/{project_id}/sources')
    def upload(project_id: str,payload: SourceUpload):
        if payload.source_id and payload.source_id.startswith('ai_notes_'):raise ValueError('Generated source identity is server-owned')
        args=payload.model_dump(mode='json',exclude_none=True);args.pop('filename',None);data=args.pop('data_base64',None)
        with project_execution(project_id,paths),V3Repository(paths) as repo:
            if repo.conn.execute('SELECT 1 FROM preparation_execution WHERE project_id=?',(project_id,)).fetchone():
                raise ConflictError('Recover interrupted execution before editing materials')
            materials=MaterialService(repo)
            if data is not None:
                try:raw=base64.b64decode(data,validate=True)
                except binascii.Error as exc:raise ValueError('Invalid encoded upload') from exc
                result=materials.import_upload(project_id,data=raw,filename=payload.filename,**args)
            else:result=materials.import_text(project_id,**args)
        # Private originals, chunks, answer-only titles and hashes never become a page response.
        response={'imported':True,'reused':result.reused,'draft_revision':result.draft_revision}
        if result.document.visibility=='assessment_private':response['private_reference_id']=reference_id(result.document.model_dump())
        return response

    @app.get('/projects/{project_id}/sources')
    def sources(project_id: str):return service.read(project_id)['sources']

    @app.get('/capabilities')
    def capabilities():
        from .capabilities import list_capabilities
        return list_capabilities()

    return app
