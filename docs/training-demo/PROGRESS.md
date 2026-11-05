# Training Demo Progress (Grok Bot)

Updated: 2026-11-05 (Asia/Shanghai). Owner: Grok Bot continuous implementation.

## Field confirmation

| Item | Result |
|---|---|
| GitHub `main` | `cebaa7f7e4566897174d2a2ab74d83e6dd090ae9` (merged PR #2 Day2 fidelity + doc sync) |
| Box clone | `/workspace/skilltree-ai` primary develop/test |
| Production deploy | **not restarted this run**; leave prod on prior SHA until live Day2 recheck + deploy checklist |

## Status

- [x] Day 2 tutor material fidelity + offline regressions (merged to `main` via PR #2)
- [ ] Day 2 live model DOCX recheck（此前 API 超时，未阻断 4A）
- [x] 4A Open registration + personal identity (`not_a_member` fixed)
- [x] 4A Admin member lookup/add/remove
- [x] 4A Backend QA admin script (`deploy/training_admins.py`)
- [x] 4A Docs: CONTRACTS / START / accounts/REPORT / this file
- [ ] Day 3 Publish + assign
- [ ] Day 4 Dashboard
- [ ] Day 5 Full demo rehearsal

## Tests this phase

- `tests/test_training_registration_members.py` + `tests/test_training_demo.py` → **14 passed**

## Next

1. PR/merge 4A branch
2. Optionally create QA admins on an isolated local instance; production only with explicit deploy
3. Day 3 course publish + task assign
