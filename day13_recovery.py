"""Offline V3 three-store recovery packages. No Graph or model is invoked.

Stop ALL writers first (including creation endpoints, workers and CLI scripts).
Per-project locks alone cannot exclude a newly created project. The additional
business BEGIN IMMEDIATE gate closes that race while the paired snapshots are
taken, and unchanged main/WAL fingerprints detect non-cooperating writers.
Packages contain private learning data and remain local by default. A manifest
detects accidental corruption; it is not a signature against a hostile author.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import sys

from app.v3.config import DB_SCHEMA_VERSION, GRAPH_VERSION, CONTRACT_VERSION
from app.v3.execution import project_execution
from app.v3.runtime_storage import RUNTIME_SCHEMA_VERSION, LEARNING_GRAPH_VERSION
from app.v3.storage import V3Paths

FORMAT = "skilltree-v3-recovery-1"
DATABASES = ("learning.sqlite", "checkpoints.sqlite", "learning-checkpoints.sqlite")
VERSIONS = {"db_schema": DB_SCHEMA_VERSION, "preparation_graph": GRAPH_VERSION,
            "learning_graph": LEARNING_GRAPH_VERSION, "contract": CONTRACT_VERSION,
            "learning_schema": RUNTIME_SCHEMA_VERSION}
EXCLUDED = {".git", ".venv", "venv", "work", "data", "__pycache__", ".pytest_cache",
            ".mypy_cache", ".ruff_cache", "node_modules", ".idea", ".vscode"}
SUFFIXES = {".py", ".js", ".css", ".html", ".md", ".json", ".txt", ".toml", ".yaml", ".yml", ".lock"}
ROOT_FILES = {".gitignore", ".gitattributes", ".env.example"}
REQUIRED_CODE = {"app.py", "requirements.txt", "app/v3/storage.py", "app/v3/runtime_storage.py",
                 "app/v3/contracts.py", "app/v3/config.py", "app/v3/learning.py",
                 "app/v3/preparation.py", "app/v3/learning_repository.py", "app/v3/repository.py",
                 "app/v3/materials.py", "app/v3/context.py", "app/services/llm.py"}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def _readonly(path, *, immutable=False):
    # immutable is reserved for already copied, self-contained package DBs.
    conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro" + ("&immutable=1" if immutable else ""), uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        yield conn
    finally:
        conn.close()


def file_fingerprints(directory, names=DATABASES):
    directory = Path(directory)
    return {path.name: {"sha256": digest(path), "bytes": path.stat().st_size}
            for name in names for path in (directory / name, directory / (name + "-wal"))
            if path.is_file() and (not path.name.endswith("-wal") or path.stat().st_size)}


def _safe_relative(relative):
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe recovery path")
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ValueError("Unsafe recovery path")
    return path


def allowed_code(relative):
    path = _safe_relative(relative)
    if any(part.lower() in EXCLUDED for part in path.parts):
        return False
    if path.name.lower().startswith(".env"):
        return relative == ".env.example"
    if any(re.search(r"(?:^|[_.-])(?:secrets?|credentials?|tokens?)(?:[_.-]|$)", part, re.I) for part in path.parts):
        return False
    if path.name.lower().endswith((".sqlite", ".db", ".pem", ".key", ".pfx", ".exe", ".dll", ".log")):
        return False
    return path.suffix.lower() in SUFFIXES or relative in ROOT_FILES


def _tree_files(root):
    root = Path(root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d.lower() not in EXCLUDED)
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("Symlinks/junctions are not recovery inputs")
        for name in sorted(files):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if allowed_code(relative):
                yield relative, path


def _code_snapshot(repo):
    files = {relative: {"sha256": digest(path), "bytes": path.stat().st_size}
             for relative, path in _tree_files(repo)}
    if not REQUIRED_CODE <= files.keys():
        raise ValueError("Matching V3 runtime/requirements are missing")
    return files


def _git_basis(repo):
    def run(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                              encoding="utf-8", timeout=20, check=True).stdout.strip()
    try:
        return {"available": True, "head": run("rev-parse", "HEAD"),
                "dirty": bool(run("status", "--porcelain")),
                "basis": "Current allowed working-tree bytes, including untracked source; not HEAD alone"}
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "head": None, "dirty": None,
                "basis": "No Git metadata: the complete code content hash identifies this snapshot"}


def check_writers(repo, data_root):
    """Conservative advisory scan; explicit stopped-writers attestation remains mandatory."""
    if os.name != "nt":
        return {"method": "Explicit operator stop + project locks + business write gate + main/WAL stability",
                "process_scan": "not available on this platform"}
    script = ("$OutputEncoding=[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "
              "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|uvicorn' } | "
              "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                            text=True, encoding="utf-8", timeout=30, check=True)
    processes = json.loads(result.stdout or "[]")
    if isinstance(processes, dict):
        processes = [processes]
    blocked = []
    for item in processes:
        if item["ProcessId"] == os.getpid():
            continue
        command = (item.get("CommandLine") or "").lower()
        if "pytest" in command or "day13_recovery.py" in command:
            continue
        entry = bool(re.search(r"(?:^|[\\/\s\"'])app\.py(?:[\"'\s]|$)", command))
        relevant = str(repo).lower() in command or str(data_root).lower() in command
        if entry or ("uvicorn" in command and (relevant or "app.v3." in command or "app.main:" in command)):
            blocked.append(item["ProcessId"])
    if blocked:
        raise RuntimeError(f"Stop application writers before capture; possible writer PIDs: {blocked}")
    return {"method": "Windows advisory process scan + explicit stop + locks/write gate/main-WAL stability",
            "possible_writer_pids": []}


def _inventory(path, kind):
    with _readonly(path, immutable=True) as conn:
        if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Recovery SQLite integrity check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Recovery SQLite foreign-key check failed")
        metadata = dict(conn.execute("SELECT key,value FROM runtime_metadata"))
        expected = {"db_schema_version": DB_SCHEMA_VERSION, "contract_version": CONTRACT_VERSION,
                    "store_kind": kind, "graph_version": LEARNING_GRAPH_VERSION if kind == "learning_checkpoint" else GRAPH_VERSION}
        if kind == "business":
            expected["learning_schema_version"] = RUNTIME_SCHEMA_VERSION
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("Recovery V3 schema/graph/contract version mismatch")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        counts = {name: conn.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in tables}
        schema = list(conn.execute("SELECT type,name,sql FROM sqlite_master ORDER BY type,name"))
        return {"metadata": metadata, "integrity_check": "ok", "foreign_key_check": "ok",
                "table_counts": counts, "schema_sha256": sha256(_json(schema).encode()).hexdigest()}


def _identities(directory):
    with _readonly(Path(directory) / "learning.sqlite", immutable=True) as conn:
        conn.row_factory = sqlite3.Row
        projects = [dict(row) for row in conn.execute(
            "SELECT id,thread_id,lifecycle,pending_input_id,draft_revision FROM learning_projects ORDER BY id")]
        if any(row["id"] != row["thread_id"] for row in projects):
            raise ValueError("Business project/thread identity mismatch")
        ids = {row["id"] for row in projects}
        sessions = [dict(row) for row in conn.execute("SELECT project_id,current_node_id,current_assessment_id,mode,pause_reason FROM learning_sessions ORDER BY project_id")]
        for row in sessions:
            if row["current_assessment_id"]:
                identity = conn.execute("SELECT project_id,node_id FROM assessments WHERE id=?", (row["current_assessment_id"],)).fetchone()
                if not identity or tuple(identity) != (row["project_id"], row["current_node_id"]):
                    raise ValueError("Session assessment identity mismatch")
        facts = []
        for row in conn.execute("SELECT * FROM assessments ORDER BY project_id,id"):
            value = dict(row)
            for field in ("quiz_json", "evaluation_json", "diagnosis_json"):
                if value[field]:
                    body = json.loads(value[field])
                    if any(body.get(key) != value[column] for key, column in (
                        ("project_id", "project_id"), ("node_id", "node_id"), ("assessment_id", "id"))):
                        raise ValueError("Saved assessment result identity mismatch")
            facts.append(value)
        for row in conn.execute("SELECT project_id,source_id,source_version,document_json FROM source_documents"):
            doc = json.loads(row["document_json"])
            if (doc.get("project_id"), doc.get("source_id"), doc.get("source_version")) != tuple(row)[:3]:
                raise ValueError("Saved source identity mismatch")
            if sha256(doc["content"].encode("utf-8")).hexdigest() != doc["content_hash"]:
                raise ValueError("Saved source content hash mismatch")
        progress = [dict(row) for row in conn.execute("SELECT * FROM learning_progress ORDER BY project_id,node_id")]
    checkpoint_threads = {}
    for name in DATABASES[1:]:
        with _readonly(Path(directory) / name, immutable=True) as conn:
            threads = sorted(row[0] for row in conn.execute("SELECT DISTINCT thread_id FROM checkpoints"))
            if not set(threads) <= ids:
                raise ValueError("Checkpoint contains an unknown V3 project/thread")
            checkpoint_threads[name] = threads
    return {"projects": projects, "sessions": sessions, "checkpoint_threads": checkpoint_threads,
            "assessment_facts_sha256": sha256(_json(facts).encode()).hexdigest(),
            "progress_facts_sha256": sha256(_json(progress).encode()).hexdigest()}


def _package_relative_allowed(relative):
    path = _safe_relative(relative)
    if relative in {"environment/python.json", "environment/packages.json"}:
        return True
    if len(path.parts) == 3 and path.parts[:2] == ("data", "v3") and path.name in DATABASES:
        return True
    return path.parts[0] == "code" and len(path.parts) > 1 and allowed_code("/".join(path.parts[1:]))


def capture(repo, package, *, data_root=None, writers_stopped=False):
    if writers_stopped is not True:
        raise ValueError("Stop ALL writers, including project creation, and explicitly set writers_stopped=True")
    repo, package = Path(repo).resolve(), Path(package).resolve()
    paths = V3Paths(data_root or repo / "data" / "v3")
    paths.validate()
    if paths.root == (repo / "data").resolve():
        raise ValueError("V2 data is not a V3 recovery source")
    if package.exists():
        raise FileExistsError("Recovery packages are immutable; select a fresh directory")
    if package == repo or (repo in package.parents and repo / "work" not in package.parents):
        raise ValueError("Use a local work directory or a separate package location")
    if package == paths.root or paths.root in package.parents:
        raise ValueError("Package cannot be placed inside live V3 data")
    if any(not (paths.root / name).is_file() for name in DATABASES):
        raise FileNotFoundError("All three V3 stores must exist; initialize Day 11 explicitly first")
    if any((paths.root / (name + suffix)).is_symlink() for name in DATABASES for suffix in ("", "-wal", "-shm")):
        raise ValueError("Recovery database sources cannot be symlinks")
    writer_check = check_writers(repo, paths.root)
    code_before = _code_snapshot(repo)
    basis = _git_basis(repo)
    v2_before = file_fingerprints(repo / "data", DATABASES[:2])
    # Acquiring the global business write gate BEFORE enumeration prevents a
    # creation request slipping past the project lock list. Nonblocking project
    # locks reject an existing executor instead of permitting concurrent backup.
    with ExitStack() as stack:
        gate = sqlite3.connect(paths.learning, timeout=0)
        stack.callback(gate.close)
        gate.execute("BEGIN IMMEDIATE")
        stack.callback(gate.rollback)
        projects = sorted(row[0] for row in gate.execute("SELECT id FROM learning_projects"))
        for project_id in projects:
            stack.enter_context(project_execution(project_id, paths))
        before = file_fingerprints(paths.root)
        package.mkdir(parents=True, exist_ok=False)
        target_data = package / "data" / "v3"
        target_data.mkdir(parents=True)
        for name in DATABASES:
            with _readonly(paths.root / name) as original:
                backup = sqlite3.connect(target_data / name)
                try:
                    original.backup(backup)
                finally:
                    backup.close()
        for relative in code_before:
            target = package / "code" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo / relative, target)
        environment = package / "environment"
        environment.mkdir()
        installed = subprocess.run([sys.executable, "-X", "utf8", "-m", "pip", "list", "--format=json", "--disable-pip-version-check"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        # Only names/versions: pip freeze direct URLs could reveal credentials.
        packages = [{"name": item["name"], "version": item["version"]} for item in json.loads(installed.stdout)]
        _write(environment / "packages.json", sorted(packages, key=lambda item: item["name"].lower()))
        _write(environment / "python.json", {"version": sys.version, "platform": sys.platform,
               "secrets": "Excluded. Supply protected model configuration separately; Fake tests require no key."})
        after = file_fingerprints(paths.root)
        if before != after or projects != sorted(row[0] for row in gate.execute("SELECT id FROM learning_projects")):
            raise RuntimeError("V3 data changed during three-store capture; discard incomplete package")
        if code_before != _code_snapshot(repo):
            raise RuntimeError("Source/materials changed during capture; discard incomplete package")
        if v2_before != file_fingerprints(repo / "data", DATABASES[:2]):
            raise RuntimeError("Original V2 data changed during capture")
        databases = {name: _inventory(target_data / name, kind) for name, kind in zip(
            DATABASES, ("business", "checkpoint", "learning_checkpoint"))}
        identities = _identities(target_data)
        files = {path.relative_to(package).as_posix(): {"sha256": digest(path), "bytes": path.stat().st_size}
                 for path in sorted(package.rglob("*")) if path.is_file()}
        manifest = {"format": FORMAT, "captured_at": datetime.now(timezone.utc).isoformat(), "versions": dict(VERSIONS),
                    "source_repo": str(repo), "source_data_root": str(paths.root),
                    "private_local_package": True, "secrets_included": False, "writers_stopped_attested": True,
                    "writer_check": writer_check, "git": basis, "code_content_sha256": sha256(_json(code_before).encode()).hexdigest(),
                    "source_hashes_before": before, "source_hashes_after": after, "source_data_unchanged": before == after,
                    "v2_source_hashes": v2_before, "v2_untouched": True,
                    "databases": databases, "identities": identities, "files": files,
                    "material_storage": "All imported originals/versions/chunks are in learning.sqlite; bundled material files are in code/materials",
                    "limitation": "Unkeyed hashes detect corruption, not a maliciously replaced manifest. Trust/protect the original package."}
        _write(package / "manifest.json", manifest)
    verify(package)
    return manifest


def verify(package):
    """Inspect only hashes, SQLite rows and JSON. Never import bundled code or deserialize checkpoints."""
    package = Path(package).resolve()
    manifest_path = package / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("Recovery manifest is missing or too large")
    # Reject links anywhere, even unlisted ones, before following any input file.
    actual = set()
    for directory, dirs, files in os.walk(package, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                raise ValueError("Recovery package contains a link/junction")
        actual.update((Path(directory) / name).relative_to(package).as_posix() for name in files)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT or manifest.get("versions") != VERSIONS:
        raise ValueError("Unsupported recovery format/version")
    files = manifest.get("files")
    if not isinstance(files, dict) or not 1 <= len(files) <= 10000:
        raise ValueError("Invalid recovery file manifest")
    if actual != set(files) | {"manifest.json"}:
        raise ValueError("Recovery package contains missing or unlisted files")
    required = {"data/v3/" + name for name in DATABASES} | {"code/" + name for name in REQUIRED_CODE}
    required |= {"environment/python.json", "environment/packages.json"}
    if not required <= files.keys() or set(manifest.get("databases", {})) != set(DATABASES):
        raise ValueError("Recovery package is missing paired V3 data/code/environment")
    for relative, expected in files.items():
        if not _package_relative_allowed(relative):
            raise ValueError("Dangerous or secret recovery filename")
        path = package / relative
        if not path.is_file() or path.stat().st_size != expected.get("bytes") or digest(path) != expected.get("sha256"):
            raise ValueError(f"Missing or damaged recovery file: {relative}")
    code = {name[5:]: value for name, value in files.items() if name.startswith("code/")}
    if sha256(_json(code).encode()).hexdigest() != manifest.get("code_content_sha256"):
        raise ValueError("Recovery code content summary mismatch")
    for name, kind in zip(DATABASES, ("business", "checkpoint", "learning_checkpoint")):
        if _inventory(package / "data" / "v3" / name, kind) != manifest["databases"][name]:
            raise ValueError("Recovery database schema/count/identity mismatch")
    if _identities(package / "data" / "v3") != manifest.get("identities"):
        raise ValueError("Recovery business/checkpoint identities do not match manifest")
    if (manifest.get("secrets_included") is not False or manifest.get("writers_stopped_attested") is not True
            or manifest.get("source_hashes_before") != manifest.get("source_hashes_after")):
        raise ValueError("Recovery package has no valid stopped-writer capture evidence")
    return manifest


def restore(package, directory):
    """Restore into a NEW directory; no migration, replan, model call or checkpoint rewrite."""
    package, directory = Path(package).resolve(), Path(directory).resolve()
    if directory.exists():
        raise FileExistsError("Recovery target already exists; original data is never overwritten")
    if directory == package or package in directory.parents:
        raise ValueError("Recovery target cannot be inside the immutable package")
    manifest = verify(package)
    for live in (Path(manifest["source_data_root"]).resolve(), Path(manifest["source_repo"]).resolve() / "data"):
        if directory == live or live in directory.parents:
            raise ValueError("Restore into an isolated directory outside original runtime data")
    directory.mkdir(parents=True, exist_ok=False)
    code = directory / "code"
    shutil.copytree(package / "code", code)
    restored_data = code / "data" / "v3"
    shutil.copytree(package / "data" / "v3", restored_data)
    shutil.copytree(package / "environment", directory / "environment")
    shutil.copyfile(package / "manifest.json", directory / "recovery-manifest.json")
    if _identities(restored_data) != manifest["identities"]:
        raise ValueError("Restored identities differ from verified package")
    for name in DATABASES:
        if digest(restored_data / name) != manifest["files"]["data/v3/" + name]["sha256"]:
            raise ValueError("Restored database differs from verified snapshot")
    result = {"code_root": str(code), "data_root": str(restored_data), "project_count": len(manifest["identities"]["projects"]),
              "same_thread_and_pending_identities": True, "model_calls": 0, "checkpoint_payloads_rewritten": False}
    _write(directory / "RESTORED.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    cap = actions.add_parser("capture")
    cap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent)
    cap.add_argument("--data-root", type=Path)
    cap.add_argument("--package", type=Path, default=Path(__file__).resolve().parent / "work" / ("day13-private-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    cap.add_argument("--writers-stopped", action="store_true", required=True)
    for name in ("verify", "restore"):
        command = actions.add_parser(name)
        command.add_argument("--package", type=Path, required=True)
        if name == "restore":
            command.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "capture":
        value = capture(args.repo, args.package, data_root=args.data_root, writers_stopped=args.writers_stopped)
        print(_json({"package": str(args.package.resolve()), "verified": True, "files": len(value["files"]), "projects": len(value["identities"]["projects"])}))
    elif args.command == "verify":
        value = verify(args.package)
        print(_json({"verified": True, "files": len(value["files"]), "projects": len(value["identities"]["projects"])}))
    else:
        print(_json(restore(args.package, args.directory)))


if __name__ == "__main__":
    main()
