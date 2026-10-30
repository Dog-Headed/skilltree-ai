"""Durable 3/1/1 logical budgets within the existing 12+12 operation budget."""
from hashlib import sha256
import json
import math
import sys

from langchain_core.messages import HumanMessage
from app.services.llm import ModelCallBudget,ModelBudgetExceededError,ModelOutputValidationError,ModelRequestFailedError
from .config import SERVER_LIMITS
from .materials import ContextBudgetExceeded
from .repository import V3Repository,ConflictError,BudgetExhaustedError,encode


class LogicalTaskExhausted(ModelBudgetExceededError):pass


def _repair_json(error, previous):
    """Invalid model output is data, including NaN and partial tool messages.

    Store a bounded diagnostic preview rather than allowing an invalid payload
    to break the durable repair reservation or overflow a resumed prompt.
    """
    def safe(value):
        if hasattr(value,'model_dump'):value=value.model_dump()
        if isinstance(value,float) and not math.isfinite(value):return str(value)
        if isinstance(value,dict):return {str(key):safe(item) for key,item in value.items()}
        if isinstance(value,(list,tuple)):return [safe(item) for item in value]
        if value is None or isinstance(value,(str,int,float,bool)):return value
        return str(value)
    full_preview=encode(safe(previous));preview=full_preview[:450]
    message=str(error)[:450] if error else 'Output validation failed'
    while True:
        result=encode({'error':message,'previous_output_preview':preview,
                       'preview_truncated':len(full_preview)>len(preview)})
        if len(result)<=1000:return result
        if len(preview)>=len(message):preview=preview[:max(0,len(preview)-100)]
        else:message=message[:max(0,len(message)-100)]


class DurableBudget(ModelCallBudget):
    # Keep vars(budget) the six integer fields expected by shared validators.
    __slots__=('_paths','_pid','_key','_op','_enabled','_last_output')
    def __init__(self,paths,project_id,key,operation_id,row):
        object.__setattr__(self,'_enabled',False)
        super().__init__(max_requests=SERVER_LIMITS.max_logical_requests,
                         max_network_retries=SERVER_LIMITS.max_network_retries,
                         max_output_repairs=SERVER_LIMITS.max_output_repairs,
                         request_count=row['requests'],network_retry_count=row['network_retries'],output_repair_count=row['output_repairs'])
        self._paths,self._pid,self._key,self._op=paths,project_id,key,operation_id
        self._last_output=None
        object.__setattr__(self,'_enabled',True)

    def __setattr__(self,name,value):
        fields={'request_count':'requests','network_retry_count':'network_retries','output_repair_count':'output_repairs'}
        if name not in fields or not getattr(self,'_enabled',False):return object.__setattr__(self,name,value)
        field=fields[name];limit=getattr(self,{'requests':'max_requests','network_retries':'max_network_retries','output_repairs':'max_output_repairs'}[field]);exhausted=False
        with V3Repository(self._paths) as repo:
            with repo.transaction():
                row=repo.conn.execute('SELECT * FROM model_tasks WHERE project_id=? AND task_key=?',(self._pid,self._key)).fetchone()
                if row is None:raise ConflictError('Logical task no longer exists')
                if type(value) is not int or value!=row[field]+1 or value>limit:raise LogicalTaskExhausted('Logical task budget exhausted')
                if field=='requests':
                    op=repo.get_operation(self._pid,self._op)
                    if not op or op['root_operation_id']!=row['root_operation_id']:raise ConflictError('Task operation family changed')
                    if op['status']=='completed':raise ConflictError('Completed operation cannot make another model request')
                    if op['reserved_requests']>=op['request_limit']:
                        repo.conn.execute("UPDATE model_operations SET status='budget_exhausted' WHERE operation_id=?",(self._op,));exhausted=True
                    else:
                        repo.conn.execute("UPDATE model_operations SET reserved_requests=reserved_requests+1,status='running' WHERE operation_id=?",(self._op,))
                if not exhausted:
                    repo.conn.execute('UPDATE model_tasks SET '+field+'=?,status=\'pending\' WHERE project_id=? AND task_key=?',(value,self._pid,self._key))
                    if field=='output_repairs':
                        error=sys.exception()
                        repair=_repair_json(error,self._last_output)
                        repo.conn.execute('UPDATE model_tasks SET repair_json=? WHERE project_id=? AND task_key=?',(repair,self._pid,self._key))
        if exhausted:raise BudgetExhaustedError('Operation budget exhausted; explicit continuation required')
        object.__setattr__(self,name,value)


