"""Learning facts and atomic completions on the existing V3 repository."""
import json
from uuid import uuid4

from .contracts import AssessmentQuiz,EvaluationResult,LearningProfile,LearningPlan,SkillNode,EvaluationPolicy,validate_evaluation_context
from .repository import V3Repository,ConflictError,encode,now,request_key


class LearningRepository(V3Repository):
    def session(self,project_id):
        row=self.conn.execute('SELECT * FROM learning_sessions WHERE project_id=?',(project_id,)).fetchone()
        return dict(row) if row else None

    def completed(self,project_id):return [r['node_id'] for r in self.get_progress(project_id) if r['completed_at']]

    def node(self,project_id,node_id=None):
        p=self.get_project(project_id);profile=LearningProfile.model_validate(p['profile'])
        if profile.learning_mode=='exploration':
            return SkillNode(node_id='exploration_node',title=profile.topic,description=profile.goal,estimated_minutes=profile.session_minutes,
                objectives=[{'objective_id':'exploration_goal','observable_outcome':'探索并说明'+profile.goal,'required':False,
                    'required_capability_ids':['text_explanation'],'evidence_requirement':['text_excerpt']}])
        plan=LearningPlan.model_validate(p['candidate_plan'])
        wanted=node_id or self.session(project_id)['current_node_id']
        return next((n for n in plan.nodes if n.node_id==wanted),None)

    def ready_node(self,project_id):
        p=self.get_project(project_id);done=set(self.completed(project_id))
        return next((n for n in LearningPlan.model_validate(p['candidate_plan']).nodes
                     if n.node_id not in done and set(n.prerequisite_ids)<=done),None)

    def mark(self,project_id,stage,*,pending_input_id=None,error_type=None):
        self.conn.execute('UPDATE learning_projects SET lifecycle=?,pending_input_id=?,error_type=? WHERE id=?',
                          (stage,pending_input_id,error_type,project_id))

    def change_session(self,project_id,**fields):
        allowed={'current_node_id','current_assessment_id','mode','review_node_id','last_tutor_json','last_guard_json',
                 'pause_reason','question','tutor_request_id','next_previous_assessment_id'}
        if not fields or not fields.keys()<=allowed:raise ValueError('Unknown session field')
        self.conn.execute('UPDATE learning_sessions SET '+','.join(k+'=?' for k in fields)+' WHERE project_id=?',(*fields.values(),project_id))

    def start_session(self,project_id,request_id):
        with self.transaction():
            if self.session(project_id):return self.session(project_id)
            p=self.get_project(project_id)
            if not p:raise KeyError(project_id)
            profile=LearningProfile.model_validate(p['profile'])
            if profile.learning_mode=='formal' and not p['frozen_snapshot']:raise ConflictError('Confirm and freeze a plan before learning')
            if profile.learning_mode=='exploration' and p['lifecycle']!='exploring':raise ConflictError('Choose exploration explicitly first')
            node=self.ready_node(project_id) if profile.learning_mode=='formal' else self.node(project_id)
            if not node:raise ValueError('No learnable node')
            if profile.learning_mode=='formal':
                policy=EvaluationPolicy.model_validate(p['policy'])
                self.conn.executemany('INSERT OR IGNORE INTO node_runtime(project_id,node_id,round_limit) VALUES (?,?,?)',
                    ((project_id,n.node_id,policy.max_effective_rounds) for n in LearningPlan.model_validate(p['candidate_plan']).nodes))
                self.conn.execute('UPDATE learning_progress SET started_at=COALESCE(started_at,?) WHERE project_id=? AND node_id=?',(now(),project_id,node.node_id))
            self.conn.execute('INSERT INTO learning_sessions(project_id,current_node_id,tutor_request_id,mode) VALUES (?,?,?,?)',
                (project_id,node.node_id,request_id,'exploration' if profile.learning_mode=='exploration' else 'normal'))
            self.mark(project_id,'exploring' if profile.learning_mode=='exploration' else 'learning')
        return self.session(project_id)

    def rounds(self,project_id,node_id):
        row=self.conn.execute('SELECT * FROM node_runtime WHERE project_id=? AND node_id=?',(project_id,node_id)).fetchone()
        return dict(row) if row else None

    def tutor_history(self,project_id,node_id,*,exclude_request_id):
        result=[]
        for row in self.conn.execute('SELECT * FROM tutor_turns WHERE project_id=? AND node_id=? AND request_id<>? ORDER BY created_at,rowid',
                                     (project_id,node_id,exclude_request_id)):
            if row['question']:
                result.extend([{'role':'user','content':row['question'],'node_id':node_id},
                    {'role':'assistant','content':json.loads(row['reply_json'])['text'],'node_id':node_id}])
        return result[-12:]

    def save_tutor(self,project_id,node_id,request_id,question,reply):
        with self.transaction():
            prior=self.conn.execute('SELECT reply_json FROM tutor_turns WHERE project_id=? AND request_id=?',(project_id,request_id)).fetchone()
            if prior and prior[0]!=encode(reply):raise ConflictError('Tutor output is immutable')
            self.conn.execute('INSERT OR IGNORE INTO tutor_turns VALUES (?,?,?,?,?,?)',(project_id,node_id,request_id,question,encode(reply),now()))
            self.change_session(project_id,last_tutor_json=encode(reply))
            self.mark(project_id,'exploring' if self.get_project(project_id)['profile']['learning_mode']=='exploration' else 'learning')

    def save_quiz(self,project_id,quiz):
        quiz=AssessmentQuiz.model_validate(quiz)
        with self.transaction():
            p=self.get_project(project_id);row=self.get_assessment(project_id,quiz.assessment_id)
            if not row or quiz.project_id!=project_id or quiz.node_id!=row['node_id'] or encode(quiz.snapshot)!=row['snapshot_json']:
                raise ConflictError('Prepared assessment identity changed')
            if quiz.snapshot.model_dump()!=p['frozen_snapshot'] or quiz.previous_assessment_id!=row['previous_assessment_id']:
                raise ConflictError('Assessment snapshot changed')
            if row['quiz_json'] and row['quiz_json']!=encode(quiz):raise ConflictError('Quiz cannot be replaced in place')
            self.conn.execute("UPDATE assessments SET quiz_json=?,status='awaiting_answer' WHERE project_id=? AND id=? AND answers_json IS NULL",
                              (encode(quiz),project_id,quiz.assessment_id))
            self.mark(project_id,'quiz')

    def save_answers_in_transaction(self,project_id,assessment_id,answers):
        row=self.get_assessment(project_id,assessment_id)
        if not row or not row['quiz_json']:raise ConflictError('No frozen quiz')
        if row['answers_json'] and row['answers_json']!=encode(answers):raise ConflictError('Submitted answers are immutable')
        self.conn.execute("UPDATE assessments SET answers_json=?,status='submitted' WHERE project_id=? AND id=? AND answers_json IS NULL",
                          (encode(answers),project_id,assessment_id))

    def save_evaluation(self,project_id,evaluation):
        result=EvaluationResult.model_validate(evaluation)
        with self.transaction():
            row=self.get_assessment(project_id,result.assessment_id)
            if not row or not row['quiz_json'] or not row['answers_json']:raise ConflictError('No frozen submitted assessment')
            quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json']))
            validate_evaluation_context(result,quiz=quiz,answers=json.loads(row['answers_json']))
            if row['evaluation_json']:
                if row['evaluation_json']!=encode(result):raise ConflictError('Evaluation cannot be overwritten')
                return
            self.conn.execute('UPDATE assessments SET evaluation_json=?,status=? WHERE project_id=? AND id=?',
                              (encode(result),result.grading_status,project_id,result.assessment_id))

    def save_diagnosis(self,project_id,assessment_id,diagnosis):
        from .diagnosis import validate_diagnosis_context, _historical_entries
        with self.transaction():
            row=self.get_assessment(project_id,assessment_id)
            if not row or not row['evaluation_json'] or json.loads(row['evaluation_json'])['grading_status']!='graded':raise ConflictError('Diagnosis requires a valid evaluation')
            quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json']))
            evaluation=EvaluationResult.model_validate(json.loads(row['evaluation_json']))
            node=self.node(project_id,row['node_id'])
            history=_historical_entries(self.history(project_id,node,exclude_assessment_id=assessment_id),quiz=quiz,node=node)
            allowed={item.evidence_id for item in evaluation.evidence}
            allowed.update(fact['evidence_id'] for record in history for fact in record['evidence'])
            diagnosis=validate_diagnosis_context(diagnosis,quiz=quiz,evaluation=evaluation,node=node,valid_evidence_ids=allowed)
            if row['diagnosis_json'] and row['diagnosis_json']!=encode(diagnosis):raise ConflictError('Diagnosis cannot be overwritten')
            self.conn.execute('UPDATE assessments SET diagnosis_json=? WHERE project_id=? AND id=?',(encode(diagnosis),project_id,assessment_id))

    def history(self,project_id,node,*,exclude_assessment_id):
        allowed={node.node_id,*node.prerequisite_ids};result=[]
        for row in self.conn.execute('SELECT * FROM assessments WHERE project_id=? AND id<>? AND evaluation_json IS NOT NULL ORDER BY created_at,id',(project_id,exclude_assessment_id)):
            if row['node_id'] in allowed:
                result.append({'project_id':project_id,'node_id':row['node_id'],'assessment_id':row['id'],
                    'evaluation':json.loads(row['evaluation_json']),'answers':json.loads(row['answers_json'])})
        return result[-12:]

    def apply_transition(self,project_id,assessment_id):
        from .guard import decide_progress
        from .diagnosis import DiagnosisDecision
        with self.transaction():
            existing=self.conn.execute('SELECT result_json FROM learning_transitions WHERE project_id=? AND assessment_id=?',(project_id,assessment_id)).fetchone()
            if existing:return json.loads(existing[0])
            p=self.get_project(project_id);session=self.session(project_id);row=self.get_assessment(project_id,assessment_id)
            if not row or not row['evaluation_json'] or not row['diagnosis_json']:raise ConflictError('Incomplete assessment facts')
            if session['current_node_id']!=row['node_id']:raise ConflictError('Assessment is not current node')
            node=self.node(project_id,row['node_id']);policy=EvaluationPolicy.model_validate(p['policy'])
            guard=decide_progress(quiz=AssessmentQuiz.model_validate(json.loads(row['quiz_json'])),
                evaluation=EvaluationResult.model_validate(json.loads(row['evaluation_json'])),node=node,policy=policy,
                profile=LearningProfile.model_validate(p['profile']),completed_node_ids=self.completed(project_id),
                diagnosis=DiagnosisDecision.model_validate(json.loads(row['diagnosis_json'])),answers=json.loads(row['answers_json']))
            # Count only a complete valid evaluation/diagnosis/guard decision.
            # A technical failure after scoring still has no student outcome.
            self.conn.execute('UPDATE node_runtime SET effective_rounds=effective_rounds+1,replacements=0 WHERE project_id=? AND node_id=?',
                              (project_id,row['node_id']))
            self.change_session(project_id,last_guard_json=encode(guard),pause_reason=None)
            rounds=self.rounds(project_id,node.node_id)
            # Completion precedes the failed-round limit, including round three.
            if guard.passed:
                self.conn.execute('UPDATE learning_progress SET completed_at=COALESCE(completed_at,?),completion_assessment_id=COALESCE(completion_assessment_id,?),pass_policy_json=?,pass_basis_json=? WHERE project_id=? AND node_id=?',
                    (now(),assessment_id,encode(policy),encode(guard),project_id,node.node_id))
                next_node=self.ready_node(project_id)
                self.change_session(project_id,current_node_id=next_node.node_id if next_node else None,current_assessment_id=None,
                                    mode='normal',review_node_id=None,question=None,tutor_request_id='after_'+assessment_id)
                if next_node:
                    self.conn.execute('UPDATE learning_progress SET started_at=COALESCE(started_at,?) WHERE project_id=? AND node_id=?',(now(),project_id,next_node.node_id))
                self.mark(project_id,'learning' if next_node else 'completed')
                route='teach' if next_node else 'completed'
            elif rounds['effective_rounds']>=rounds['round_limit']:
                self.mark(project_id,'paused');self.change_session(project_id,pause_reason='round_limit');route='wait'
            else:
                diagnosis=json.loads(row['diagnosis_json'])
                self.change_session(project_id,mode='review' if guard.effective_action=='revisit_prerequisite' else 'remediate',
                    review_node_id=diagnosis.get('review_node_id') if guard.effective_action=='revisit_prerequisite' else None,
                    question=None,tutor_request_id='after_'+assessment_id)
                self.mark(project_id,'learning');route='teach'
            result={'next_step':route,'guard':guard.model_dump()}
            self.conn.execute('INSERT INTO learning_transitions VALUES (?,?,?)',(project_id,assessment_id,encode(result)))
        return result

    def show_review(self,project_id,*,reason=None):
        with self.transaction():
            s=self.session(project_id);rounds=self.rounds(project_id,s['current_node_id']);p=self.get_project(project_id)
            policy=EvaluationPolicy.model_validate(p['policy'])
            pause=rounds['replacements']>=policy.max_replacements
            self.mark(project_id,'paused' if pause else 'assessment_review',error_type=reason)
            if pause:self.change_session(project_id,pause_reason='replacement_limit')

    def extend_rounds(self,project_id):
        with self.transaction():
            s=self.session(project_id);p=self.get_project(project_id);policy=EvaluationPolicy.model_validate(p['policy'])
            rounds=self.rounds(project_id,s['current_node_id'])
            if s['pause_reason']=='extension_ready':return
            if s['pause_reason']!='round_limit' or rounds['extension_used']>=policy.max_round_extensions:raise ConflictError('Round extension unavailable')
            self.conn.execute('UPDATE node_runtime SET round_limit=round_limit+?,extension_used=1 WHERE project_id=? AND node_id=?',
                (policy.extension_rounds,project_id,s['current_node_id']))
            self.change_session(project_id,pause_reason='extension_ready')
            self.mark(project_id,'paused')
