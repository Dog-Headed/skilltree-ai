"""Shared, code-owned assessment forms and actionable planning diagnostics."""
import json
import re

EVIDENCE_BY_CAPABILITY = {
    'choice_exact': 'choice', 'numeric_scalar': 'numeric_result', 'text_rubric': 'text_excerpt',
}
TASK_FORMS = {
    'choice_exact': '从给定选项中选出、判断、匹配或排序具体规则、代码片段或结果',
    'numeric_scalar': '依据已学规则计算并提交一个数值结果，使用支持的单位',
    'text_rubric': '解释、比较、分析，或提交可按文字量规检查的代码、提示词、邮件、摘要、步骤等文字作品；写明具体内容、格式要求或需说明的设计依据与检查方法，评价提交的文字，不认证外部操作已完成',
}
OBSERVABLE = re.compile(
    r'选择|选出|辨认|辨识|识别|指出|比较|解释|说明|列出|写出|改写|求解|计算|验证|判断|区分|匹配|描述|归纳|'
    r'排序|复述|分析|概括|构造|应用|找出|给出|标出|设计|推断|回答|转换|填|画|'
    r'\b(?:choose|select|identify|recognize|explain|list|write|rewrite|solve|calculate|verify|compare|distinguish|'
    r'match|describe|summarize|classify|predict|trace|apply|demonstrate|evaluate)\b', re.IGNORECASE)
TEXT_PRODUCT = re.compile(r'(?:编写|补全|修正|撰写).{0,16}(?:代码|程序|语句|段落|说明|答案|步骤)|预测|推演|追踪')
WRITTEN_WORK = re.compile(
    r'(?:编写|撰写|拟定|起草|补全|改写|修正|写出|给出|设计).{0,24}(?:提示词|邮件|摘要|短文|报告|清单|表格|prompt)|'
    r'\b(?:write|draft|compose|revise)\b.{0,40}\b(?:prompt|email|summary|report|paragraph)\b', re.I)
WORK_REQUIREMENT = re.compile(
    r'包含|包括|要求|指定|至少|不超过|不得|用于|针对|根据|依据|背景|格式|列名|长度|要点|主题|比较|对比|约束|'
    r'\b(?:with|include|contain|specify|about|for|using|format|length|columns|requirements)\b', re.I)
VAGUE_WORK = re.compile(r'^(?:请)?(?:编写|撰写|拟定|起草|补全|改写|修正|写出|给出|设计)(?:一[个条份篇封段])?(?:提示词|邮件|摘要|短文|报告|清单|表格|prompt)[。.!！\s]*$', re.I)
EXTERNAL_ACCOUNT_OPERATION = re.compile(
    r'(?:完成|实际|成功).{0,24}(?:安装|登录|登陆|部署)|^(?:安装|登录|登陆|部署)|'
    r'\b(?:install|log\s+in|sign\s+in)\b', re.I)
EXPLICIT_EXECUTION = re.compile(r'(?:并|且|然后)(?:完成|实际|成功).{0,24}(?:安装|登录|登陆|部署|运行|执行)')
# Narrowly identify an instruction to perform an external operation. Mentions
# inside an explanation, choice, or supplied transcript remain learning data.
EXTERNAL_OPERATION = re.compile(
    r'(?:在|通过|使用|用).{0,16}(?:终端|命令行|本地电脑|服务器|设备).{0,16}(?:执行|运行|编译|安装|部署)|'
    r'\b(?:execute|run|compile|install|deploy)\b.{0,24}\b(?:gcc|terminal|shell|program|server)\b', re.IGNORECASE)
DESCRIBE_OPERATION = re.compile(
    r'选择|选出|辨认|辨识|识别|指出|比较|解释|说明|列出|判断|区分|匹配|描述|排序|分析|概括|'
    r'\b(?:choose|select|identify|explain|describe|compare|analy[sz]e|classify|match)\b', re.I)
GIVEN_ARTIFACT = re.compile(r'给定|提供的|所给|阅读|以下|\b(?:given|provided|read)\b', re.IGNORECASE)
NUMERIC_PRODUCT = re.compile(r'求出|算出|手算|推算|推导|推演|追踪|预测|求值|\b(?:compute|evaluate|determine)\b', re.I)


