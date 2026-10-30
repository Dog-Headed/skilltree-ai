"""Shared, code-owned assessment forms and actionable planning diagnostics."""
import json
import re

EVIDENCE_BY_CAPABILITY = {
    'choice_exact': 'choice', 'numeric_scalar': 'numeric_result', 'text_rubric': 'text_excerpt',
}
TASK_FORMS = {
    'choice_exact': '从给定选项中选出、判断、匹配或排序具体规则、代码片段或结果',
    'numeric_scalar': '依据已学规则计算并提交一个数值结果，使用支持的单位',
    'text_rubric': '解释、比较、分析，或编写/补全可按文字量规检查的代码、步骤或说明',
}
OBSERVABLE = re.compile(
    r'选择|选出|辨认|辨识|识别|指出|比较|解释|说明|列出|写出|改写|求解|计算|验证|判断|区分|匹配|完成|描述|归纳|'
    r'排序|复述|分析|概括|构造|应用|找出|给出|标出|设计|推断|回答|转换|填|画|'
    r'\b(?:choose|select|identify|recognize|explain|list|write|rewrite|solve|calculate|verify|compare|distinguish|'
    r'match|describe|summarize|classify|predict|trace|apply|demonstrate|evaluate)\b', re.IGNORECASE)
TEXT_PRODUCT = re.compile(r'(?:编写|补全|修正|撰写).{0,16}(?:代码|程序|语句|段落|说明|答案|步骤)|预测|推演|追踪')
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


def assessment_contract(capabilities):
    supported = [cap for cap in EVIDENCE_BY_CAPABILITY if cap in capabilities]
    return {'task_forms': {cap: TASK_FORMS[cap] for cap in supported},
            'execution_boundary': '只评价本次提交的选择、数值或文字证据；不验证真实程序运行、设备操作或其他外部实践已经完成。',
            'practice_boundary': '可以讲解实际操作和安排自愿练习；正式解锁目标须写成当前可评价的任务，不能以文字测评冒充真实操作认证。'}


class PlanningTaskError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__(json.dumps({'planning_errors': [
            {'field': '.'.join(map(str, issue['loc'])), 'type': issue['type'], 'message': issue['msg']}
            for issue in issues]}, ensure_ascii=False))

    def errors(self, **kwargs):
        return self.issues


def validate_objective_tasks(nodes, allowed_capabilities):
    """Report all affected model slots without changing any proposed goal."""
    issues = []
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
            operation = EXTERNAL_OPERATION.search(outcome)
            text_action = OBSERVABLE.search(outcome)
            describe_operation = DESCRIBE_OPERATION.search(outcome)
            supplied = GIVEN_ARTIFACT.search(outcome)
            product = TEXT_PRODUCT.search(outcome) if 'text_rubric' in evaluated else None
            if product is None and 'numeric_scalar' in evaluated:
                product = NUMERIC_PRODUCT.search(outcome)
            external = operation and not (
                describe_operation and describe_operation.start() < operation.start()
                or supplied and supplied.start() < operation.start() and (text_action or product))
            if external:
                issue('observable_outcome', 'unverifiable_external_operation',
                      '目标要求真实外部操作，当前不能验证其实际执行。保留知识范围，改成对给定命令、代码、输出或步骤的可检查任务：'+forms+'。')
            elif not text_action and not product:
                issue('observable_outcome', 'observable_task_required',
                      '目标没有明确当前可评分的作答任务。保留具体知识内容，使用：'+forms+'；不要只写掌握、理解或知识点名称。')
            expected = {EVIDENCE_BY_CAPABILITY[cap] for cap in evaluated}
            if set(objective['evidence_requirement']) != expected:
                issue('evidence_requirement', 'evidence_capability_mismatch', '证据形式必须与所选评价能力一致：'+','.join(sorted(expected)))
            if 'text_rubric' not in evaluated and objective.get('criterion_ids'):
                issue('criterion_ids', 'rubric_not_applicable', '确定性选择/数值评价不使用文字量规，criterion_ids必须为空。')
    if issues:
        raise PlanningTaskError(issues)
