"""Day 11 learning graph: frozen facts, durable commands and bounded model tasks."""
from contextlib import contextmanager
from hashlib import sha256
import json
from typing import TypedDict
from uuid import uuid5, NAMESPACE_URL

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from pydantic import Field, model_validator
from app.services.observability import observed_node

from . import assessment, diagnosis, tutor
from .contracts import (ContractModel, Identity, LearningProfile, EvaluationPolicy,
                        AssessmentQuiz, EvaluationResult, PublicQuiz, FrozenSnapshot)
from .context import ContextBuilder
from .execution import project_execution, execution_is_active
from .learning_repository import LearningRepository
from .model_tasks import run_model_task
from .repository import ConflictError, BudgetExhaustedError, encode, request_key, now
from .runtime_storage import (open_learning_checkpointer, validate_learning_storage,
                              RUNTIME_SCHEMA_VERSION, LEARNING_GRAPH_VERSION)
from .storage import V3Paths
from .config import SERVER_LIMITS
from .tutor_feedback import build_tutor_feedback


class LearningInput(ContractModel):
    request_id: str = Field(min_length=1, max_length=128)
    pending_input_id: Identity
    draft_revision: int = Field(ge=1)
    action: str
    assessment_id: Identity | None = None
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    answers: dict[str, str | list[str]] | None = None
    annotation: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode='after')
    def validate_payload(self):
        object.__setattr__(self,'request_id',request_key(self.request_id))
        if (self.action == 'ask') != (self.question is not None): raise ValueError('Question payload mismatch')
        if (self.action == 'submit_answer') != (self.answers is not None): raise ValueError('Answer payload mismatch')
        if (self.action == 'annotate_dispute') != (self.annotation is not None): raise ValueError('Annotation payload mismatch')
        if self.answers and (len(self.answers)>10 or any(
                (isinstance(v,str) and len(v)>8000) or (isinstance(v,list) and (len(v)>10 or any(len(item)>128 for item in v)))
                for v in self.answers.values())):
            raise ValueError('Answers exceed server limits')
        return self


class LearningState(TypedDict, total=False):
    project_id: str
    learning_event: dict
    next_step: str
    assessment_id: str


def fingerprint(value): return sha256(encode(value).encode()).hexdigest()


