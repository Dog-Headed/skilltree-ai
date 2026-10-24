# Development guide

This guide describes the current V3 implementation. The browser runs locally without a frontend build. Start with [installation and use](GETTING_STARTED.md) for environment and storage setup.

## Source map

| Path | Responsibility |
| --- | --- |
| `app.py` | Default V3 launcher on loopback port 8765 |
| `app/v3/learning_api.py`, `public_view.py` | Current product API and public response projections |
| `app/v3/preparation.py`, `planner.py`, `materials.py` | Profile, source import, planning, and explicit confirmation |
| `app/v3/learning.py`, `tutor.py`, `assessment.py`, `diagnosis.py` | Learning graph and model-assisted learning operations |
| `app/v3/capabilities.py`, `evaluators.py`, `guard.py` | Runtime capability registry, evaluators, and deterministic progression checks |
| `app/v3/repository.py`, `learning_repository.py` | Business facts and idempotent writes |
| `app/v3/storage.py`, `runtime_storage.py`, `execution.py`, `model_tasks.py` | Separate stores, checkpoints, execution recovery, and persistent request budgets |
| `app/v3/legacy.py` | Read-only V2 history projection |
| `app/static/v3.html`, `v3.css`, `v3.js` | Current Chinese browser workbench |
| `configs/v3/`, `materials/v3/`, `evals/v3/` | Subject/policy configurations, example sources, and draft evaluation cases |
| `tests/` | Contract, evaluator, workflow, persistence, and browser regressions |

The [current API contract](v3/DAY12_API.md) covers routes and recovery semantics. Runtime `/capabilities` and `app/v3/capabilities.py` are the source of truth for available evaluators. `docs/v3/capabilities.json` is an older foundation snapshot; its planned statuses do not describe the current runtime. The older V2 architecture document and earlier development records are historical references.

## Verification

Use the installed Python 3.11 virtual environment. On Windows replace `python` with `.\.venv\Scripts\python.exe`; on macOS/Linux activate `.venv` first. The pytest fixtures block real model calls and isolate storage, so no model key is needed.

For launcher, public API, and legacy-read isolation changes:

```sh
python -X utf8 -m pytest tests/test_app_launcher.py tests/test_day12_public_api.py tests/test_day12_legacy.py tests/test_day12_legacy_api.py -q
```

For offline subject-pack consistency:

Keep `.gitattributes` in place: frozen material Markdown uses LF; case JSON and pack manifests use CRLF. These rules preserve the existing content hashes and aggregate freeze digest across Git checkouts without changing content or expectations.

```sh
python -X utf8 day10_check_fixtures.py
```

For the complete automated suite:

```sh
python -X utf8 -m pytest -q
```

Browser regressions are optional test tooling and need Node.js plus Playwright. One isolated setup, from the repository root:

```sh
npm install --prefix work/browser-tools playwright
```

Windows PowerShell, using an installed Microsoft Edge:

```powershell
$env:NODE_PATH = (Resolve-Path work/browser-tools/node_modules).Path
$env:SKILLTREE_TEST_BROWSER_CHANNEL = 'msedge'
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_day12_frontend.py -q
```

macOS/Linux, using Playwright Chromium:

```sh
./work/browser-tools/node_modules/.bin/playwright install chromium
export NODE_PATH="$PWD/work/browser-tools/node_modules"
python -X utf8 -m pytest tests/test_day12_frontend.py -q
```

On Linux the browser may also require system libraries; use Playwright's `install --with-deps chromium` when appropriate for your environment. The browser tests use isolated stores and Fake content. If Node or Playwright is unavailable, they skip; a skipped browser test is not a browser pass. You can set `DAY12_FRONTEND_EVIDENCE_DIR` to a local directory to retain screenshots and request traces.

## Evaluation boundaries

- Choice and restricted numeric evaluation run in application code; text-rubric evaluation uses the configured model and can be wrong.
- Valid JSON, valid citations, or a completed workflow do not establish teaching or scoring quality.
- The 36 V3 subject cases remain draft expectations pending human review. The [evaluation dataset notes](../evals/v3/README.md) describe the frozen preparation snapshot, debug/holdout split, and review discipline. Their original statements about missing evaluators describe that earlier snapshot; the current runtime has numeric and text handlers.
- Keep human approval, Fake workflow checks, and real-model quality reports distinct. Review standards before evaluation; avoid tuning on held-out cases.

## Screenshots

The three homepage PNGs are unaltered captures of the shipped V3 interface at **1440 × 1000**, taken on **2026-10-24** from source commit `97d8bc4c03cd33af13bdfcb7e4858c968833b939`:

| Asset | Actual page state |
| --- | --- |
| [v3-plan.png](assets/v3-plan.png) | Mathematics example, imported sources, plan review before confirmation |
| [v3-learning.png](assets/v3-learning.png) | Same example, confirmed plan, active lesson and source references |
| [v3-assessment.png](assets/v3-assessment.png) | Same example, numeric and text questions awaiting an answer |

Capture method: run `day12_demo_server.py` with a fresh root under `work/`, then use an isolated Playwright/Edge browser to create a mathematics record, import its example materials, confirm the profile, confirm the plan, start learning, and start an assessment. No mock HTML, image generation, or page-content replacement is used. The demo's existing Fake provider supplies content and shortened plans; no paid model calls or deployment databases are involved. The visible Fake label is preserved.

These screenshots prove the V3 pages and workflow render; they do not measure real-model learning outcomes. Existing V2 screenshots remain available as historical assets and are not presented as V3.

## Documentation contributions

Keep the English and Chinese READMEs aligned. Describe implemented behavior against current code and label future work as planned. Verify fresh-install commands in an empty directory and check relative links, anchors, and screenshot paths.

Each README has one **Latest Development** section linking only the newest development or acceptance record. Update that single pointer when a newer record is added. A small repair can be the newest record while the introduction continues to emphasize the latest delivered V3 milestone. Preserve historical development/acceptance files rather than recreating a daily log on the homepage.

Report reproducible bugs with the operation, observed page state, and expected behavior. Exclude model keys, private learner answers, and local runtime databases from public reports.
