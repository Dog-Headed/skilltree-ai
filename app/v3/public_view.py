"""Explicit learner projection: no raw state, private standards or private IDs."""
from copy import deepcopy
import json

from .contracts import PublicSource, SourceDocument
from .project_management import metadata, require_visible
from .tutor_feedback import PrivateFeedbackFilter


def source_documents(repo,pid):
    project=repo.get_project(pid)
    documents=repo.list_sources(pid)
    frozen=project['frozen_snapshot']
    if frozen:
        versions={(s['source_id'],s['source_version']) for s in frozen['source_manifest']}
        return [d for d in documents if (d['source_id'],d['source_version']) in versions]
    latest={}
    for document in documents:latest[document['source_id']]=document
    return list(latest.values())


def source_detail(repo,pid,source_id,version):
    require_visible(repo,pid)
    doc=next((d for d in repo.list_sources(pid) if (d['source_id'],d['source_version'])==(source_id,version)),None)
    if not doc:raise KeyError(source_id)
    return {**PublicSource.from_document(SourceDocument.model_validate(doc)).model_dump(),
            'content':doc['content'],'content_hash':doc['content_hash'],
            'chunks':repo.list_source_chunks(pid,source_id,version)}


def project_view(repo,base):
    view=deepcopy(base);pid=view['project_id'];require_visible(repo,pid)
    p=repo.get_project(pid)
    documents=source_documents(repo,pid)
    public_chunks={c['chunk_id']:c for d in documents for c in repo.list_source_chunks(pid,d['source_id'],d['source_version'])}
    def citations(items):
        return [c for c in items if c.get('chunk_id') in public_chunks
                and (c.get('source_id'),c.get('source_version'))==(public_chunks[c['chunk_id']]['source_id'],public_chunks[c['chunk_id']]['source_version'])]
    plan=deepcopy(p['candidate_plan'])
    if plan:
        for node in plan['nodes']:
            for objective in node['objectives']:
                objective['source_chunk_ids']=[c for c in objective['source_chunk_ids'] if c in public_chunks]
                objective.pop('criterion_ids',None)
    progress=repo.get_progress(pid)
    done={r['node_id'] for r in progress if r['completed_at']}
    nodes=[]
    for node in (plan or {}).get('nodes',[]):
        nodes.append({**node,'passed':node['node_id'] in done,
                      'status':'passed' if node['node_id'] in done else 'current' if node['node_id']==view.get('current_node_id') else 'available' if set(node['prerequisite_ids'])<=done else 'locked'})
    view.update(version='v3',read_only=False,display_name=metadata(repo,pid).get('display_name'),
                plan=plan,nodes=nodes,
                progress=[{key:r[key] for key in ('node_id','started_at','completed_at','completion_assessment_id')} for r in progress],
                sources=[PublicSource.from_document(SourceDocument.model_validate(d)).model_dump() for d in documents])
    # A frozen preparation project has one explicit transition to its learning
    # graph. Opening or refreshing it does not run Tutor.
    if not view.get('learning_runtime_ready') and p['lifecycle'] in ('learning','exploring') and not view.get('recovery_required'):
        view['allowed_actions']=['begin']
    tutor=view.get('tutor')
    if tutor:tutor['citations']=citations(tutor.get('citations',[]))
    # Derive a feedback panel even when a pass has already moved the session to
    # the next node and cleared current_assessment_id.
    aid=view.get('assessment_id')
    row=repo.get_assessment(pid,aid) if aid else None
    if not row or not row['evaluation_json']:
        row=repo.conn.execute('SELECT * FROM assessments WHERE project_id=? AND evaluation_json IS NOT NULL ORDER BY created_at DESC,rowid DESC LIMIT 1',(pid,)).fetchone()
        row=dict(row) if row else None
    if row and row['evaluation_json']:
        evaluation=json.loads(row['evaluation_json']);quiz=json.loads(row['quiz_json'])
        fragments=[d['content'] for d in repo.list_sources(pid,include_private=True) if d['visibility']=='assessment_private']
        for question in quiz['questions']:
            key=question.get('answer_key');fragments.extend([key] if isinstance(key,str) else key or [])
            fragments.extend(c['description'] for c in question.get('rubric',[]))
            if question.get('numeric_rules'):fragments.append(str(question['numeric_rules']['expected']))
        privacy=PrivateFeedbackFilter(fragments,[d['content'] for d in documents]+[q['prompt'] for q in quiz['questions']])
        policy=p['policy'];rules={r['objective_id']:r for r in policy['objective_rules']}
        objectives={o['objective_id']:o for n in (plan or {}).get('nodes',[]) for o in n['objectives']}
        transition=repo.conn.execute('SELECT result_json FROM learning_transitions WHERE project_id=? AND assessment_id=?',(pid,row['id'])).fetchone()
        feedback_guard=json.loads(transition[0])['guard'] if transition else None
        view['feedback']={'assessment_id':row['id'],'node_id':row['node_id'],
            'node_title':next((n['title'] for n in nodes if n['node_id']==row['node_id']),row['node_id']),
            'guard':feedback_guard,'grading_status':evaluation['grading_status'],
            'total_score':sum(r['score'] for r in evaluation['question_results']),
            'max_score':sum(r['max_score'] for r in evaluation['question_results']),
            'question_scores':[{'question_id':r['question_id'],'score':r['score'],'max_score':r['max_score'],
                               'feedback':privacy.public(r['feedback'],'请结合目标和自己的作答继续检查。',400)} for r in evaluation['question_results']],
            'objective_results':[{'objective_id':r['objective_id'],'observable_outcome':objectives[r['objective_id']]['observable_outcome'],
                                  'score_ratio':r['score_ratio'],'threshold':rules[r['objective_id']]['pass_threshold'],
                                  'required':rules[r['objective_id']]['required']} for r in evaluation['objective_results']]}
    view['conversation']=[]
    if view.get('learning_runtime_ready'):
        node_id=view.get('review_node_id') or view.get('current_node_id')
        for row in repo.conn.execute('SELECT question,reply_json FROM tutor_turns WHERE project_id=? AND node_id=? ORDER BY created_at,rowid',(pid,node_id)):
            reply=json.loads(row['reply_json'])
            view['conversation'].append({'question':row['question'],'text':reply['text'],'citations':citations(reply.get('citations',[]))})
        view['conversation']=view['conversation'][-12:]
    return view