class LearningService:
    def __init__(self, paths=V3Paths(), *, llm=None):
        validate_learning_storage(paths)
        self.paths, self.llm = paths, llm
        with LearningRepository(paths) as repo:
            if repo.conn.execute("SELECT 1 FROM runtime_metadata WHERE key='demo_only'").fetchone():
                raise ValueError('Fake preparation stores are not live learning stores')

    def _provider(self):
        if self.llm is not None: return self.llm
        from app.services.llm import get_llm
        return get_llm()

    @staticmethod
    def _config(pid): return {'configurable': {'thread_id': pid}, 'recursion_limit': 30}

    @contextmanager
    def _graph(self):
        with open_learning_checkpointer(self.paths) as saver:
            yield self._build_graph().compile(checkpointer=saver)

    def read(self, pid):
        """Pure projection; never repairs a checkpoint or calls a model."""
        with LearningRepository(self.paths) as repo:
            p=repo.get_project(pid)
            if not p: raise KeyError(pid)
            s=repo.session(pid)
            marker=repo.conn.execute('SELECT 1 FROM learning_execution WHERE project_id=?',(pid,)).fetchone()
            if not s:
                if not marker: raise ConflictError('Learning has not started')
                # A hard exit can happen before initialize commits the session.
                # The durable execution journal still owns routing and retry.
                s={'current_node_id':None,'current_assessment_id':None,'mode':'normal','review_node_id':None,
                   'last_tutor_json':None,'last_guard_json':None,'pause_reason':None}
            stage=p['lifecycle']
            if p['error_type'] and stage!='budget_exhausted' and s['pause_reason']!='replacement_limit': stage='error'
            active=bool(marker and execution_is_active(self.paths,pid))
            interrupted=bool(marker and not active)
            if marker: stage='running' if active else 'error'
            rounds=repo.rounds(pid,s['current_node_id']) if s['current_node_id'] else None
            actions={'learning':['ask','start_quiz','rest'], 'exploring':['ask','rest'],
                     'quiz':['submit_answer','return_to_teaching','rest'],
                     'assessment_review':['view_feedback','annotate_dispute','replace_assessment','return_to_teaching','rest'],
                     'error':['retry','return_to_teaching','rest'],
                     'budget_exhausted':['continue_with_new_budget','rest']}.get(stage,[])
            if stage=='learning' and s['mode']=='review': actions.append('return_to_current')
            if stage=='paused':
                actions=['rest']
                if s['pause_reason']=='round_limit' and rounds and not rounds['extension_used']: actions.append('retry_3')
                if s['pause_reason']=='extension_ready': actions.append('return_to_teaching')
            if interrupted: actions=['retry']
            row=repo.get_assessment(pid,s['current_assessment_id']) if s['current_assessment_id'] else None
            if stage=='error' and row and not interrupted:
                rounds=repo.rounds(pid,row['node_id'])
                policy=EvaluationPolicy.model_validate(p['policy'])
                if rounds['replacements']<policy.max_replacements: actions.append('replace_assessment')
            if stage=='error' and (s['current_node_id'] is None or s['pause_reason']=='round_limit'):
                actions=[a for a in actions if a not in ('return_to_teaching','replace_assessment')]
            quiz=PublicQuiz.from_private(AssessmentQuiz.model_validate(json.loads(row['quiz_json']))).model_dump() if row and row['quiz_json'] else None
            evaluation=json.loads(row['evaluation_json']) if row and row['evaluation_json'] else None
            feedback=None
            if evaluation:
                feedback={'grading_status':evaluation['grading_status'],
                          'question_scores':[{'question_id':v['question_id'],'score':v['score'],'max_score':v['max_score']}
                                             for v in evaluation['question_results']],
                          'total_score':sum(v['score'] for v in evaluation['question_results']),
                          'max_score':sum(v['max_score'] for v in evaluation['question_results'])}
            op=repo.get_operation(pid,p['operation_id']) if p['operation_id'] else None
            if stage=='budget_exhausted' and op and op['parent_operation_id']:
                actions=['rest']
            family=[] if not op else [dict(r) for r in repo.conn.execute(
                'SELECT reserved_requests,request_limit FROM model_operations WHERE project_id=? AND root_operation_id=?',(pid,op['root_operation_id']))]
            terminal=None
            if stage=='error' and not marker and op:
                terminal=repo.conn.execute("""SELECT task_key,error_type FROM model_tasks
                    WHERE project_id=? AND root_operation_id=? AND result_json IS NULL
                    AND (status='invalid' OR requests>=?) ORDER BY rowid DESC LIMIT 1""",
                    (pid,op['root_operation_id'],SERVER_LIMITS.max_logical_requests)).fetchone()
                if terminal:actions=[a for a in actions if a!='retry']
            failed_kind=terminal['task_key'].split(':',1)[0] if terminal else None
            notices={'assessment_review':'本轮无法可靠评价，不计入有效失败轮次。可以查看结果、留存说明或申请受限换题。',
                     'budget_exhausted':'本操作请求额度已用完；只能显式追加一次，普通重试不会刷新额度。',
                     'error':'本次操作未完成。重试沿用原身份与剩余额度；也可以返回教学或暂存。',
                     'paused':'当前已暂停，重启或休息不会自动调用教学、出题或诊断。',
                     'exploring':'探索讲解尚未形成正式评价依据，不产生通过和依赖解锁。'}
            if terminal:
                notices['error']=('这次讲解未能完成，已停止继续尝试。可以重新生成讲解，或休息保留进度。'
                    if failed_kind=='tutor' else '这次模型任务已停止继续尝试，普通重试不会恢复次数。请使用下方可用操作继续，或休息保留进度。')
            return {'project_id':pid,'thread_id':p['thread_id'],'profile':p['profile'],
                    'page_state':stage,'allowed_actions':actions,'pending_input_id':p['pending_input_id'],
                    'draft_revision':p['draft_revision'],'current_node_id':s['current_node_id'],
                    'mode':s['mode'],'review_node_id':s['review_node_id'],'assessment_id':s['current_assessment_id'],
                    'quiz':quiz,'feedback':feedback,'tutor':json.loads(s['last_tutor_json']) if s['last_tutor_json'] else None,
                    'guard':json.loads(s['last_guard_json']) if s['last_guard_json'] else None,
                    'rounds':rounds,'pause_reason':s['pause_reason'],'completed_node_ids':repo.completed(pid),
                    'notice':notices.get(stage),
                    'retry_token':p['retry_token'],'error_type':'ExecutionInterrupted' if interrupted else p['error_type'],
                    'error_code':'model_task_exhausted' if terminal else None,'failed_task_kind':failed_kind,
                    'recovery_required':interrupted,'execution_status':'active' if active else 'interrupted' if interrupted else 'idle',
                    'operation_budget':{'used':sum(v['reserved_requests'] for v in family),'limit':sum(v['request_limit'] for v in family)},
                    'learning_runtime_ready':True,'learning_schema_version':RUNTIME_SCHEMA_VERSION,
                    'graph_version':LEARNING_GRAPH_VERSION,'contract_version':'3.0.0'}

    def _operation(self,repo,pid,event):
        op=repo.create_operation(pid,event['request_id'],kind=event['action'])
        with repo.transaction():
            repo.conn.execute('UPDATE learning_projects SET operation_id=?,retry_token=?,error_type=NULL WHERE id=?',
                              (op['operation_id'],op['retry_token'],pid))

    def _journal(self,repo,pid,event,kind,retry_id=None):
        with repo.transaction():
            repo.conn.execute('INSERT OR REPLACE INTO learning_execution VALUES (?,?,?,?)',(pid,encode(event),kind,retry_id))

    def _finish(self,pid):
        with LearningRepository(self.paths) as repo:
            with repo.transaction(): repo.conn.execute('DELETE FROM learning_execution WHERE project_id=?',(pid,))

    def _failure(self,pid,exc,event):
        with LearningRepository(self.paths) as repo:
            with repo.transaction():
                # Keep the last committed business phase. Error is a projection;
                # replacing quiz/completed/paused here breaks cached step recovery.
                stage='budget_exhausted' if isinstance(exc,BudgetExhaustedError) else repo.get_project(pid)['lifecycle']
                session=repo.session(pid)
                if not isinstance(exc,BudgetExhaustedError) and session and session['current_assessment_id']:
                    rounds=repo.rounds(pid,session['current_node_id'])
                    policy=EvaluationPolicy.model_validate(repo.get_project(pid)['policy'])
                    if rounds and rounds['replacements'] and rounds['replacements']>=policy.max_replacements:
                        stage='paused';repo.change_session(pid,pause_reason='replacement_limit')
                repo.mark(pid,stage,pending_input_id='error_'+uuid5(NAMESPACE_URL,pid+event['request_id']).hex,error_type=type(exc).__name__)

    def _succeeded(self,pid):
        with LearningRepository(self.paths) as repo:
            with repo.transaction():
                repo.conn.execute('UPDATE learning_projects SET error_type=NULL WHERE id=?',(pid,))
                repo.conn.execute("UPDATE model_operations SET status='completed' WHERE project_id=? AND operation_id=? AND status!='budget_exhausted'",
                                  (pid,repo.get_project(pid)['operation_id']))

    def start(self,pid,request_id):
        event={'request_id':request_key(request_id),'action':'begin_learning'}
        with project_execution(pid,self.paths),LearningRepository(self.paths) as repo,self._graph() as graph:
            s=repo.session(pid)
            if repo.conn.execute('SELECT 1 FROM learning_execution WHERE project_id=?',(pid,)).fetchone():
                raise ConflictError('Recover interrupted learning initialization first')
            if s:
                return self.read(pid)
            # Validate before journaling; this operation cannot silently choose exploration.
            p=repo.get_project(pid)
            if not p: raise KeyError(pid)
            if not p['frozen_snapshot'] and not (p['profile']['learning_mode']=='exploration' and p['lifecycle']=='exploring'):
                raise ConflictError('Confirm a plan or explicitly choose exploration')
            self._operation(repo,pid,event)
            self._journal(repo,pid,event,'start')
            try: graph.invoke({'project_id':pid,'learning_event':event},self._config(pid),durability='sync')
            except Exception as exc: self._failure(pid,exc,event)
            else: self._succeeded(pid)
            self._finish(pid)
        return self.read(pid)

    def resume(self,pid,event):
        event=LearningInput.model_validate(event).model_dump(exclude_none=True)
        if event['action']=='rest':
            view=self.read(pid)
            self._validate_input(view,event)
            return view
        with project_execution(pid,self.paths),LearningRepository(self.paths) as repo,self._graph() as graph:
            prior=repo.conn.execute('SELECT fingerprint FROM learning_commands WHERE project_id=? AND request_id=?',(pid,event['request_id'])).fetchone()
            if prior:
                if prior[0]!=fingerprint(event): raise ConflictError('Learning command changed')
                return self.read(pid)
            view=self.read(pid);self._validate_input(view,event)
            if event['action'] in ('retry','continue_with_new_budget'): raise ValueError('Use retry endpoint')
            if event['action'] in ('submit_answer','annotate_dispute','replace_assessment') and event.get('assessment_id')!=view['assessment_id']:
                raise ConflictError('Assessment identity changed')
            if event['action']=='submit_answer':
                row=repo.get_assessment(pid,event['assessment_id']);quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json']))
                if set(event['answers'])!={q.question_id for q in quiz.questions}: raise ValueError('Answer every question exactly once')
            self._operation(repo,pid,event)
            self._journal(repo,pid,event,'resume')
            try:
                snap=graph.get_state(self._config(pid))
                if snap.interrupts: graph.invoke(Command(resume=event),self._config(pid),durability='sync')
                elif view['page_state']=='error' and event['action'] in ('return_to_teaching','replace_assessment'):
                    graph.update_state(self._config(pid),{'learning_event':event},as_node='wait')
                    graph.invoke(None,self._config(pid),durability='sync')
                else: raise ConflictError('Graph is not waiting')
            except Exception as exc: self._failure(pid,exc,event)
            else: self._succeeded(pid)
            self._finish(pid)
        return self.read(pid)

    @staticmethod
    def _validate_input(view,event):
        if event['pending_input_id']!=view['pending_input_id'] or event['draft_revision']!=view['draft_revision']:
            raise ConflictError('Stale learning input')
        if event['action'] not in view['allowed_actions']: raise ValueError('Action not allowed')

    def retry(self,pid,*,retry_token,request_id,continue_budget=False):
        key=request_key(request_id);digest=fingerprint({'retry_token':retry_token,'continue_budget':continue_budget})
        with project_execution(pid,self.paths),LearningRepository(self.paths) as repo,self._graph() as graph:
            old=repo.conn.execute('SELECT fingerprint FROM learning_retries WHERE project_id=? AND request_id=?',(pid,key)).fetchone()
            if old:
                if old[0]!=digest: raise ConflictError('Retry command changed')
                return self.read(pid)
            p=repo.get_project(pid)
            if not p or p['retry_token']!=retry_token: raise ConflictError('Stale retry identity')
            marker=repo.conn.execute('SELECT * FROM learning_execution WHERE project_id=?',(pid,)).fetchone()
            snap=graph.get_state(self._config(pid))
            if continue_budget:
                if marker or p['lifecycle']!='budget_exhausted': raise ConflictError('Not awaiting budget continuation')
                parent=repo.get_operation(pid,p['operation_id'])
                if parent['parent_operation_id'] or repo.conn.execute('SELECT 1 FROM model_operations WHERE parent_operation_id=?',(parent['operation_id'],)).fetchone():
                    raise ConflictError('Budget already extended')
            elif not marker and (not p['error_type'] or 'retry' not in self.read(pid)['allowed_actions']):
                raise ConflictError('No retryable unfinished task; use an allowed recovery action')
            event=json.loads(marker['event_json']) if marker else snap.values.get('learning_event')
            if not event: raise ConflictError('No command to recover')
            payload={'continue_budget':continue_budget,'parent':p['operation_id'],'retry_token':retry_token,'request_id':key}
            with repo.transaction():
                repo.conn.execute('INSERT INTO learning_retries VALUES (?,?,?,?)',(pid,key,digest,encode(payload)))
                repo.conn.execute('INSERT OR REPLACE INTO learning_execution VALUES (?,?,?,?)',
                    (pid,encode(event),marker['kind'] if marker else 'resume',marker['retry_request_id'] if marker else key))
            try:
                pending_key=marker['retry_request_id'] if marker and marker['retry_request_id'] else key
                record=repo.conn.execute('SELECT payload_json FROM learning_retries WHERE project_id=? AND request_id=?',(pid,pending_key)).fetchone()
                pending_payload=json.loads(record[0]) if record else payload
                if pending_payload['continue_budget']:
                    parent=repo.get_operation(pid,pending_payload['parent'])
                    child=repo.create_operation(pid,pending_payload['request_id'],kind=parent['kind'],parent_operation_id=parent['operation_id'],retry_token=pending_payload['retry_token'])
                    with repo.transaction(): repo.conn.execute('UPDATE learning_projects SET operation_id=?,retry_token=? WHERE id=?',(child['operation_id'],child['retry_token'],pid))
                if not snap.values:
                    graph.invoke({'project_id':pid,'learning_event':event},self._config(pid),durability='sync')
                elif snap.interrupts:
                    if (snap.values.get('learning_event') or {}).get('request_id')!=event['request_id']:
                        graph.invoke(Command(resume=event),self._config(pid),durability='sync')
                elif snap.next: graph.invoke(None,self._config(pid),durability='sync')
                else: raise ConflictError('No unfinished graph step')
            except Exception as exc: self._failure(pid,exc,event)
            else: self._succeeded(pid)
            self._finish(pid)
        return self.read(pid)

    def _task(self,pid,key,data,kind,callback):
        with LearningRepository(self.paths) as repo: p=repo.get_project(pid)
        return run_model_task(self.paths,pid,p['operation_id'],key,data,kind,callback,llm=self._provider)

    def _contexts(self,repo,pid,node,purpose):
        builder=ContextBuilder(repo)
        method=getattr(builder,'for_'+purpose)
        return {o.objective_id:method(pid,node.node_id,o.objective_id) for o in node.objectives}

    def _build_graph(self):
        def initialize(state):
            with LearningRepository(self.paths) as repo: repo.start_session(state['project_id'],state['learning_event']['request_id'])
            return {}

        def teach(state):
            pid=state['project_id']
            with LearningRepository(self.paths) as repo:
                p=repo.get_project(pid);s=repo.session(pid)
                node=repo.node(pid,s['review_node_id'] if s['mode']=='review' else s['current_node_id'])
                if p['lifecycle']=='paused': raise ConflictError('Paused projects cannot invoke Tutor')
                profile=LearningProfile.model_validate(p['profile'])
                contexts=[] if profile.learning_mode=='exploration' else list(self._contexts(repo,pid,node,'teaching').values())
                history=repo.tutor_history(pid,node.node_id,exclude_request_id=s['tutor_request_id'])
                feedback,validate_reply=build_tutor_feedback(repo,pid,s)
            data={'profile':profile.model_dump(),'node':node.model_dump(),'mode':s['mode'],'question':s['question'],
                  'contexts':[c.payload for c in contexts],'history':history}
            if feedback is not None:data['remediation_feedback']=feedback.model_dump()
            result=self._task(pid,'tutor:'+s['tutor_request_id'],data,tutor.TutorReply,
                lambda model,budget:tutor.generate_tutor_reply(profile=profile,node=node,mode=s['mode'],contexts=contexts,
                    history=history,question=s['question'],llm=model,budget=budget,feedback=feedback,validate_public_reply=validate_reply))
            with LearningRepository(self.paths) as repo: repo.save_tutor(pid,node.node_id,s['tutor_request_id'],s['question'],result)
            return {}

        def prepare_wait(state):
            pid=state['project_id']
            with LearningRepository(self.paths) as repo:
                p=repo.get_project(pid);s=repo.session(pid)
                token=pid+state['learning_event']['request_id']+p['lifecycle']+str(s['current_assessment_id'])
                with repo.transaction(): repo.mark(pid,p['lifecycle'],pending_input_id='input_'+uuid5(NAMESPACE_URL,token).hex,error_type=p['error_type'])
            return {}

        def wait(state):
            with LearningRepository(self.paths) as repo: p=repo.get_project(state['project_id'])
            return {'learning_event':interrupt({'kind':p['lifecycle'],'pending_input_id':p['pending_input_id']})}

        def handle(state):
            pid=state['project_id'];e=state['learning_event'];a=e['action']
            routes={'ask':'teach','start_quiz':'prepare_assessment','submit_answer':'grade',
                    'return_to_current':'teach','return_to_teaching':'teach','replace_assessment':'prepare_assessment',
                    'retry_3':'extend_rounds','annotate_dispute':'prepare_wait','view_feedback':'prepare_wait'}
            with LearningRepository(self.paths) as repo:
                with repo.transaction():
                    prior=repo.conn.execute('SELECT fingerprint FROM learning_commands WHERE project_id=? AND request_id=?',(pid,e['request_id'])).fetchone()
                    if prior:
                        if prior[0]!=fingerprint(e): raise ConflictError('Learning request changed')
                        return {'next_step':routes[a]}
                    s=repo.session(pid);p=repo.get_project(pid)
                    old=repo.get_assessment(pid,s['current_assessment_id']) if s['current_assessment_id'] else None
                    unfinished=old and (old['status'] in ('needs_review','invalid_item','submitted') or
                        (old['status']=='graded' and not repo.conn.execute('SELECT 1 FROM learning_transitions WHERE project_id=? AND assessment_id=?',(pid,old['id'])).fetchone()))
                    if a=='submit_answer': repo.save_answers_in_transaction(pid,e['assessment_id'],e['answers'])
                    elif a=='annotate_dispute': repo.conn.execute('INSERT INTO assessment_annotations VALUES (?,?,?,?,?)',(pid,e['assessment_id'],e['request_id'],e['annotation'],now()))
                    elif a=='replace_assessment' or (a=='start_quiz' and unfinished):
                        rounds=repo.rounds(pid,s['current_node_id']);policy=EvaluationPolicy.model_validate(p['policy'])
                        if rounds['replacements']>=policy.max_replacements: raise ConflictError('Replacement limit reached')
                        repo.conn.execute('UPDATE node_runtime SET replacements=replacements+1 WHERE project_id=? AND node_id=?',(pid,s['current_node_id']))
                        repo.change_session(pid,next_previous_assessment_id=s['current_assessment_id'])
                    elif a in ('ask','return_to_teaching','return_to_current'):
                        repo.change_session(pid,question=e.get('question'),tutor_request_id=e['request_id'],
                                            mode='exploration' if p['profile']['learning_mode']=='exploration' else
                                                 (s['mode'] if a=='ask' and s['mode'] in ('review','remediate') else 'qa' if a=='ask' else 'normal'),
                                            review_node_id=s['review_node_id'] if a=='ask' else None,pause_reason=None)
                        repo.mark(pid,'exploring' if p['profile']['learning_mode']=='exploration' else 'learning')
                    repo.conn.execute('INSERT INTO learning_commands VALUES (?,?,?,?)',(pid,e['request_id'],fingerprint(e),encode(e)))
            return {'next_step':routes[a]}

        def prepare_assessment(state):
            pid=state['project_id'];e=state['learning_event']
            with LearningRepository(self.paths) as repo:
                s=repo.session(pid);p=repo.get_project(pid);rounds=repo.rounds(pid,s['current_node_id'])
                if p['profile']['learning_mode']!='formal' or p['lifecycle']=='paused': raise ConflictError('Formal assessment unavailable')
                if rounds['effective_rounds']>=rounds['round_limit']: raise ConflictError('Round limit reached')
                # Stable previous identity survives the commit before the Graph checkpoint.
                existing=repo.conn.execute('SELECT * FROM assessments WHERE project_id=? AND prepare_request_id=?',(pid,e['request_id'])).fetchone()
                current=repo.get_assessment(pid,s['current_assessment_id']) if s['current_assessment_id'] else None
                if current and current['status'] in ('prepared','awaiting_answer') and e['action']!='replace_assessment':
                    row=current
                else:
                    previous=existing['previous_assessment_id'] if existing else s['current_assessment_id']
                    row=repo.prepare_assessment(pid,s['current_node_id'],request_id=e['request_id'],previous_assessment_id=previous)
                with repo.transaction():
                    repo.change_session(pid,current_assessment_id=row['id'],next_previous_assessment_id=None)
                    repo.mark(pid,'running')
            return {'assessment_id':row['id']}

        def generate_quiz(state):
            pid=state['project_id']
            with LearningRepository(self.paths) as repo:
                p=repo.get_project(pid);s=repo.session(pid);row=repo.get_assessment(pid,s['current_assessment_id'])
                if row['quiz_json']:
                    with repo.transaction(): repo.mark(pid,'quiz')
                    return {}
                node=repo.node(pid);policy=EvaluationPolicy.model_validate(p['policy']);snapshot=FrozenSnapshot.model_validate(p['frozen_snapshot'])
                contexts=self._contexts(repo,pid,node,'assessment')
                previous=[]
                for old in repo.conn.execute('SELECT quiz_json FROM assessments WHERE project_id=? AND node_id=? AND id<>? AND quiz_json IS NOT NULL ORDER BY created_at DESC,id LIMIT 3',(pid,node.node_id,row['id'])):
                    previous.extend(q['prompt'] for q in json.loads(old[0])['questions'])
            data={'assessment_id':row['id'],'snapshot':snapshot.model_dump(),'node':node.model_dump(),'policy':policy.model_dump(),'previous':previous}
            quiz=self._task(pid,'quiz:'+row['id'],data,AssessmentQuiz,
                lambda model,budget:assessment.generate_quiz(project_id=pid,node=node,assessment_id=row['id'],snapshot=snapshot,
                    policy=policy,contexts=contexts,previous_assessment_id=row['previous_assessment_id'],previous_question_prompts=previous,llm=model,budget=budget))
            assessment.validate_quiz(quiz,node=node,policy=policy,contexts=contexts,previous_question_prompts=previous)
            with LearningRepository(self.paths) as repo: repo.save_quiz(pid,quiz)
            return {}

        def grade(state):
            pid=state['project_id']
            with LearningRepository(self.paths) as repo:
                p=repo.get_project(pid);s=repo.session(pid);row=repo.get_assessment(pid,s['current_assessment_id']);node=repo.node(pid)
                if row['evaluation_json']:
                    status=json.loads(row['evaluation_json'])['grading_status']
                else:
                    status=None;quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json']));answers=json.loads(row['answers_json'])
                    policy=EvaluationPolicy.model_validate(p['policy']);contexts=self._contexts(repo,pid,node,'grading')
            if status is None:
                data={'quiz':quiz.model_dump(),'answers':answers,'policy':policy.model_dump()}
                result=self._task(pid,'grade:'+row['id'],data,EvaluationResult,
                    lambda model,budget:assessment.evaluate_quiz(quiz=quiz,answers=answers,policy=policy,node=node,contexts=contexts,llm=model,budget=budget))
                with LearningRepository(self.paths) as repo: repo.save_evaluation(pid,result)
                status=result.grading_status
            if status!='graded':
                with LearningRepository(self.paths) as repo: repo.show_review(pid,reason=status)
            return {'next_step':'diagnose' if status=='graded' else 'prepare_wait'}

        def diagnose(state):
            pid=state['project_id']
            with LearningRepository(self.paths) as repo:
                p=repo.get_project(pid);s=repo.session(pid);row=repo.get_assessment(pid,s['current_assessment_id']);node=repo.node(pid)
                if row['diagnosis_json']: return {}
                quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json']));result=EvaluationResult.model_validate(json.loads(row['evaluation_json']))
                policy=EvaluationPolicy.model_validate(p['policy']);history=repo.history(pid,node,exclude_assessment_id=row['id']);done=repo.completed(pid)
            data={'quiz':quiz.model_dump(),'evaluation':result.model_dump(),'history':history,'completed':done}
            decision=self._task(pid,'diagnosis:'+row['id'],data,diagnosis.DiagnosisDecision,
                lambda model,budget:diagnosis.diagnose(quiz=quiz,evaluation=result,node=node,policy=policy,history=history,completed_node_ids=done,llm=model,budget=budget))
            with LearningRepository(self.paths) as repo: repo.save_diagnosis(pid,row['id'],decision)
            return {}

        def advance(state):
            pid=state['project_id']
            with LearningRepository(self.paths) as repo: result=repo.apply_transition(pid,state['assessment_id'])
            return {'next_step':'prepare_wait' if result['next_step']=='wait' else result['next_step']}

        def extend_rounds(state):
            with LearningRepository(self.paths) as repo: repo.extend_rounds(state['project_id'])
            return {}

        graph=StateGraph(LearningState)
        nodes={'initialize':initialize,'teach':teach,'prepare_wait':prepare_wait,'wait':wait,'handle':handle,
               'prepare_assessment':prepare_assessment,'generate_quiz':generate_quiz,'grade':grade,
               'diagnose':diagnose,'advance':advance,'extend_rounds':extend_rounds,'completed':lambda state:{}}
        def observe(fn):
            wrapped=observed_node(fn)
            def invoke(state):
                with LearningRepository(self.paths) as repo: session=repo.session(state['project_id'])
                return wrapped({**state,'current_node_id':session['current_node_id'] if session else None,
                                'assessment_id':state.get('assessment_id') or (session['current_assessment_id'] if session else None)})
            return invoke
        for name,fn in nodes.items(): graph.add_node(name,observe(fn))
        for first,last in [(START,'initialize'),('initialize','teach'),('teach','prepare_wait'),('prepare_wait','wait'),
                           ('wait','handle'),('prepare_assessment','generate_quiz'),('generate_quiz','prepare_wait'),
                           ('diagnose','advance'),('extend_rounds','prepare_wait'),('completed',END)]: graph.add_edge(first,last)
        graph.add_conditional_edges('handle',lambda s:s['next_step'])
        graph.add_conditional_edges('grade',lambda s:s['next_step'])
        graph.add_conditional_edges('advance',lambda s:s['next_step'])
        return graph
