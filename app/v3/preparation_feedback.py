"""Bounded, private-content-free terminal diagnostics and repeated-plan guard."""
from hashlib import sha256
import json
from time import perf_counter

from app.services.llm import ModelOutputValidationError
from .planning_contract import EVIDENCE_BY_CAPABILITY, PlanningTaskError
from .repository import V3Repository, encode

TABLE_SQL = '''CREATE TABLE IF NOT EXISTS preparation_diagnostics (
 project_id TEXT NOT NULL, task_key TEXT NOT NULL, input_hash TEXT NOT NULL,
 summary_json TEXT NOT NULL, PRIMARY KEY(project_id,task_key))'''


class RepeatedPlanFailure(ModelOutputValidationError):
    pass


def safe_summary(error, stage, elapsed_ms):
    """Only code-owned types/slots/registered IDs, never exception text or output."""
    summary = {'stage': stage, 'code': 'model_output_invalid', 'elapsed_ms': elapsed_ms}
    current = error
    for _ in range(12):
        if isinstance(current, PlanningTaskError):
            for issue in current.issues:
                if issue['type'] == 'missing_required_plan_capability':
                    summary.update(code=issue['type'], field='nodes[*].objectives[*].required_capability_ids')
                    summary.update({k: [c for c in EVIDENCE_BY_CAPABILITY if c in issue['coverage'][k]]
                                    for k in ('required', 'actual_required', 'missing')})
                    return summary
        current = getattr(current, '__cause__', None)
        if current is None:
            break
    return summary


def guarded_plan(paths, pid, task_key, inputs, version, model, callback):
    """Two identical terminal coverage failures require input/model/version change.

    Completed cached logical tasks still use their original hash and budgets.
    The guard is specific to a diagnosed content failure, never timeouts/auth.
    """
    resolved = model.current() if callable(getattr(model, 'current', None)) else model
    model_name = str(getattr(resolved, 'model_name', type(resolved).__name__))
    fingerprint = sha256(encode({'input': inputs, 'version': version, 'model': model_name}).encode()).hexdigest()
    with V3Repository(paths) as repo:
        exists = repo.conn.execute("SELECT 1 FROM sqlite_master WHERE name='preparation_diagnostics'").fetchone()
        if exists:
            rows = repo.conn.execute('SELECT summary_json FROM preparation_diagnostics WHERE project_id=? AND input_hash=? ORDER BY rowid DESC LIMIT 2',
                                     (pid, fingerprint)).fetchall()
            if len(rows) == 2 and all(json.loads(r[0])['code'] == 'missing_required_plan_capability' for r in rows):
                raise RepeatedPlanFailure('同一规划输入连续两次缺少必要评价能力，已停止重复调用。请修改学习目标或资料后重新整理；模型切换或规划修复版本更新后可显式重试。已用请求不会清零。')
    started = perf_counter()
    try:
        result = callback()
    except ModelOutputValidationError as exc:
        summary = safe_summary(exc, 'plan', round((perf_counter()-started)*1000, 3))
        with V3Repository(paths) as repo, repo.transaction():
            repo.conn.execute(TABLE_SQL)
            repo.conn.execute('INSERT OR REPLACE INTO preparation_diagnostics VALUES (?,?,?,?)',
                              (pid, task_key, fingerprint, encode(summary)))
        raise
    else:
        # A successful intervening attempt breaks a consecutive failure run.
        with V3Repository(paths) as repo, repo.transaction():
            repo.conn.execute(TABLE_SQL)
            repo.conn.execute('INSERT OR REPLACE INTO preparation_diagnostics VALUES (?,?,?,?)',
                              (pid, task_key, fingerprint, encode({'stage':'plan','code':'completed'})))
        return result


def failure_notice(error):
    if isinstance(error, RepeatedPlanFailure):
        return str(error)
    summary = safe_summary(error, 'plan', 0)
    if summary['code'] == 'missing_required_plan_capability':
        names = {'choice_exact':'选择题', 'text_rubric':'文字解释', 'numeric_scalar':'数值作答'}
        missing = '、'.join(names[c] for c in summary['missing'])
        return f'学习计划未覆盖必要的{missing}目标，自动修复未成功，未确认任何计划。请修改目标或补充资料后重新整理；相同输入连续失败后会停止重复调用。已用请求不会清零。'
    if isinstance(error, ModelOutputValidationError):
        return '这次 AI 准备内容未通过校验，自动修复未成功，未确认任何计划。请检查目标或资料后重新整理；已用请求不会清零。'
    return '这次 AI 准备请求未完成，未确认任何计划。请稍后检查模型服务再重试；已用请求不会清零。'
