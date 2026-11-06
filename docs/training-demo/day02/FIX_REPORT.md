# Day 2 Fix Report — Material fidelity (tutor)

Date: 2026-11-05 (Asia/Shanghai). Branch: `grokbot/day2-fidelity` @ base `80d53f4`.
Primary workspace: Grok Bot box `/workspace/skilltree-ai` (server worktree mirror for live checks only).

## Problem (from independent REVIEW / handoff)

Sample `docs/training-demo/samples/培训制度.docx` states only:

> 每位新员工须在入职后 5 个工作日内完成基础制度学习。

Live tutor previously elaborated as policy fact: start-of-count on hire day, exclude weekends/法定节假日, and「周一入职 → 下周一前」. Citations pointed at the right paragraph, but the elaboration was not in the source.

## Change

File: `app/v3/tutor.py` (`TUTOR_PROMPT_VERSION` → `v3-day2-fidelity-1`)

1. **Prompt**: for user-provided policy/ops materials, require three-way split — 原文事实 / 一般解释 / 带假设的例子; unspecified 起算日、节假日口径、日历截止、审批、处罚 must not be stated as rules; keep general-knowledge teaching useful.
2. **Validation**: `has_ungrounded_policy_assertion` + `material_corpus_from_contexts` reject unhedged inventions of start-count / concrete weekday deadlines / penalties / approvers when materials do not state them; hedged「原文未规定…假设…」passes; materials that *do* specify start-count still allow restating it.
3. **Planner / quiz / score light check**: `planner.py` already binds chunks and says not to fabricate sources; `assessment.py` / `evaluators.py` already say sources do not prove conclusions and not to invent unique answers without basis. No evidenced same-class tutor bug there — **no code change** in this fix.

## Offline tests

```bash
cd /workspace/skilltree-ai
.venv/bin/python -m pytest tests/test_v3_tutor_fidelity.py tests/test_v3_tutor.py -q
```

Result on box: **57 passed** (new fidelity file + existing tutor suite).

Covers: invented start-count, hedged example, grounded restatement, material-specified start-count, invented penalty, QA follow-up「周几截止」, system prompt markers, corpus join.

## Live model

Attempted on server worktree `/home/admin/skilltree-work/grokbot-day2` with sample `培训制度.docx` (no production restart). First `generate_tutor_reply` call failed with `openai.APITimeoutError` / `ModelRequestFailedError` after exhausting network retries (~102s). **No live teaching JSON recorded.** Offline detector still flags the historical invented reply as ungrounded. Retry live evidence later with a longer task timeout; do **not** claim prompts eliminate all hallucination.


## Production

No production service restart, no DB/env overwrite in this fix step. Deploy only after review/sync.

## Independent REVIEW

Not rewritten to “passed”. This FIX_REPORT documents the remediation attempt only.

## 2026-11-06 follow-up

R06 的否定、主体和条件盲区，以及 R07 的 PDF 拆章，记在 [R06_R07_FIX_REPORT.md](../R06_R07_FIX_REPORT.md)。上面的 Live model 节仍是当时的超时记录，没有被改成真实模型通过。本次环境没有模型密钥，没有补写教学 JSON。