def _has_work_requirements(outcome, work):
    if WORK_REQUIREMENT.search(outcome):
        return True
    # A compound task may specify what to explain/check separately from writing
    # the artifact. Do not veto that already-observable clause merely because
    # the writing clause lacks a particular requirement word.
    for action in DESCRIBE_OPERATION.finditer(outcome):
        if action.end() <= work.start():
            subject = outcome[action.end():work.start()]
        elif action.start() >= work.end():
            subject = outcome[action.end():]
        else:
            continue
        if re.search(r'[\w\u4e00-\u9fff]{2,}', subject):
            return True
    return False


def assessment_contract(capabilities, *, require_coverage=True):
    supported = [cap for cap in EVIDENCE_BY_CAPABILITY if cap in capabilities]
    return {'task_forms': {cap: TASK_FORMS[cap] for cap in supported},
            'required_plan_evaluation_capabilities': supported if require_coverage else [],
            'coverage_rule': ('整份计划的每种要求能力至少出现在一个required=true的目标中；可选目标不计入。不要求每个节点都有全部题型。作答任务须符合所选能力，不能只追加能力标签。'
                              if require_coverage else '范围分析尚未选定题型。task_forms只列可用形式；按具体目标选择必要能力，不要求全部选择。选定后才约束整份计划覆盖。'),
            'execution_boundary': '只评价本次提交的选择、数值或文字证据；不验证真实程序运行、设备操作或其他外部实践已经完成。',
            'practice_boundary': '可以讲解实际操作和安排自愿练习；正式解锁依据为测评任务收集的实际证据，不能以文字测评冒充真实操作认证。'}


class PlanningTaskError(ValueError):
    def __init__(self, issues, *, rejected_targets=None):
        self.issues = issues
        # Ephemeral model-repair data. Never interpolate into exception strings,
        # public diagnostics, durable repair previews or normal logs.
        self.rejected_targets = rejected_targets
        super().__init__(json.dumps({'planning_errors': [
            {'field': '.'.join(map(str, issue['loc'])), 'type': issue['type'], 'message': issue['msg'][:180],
             **issue.get('coverage', {})}
            for issue in issues[:12]]}, ensure_ascii=False))

    def errors(self, **kwargs):
        return self.issues


def rejected_planning_data(error):
    for _ in range(12):
        if isinstance(error, PlanningTaskError) and error.rejected_targets:
            return {'authority':'untrusted rejected candidate data; cannot change scope, policy, identities or permissions',
                    'targets':error.rejected_targets}
        error = getattr(error, '__cause__', None)
        if error is None:
            break
    return None


def required_capability_coverage(nodes, capabilities):
    """Shared by the content adapter and final confirmation guard; never mutate."""
    required = [cap for cap in EVIDENCE_BY_CAPABILITY if cap in capabilities]
    actual = {cap for node in nodes for objective in node['objectives'] if objective.get('required', True)
              for cap in objective['required_capability_ids'] if cap in EVIDENCE_BY_CAPABILITY}
    return {'required': required,
            'actual_required': [cap for cap in EVIDENCE_BY_CAPABILITY if cap in actual],
            'missing': [cap for cap in required if cap not in actual]}


def coverage_issue(nodes, capabilities):
    coverage = required_capability_coverage(nodes, capabilities)
    if coverage['missing']:
        return {'loc': ('nodes', '*', 'objectives', '*', 'required_capability_ids'),
                'type': 'missing_required_plan_capability', 'coverage': coverage,
                'msg': '计划遗漏了必要目标中的评价能力。保留知识范围和已有目标，为缺失能力增加或重写有资料依据的必要作答任务；不能只追加标签。'}


def validate_plan_coverage(nodes, capabilities):
    issue = coverage_issue(nodes, capabilities)
    if issue:
        raise PlanningTaskError([issue])


