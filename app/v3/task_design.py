"""Structured answer collection; learner goals are never verb allowlists.

Exact references and quotes are factual checks. Narrow known unsupported
claims are repairable content issues, not proof of general semantic quality.
"""
from .contracts import AssessmentTask

TASK_CAPABILITIES = {'choice': 'choice_exact', 'numeric': 'numeric_scalar', 'text': 'text_rubric'}
TASK_INSTRUCTIONS = {
    'choice': '从题目提供的选项中提交选择，按确定性答案评分',
    'numeric': '提交一个数值结果及题目允许的单位，按确定性数值规格评分',
    'text': '提交文字作品或解释，按文字量规评分',
}
PROTOCOL = 'assessment-design-1'
PLACEHOLDERS = frozenset({'任务', '要求', '评价标准', '按要求完成', '完成任务', '提交答案', '同上', '无', '待定',
                          'task', 'requirements', 'criteria', 'answer', 'tbd', 'n/a'})


def capabilities(tasks):
    kinds = {t['task_form'] for t in tasks}
    return [cap for form,cap in TASK_CAPABILITIES.items() if form in kinds]


def content_issues(tasks, path):
    """Missing evidence instructions and explicit execution claims get repair.

    An unfamiliar verb or artifact name is never an error. The goal itself may
    name a real-world skill: only the proposed assessment is bounded here.
    """
    from .planning_contract import EXTERNAL_OPERATION, EXTERNAL_ACCOUNT_OPERATION, EXPLICIT_EXECUTION, DESCRIBE_OPERATION, GIVEN_ARTIFACT
    issues=[]
    for i,task in enumerate(tasks):
        for field in ('submission','requirements','criteria'):
            values=task[field] if isinstance(task[field],list) else [task[field]]
            if any(v.strip().casefold().strip('。.!！ ') in PLACEHOLDERS for v in values):
                issues.append({'loc':(*path,'assessment_tasks',i,field),'type':'assessment_task_incomplete',
                               'msg':'提供具体提交物、知识要求和可检查的评价依据，不能用空泛标签代替。'})
        # Positive risk detection only. Unknown wording is not invalidity.
        # Describing a command or interpreting a supplied transcript is valid.
        for field in ('submission','requirements','criteria'):
            for value in task[field] if isinstance(task[field],list) else [task[field]]:
                op=EXTERNAL_OPERATION.search(value) or EXTERNAL_ACCOUNT_OPERATION.search(value)
                describe=DESCRIBE_OPERATION.search(value);given=GIVEN_ARTIFACT.search(value)
                if EXPLICIT_EXECUTION.search(value) or op and not (
                        describe and describe.start()<op.start() or given and given.start()<op.start()):
                    issues.append({'loc':(*path,'assessment_tasks',i,field),'type':'unsupported_assessment_claim',
                                   'msg':'当前只收集文字、选项或数值；改为检查提交内容，不以真实安装、登录、运行成功作为通过证据。'})
                    break
    return issues


def validate_design(objective, path):
    """Check typed evidence mapping, never match verbs in the learning target."""
    from .planning_contract import PlanningTaskError
    tasks=[AssessmentTask.model_validate(t).model_dump() for t in objective['assessment_tasks']]
    issues=content_issues(tasks,path)
    if set(capabilities(tasks)) != set(objective['required_capability_ids']):
        issues.append({'loc':(*path,'required_capability_ids'),'type':'assessment_task_capability_mismatch',
                       'msg':'作答形式必须与程序绑定的评价器一致。'})
    if issues:
        targets=[]
        for item in issues[:3]:
            index=item['loc'][len(path)+1] if len(item['loc'])>len(path)+1 else None
            target={'field':'.'.join(map(str,item['loc'])),'learning_target':objective['observable_outcome'][:160]}
            if isinstance(index,int):
                task=tasks[index]
                target['assessment_task']={k:(v[:2] if isinstance(v,list) else v) for k,v in task.items() if k!='support_quote'}
            targets.append(target)
        raise PlanningTaskError(issues,rejected_targets=targets)


def validate_quotes(objective, chunks, path):
    """A real extract is required; its existence is not semantic entailment."""
    from .planning_contract import PlanningTaskError
    for i,task in enumerate(objective.assessment_tasks):
        if not any(task.support_quote in chunks[c].content for c in objective.source_chunk_ids):
            raise PlanningTaskError([{'loc':(*path,'assessment_tasks',i,'support_quote'),
                'type':'assessment_source_quote_missing','msg':'逐字摘录本目标所选真实教学片段中的短句，不得编造或引用其他目标未选择的资料。'}])


def task_payload(objective, question_type=None):
    form={'single_choice':'choice','multiple_choice':'choice','numeric_scalar':'numeric','text':'text'}.get(question_type)
    return [{**task.model_dump(), 'collection_instruction':TASK_INSTRUCTIONS[task.task_form]}
            for task in objective.assessment_tasks if form is None or task.task_form==form]
