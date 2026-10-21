"""Day 9: capture matching V2 code/data, verify, and demonstrate isolated recovery.

Capture requires stopped writers. SQLite backup creates each consistent database;
it does not make the two databases a joint transaction. Secrets are external.
The recovery adapter relocates ONLY the in-memory business path returned by the
V2 Saver. It never edits serialized checkpoints or executes a V3 Graph.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone


FORMAT = "skilltree-v2-recovery-1"
EXCLUDED_PARTS = {".git", ".venv", "venv", "work", "__pycache__", ".pytest_cache", "data"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def database_files(directory):
    return {str(path.resolve()): sha256(path) for name in ("learning.sqlite", "checkpoints.sqlite")
            for path in [Path(directory) / name, Path(directory) / (name + "-wal")]
            if path.is_file() and (not path.name.endswith("-wal") or path.stat().st_size > 0)}


def sqlite_readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)


def sqlite_backup(source, destination):
    """Includes committed WAL pages; does not write to the source connection."""
    with sqlite_readonly(source) as original, sqlite3.connect(destination) as restored:
        original.backup(restored)


def inventory(path):
    with sqlite_readonly(path) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise ValueError(f"SQLite integrity check failed: {Path(path).name}")
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {name: conn.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                  for name in tables}
        schema = list(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
        return {"integrity_check": "ok", "table_counts": counts,
                "schema_sha256": hashlib.sha256(json.dumps(schema).encode()).hexdigest()}


def check_writers(repo):
    """Inspect relevant Windows processes; never stop another process automatically."""
    if os.name != "nt":
        raise RuntimeError("Non-Windows capture needs an explicit stopped-writer implementation")
    script = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|uvicorn' } | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                               text=True, encoding="utf-8", timeout=30, check=True)
    processes = json.loads(completed.stdout or "[]")
    if isinstance(processes, dict):
        processes = [processes]
    relevant = []
    blocked = []
    for item in processes:
        command = item.get("CommandLine") or ""
        generic_v2_server = "uvicorn" in command.lower() and "app.main:app" in command.lower()
        if str(repo).lower() not in command.lower() and not generic_v2_server:
            continue
        # Tests use their own temporary databases; this CLI does not execute V2.
        isolated = ("pytest" in command or "tests\\support\\" in command or "tests/support/" in command
                    or "day9_v2_recovery.py" in command)
        relevant.append({"pid": item["ProcessId"], "classification": "isolated_test_or_recovery" if isolated else "possible_v2_writer"})
        if not isolated:
            blocked.append(item["ProcessId"])
    if blocked:
        raise RuntimeError(f"Stop V2 writers before capture; possible writer PIDs: {blocked}")
    return {"method": "Win32_Process project-path scan plus source main/WAL hash stability",
            "relevant_processes": relevant, "possible_v2_writers": []}


def allowed_code(relative):
    path = Path(relative)
    if any(part in EXCLUDED_PARTS for part in path.parts):
        return False
    normalized = path.as_posix().lower()
    if normalized.startswith(("app/v3/", "configs/v3/", "materials/v3/")):
        return False
    if "day9" in normalized or path.name.startswith("test_v3_"):
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    return path.suffix.lower() not in {".sqlite", ".db", ".log", ".pem", ".key", ".pyc", ".pyo"}


def git(repo, *args):
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=repo, capture_output=True,
                          text=True, encoding="utf-8", check=True).stdout


def capture(repo, package):
    repo, package = Path(repo).resolve(), Path(package).resolve()
    if package.exists():
        raise FileExistsError("Use a fresh package directory; existing recovery packages are immutable")
    if package == repo or repo in package.parents and not (repo / "work") in package.parents:
        raise ValueError("Package must be outside runtime code, or in the local work directory")
    writer_check = check_writers(repo)
    before = database_files(repo / "data")
    if len([key for key in before if key.endswith(".sqlite")]) != 2:
        raise FileNotFoundError("Capture requires both V2 business and Checkpoint databases")
    time.sleep(0.15)
    if database_files(repo / "data") != before:
        raise RuntimeError("V2 databases are changing; stop writers and capture again")
    package.mkdir(parents=True)
    (package / "data").mkdir()
    for name in ("learning.sqlite", "checkpoints.sqlite"):
        sqlite_backup(repo / "data" / name, package / "data" / name)
    # ls-files combines the index with working-tree bytes, including necessary
    # untracked runtime helpers. It does not restore HEAD over the user's work.
    candidates = set(git(repo, "ls-files", "-z").split("\0"))
    candidates.update(git(repo, "ls-files", "--others", "--exclude-standard", "-z").split("\0"))
    copied = []
    for relative in sorted(filter(None, candidates)):
        source = repo / relative
        if not allowed_code(relative) or not source.is_file():
            continue
        target = package / "code" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(relative)
    freeze = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True,
                            text=True, encoding="utf-8", timeout=60, check=True).stdout
    # Direct URL dependencies may contain credentials: never package userinfo.
    freeze = re.sub(r"(https?://)[^/\s@]+@", r"\1[REDACTED]@", freeze)
    (package / "environment").mkdir()
    (package / "environment" / "pip-freeze.txt").write_text(freeze, encoding="utf-8")
    write_json(package / "environment" / "python.json", {
        "version": sys.version, "executable": sys.executable, "platform": sys.platform,
        "secret_configuration": "External protected .env; excluded from package. Offline demo needs no key."})
    (package / "environment" / "git-status.txt").write_text(git(repo, "status", "--short"), encoding="utf-8")
    baseline = {}
    baseline_log = repo / "work" / "day9" / "baseline-pytest.log"
    if baseline_log.is_file():
        baseline_text = baseline_log.read_text(encoding="utf-8")
        passed = re.search(r"(\d+) passed in ([\d.]+)s", baseline_text)
        if passed:
            shutil.copy2(baseline_log, package / "environment" / "baseline-pytest.log")
            test_list = baseline_log.with_name("baseline-test-files.txt")
            if test_list.is_file():
                shutil.copy2(test_list, package / "environment" / test_list.name)
            baseline = {"passed": int(passed[1]), "duration_seconds": float(passed[2]),
                        "evidence": "environment/baseline-pytest.log", "scope": "Actual pre-V3 V2 test file list"}
    after = database_files(repo / "data")
    if before != after:
        raise RuntimeError("V2 main/WAL changed during capture; discard this incomplete package")
    code_source_unchanged = all(sha256(repo / name) == sha256(package / "code" / name) for name in copied)
    if not code_source_unchanged:
        raise RuntimeError("V2 source changed during capture; recapture matching code and data")
    files = {path.relative_to(package).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
             for path in sorted(package.rglob("*")) if path.is_file()}
    manifest = {"format": FORMAT, "captured_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                "source_repo": str(repo), "git_head": git(repo, "rev-parse", "HEAD").strip(),
                "code_basis": "Current V2 working tree and necessary untracked runtime files, not clean HEAD",
                "writer_check": writer_check, "source_database_hashes_before": before,
                "source_database_hashes_after": after, "source_data_unchanged": before == after,
                "code_source_unchanged": code_source_unchanged,
                "databases": {name: inventory(package / "data" / name)
                              for name in ("learning.sqlite", "checkpoints.sqlite")},
                "materials": {"storage": "V2 built-in app/tools/knowledge.py captured with code",
                              "additional_directories": [name for name in copied if name.startswith("materials/")]},
                "private_package": True, "secrets_included": False,
                "baseline_tests": baseline,
                "excluded": [".env", ".git", "venv", "work", "private logs", "V3/Day9 implementation"],
                "files": files}
    write_json(package / "manifest.json", manifest)
    return manifest


def verify(package):
    package = Path(package).resolve()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise ValueError("Unsupported recovery manifest format")
    if set(manifest.get("databases", {})) != {"learning.sqlite", "checkpoints.sqlite"}:
        raise ValueError("Recovery package must contain both databases")
    for required in ("code/app/graph.py", "code/app/state.py", "code/app/services/learning_session.py", "code/app/db/repository.py"):
        if required not in manifest.get("files", {}):
            raise ValueError("Recovery package is missing matching V2 implementation")
    for relative, expected in manifest["files"].items():
        path = (package / relative).resolve()
        if package not in path.parents:
            raise ValueError("Recovery package path escapes package directory")
        if not path.is_file() or sha256(path) != expected["sha256"] or path.stat().st_size != expected["bytes"]:
            raise ValueError(f"Recovery package missing or damaged file: {relative}")
    extra = [path.relative_to(package).as_posix() for path in package.rglob("*")
             if path.is_file() and path.name != "manifest.json"
             and path.relative_to(package).as_posix() not in manifest["files"]
             and not path.name.endswith("-shm") and not (path.name.endswith("-wal") and path.stat().st_size == 0)]
    if extra:
        raise ValueError(f"Recovery package contains untracked files: {extra}")
    for name, expected in manifest["databases"].items():
        if name not in {"learning.sqlite", "checkpoints.sqlite"}:
            raise ValueError("Unexpected database filename")
        if inventory(package / "data" / name) != expected:
            raise ValueError(f"Recovery database counts/schema mismatch: {name}")
    return manifest


def run_worker(package, directory, phase, project_id=None):
    manifest = json.loads((Path(package) / "manifest.json").read_text(encoding="utf-8"))
    args = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "_worker", "--code",
            str(Path(package).resolve() / "code"), "--directory", str(Path(directory).resolve()), "--phase", phase,
            "--original-business", str(Path(manifest["source_repo"]) / "data" / "learning.sqlite")]
    if project_id:
        args += ["--project-id", project_id]
    completed = subprocess.run(args, cwd=directory, capture_output=True, text=True, encoding="utf-8",
                               timeout=60, check=True)
    return json.loads(completed.stdout.strip().splitlines()[-1])


def demo(package, directory, *, project_id=None, fake_wait_answer=False):
    package, directory = Path(package).resolve(), Path(directory).resolve()
    manifest = verify(package)
    if directory.exists():
        raise FileExistsError("Use a new isolated recovery directory")
    source_repo = Path(manifest["source_repo"])
    if directory == source_repo or directory in source_repo.parents or (source_repo / "data") == directory or (source_repo / "data") in directory.parents:
        raise ValueError("Recovery may not target the original V2 runtime data")
    if directory == package or package in directory.parents:
        raise ValueError("Do not execute recovery inside the immutable package")
    original_before = database_files(source_repo / "data")
    directory.mkdir(parents=True)
    for name in ("learning.sqlite", "checkpoints.sqlite"):
        sqlite_backup(package / "data" / name, directory / name)
    isolated_before = database_files(directory)
    first = run_worker(package, directory, "inspect", project_id)
    waiting = [item for item in first["projects"] if item["wait_type"] in {"wait_answer", "wait_learning", "pause"}]
    selected = next((item for item in waiting if item["project_id"] == project_id), None) if project_id else None
    if not selected and not project_id:
        selected = next((item for item in waiting if item["wait_type"] == "wait_answer"), None)
        selected = selected or next((item for item in waiting if item["pending_input_id"]), None)
        selected = selected or next(iter(waiting), None)
    if selected is None:
        raise ValueError("No matching real waiting V2 checkpoint; inspect project inventory")
    restarted = run_worker(package, directory, "inspect", selected["project_id"])
    second = next(item for item in restarted["projects"] if item["project_id"] == selected["project_id"])
    if selected != second:
        raise AssertionError("Restored identity/wait/quiz changed across processes")
    result = {"format": FORMAT, "original_data_unchanged": original_before == database_files(source_repo / "data"),
              "isolated_read_unchanged": isolated_before == database_files(directory),
              "package_verified_after_demo": bool(verify(package)), "inventory": first,
              "real_restored_project": selected, "restart_process_ids": [first["process_id"], restarted["process_id"]],
              "model_calls": 0, "recovery_adapter": "Read-only Saver overlays learning_db_path in memory; no Checkpoint table edits; matching V2 build_graph and LearningSession.restore",
              "hash_scope": "Database main files and nonempty WAL; zero-byte transient WAL/SHM contain no business facts",
              "original_database_hashes_before": original_before,
              "original_database_hashes_after": database_files(source_repo / "data"),
              "genuine_original_wait_answer_available": any(item["wait_type"] == "wait_answer" for item in waiting)}
    if fake_wait_answer:
        generated = run_worker(package, directory, "fake_wait_answer", "day9_isolated_fake_wait_answer")
        restored = run_worker(package, directory, "inspect", generated["project_id"])
        actual = next(item for item in restored["projects"] if item["project_id"] == generated["project_id"])
        if generated["identity"] != actual:
            raise AssertionError("Fake wait-answer identity/quiz failed restart recovery")
        result["fake_wait_answer_demo"] = {"label": "New Fake scenario created only in isolated copy; not existing user waiting-answer evidence",
                                           "identity": actual, "generation_process_id": generated["process_id"],
                                           "recovery_process_id": restored["process_id"], "real_model_calls": 0}
    if original_before != database_files(source_repo / "data"):
        raise AssertionError("Original V2 data changed during recovery")
    verify(package)
    write_json(directory / "recovery-evidence.json", result)
    return result


def worker(args):
    # The process imports ONLY the captured V2 implementation. Exclude the live
    # repo from search paths and disable .env ingestion before V2 module imports.
    sys.dont_write_bytecode = True
    code, directory = Path(args.code).resolve(), Path(args.directory).resolve()
    sys.path = [str(code)] + [path for path in sys.path[1:] if Path(path or ".").resolve() != Path(__file__).resolve().parent]
    import dotenv
    dotenv.load_dotenv = lambda *a, **kw: False
    import socket
    def forbidden(*a, **kw):
        raise AssertionError("Recovery read must not call a model or the network")
    socket.socket.connect = forbidden
    import app.agents.planner as planner
    import app.agents.tutor as tutor
    import app.agents.assessment as assessment
    import app.agents.diagnosis as diagnosis
    import app.services.llm as llm
    for module in (planner, tutor, assessment, diagnosis, llm):
        module.get_llm = forbidden
    planner.generate_plan = tutor.generate_tutor_content = assessment.generate_quiz = forbidden
    assessment.grade_short_answer = diagnosis.run_real_diagnosis = forbidden
    from app.db.repository import LearningRepository
    from app.graph import build_graph
    from app.services.learning_session import LearningSession, open_learning_session
    from langgraph.checkpoint.sqlite import SqliteSaver

    business, checkpoint = directory / "learning.sqlite", directory / "checkpoints.sqlite"

    class RelocatedReadSaver(SqliteSaver):
        def get_tuple(self, config):
            value = super().get_tuple(config)
            if value is None:
                return None
            copied = copy.deepcopy(value.checkpoint)
            saved_path = copied.get("channel_values", {}).get("learning_db_path")
            if saved_path:
                if Path(saved_path).resolve() not in {Path(args.original_business).resolve(), business.resolve()}:
                    raise ValueError("Checkpoint references an unrelated business database; refusing relocation")
                copied["channel_values"]["learning_db_path"] = str(business)
            writes = []
            for task, channel, pending in (value.pending_writes or []):
                if channel == "learning_db_path":
                    if Path(pending).resolve() not in {Path(args.original_business).resolve(), business.resolve()}:
                        raise ValueError("Pending checkpoint write references an unrelated business database")
                    pending = str(business)
                writes.append((task, channel, pending))
            return value._replace(checkpoint=copied, pending_writes=writes)

    def read_projects():
        from app.services.project_view import build_project_view
        with sqlite_readonly(checkpoint) as connection:
            saver = RelocatedReadSaver(connection)
            # Exhaust list before get_state: SqliteSaver's cursor lock spans yields.
            threads = sorted({item.config["configurable"]["thread_id"] for item in saver.list(None)})
            graph = build_graph(checkpointer=saver)
            projects = []
            for project in threads:
                if args.project_id and project != args.project_id:
                    continue
                session = LearningSession(graph, project, business.resolve(), checkpoint.resolve())
                state = session.restore()
                snapshot = session.snapshot()
                # Read-only repository: do not invoke its schema-creating constructor.
                repo = LearningRepository.__new__(LearningRepository)
                repo.db_path = business.resolve()
                repo.conn = sqlite_readonly(business)
                repo.conn.row_factory = sqlite3.Row
                try:
                    public = build_project_view(session, repo)
                    stored = repo.get_assessment(state["assessment_id"]) if state.get("assessment_id") else None
                    quiz = state.get("quiz") or {}
                    if quiz and state.get("assessment_id") and (stored is None or stored["quiz"] != quiz):
                        raise ValueError("Recovered quiz is inconsistent with its business assessment")
                    projects.append({"project_id": project, "thread_id": session.config["configurable"]["thread_id"],
                                     "pending_input_id": state.get("pending_input_id"), "assessment_id": state.get("assessment_id"),
                                     "current_node_id": state.get("current_node_id"), "next": list(snapshot.next),
                                     "wait_type": snapshot.interrupts[0].value.get("type") if snapshot.interrupts else None,
                                     "public_page": public.page_state if public else None,
                                     "lesson_preview": public.lesson[:300] if public else "",
                                     "lesson_sha256": hashlib.sha256((public.lesson if public else "").encode()).hexdigest(),
                                     "public_quiz": assessment.build_public_quiz(quiz) if quiz else None,
                                     "quiz_sha256": hashlib.sha256(json.dumps(quiz, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                                     "assessment_status": stored["status"] if stored else None,
                                     "business_quiz_matches_checkpoint": stored["quiz"] == quiz if stored and quiz else None})
                finally:
                    repo.conn.close()
            with sqlite_readonly(business) as connection:
                orphan = [row[0] for row in connection.execute(
                    "SELECT DISTINCT project_id FROM assessments WHERE status='awaiting_answer'") if row[0] not in threads]
            return {"projects": projects, "awaiting_answer_business_projects_without_checkpoint": orphan,
                    "process_id": os.getpid(), "code_root": str(code), "real_model_calls": 0}

    if args.phase == "fake_wait_answer":
        from app.models.schemas import TreePlan, AssessmentQuiz
        def fake_plan(goal):
            return TreePlan.model_validate({"nodes": [{"id": f"fake_node_{i}", "title": f"Fake node {i}",
                "description": "Isolated recovery sample", "difficulty": "beginner", "estimated_minutes": 10,
                "objectives": [{"id": f"objective_{i}", "description": "Explain assignment"}],
                "prerequisite_ids": [] if i == 0 else [f"fake_node_{i-1}"]} for i in range(8)]})
        planner.generate_plan = fake_plan
        tutor.generate_tutor_content = lambda state, node: "Fake recovery sample: assignment stores a value."
        def fake_quiz(node, assessment_id, **kwargs):
            return AssessmentQuiz.model_validate({"assessment_id": assessment_id, "node_id": node.id, "questions": [
                {"id": "q1", "type": "single_choice", "objective_id": node.objectives[0].id,
                 "prompt": "Which statement assigns a value?", "options": ["x = 3", "x == 3"],
                 "answer_key": "x = 3", "rubric": "Select assignment.", "max_score": 50},
                {"id": "q2", "type": "short_answer", "objective_id": node.objectives[0].id,
                 "prompt": "Explain assignment.", "answer_key": "Stores a value.", "rubric": "Explain storage.", "max_score": 50}]})
        assessment.generate_quiz = fake_quiz
        with open_learning_session(args.project_id, checkpoint_db_path=checkpoint, learning_db_path=business) as session:
            session.start("Day 9 isolated Fake waiting-answer sample")
            session.resume({"action": "start_quiz"})
        identity = read_projects()["projects"][0]
        print(json.dumps({"project_id": args.project_id, "identity": identity, "process_id": os.getpid()}, ensure_ascii=False))
    else:
        print(json.dumps(read_projects(), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    capture_parser = actions.add_parser("capture")
    capture_parser.add_argument("--repo", default=str(Path(__file__).resolve().parent))
    capture_parser.add_argument("--package", required=True)
    verify_parser = actions.add_parser("verify")
    verify_parser.add_argument("--package", required=True)
    for name in ("demo", "recover"):
        demo_parser = actions.add_parser(name)
        demo_parser.add_argument("--package", required=True)
        demo_parser.add_argument("--directory", required=True)
        demo_parser.add_argument("--project-id")
        demo_parser.add_argument("--fake-wait-answer", action="store_true")
    worker_parser = actions.add_parser("_worker")
    worker_parser.add_argument("--code", required=True)
    worker_parser.add_argument("--directory", required=True)
    worker_parser.add_argument("--phase", choices=("inspect", "fake_wait_answer"), required=True)
    worker_parser.add_argument("--original-business", required=True)
    worker_parser.add_argument("--project-id")
    args = parser.parse_args()
    if args.command == "_worker":
        worker(args)
    elif args.command == "capture":
        value = capture(args.repo, args.package)
        print(json.dumps({"package": str(Path(args.package).resolve()), "captured_files": len(value["files"]),
                          "source_data_unchanged": value["source_data_unchanged"]}, ensure_ascii=False))
    elif args.command == "verify":
        value = verify(args.package)
        print(json.dumps({"verified": True, "files": len(value["files"]), "databases": value["databases"]}, ensure_ascii=False))
    else:
        value = demo(args.package, args.directory, project_id=args.project_id, fake_wait_answer=args.fake_wait_answer)
        print(json.dumps({"original_data_unchanged": value["original_data_unchanged"],
                          "real_restored_project": value["real_restored_project"],
                          "fake_wait_answer_demo": value.get("fake_wait_answer_demo")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
