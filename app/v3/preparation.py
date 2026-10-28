"""Day10 persisted preparation Graph. No Tutor, grading or unlock runs here."""
from contextlib import contextmanager
from hashlib import sha256
import json
from uuid import uuid4

from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt

from . import planner
from .capabilities import check_capabilities, get_capability
from .config import DB_SCHEMA_VERSION, GRAPH_VERSION, CONTRACT_VERSION
from .config import SERVER_LIMITS
from .contracts import LearningProfile, LearningPlan, EvaluationPolicy, ObjectivePolicy, PublicSource, SourceDocument
from .materials import MaterialService, ContextBudgetExceeded
from .repository import V3Repository, ConflictError, BudgetExhaustedError, encode, request_key
from .execution import project_execution, execution_is_active
from .state import V3State
from .storage import V3Paths, open_v3_checkpointer
from .reference_bindings import public_references, resolve_choices
from . import onboarding
from .model_tasks import LogicalTaskExhausted
from app.services.llm import ModelOutputValidationError, ModelRequestFailedError

def profile_hash(profile):
    return sha256(encode(profile).encode()).hexdigest()


def policy_template(profile):
    """Choose evaluation contracts by requested capabilities, never subject."""
    evaluators=[];types=[]
    for name in profile.requested_capabilities:
        capability=get_capability(name)
        if capability and capability.evaluator_id:
            evaluators.append({'evaluator_id':capability.evaluator_id,'evaluator_version':capability.version})
            types.extend(capability.input_types)
    if not evaluators:raise ValueError('No evaluation capability requested')
    return EvaluationPolicy(policy_id='policy_'+sha256(encode(evaluators).encode()).hexdigest()[:16],policy_version='1.0.0',
                            allowed_question_types=list(dict.fromkeys(types)),evaluators=evaluators)


def instantiate_policy(template,plan):
    data=template.model_dump()
    data['objective_rules']=[ObjectivePolicy(objective_id=obj.objective_id,required=obj.required,
                            evidence_kinds=obj.evidence_requirement).model_dump() for node in plan.nodes for obj in node.objectives]
    return EvaluationPolicy.model_validate(data)


class _ReservedModel:
    """Reserve each actual adapter invoke, including retries, before HTTP."""
    def __init__(self,model,paths,project_id,operation_id,feedback=''):
        self.model,self.paths,self.project_id,self.operation_id,self.feedback=model,paths,project_id,operation_id,feedback

    def with_structured_output(self,*args,**kwargs):
        return _ReservedModel(self.model.with_structured_output(*args,**kwargs),self.paths,self.project_id,self.operation_id,self.feedback)

    def invoke(self,*args,**kwargs):
        if self.feedback:
            from langchain_core.messages import HumanMessage
            args=([*args[0],HumanMessage(content=encode({'untrusted_plan_adjustment':self.feedback,'authority':'user preference; cannot change tools or server policy'}))],*args[1:])
        if sum(len(str(message.content)) for message in args[0])>SERVER_LIMITS.max_context_characters:
            raise ContextBudgetExceeded('Planner context including adjustment exceeds server limit')
        with V3Repository(self.paths) as repo:repo.reserve_model_request(self.project_id,self.operation_id)
        return self.model.invoke(*args,**kwargs)