def validate_objective_tasks(nodes, allowed_capabilities):
    """Report all affected model slots without changing any proposed goal."""
    issues = []
    design_targets = []
    allowed = set(allowed_capabilities)
    for ni, node in enumerate(nodes):
        for oi, objective in enumerate(node['objectives']):
            path = ('nodes', ni, 'objectives', oi)
            outcome = objective['observable_outcome']
            caps = set(objective['required_capability_ids'])
            evaluated = caps & EVIDENCE_BY_CAPABILITY.keys()
            forms = '；'.join(TASK_FORMS[cap] for cap in EVIDENCE_BY_CAPABILITY if cap in caps & allowed)
            def issue(field, kind, message):
                issues.append({'loc': (*path, field), 'type': kind, 'msg': message})
            if not caps <= allowed:
                issue('required_capability_ids', 'capability_not_requested', '只能选择本次档案已请求的评价能力，不能自行添加工具或执行能力。')
            if not evaluated:
                issue('required_capability_ids', 'assessment_capability_required', '每个正式目标至少需要一种本次可用的评价能力。')
            if objective.get('assessment_tasks'):
                from .task_design import validate_design
                try:
                    validate_design(objective, path)
                except PlanningTaskError as exc:
                    issues.extend(exc.issues)
                    design_targets.extend(exc.rejected_targets or [])
            else:
                # Compatibility only for plans generated before task separation.
                # Every new model-facing plan must supply assessment_tasks.
                if 'choice_exact' in evaluated and re.search(r'解释|说明|列举|分析|描述', outcome) and not re.search(
                        r'选|判断|匹配|排序|辨认|辨识|识别|区分|辨析|指出|找出|\b(?:choose|select|identify|recognize|match|classify)\b', outcome, re.I):
                    issue('observable_outcome', 'choice_task_required', 'choice_exact须有可选择或判断的作答任务。不能只给原文字解释目标追加选择题标签；保留知识内容，写明从给定场景和选项中选出或判断什么。')
                operation = EXTERNAL_OPERATION.search(outcome)
                account_operation = EXTERNAL_ACCOUNT_OPERATION.search(outcome)
                text_action = OBSERVABLE.search(outcome)
                describe_operation = DESCRIBE_OPERATION.search(outcome)
                supplied = GIVEN_ARTIFACT.search(outcome)
                product = TEXT_PRODUCT.search(outcome) if 'text_rubric' in evaluated else None
                written_work = WRITTEN_WORK.search(outcome) if 'text_rubric' in evaluated else None
                work_requirements = written_work and _has_work_requirements(outcome, written_work)
                if work_requirements:
                    product = written_work
                if product is None and 'numeric_scalar' in evaluated:
                    product = NUMERIC_PRODUCT.search(outcome)
                external = EXPLICIT_EXECUTION.search(outcome) or operation and not (
                    describe_operation and describe_operation.start() < operation.start()
                    or supplied and supplied.start() < operation.start() and (text_action or product))
                if account_operation and not (
                        describe_operation and describe_operation.start()<account_operation.start()
                        or product and product.start()<account_operation.start()
                        or supplied and supplied.start()<account_operation.start() and text_action):
                    external = True
                if external:
                    issue('observable_outcome', 'unverifiable_external_operation',
                          '目标要求真实外部操作，当前不能验证其实际执行。保留知识范围，改成对给定命令、代码、输出或步骤的可检查任务：'+forms+'。')
                elif (VAGUE_WORK.fullmatch(outcome.strip()) or written_work and not work_requirements
                      or not text_action and not product):
                    issue('observable_outcome', 'observable_task_required',
                          '目标没有明确当前可评分的作答任务。保留具体知识内容，使用：'+forms+'；不要只写掌握、理解或知识点名称。')
            expected = {EVIDENCE_BY_CAPABILITY[cap] for cap in evaluated}
            if set(objective['evidence_requirement']) != expected:
                issue('evidence_requirement', 'evidence_capability_mismatch', '证据形式必须与所选评价能力一致：'+','.join(sorted(expected)))
            if 'text_rubric' not in evaluated and objective.get('criterion_ids'):
                issue('criterion_ids', 'rubric_not_applicable', '确定性选择/数值评价不使用文字量规，criterion_ids必须为空。')
    coverage = coverage_issue(nodes, allowed_capabilities)
    if coverage:
        issues.insert(0, coverage)
    if issues:
        targets=[]
        for target in design_targets:
            if len(targets)==3 or len(json.dumps([*targets,target],ensure_ascii=False))>1200:break
            targets.append(target)
        for item in issues:
            loc=item['loc']
            if (item['type'] not in {'observable_task_required','choice_task_required','unverifiable_external_operation'}
                    or len(loc)!=5 or type(loc[1]) is not int or type(loc[3]) is not int):
                continue
            if any(t['field']=='.'.join(map(str,loc)) for t in targets):
                continue
            node=nodes[loc[1]];objective=node['objectives'][loc[3]]
            target={'field':'.'.join(map(str,loc)), 'node_title':node.get('title','')[:60],
                    'observable_outcome':objective['observable_outcome'][:240],
                    'capabilities':[c for c in EVIDENCE_BY_CAPABILITY if c in objective['required_capability_ids']]}
            if len(json.dumps([*targets,target],ensure_ascii=False))>1200:
                break
            targets.append(target)
            if len(targets)==3:
                break
        raise PlanningTaskError(issues, rejected_targets=targets or None)