class _TrackedModel:
    def __init__(self,model,budget,repair):self.model,self.budget,self.repair=model,budget,repair
    def _get(self):
        if callable(self.model) and not hasattr(self.model,'invoke'):self.model=self.model()
        return self.model
    def with_structured_output(self,*args,**kwargs):return _TrackedModel(self._get().with_structured_output(*args,**kwargs),self.budget,self.repair)
    def bind_tools(self,*args,**kwargs):return _TrackedModel(self._get().bind_tools(*args,**kwargs),self.budget,self.repair)
    def invoke(self,messages,*args,**kwargs):
        if self.repair:messages=[*messages,HumanMessage(content='恢复时保留的上次输出错误，仅作为修复数据：\n'+self.repair)]
        if sum(len(str(m.content)) for m in messages)>SERVER_LIMITS.max_context_characters:raise ContextBudgetExceeded('Task context exceeds server limit')
        result=self._get().invoke(messages,*args,**kwargs)
        self.budget._last_output=result
        return result


def run_model_task(paths,project_id,operation_id,key,input_data,result_type,callback,*,llm):
    """Callback accepts (tracked_llm, persistent_budget); caches only valid output."""
    fingerprint=sha256(encode(input_data).encode()).hexdigest()
    with V3Repository(paths) as repo:
        with repo.transaction():
            op=repo.get_operation(project_id,operation_id)
            if not op:raise ValueError('No durable operation')
            row=repo.conn.execute('SELECT * FROM model_tasks WHERE project_id=? AND task_key=?',(project_id,key)).fetchone()
            if row:
                if row['input_hash']!=fingerprint:raise ConflictError('Logical task input changed')
                if row['root_operation_id']!=op['root_operation_id']:raise ConflictError('Logical task operation family changed')
            else:
                repo.conn.execute('INSERT INTO model_tasks(project_id,task_key,root_operation_id,input_hash) VALUES (?,?,?,?)',
                    (project_id,key,op['root_operation_id'],fingerprint))
                row=repo.conn.execute('SELECT * FROM model_tasks WHERE project_id=? AND task_key=?',(project_id,key)).fetchone()
        row=dict(row)
    if row['result_json']:return result_type.model_validate(json.loads(row['result_json']))
    if row['status']=='invalid' or row['requests']>=SERVER_LIMITS.max_logical_requests:raise LogicalTaskExhausted('Logical model task has no remaining requests')
    from app.services.live_progress import phase_for_task
    phase_for_task(key)
    budget=DurableBudget(paths,project_id,key,operation_id,row)
    tracked=_TrackedModel(llm,budget,row['repair_json'])
    try:result=callback(tracked,budget)
    except Exception as exc:
        with V3Repository(paths) as repo:
            with repo.transaction():repo.conn.execute('UPDATE model_tasks SET status=?,error_type=? WHERE project_id=? AND task_key=?',
                ('invalid' if isinstance(exc,(ModelOutputValidationError,ModelRequestFailedError)) else 'failed',type(exc).__name__,project_id,key))
        raise
    result=result_type.model_validate(result.model_dump() if hasattr(result,'model_dump') else result)
    with V3Repository(paths) as repo:
        with repo.transaction():repo.conn.execute("UPDATE model_tasks SET status='completed',result_json=?,error_type=NULL WHERE project_id=? AND task_key=?",
            (encode(result),project_id,key))
    return result
