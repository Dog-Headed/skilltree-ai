# Installation and use / 安装与使用

The [English README](../README.md#quick-start) and [中文 README](../README.zh-CN.md#快速开始) cover installation with Python 3.11. Commands below run from the repository root. On Windows, use `.\.venv\Scripts\python.exe` wherever `python` appears; on macOS/Linux, activate `.venv` first.

Clone with Git and retain `.gitattributes`: it preserves the original bytes of versioned files, including their existing LF/CRLF formats, to match frozen hashes. Do not apply a blanket newline conversion to source files or datasets.

## Model configuration

Copy `.env.example` to `.env` once, then set all three values:

```dotenv
LLM_MODEL=your-model-name
LLM_API_KEY=your-local-provider-key
LLM_BASE_URL=https://your-provider.example/v1
```

These are placeholders, not a working provider configuration. Use the model name and endpoint supplied by your provider. The adapter uses an OpenAI-compatible chat API, structured JSON output, and tool calling; provider compatibility and content quality need checking with your chosen model. The local backend loads `.env` from the repository root. Real operations can incur provider charges; simply reading project state does not call the model.

`.env` and runtime databases are ignored by Git. Do not enter keys in study materials or browser fields.

## First launch

For a **new, empty** `data/v3` directory:

```sh
python -X utf8 day11_storage.py --root data/v3
python app.py
```

The existing storage command initializes both preparation stores and the learning extension. It creates:

| File under `data/v3/` | Purpose |
| --- | --- |
| `learning.sqlite` | Projects, materials, frozen plans, assessments, and completion facts |
| `checkpoints.sqlite` | Preparation graph checkpoints |
| `learning-checkpoints.sqlite` | Learning graph checkpoints |

Open <http://127.0.0.1:8765/>. The launcher opens a browser after the server is ready; `Ctrl+C` stops it. The server binds to loopback and is intended for a local single user.

Prefer another port or an isolated data directory? Initialize that directory first, then run the alternate entry point:

```sh
python -X utf8 day11_storage.py --root work/my-v3-data
python day12_server.py --root work/my-v3-data --port 8012
```

Open <http://127.0.0.1:8012/> manually. The alternate launcher does not open a browser for you.

## Existing data

Do **not** run fresh-install initialization on every launch. Normal startup only validates storage; it does not migrate or fall back to V2.

- An already compatible V3 directory can start directly with `python app.py`.
- For compatible preparation stores that need the learning extension, stop all writers and use a **new, nonexistent** backup directory:

  ```sh
  python -X utf8 day11_storage.py --root data/v3 --backup work/v3-learning-backup-001
  ```

- Older preparation schemas may first need the explicit preparation migration. Stop writers, keep backups, and use separate new backup directories for each stage:

  ```sh
  python -X utf8 day10_storage.py --root data/v3 --migrate-day9 --backup work/v3-preparation-backup-001
  python -X utf8 day11_storage.py --root data/v3 --backup work/v3-learning-backup-001
  ```

The migration code refuses incompatible checkpoints; these commands are not a universal converter. See the [preparation contract](v3/DAY10_PREPARATION.md) and [learning runtime notes](v3/DAY11_RUNTIME.md) before upgrading older stores. Back up all three current V3 databases together while the service is stopped.

V2 files remain under `data/learning.sqlite` and `data/checkpoints.sqlite`. The V2 history entry has been removed from the browser. Existing V2 data and the compatibility read API remain; V3 does not resume V2 checkpoints or convert them into V3 projects. Never pass the V2 `data` directory as a V3 root.

## Demo without a model key

After installing `requirements.txt`, run the repository's existing isolated demo:

```sh
python day12_demo_server.py --root work/readme-demo --port 18120
```

Open <http://127.0.0.1:18120/>. No `.env` or paid model request is needed. Use a new demo directory under `work/`; this entry point refuses a root outside that directory. It uses actual V3 HTML, APIs, graphs, and SQLite with an explicitly **Fake** model and shortened two-node plans. It does not open your normal V3 or V2 databases.

This is a workflow demonstration, not evidence of real teaching, grading, or subject generalization. Stop it with `Ctrl+C`; keep demo stores separate from real study records.

## Browser workflow

1. Enter a learning goal and optional prior knowledge. AI will propose the subject, bounded first unit, and evaluation requirements; no scope or mode selector is required.
2. Create the record and optionally import an example pack or your own materials, then ask AI to prepare the plan. Without teaching materials, AI drafts labeled notes; organization-specific rules require actual documents. TXT/Markdown uploads must be UTF-8; PDFs and Word documents are not accepted.
3. Review the generated skill dependencies, source coverage, and assessment criteria. Confirm and freeze the plan before formal learning.
4. Start a lesson, ask questions, then request and answer an assessment. Numeric and explanation objectives are assessed separately when required by the plan.
5. Read feedback and follow the permitted next action: advance, remediate, review prerequisites, or resolve an uncertain assessment. Legacy exploration records still provide text Q&A without formal completion; the new creation flow has one entry point and preserves evaluator limits.
6. Reopen the record to continue. Refresh reads saved state. If a response is lost, inspect the recovered state before choosing another action.

Day 13 reference standards were approved by the user before the corresponding real-model runs; evaluation roles, exposed cases, revalidation, and failures are recorded separately in [the delivery report](v3/day13/FINAL_DELIVERY.md). This finite review does not certify arbitrary materials or model answers. See [goal-first creation](v3/GOAL_FIRST_ONBOARDING.md) for the current increment and verification.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `UnicodeDecodeError` while installing requirements on Windows | Use `python -X utf8 -m pip install -r requirements.txt`; the requirements file contains UTF-8 comments. |
| Frozen material/case hash mismatch | Use a fresh Git clone with the repository's `.gitattributes`; preserve the declared line endings rather than regenerating frozen hashes. |
| V3 storage is uninitialized or incompatible | Use the fresh-directory or existing-data procedure above; do not delete learning databases to bypass the check. |
| Browser still shows an older version | Stop the old server in its terminal, restart the intended entry point, then reload. |
| Port is already in use | Stop the service you started or use the alternate launcher with an unused port. |
| Planning or text scoring fails | Check all `.env` values and provider support for JSON output/tool calling. Model output still must satisfy application validation. |
| Requested task cannot be formally assessed | Check the browser's capability panel; adjust the goal to a supported text-based task. The UI does not offer a separate mode selector. |

The current [API contract](v3/DAY12_API.md) documents routes, state-specific actions, public fields, and recovery behavior.
