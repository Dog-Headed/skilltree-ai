"""Recovery engineering evidence only: injected Fake content, no paid model."""
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

import day13_recovery as recovery
from app.v3.learning import LearningService
from app.v3.learning_repository import LearningRepository
from app.v3.storage import V3Paths
from tests.day11_support import build_frozen_project, FakeLearningModel, learning_event, answers_for_quiz

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def local_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    # Minimal matching runtime + materials with no dependency on this checkout's
    # Git metadata or actual data. No .env contents are read from the checkout.
    for name in ("app", "materials", "configs"):
        shutil.copytree(ROOT / name, repo / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("app.py", "requirements.txt", "day13_recovery.py"):
        shutil.copyfile(ROOT / name, repo / name)
    (repo / ".env").write_text("OPENAI_API_KEY=private-test-token-never-package", encoding="utf-8")
    (repo / ".env.example").write_text("OPENAI_API_KEY=your-key-here\n", encoding="utf-8")
    (repo / "credentials.json").write_text('{"token":"also-private-test-token"}', encoding="utf-8")
    (repo / "work").mkdir()
    # Fast deterministic runtime evidence; capture still uses its real pip-list
    # command in CLI. No tests turn a running app into an attested idle service.
    monkeypatch.setattr(recovery, "check_writers", lambda *args: {"method": "Fake isolated stores; no live service"})
    return repo


def make_package(local_repo, tmp_path, *, complete_first=False):
    case = build_frozen_project(tmp_path / "isolated-v3")
    service = LearningService(case["paths"], llm=case["model"])
    view = service.start(case["project_id"], str(uuid4()))
    view = service.resume(case["project_id"], learning_event(view, "start_quiz"))
    if complete_first:
        with LearningRepository(case["paths"]) as repo:
            quiz = json.loads(repo.get_assessment(case["project_id"], view["assessment_id"])["quiz_json"])
        view = service.resume(case["project_id"], learning_event(view, "submit_answer", answers=answers_for_quiz(quiz)))
        assert view["completed_node_ids"] == ["node_1"]
        view = service.resume(case["project_id"], learning_event(view, "start_quiz"))
    package = local_repo / "work" / "private-package"
    before = recovery.file_fingerprints(case["paths"].root)
    manifest = recovery.capture(local_repo, package, data_root=case["paths"].root, writers_stopped=True)
    assert recovery.file_fingerprints(case["paths"].root) == before
    return case, view, package, manifest


def test_three_store_restore_preserves_wait_identity_saved_results_and_no_model_on_refresh(local_repo, tmp_path):
    case, waiting, package, manifest = make_package(local_repo, tmp_path, complete_first=True)
    assert not manifest["git"]["available"]
    assert set(manifest["databases"]) == set(recovery.DATABASES)
    assert len(manifest["identities"]["checkpoint_threads"]["learning-checkpoints.sqlite"]) == 1
    before_package = {p.relative_to(package).as_posix(): recovery.digest(p) for p in package.rglob("*") if p.is_file()}
    assert recovery.verify(package) == manifest
    assert before_package == {p.relative_to(package).as_posix(): recovery.digest(p) for p in package.rglob("*") if p.is_file()}
    restored = recovery.restore(package, tmp_path / "new-machine")
    paths = V3Paths(restored["data_root"])
    # Import the PACKAGED matching implementation in another interpreter. Its
    # read-only recovery must not depend on this process or the source checkout.
    script = ("import json,sys; from app.v3.learning import LearningService; "
              "from app.v3.storage import V3Paths; "
              "s=LearningService(V3Paths(sys.argv[1]),llm=object()); "
              "print(json.dumps(s.read(sys.argv[2]),ensure_ascii=False))")
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(paths.root), case["project_id"]],
                           cwd=restored["code_root"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert child.returncode == 0, child.stdout + child.stderr
    reopened = json.loads(child.stdout)
    assert reopened["assessment_id"] == waiting["assessment_id"]
    assert reopened["pending_input_id"] == waiting["pending_input_id"]
    model = FakeLearningModel()
    service = LearningService(paths, llm=model)
    after = service.read(case["project_id"])
    for key in ("project_id", "thread_id", "pending_input_id", "assessment_id", "draft_revision", "page_state", "quiz", "completed_node_ids"):
        assert after[key] == waiting[key]
    assert after["page_state"] == "quiz" and after["completed_node_ids"] == ["node_1"]
    assert not model.calls
    with case_service_graph(service) as graph:
        snapshot = graph.get_state(service._config(case["project_id"]))
        assert snapshot.next == ("wait",) and snapshot.interrupts
    # Reopening the same unanswered assessment reuses its saved frozen quiz.
    after = service.resume(case["project_id"], learning_event(after, "return_to_teaching"))
    after = service.resume(case["project_id"], learning_event(after, "start_quiz"))
    assert after["assessment_id"] == waiting["assessment_id"]
    assert model.call_counts["AssessmentQuiz"] == 0
    with LearningRepository(paths) as repo:
        rows = repo.conn.execute("SELECT * FROM assessments WHERE project_id=? AND status='graded'", (case["project_id"],)).fetchall()
        assert len(rows) == 1 and rows[0]["evaluation_json"] and rows[0]["diagnosis_json"]
        assert repo.conn.execute("SELECT COUNT(*) FROM learning_transitions").fetchone()[0] == 1
        assert repo.rounds(case["project_id"], "node_1")["effective_rounds"] == 1
    assert restored["checkpoint_payloads_rewritten"] is False and restored["model_calls"] == 0


def case_service_graph(service):
    # Named wrapper keeps the test focused on actual persisted Graph state.
    return service._graph()


def test_secret_files_and_v2_databases_are_excluded_and_restore_cannot_overwrite(local_repo, tmp_path):
    v2 = local_repo / "data"
    v2.mkdir()
    for name in recovery.DATABASES[:2]:
        with sqlite3.connect(v2 / name) as conn:
            conn.execute("CREATE TABLE v2_only(value TEXT)")
            conn.execute("INSERT INTO v2_only VALUES ('original')")
    v2_before = recovery.file_fingerprints(v2, recovery.DATABASES[:2])
    case, _, package, manifest = make_package(local_repo, tmp_path)
    assert manifest["v2_untouched"] and manifest["v2_source_hashes"] == v2_before
    assert recovery.file_fingerprints(v2, recovery.DATABASES[:2]) == v2_before
    assert not (package / "code" / ".env").exists()
    assert not (package / "code" / "credentials.json").exists()
    assert (package / "code" / ".env.example").exists()
    assert not (package / "data" / "learning.sqlite").exists()
    for path in package.rglob("*"):
        if path.is_file():
            assert b"private-test-token" not in path.read_bytes()
    target = tmp_path / "restore"
    with pytest.raises(ValueError, match="isolated"):
        recovery.restore(package, case["paths"].root / "nested-restore")
    recovery.restore(package, target)
    before = recovery.file_fingerprints(target / "code" / "data" / "v3")
    with pytest.raises(FileExistsError):
        recovery.restore(package, target)
    assert recovery.file_fingerprints(target / "code" / "data" / "v3") == before


@pytest.mark.parametrize("attack", ["tamper", "extra_secret", "listed_secret", "traversal", "missing_store", "wrong_version", "missing_manifest"])
def test_verifier_rejects_corruption_missing_stores_and_dangerous_paths(local_repo, tmp_path, attack):
    _, _, package, manifest = make_package(local_repo, tmp_path)
    if attack == "tamper":
        (package / "code" / "app.py").write_text("tampered", encoding="utf-8")
    elif attack == "extra_secret":
        (package / ".env").write_text("PRIVATE=yes", encoding="utf-8")
    elif attack == "listed_secret":
        path = package / "code" / ".env"
        path.write_text("PRIVATE=yes", encoding="utf-8")
        manifest["files"]["code/.env"] = {"sha256": recovery.digest(path), "bytes": path.stat().st_size}
    elif attack == "traversal":
        manifest["files"]["code/../../outside.py"] = {"sha256": "0" * 64, "bytes": 0}
    elif attack == "missing_store":
        (package / "data" / "v3" / "learning-checkpoints.sqlite").unlink()
    elif attack == "wrong_version":
        manifest["versions"]["contract"] = "future-contract"
    elif attack == "missing_manifest":
        (package / "manifest.json").unlink()
    if attack != "missing_manifest":
        recovery._write(package / "manifest.json", manifest)
    with pytest.raises((ValueError, FileNotFoundError)):
        recovery.verify(package)
    assert not (tmp_path / "outside.py").exists()


def test_capture_requires_stopped_writers_and_three_stores(local_repo, tmp_path):
    with pytest.raises(ValueError, match="Stop ALL writers"):
        recovery.capture(local_repo, local_repo / "work" / "no-attestation")
    with pytest.raises(FileNotFoundError, match="All three"):
        recovery.capture(local_repo, local_repo / "work" / "missing", data_root=tmp_path / "empty", writers_stopped=True)
    with pytest.raises(ValueError, match="V2 data"):
        recovery.capture(local_repo, local_repo / "work" / "v2", data_root=local_repo / "data", writers_stopped=True)


def test_capture_detects_changed_checkpoint_and_never_publishes_manifest(local_repo, tmp_path, monkeypatch):
    case = build_frozen_project(tmp_path / "isolated-v3")
    original = recovery.file_fingerprints
    calls = 0
    def fingerprints(directory, names=recovery.DATABASES):
        nonlocal calls
        value = original(directory, names)
        if Path(directory) == case["paths"].root:
            calls += 1
            if calls > 1:
                value["checkpoints.sqlite"] = {"sha256": "changed-by-noncooperating-writer", "bytes": 0}
        return value
    monkeypatch.setattr(recovery, "file_fingerprints", fingerprints)
    package = local_repo / "work" / "incomplete"
    with pytest.raises(RuntimeError, match="V3 data changed"):
        recovery.capture(local_repo, package, data_root=case["paths"].root, writers_stopped=True)
    assert not (package / "manifest.json").exists()
    with pytest.raises(ValueError, match="manifest"):
        recovery.verify(package)


def test_business_write_gate_excludes_new_project_creation(local_repo, tmp_path, monkeypatch):
    case = build_frozen_project(tmp_path / "isolated-v3")
    original = recovery._readonly
    attempted = []
    def readonly(path, **kwargs):
        if Path(path) == case["paths"].learning and not attempted:
            with sqlite3.connect(path, timeout=0) as writer:
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    writer.execute("BEGIN IMMEDIATE")
            attempted.append(True)
        return original(path, **kwargs)
    monkeypatch.setattr(recovery, "_readonly", readonly)
    recovery.capture(local_repo, local_repo / "work" / "gate", data_root=case["paths"].root, writers_stopped=True)
    assert attempted == [True]


def test_capture_refuses_a_project_lock_owned_by_another_process(local_repo, tmp_path):
    case = build_frozen_project(tmp_path / "isolated-v3")
    script = ("import sys; from app.v3.execution import project_execution; from app.v3.storage import V3Paths; "
              "lock=project_execution(sys.argv[2],V3Paths(sys.argv[1])); lock.__enter__(); "
              "print('locked',flush=True); sys.stdin.readline(); lock.__exit__(None,None,None)")
    child = subprocess.Popen([sys.executable, "-X", "utf8", "-c", script, str(case["paths"].root), case["project_id"]],
                             cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8")
    package = local_repo / "work" / "active-project"
    try:
        assert child.stdout.readline().strip() == "locked"
        with pytest.raises(ValueError, match="Project execution is active"):
            recovery.capture(local_repo, package, data_root=case["paths"].root, writers_stopped=True)
        assert not package.exists()
    finally:
        child.communicate("release\n", timeout=15)
        assert child.returncode == 0
