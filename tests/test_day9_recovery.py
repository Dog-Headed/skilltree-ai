"""The recovery CLI must use matching V2 code in another process and never mutate originals."""

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from app.services.learning_session import open_learning_session
from day9_v2_recovery import (
    FORMAT, allowed_code, database_files, demo, inventory, sha256, sqlite_backup, verify, write_json,
)


@pytest.fixture
def recovery_package(tmp_path):
    source = tmp_path / "original"
    data = source / "data"
    data.mkdir(parents=True)
    with open_learning_session("original_wait_answer", learning_db_path=data / "learning.sqlite",
                               checkpoint_db_path=data / "checkpoints.sqlite") as session:
        session.start("Isolated Fake test fixture")
        session.resume({"action": "start_quiz"})
        identity = dict(session.snapshot().values)
    package = tmp_path / "package"
    (package / "data").mkdir(parents=True)
    for name in ("learning.sqlite", "checkpoints.sqlite"):
        sqlite_backup(data / name, package / "data" / name)
    app_path = Path(__file__).resolve().parents[1] / "app"
    shutil.copytree(app_path, package / "code" / "app", ignore=shutil.ignore_patterns("v3", "__pycache__"))
    files = {path.relative_to(package).as_posix(): {"sha256": sha256(path), "bytes": path.stat().st_size}
             for path in package.rglob("*") if path.is_file()}
    write_json(package / "manifest.json", {"format": FORMAT, "source_repo": str(source), "files": files,
               "databases": {name: inventory(package / "data" / name)
                             for name in ("learning.sqlite", "checkpoints.sqlite")}})
    return source, package, identity


def test_restart_recovers_wait_answer_identity_without_original_or_package_writes(recovery_package, tmp_path):
    source, package, original = recovery_package
    before = database_files(source / "data")
    package_hashes = database_files(package / "data")
    result = demo(package, tmp_path / "restored")
    actual = result["real_restored_project"]
    assert actual["project_id"] == actual["thread_id"] == original["project_id"]
    assert actual["assessment_id"] == original["assessment_id"]
    assert actual["pending_input_id"] == original["pending_input_id"]
    assert actual["wait_type"] == "wait_answer" and actual["public_page"] == "quiz"
    assert actual["business_quiz_matches_checkpoint"] is True
    assert actual["public_quiz"]["questions"][0]["prompt"] == original["quiz"]["questions"][0]["prompt"]
    assert "answer_key" not in json.dumps(actual["public_quiz"])
    assert "rubric" not in json.dumps(actual["public_quiz"])
    assert len(set(result["restart_process_ids"])) == 2
    assert result["original_data_unchanged"] and result["isolated_read_unchanged"]
    assert result["model_calls"] == 0
    assert database_files(source / "data") == before
    assert database_files(package / "data") == package_hashes


@pytest.mark.parametrize("relative", ["data/checkpoints.sqlite", "code/app/graph.py"])
def test_damaged_database_or_matching_code_is_rejected(recovery_package, relative):
    _, package, _ = recovery_package
    (package / relative).write_bytes(b"damaged")
    with pytest.raises(ValueError, match="missing or damaged"):
        verify(package)


def test_missing_database_manifest_cannot_pass_verification(recovery_package):
    _, package, _ = recovery_package
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    del manifest["databases"]["checkpoints.sqlite"]
    write_json(package / "manifest.json", manifest)
    with pytest.raises(ValueError, match="both databases"):
        verify(package)


def test_manifest_cannot_reference_files_outside_package(recovery_package):
    _, package, _ = recovery_package
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["../secret.key"] = {"sha256": "x", "bytes": 1}
    write_json(package / "manifest.json", manifest)
    with pytest.raises(ValueError, match="escapes"):
        verify(package)


def test_extra_executable_file_is_rejected(recovery_package):
    _, package, _ = recovery_package
    (package / "code" / "unexpected.py").write_text("raise RuntimeError('untracked')", encoding="utf-8")
    with pytest.raises(ValueError, match="untracked files"):
        verify(package)


def test_recovery_refuses_to_relocate_an_unrelated_business_database(recovery_package, tmp_path):
    _, package, _ = recovery_package
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["source_repo"] = str(tmp_path / "different_source")
    write_json(package / "manifest.json", manifest)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        demo(package, tmp_path / "refused")
    assert "unrelated business database" in exc.value.stderr


def test_matching_file_hashes_do_not_hide_quiz_fact_inconsistency(recovery_package, tmp_path):
    _, package, _ = recovery_package
    path = package / "data" / "learning.sqlite"
    with sqlite3.connect(path) as conn:
        assessment_id, quiz_text = conn.execute("SELECT id,quiz_json FROM assessments").fetchone()
        quiz = json.loads(quiz_text)
        quiz["questions"][0]["prompt"] = "Different business question"
        conn.execute("UPDATE assessments SET quiz_json=? WHERE id=?", (json.dumps(quiz), assessment_id))
        conn.commit()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["data/learning.sqlite"] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest["databases"]["learning.sqlite"] = inventory(path)
    write_json(package / "manifest.json", manifest)
    with pytest.raises(subprocess.CalledProcessError) as exc:
        demo(package, tmp_path / "inconsistent")
    assert "inconsistent with its business assessment" in exc.value.stderr


def test_recovery_rejects_original_runtime_and_immutable_package(recovery_package):
    source, package, _ = recovery_package
    with pytest.raises(ValueError, match="original V2 runtime"):
        demo(package, source / "data" / "nested")
    with pytest.raises(ValueError, match="immutable package"):
        demo(package, package / "nested")


def test_backup_reads_committed_wal_without_mutating_original(tmp_path):
    source, backup = tmp_path / "wal.sqlite", tmp_path / "backup.sqlite"
    with sqlite3.connect(source) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE evidence(value TEXT)")
        conn.execute("INSERT INTO evidence VALUES ('committed WAL fact')")
        conn.commit()
        before = sha256(source), sha256(str(source) + "-wal")
        sqlite_backup(source, backup)
        assert (sha256(source), sha256(str(source) + "-wal")) == before
        with sqlite3.connect(backup) as restored:
            assert restored.execute("SELECT value FROM evidence").fetchone()[0] == "committed WAL fact"


def test_capture_filter_excludes_secrets_v3_and_generated_runtime():
    assert allowed_code("app/services/learner_feedback.py")
    assert allowed_code(".env.example")
    for path in (".env", ".env.production", "venv/Lib/module.py", "app/v3/repository.py",
                 "configs/v3/policy.json", "tests/test_v3_repository.py", "tests/test_day9_recovery.py",
                 "data/learning.sqlite", "work/day9/evidence.json", "private.key"):
        assert not allowed_code(path), path