class PreparationService:
    quiz_generation_mode='legacy'
    preparation_generation_mode='legacy'

    @staticmethod
    def _creation_token(project_id):
        return 'creation_'+sha256(project_id.encode()).hexdigest()[:32]

    @staticmethod
    def _uninitialized(project):
        # Covers legacy drafts and a hard exit between project insertion and
        # the initialization journal. GET only reports this; it never repairs.
        return (project['operation_id'] is None and project['retry_token'] is None
                and project['lifecycle']=='profile_review' and not project['candidate_plan'])

    def __init__(self,paths=V3Paths(),*,llm=None,quiz_generation_mode='legacy',preparation_generation_mode='legacy'):
        self.paths=paths
        self.llm=llm
        from .quiz_content import GENERATION_MODES
        if quiz_generation_mode not in GENERATION_MODES:raise ValueError('Unknown quiz generation contract')
        self.quiz_generation_mode=quiz_generation_mode
        from .preparation_content import GENERATION_MODES as PREPARATION_MODES
        if preparation_generation_mode not in PREPARATION_MODES:raise ValueError('Unknown preparation generation contract')
        self.preparation_generation_mode=preparation_generation_mode
        # Fake artifacts are never a live-service runtime or an evaluator grant.
        with V3Repository(paths) as repo:
            marker=repo.conn.execute("SELECT value FROM runtime_metadata WHERE key='demo_only'").fetchone()
            if marker:raise ValueError('Fake contract stores cannot be opened by the real service')

    def _mark(self,repo,project_id,**fields):
        allowed={'lifecycle','pending_input_id','profile_confirmation_hash','planning_feedback','capability_json',
                 'operation_id','retry_token','error_type','last_confirmation_id'}
        if not fields.keys()<=allowed:raise ValueError('Unknown server field')
        with repo.transaction():
            repo.conn.execute('UPDATE learning_projects SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),project_id))

    def read(self,project_id):
        """Authoritative projection: upload invalidation is visible without Graph."""
        with V3Repository(self.paths) as repo:
            project=repo.get_project(project_id)
            if project is None:raise KeyError(project_id)
            guided=onboarding.metadata(repo,project_id)
            stage=project['lifecycle'];stale=project['requires_replan']
            pending=repo.conn.execute('SELECT 1 FROM preparation_execution WHERE project_id=?',(project_id,)).fetchone()
            uninitialized=self._uninitialized(project)
            active=bool((pending or uninitialized) and execution_is_active(self.paths,project_id))
            recovery_required=bool((pending or uninitialized) and not active)
            if pending or uninitialized:stage='running' if active else 'error'
            actions={'profile_review':['confirm_profile','update_profile','import_material','rest'],
                     'materials_required':['import_material','adjust_scope','rest'],
                     'plan_review':['confirm_plan','adjust_plan','import_material','replan','rest'],
                     'error':['retry','rest'],'budget_exhausted':['continue_with_new_budget','rest']}.get(stage,[])
            capability=json.loads(project['capability_json']) if project.get('capability_json') else None
            if stage=='materials_required':
                if guided or project['profile_confirmation_hash']==profile_hash(project['profile']):actions.append('replan')
                if capability and capability['status']=='exploration_only':actions.append('choose_exploration')
            if stale:actions=[a for a in actions if a!='confirm_plan']
            if stage in ('error','budget_exhausted') and not project['pending_input_id']:
                actions=[a for a in actions if a!='rest']
            latest={}
            for source in repo.list_sources(project_id,include_private=True):latest[source['source_id']]=source
            sources=[PublicSource.from_document(SourceDocument.model_validate(d)).model_dump()
                     for d in latest.values() if d['visibility']=='teaching']
            return {'project_id':project['id'],'thread_id':project['thread_id'],'profile':project['profile'],
                    'guided':bool(guided),'learning_basis':guided['basis'] if guided else None,
                    'preparation_notice':guided['message'] if guided else None,
                    'page_state':stage,'allowed_actions':actions,'pending_input_id':project['pending_input_id'],
                    'draft_revision':project['draft_revision'],'requires_replan':stale,
                    'plan':project['candidate_plan'],'policy':json.loads(project['candidate_policy_json']) if project.get('candidate_policy_json') else None,
                    'sources':sources,'capability_check':capability,'frozen':bool(project['frozen_snapshot']),
                    'private_references':public_references(repo,project_id) if not project['frozen_snapshot'] else [],
                    'retry_token':project['retry_token'] or (self._creation_token(project_id) if uninitialized else None),
                    'error_type':'ExecutionInterrupted' if recovery_required else project['error_type'],
                    'execution_status':'active' if active else 'interrupted' if recovery_required else 'idle',
                    'recovery_required':recovery_required,
                    'db_schema_version':DB_SCHEMA_VERSION,'graph_version':project['graph_version'],'contract_version':CONTRACT_VERSION,
                    'learning_runtime_ready':False}

    @contextmanager
    def _graph(self):
        with open_v3_checkpointer(self.paths) as saver:yield self._build_graph().compile(checkpointer=saver)

    @staticmethod
    def _config(project_id):
        return {'configurable':{'thread_id':project_id},'recursion_limit':30}

    def create(self,request_id,profile,*,guided_intent=None):
        with V3Repository(self.paths) as repo:project=repo.create_project(request_id,profile,guided_intent=guided_intent)
        project_id=project['id']
        with project_execution(project_id,self.paths),self._graph() as graph:
            snapshot=graph.get_state(self._config(project_id))
            with V3Repository(self.paths) as repo:
                pending=repo.conn.execute('SELECT event_json FROM preparation_execution WHERE project_id=?',(project_id,)).fetchone()
            event=json.loads(pending[0]) if pending else None
            creating=event and event['action']=='initialize_profile'
            initial_step=not snapshot.values or (snapshot.next and not snapshot.interrupts and
                not snapshot.values.get('preparation_event'))
            if creating or (not pending and initial_step):
                self._initialize_creation(project_id,graph)
        return self.read(project_id)

    def _initialize_creation(self,project_id,graph):
        with V3Repository(self.paths) as repo:
            project=repo.get_project(project_id)
            if project['graph_version']!=GRAPH_VERSION:raise ConflictError('Graph version mismatch')
            if project['candidate_plan'] or project['profile_confirmation_hash'] or project['frozen_snapshot']:
                raise ConflictError('Existing preparation facts require their matching checkpoint; cannot initialize again')
            event={'request_id':project['create_request_id'],'action':'initialize_profile'}
            # Initialization has no HTTP/model operation. Its stable recovery
            # token and journal commit together before any Graph checkpoint.
            with repo.transaction():
                repo.conn.execute('UPDATE learning_projects SET lifecycle=\'profile_review\',error_type=NULL,retry_token=? WHERE id=?',
                                  (self._creation_token(project_id),project_id))
                repo.conn.execute('INSERT OR REPLACE INTO preparation_execution VALUES (?,?,NULL)',(project_id,encode(event)))
        try:
            snapshot=graph.get_state(self._config(project_id))
            if not snapshot.values:
                graph.invoke({'project_id':project_id,'thread_id':project_id,'db_schema_version':DB_SCHEMA_VERSION,
                    'graph_version':GRAPH_VERSION,'contract_version':CONTRACT_VERSION,'preparation_event':event},
                    self._config(project_id),durability='sync')
            elif not snapshot.interrupts and snapshot.next:
                graph.invoke(None,self._config(project_id),durability='sync')
        except Exception as exc:self._record_failure(project_id,exc)
        self._finish_execution(project_id)

    def resume(self,project_id,event):
        # Rest never changes a fact or advances the checkpoint. In particular,
        # it cannot leave an ownerless execution marker if the process exits.
        if event['action']=='rest':
            view=self.read(project_id)
            if event.get('pending_input_id')!=view['pending_input_id'] or event.get('draft_revision')!=view['draft_revision']:
                raise ConflictError('Stale rest input')
            if 'rest' not in view['allowed_actions']:raise ValueError('Rest not allowed')
            return view
        with project_execution(project_id,self.paths):
            view=self.read(project_id)
            # A repeated accepted command is a read, even after its input has
            # advanced. Reusing its identity with changed data remains a conflict.
            with V3Repository(self.paths) as repo:
                accepted=repo.conn.execute('SELECT fingerprint FROM preparation_inputs WHERE project_id=? AND request_id=?',
                                          (project_id,event['request_id'])).fetchone()
            if accepted:
                if accepted[0]!=profile_hash(event):raise ConflictError('Preparation request changed')
                return view
            if event.get('pending_input_id')!=view['pending_input_id']:raise ConflictError('Stale pending_input_id')
            if event.get('draft_revision')!=view['draft_revision'] or (event['action']=='confirm_plan' and view['requires_replan']):
                raise ConflictError('Draft changed; requires_replan')
            if event['action'] not in view['allowed_actions'] or event['action'] in {'import_material','retry','continue_with_new_budget'}:
                raise ValueError('Action not allowed by this resume entry')
            # Reject correctable user errors before persisting a Graph command;
            # technical retry must never replay an invalid user payload forever.
            if event['action']=='confirm_profile' and not view['profile']['bounded_goal'] and not view['guided']:
                raise ValueError('Confirm a bounded learning goal first')
            if event.get('private_references') is not None and event['action']!='confirm_plan':
                raise ValueError('Reference choices require plan confirmation')
            if event['action']=='confirm_plan':
                with V3Repository(self.paths) as repo:
                    project=repo.get_project(project_id)
                    resolve_choices(repo,project_id,project['candidate_plan'],event.get('private_references'),quiz_generation_mode=self.quiz_generation_mode)
            if event['action'] in ('update_profile','adjust_scope'):
                proposed=LearningProfile.model_validate(event['profile'])
                if proposed.profile_version!=view['profile']['profile_version'] or proposed.prior_knowledge.assessed_evidence:
                    raise ValueError('Cannot mint version or evidence')
            if event['action']=='rest' and view['page_state'] in ('error','budget_exhausted'):return view
            with self._graph() as graph:
                if not graph.get_state(self._config(project_id)).interrupts:raise ConflictError('Not waiting for user input')
                if event['action']!='rest':
                    with V3Repository(self.paths) as repo:
                        op=repo.create_operation(project_id,event['request_id'],kind=event['action'])
                        self._mark(repo,project_id,operation_id=op['operation_id'],retry_token=op['retry_token'],error_type=None)
                with V3Repository(self.paths) as repo:
                    with repo.transaction():
                        repo.conn.execute('INSERT INTO preparation_execution VALUES (?,?,NULL)',(project_id,encode(event)))
                try:graph.invoke(Command(resume=event),self._config(project_id),durability='sync')
                except Exception as exc:
                    self._record_failure(project_id,exc)
                self._finish_execution(project_id)
            return self.read(project_id)

    def retry(self,project_id,*,retry_token,request_id,continue_budget=False):
        key=request_key(request_id)
        fingerprint=profile_hash({'retry_token':retry_token,'continue_budget':continue_budget})
        # Safe even while another process owns the execution lock: a duplicate
        # command only reads state. It never resumes the same execution twice.
        if self._retry_replayed(project_id,key,fingerprint):return self.read(project_id)
        with project_execution(project_id,self.paths),V3Repository(self.paths) as repo:
            if self._retry_replayed(project_id,key,fingerprint):return self.read(project_id)
            project=repo.get_project(project_id)
            expected_token=(project['retry_token'] or self._creation_token(project_id)) if project else None
            if not project or retry_token!=expected_token:raise ConflictError('Stale retry_token')
            with self._graph() as graph:
                snapshot=graph.get_state(self._config(project_id))
                pending=repo.conn.execute('SELECT * FROM preparation_execution WHERE project_id=?',(project_id,)).fetchone()
                creating=(pending and json.loads(pending['event_json'])['action']=='initialize_profile') or self._uninitialized(project) or (
                    project['operation_id'] is None and project['lifecycle']=='error')
                if creating:
                    if continue_budget:raise ConflictError('Initialization does not require model budget')
                    payload={'request_id':key,'retry_token':retry_token,'continue_budget':False,'parent_operation_id':None}
                    with repo.transaction():
                        repo.conn.execute('INSERT INTO preparation_retries VALUES (?,?,?,?)',(project_id,key,fingerprint,encode(payload)))
                    self._initialize_creation(project_id,graph)
                    return self.read(project_id)
                if continue_budget:
                    if pending or project['lifecycle']!='budget_exhausted':raise ConflictError('Wrong continuation route')
                    old=repo.get_operation(project_id,project['operation_id'])
                    if old['parent_operation_id'] or repo.conn.execute('SELECT 1 FROM model_operations WHERE parent_operation_id=?',(old['operation_id'],)).fetchone():
                        raise ConflictError('Budget already extended')
                elif not pending and project['lifecycle']!='error':raise ConflictError('Wrong retry route')
                if not pending and (snapshot.interrupts or not snapshot.next):raise ConflictError('No failed step to retry')
                event=json.loads(pending['event_json']) if pending else snapshot.values.get('preparation_event')
                if not event:raise ConflictError('No persisted command to recover')
                payload={'request_id':key,'retry_token':retry_token,'continue_budget':continue_budget,
                         'parent_operation_id':project['operation_id'] if continue_budget else None}
                # Journal the retry and unfinished execution BEFORE any Graph or
                # continuation mutation. Hard exit leaves a recoverable marker.
                with repo.transaction():
                    repo.conn.execute('INSERT INTO preparation_retries VALUES (?,?,?,?)',(project_id,key,fingerprint,encode(payload)))
                    if not pending:
                        repo.conn.execute('INSERT INTO preparation_execution VALUES (?,?,?)',(project_id,encode(event),key))
                try:
                    if pending and pending['retry_request_id']:
                        self._ensure_continuation(repo,project_id,pending['retry_request_id'])
                    if continue_budget:self._ensure_continuation(repo,project_id,key)
                    if snapshot.interrupts:
                        # Crash before Command checkpoint: submit the saved input.
                        # Crash after wait checkpoint: the command is already done.
                        previous=snapshot.values.get('preparation_event') or {}
                        if previous.get('request_id')!=event['request_id']:
                            graph.invoke(Command(resume=event),self._config(project_id),durability='sync')
                    elif snapshot.next:
                        graph.invoke(None,self._config(project_id),durability='sync')
                except Exception as exc:self._record_failure(project_id,exc)
                self._finish_execution(project_id)
            return self.read(project_id)

    def _retry_replayed(self,project_id,key,fingerprint):
        with V3Repository(self.paths) as repo:
            prior=repo.conn.execute('SELECT fingerprint FROM preparation_retries WHERE project_id=? AND request_id=?',(project_id,key)).fetchone()
        if prior and prior[0]!=fingerprint:raise ConflictError('Retry request changed')
        return bool(prior)

    def _ensure_continuation(self,repo,project_id,key):
        row=repo.conn.execute('SELECT payload_json FROM preparation_retries WHERE project_id=? AND request_id=?',(project_id,key)).fetchone()
        payload=json.loads(row[0])
        if not payload['continue_budget']:return
        parent=repo.get_operation(project_id,payload['parent_operation_id'])
        child=repo.create_operation(project_id,payload['request_id'],kind=parent['kind'],
                                    parent_operation_id=parent['operation_id'],retry_token=payload['retry_token'])
        self._mark(repo,project_id,operation_id=child['operation_id'],retry_token=child['retry_token'])

    def _finish_execution(self,project_id):
        with V3Repository(self.paths) as repo:
            with repo.transaction():repo.conn.execute('DELETE FROM preparation_execution WHERE project_id=?',(project_id,))

    def _record_failure(self,project_id,exc):
        with V3Repository(self.paths) as repo:
            self._mark(repo,project_id,lifecycle='budget_exhausted' if isinstance(exc,BudgetExhaustedError) else 'error',
                       error_type=type(exc).__name__)

    def _build_graph(self):
        def wait(state):
            with V3Repository(self.paths) as repo:project=repo.get_project(state['project_id'])
            event=interrupt({'kind':project['lifecycle'],'pending_input_id':project['pending_input_id']})
            return {'preparation_event':event}

        def handle(state):
            event=state['preparation_event'];pid=state['project_id'];action=event['action']
            if action=='rest':return {}
            with V3Repository(self.paths) as repo:
                with repo.transaction():
                    fingerprint=profile_hash(event)
                    prior=repo.conn.execute('SELECT fingerprint FROM preparation_inputs WHERE project_id=? AND request_id=?',(pid,event['request_id'])).fetchone()
                    if prior:
                        if prior[0]!=fingerprint:raise ConflictError('Preparation request changed')
                        # The input transaction committed but its Graph checkpoint
                        # may not have. Restore its waiting stage without applying
                        # the profile change or incrementing the revision again.
                        if action in ('update_profile','adjust_scope','choose_exploration'):
                            stage='exploring' if action=='choose_exploration' else 'profile_review'
                            repo.conn.execute('UPDATE learning_projects SET lifecycle=?,error_type=NULL WHERE id=?',(stage,pid))
                        return {}
                    p=repo._draft(pid,event['draft_revision'])
                    if p['pending_input_id']!=event['pending_input_id']:raise ConflictError('Stale input')
                    if action=='confirm_profile':
                        if not p['profile']['bounded_goal'] and not onboarding.metadata(repo,pid):raise ValueError('Confirm a bounded learning goal first')
                        repo.conn.execute('UPDATE learning_projects SET profile_confirmation_hash=? WHERE id=?',(profile_hash(p['profile']),pid))
                    elif action in ('update_profile','adjust_scope','choose_exploration'):
                        raw={**p['profile'],'learning_mode':'exploration'} if action=='choose_exploration' else event['profile']
                        profile=LearningProfile.model_validate(raw)
                        if profile.profile_version!=p['profile']['profile_version'] or profile.prior_knowledge.assessed_evidence:raise ValueError('Cannot mint version or evidence')
                        repo.conn.execute("UPDATE learning_projects SET profile_json=?,goal=?,draft_revision=draft_revision+1,profile_confirmation_hash=?,lifecycle=?,pending_input_id=? WHERE id=?",
                            (encode(profile),profile.goal,profile_hash(profile) if action=='choose_exploration' else None,
                             'exploring' if action=='choose_exploration' else 'profile_review',None if action=='choose_exploration' else 'profile_'+uuid4().hex,pid))
                    elif action in ('adjust_plan','replan'):
                        repo.conn.execute('UPDATE learning_projects SET planning_feedback=?,draft_revision=draft_revision+1 WHERE id=?',(event.get('feedback',p['planning_feedback']),pid))
                    repo.conn.execute('INSERT INTO preparation_inputs VALUES (?,?,?)',(pid,event['request_id'],fingerprint))
            return {}

        def plan_unchecked(state):
            pid=state['project_id']
            provider=getattr(self,'llm',None)
            with V3Repository(self.paths) as repo:guided=bool(onboarding.metadata(repo,pid))
            if guided and not onboarding.prepare(self.paths,pid,state['preparation_event'],
                    llm=provider if provider is not None else planner.get_llm,
                    generation_mode=self.preparation_generation_mode):return {}
            with V3Repository(self.paths) as repo:
                p=repo.get_project(pid);profile=LearningProfile.model_validate(p['profile'])
                if p['profile_confirmation_hash']!=profile_hash(profile):raise ConflictError('Profile not confirmed')
                catalog=onboarding.teaching_catalog(repo,pid) if guided else MaterialService(repo).catalog(pid)
                check=check_capabilities(profile,has_material=bool(catalog))
                if profile.learning_mode=='exploration':
                    self._mark(repo,pid,lifecycle='exploring',pending_input_id=None,capability_json=encode(check));return {}
                if check.status!='supported':
                    self._mark(repo,pid,lifecycle='materials_required',pending_input_id='materials_'+uuid4().hex,capability_json=encode(check));return {}
                self._mark(repo,pid,lifecycle='running',pending_input_id=None,capability_json=encode(check))
                policy=policy_template(profile);operation_id=p['operation_id']
                # If business save succeeded before a checkpoint crash, reuse it.
                if p['candidate_plan'] and not p['requires_replan'] and p.get('candidate_policy_json'):
                    self._mark(repo,pid,lifecycle='plan_review',pending_input_id=p['candidate_input_id'] or 'plan_'+uuid4().hex,error_type=None);return {}
                revision=p['draft_revision'];feedback=p['planning_feedback']
            # Feedback is bounded user data, cannot edit server policy or tools.
            material_catalog=catalog
            provider=getattr(self,'llm',None)
            model=None if guided else _ReservedModel(provider if provider is not None else planner.get_llm(),self.paths,pid,operation_id,feedback)
            if guided:
                from langchain_core.messages import HumanMessage
                # Adjustment remains untrusted preference; use the same durable
                # HTTP budget/cache as scope and generated notes.
                def generate(tracked,budget):
                    class Adjusted:
                        def with_structured_output(inner,*args,**kwargs):
                            bound=tracked.with_structured_output(*args,**kwargs)
                            class Bound:
                                def invoke(inner,messages):
                                    if feedback:messages=[*messages,HumanMessage(content=encode({'untrusted_plan_adjustment':feedback}))]
                                    return bound.invoke(messages)
                            return Bound()
                    return planner.generate_plan(profile,pid,revision,material_catalog,policy,llm=Adjusted(),budget=budget)
                proposal=onboarding.run_preparation_task(self.paths,pid,operation_id,'guided_plan:'+state['preparation_event']['request_id'],
                    {'profile':profile.model_dump(),'catalog':material_catalog,'policy':policy.model_dump(),'revision':revision,'feedback':feedback},
                    LearningPlan,generate,llm=provider if provider is not None else planner.get_llm)
            else:proposal=planner.generate_plan(profile,pid,revision,material_catalog,policy,llm=model)
            frozen_policy=instantiate_policy(policy,proposal)
            with V3Repository(self.paths) as repo:
                repo.save_candidate_plan(pid,proposal,expected_revision=revision,policy=frozen_policy)
            return {'operation_id':operation_id,'draft_revision':revision}

        def plan(state):
            try:return plan_unchecked(state)
            except ContextBudgetExceeded:
                with V3Repository(self.paths) as repo:
                    self._mark(repo,state['project_id'],lifecycle='materials_required',pending_input_id='materials_'+uuid4().hex,
                               error_type='ContextBudgetExceeded')
                return {}
            except (ModelOutputValidationError,ModelRequestFailedError,LogicalTaskExhausted) as exc:
                with V3Repository(self.paths) as repo:
                    if not onboarding.metadata(repo,state['project_id']):raise
                    # A terminal logical task cannot be repaired by ordinary
                    # retry. Return to an editable wait; a new explicit prepare
                    # command owns a new task, while old charges stay recorded.
                    with repo.transaction():
                        repo.conn.execute('UPDATE guided_projects SET message=? WHERE project_id=?',
                            ('这次 AI 准备没有完成，未确认任何计划。可检查模型服务后重新整理，或修改目标；已用请求不会清零。',state['project_id']))
                        repo.conn.execute("UPDATE learning_projects SET lifecycle='profile_review',pending_input_id=?,error_type=? WHERE id=?",
                            ('profile_'+uuid4().hex,type(exc).__name__,state['project_id']))
                return {}

        def freeze(state):
            event=state['preparation_event'];pid=state['project_id']
            with V3Repository(self.paths) as repo:
                p=repo.get_project(pid)
                if p['frozen_snapshot']:
                    if p['last_confirmation_id']!=event['pending_input_id']:raise ConflictError('Different confirmation identity')
                    self._mark(repo,pid,lifecycle='learning',pending_input_id=None,error_type=None)
                    return {}
                if p['profile_confirmation_hash']!=profile_hash(p['profile']):raise ConflictError('Profile not confirmed')
                policy=EvaluationPolicy.model_validate(json.loads(p['candidate_policy_json']))
                planner.validate_learnability(p['candidate_plan'],p['profile'],onboarding.teaching_catalog(repo,pid) if onboarding.metadata(repo,pid) else MaterialService(repo).catalog(pid),policy)
                # Old accepted commands retain their pre-extension semantics.
                # New submissions validate explicit choices before journaling.
                links=resolve_choices(repo,pid,p['candidate_plan'],event['private_references'],quiz_generation_mode=self.quiz_generation_mode) if 'private_references' in event else []
                repo.freeze_plan(pid,policy,expected_revision=event['draft_revision'],pending_input_id=event['pending_input_id'],material_links=links,
                    quiz_generation_mode=self.quiz_generation_mode)
            return {}

        def route(state):
            action=state['preparation_event']['action']
            if action=='confirm_plan':return 'freeze'
            if action in ('confirm_profile','replan','adjust_plan'):return 'plan'
            if action=='choose_exploration':return END
            return 'wait'

        def after_plan(state):
            with V3Repository(self.paths) as repo:stage=repo.get_project(state['project_id'])['lifecycle']
            return END if stage=='exploring' else 'wait'

        graph=StateGraph(V3State)
        graph.add_node('wait',wait);graph.add_node('handle',handle);graph.add_node('plan',plan);graph.add_node('freeze',freeze)
        graph.add_edge(START,'wait');graph.add_edge('wait','handle')
        graph.add_conditional_edges('handle',route);graph.add_conditional_edges('plan',after_plan)
        graph.add_edge('freeze',END)
        return graph
