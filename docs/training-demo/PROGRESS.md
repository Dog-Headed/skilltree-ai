# Training Demo Progress (Grok Bot)

Updated: 2026-11-05 (Asia/Shanghai). Owner: Grok Bot continuous implementation.

## Field confirmation

| Item | Result |
|---|---|
| Server HEAD | `80d53f4425a5701dbf78237d00b968fc9f072890` on `main` (ahead of `origin/main` by 5 commits) |
| Services | `skilltree` / `skilltree-evaluation` / `nginx` active; healthz 8765 & 8767 ok at same SHA |
| WorkingDirectory | `/home/admin/skilltree-ai` |
| Python | `/home/admin/skilltree-ai/.venv/bin/python` via uvicorn factory `deploy.asgi:create_app` |
| Public data root (8767) | `SKILLTREE_DATA_ROOT=data/evaluation-v3` + training overlay `work/training-demo/production` via `training.env` |
| Docs on server | `CONTRACTS.md`, `START.md`, `day01/`, `day02/REPORT.md`, `SAMPLE_CHECKS.md`, `samples/` present; **`day02/REVIEW.md` missing on server** (expected per handoff) |

## Working copies

| Location | Role |
|---|---|
| `/workspace/skilltree-ai` (Grok Bot box) | **Primary** develop/test clone; branch `grokbot/day2-fidelity` |
| `/home/admin/skilltree-work/grokbot-day2` | Server worktree same branch for field/live checks; production data roots untouched |
| `/home/admin/skilltree-ai` | Production checkout; do not reset / clear DBs / overwrite env |

## Status

- [x] Server `git fetch`: `origin/main` == HEAD `80d53f4` (tracking aligned; no force-push / no reset)
- [x] GitHub-facing doc drift pass on box (START L63, CONTRACTS guest/admin/materials rows, GOAL_FIRST, ARCHITECTURE; README/GETTING_STARTED already partly current)
- [ ] C Live model re-check (attempted; API timeout — see FIX_REPORT)

- [x] A Field confirmation
- [x] B Isolated work branch
- [x] C Day 2 material fidelity fix + offline regressions (box 57 passed: fidelity + tutor suite)
- [ ] C Live model re-check with `培训制度.docx` + follow-up「周一入职具体哪天截止」
- [ ] D Commit / push branch (GitHub auth for this Cursor account may still be needed)
- [ ] 4A Open registration + `not_a_member` fix
- [ ] Day 3–5

## Next

1. Finish live model evidence → `day02/FIX_REPORT.md`
2. Commit on `grokbot/day2-fidelity` from box; sync carefully to GitHub when credentials available
3. Start 4A (registration + TrainingGateway)

## Commits (box)

- Branch `grokbot/docs-sync-and-day2` @ `a96a752` (base `80d53f4`)
- `git push` blocked: GitHub HTTPS credentials not available to this bot (`could not read Username`). Connect GitHub / provide push access; **no force-push used**.
