"""Day 9: separate V3 stores; never initialize or migrate a V2 file in place."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from .config import DB_SCHEMA_VERSION, GRAPH_VERSION, CONTRACT_VERSION

SCHEMA_VERSION = DB_SCHEMA_VERSION
PROJECT_ROOT = Path(__file__).resolve().parents[2]

RECOVERY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS preparation_retries (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(project_id,request_id)
);
CREATE TABLE IF NOT EXISTS preparation_execution (
 project_id TEXT PRIMARY KEY REFERENCES learning_projects(id),
 event_json TEXT NOT NULL, retry_request_id TEXT
);
"""


@dataclass(frozen=True)
class V3Paths:
    root: Path = PROJECT_ROOT / "data" / "v3"

    def __post_init__(self):
        object.__setattr__(self, "root", Path(self.root).resolve())

    @property
    def learning(self):
        return self.root.resolve() / "learning.sqlite"

    @property
    def checkpoints(self):
        return self.root.resolve() / "checkpoints.sqlite"

    def validate(self):
        if self.root.resolve() == (PROJECT_ROOT / "data").resolve():
            raise ValueError("V3 must use a separate directory from V2")
        if self.learning == self.checkpoints:
            raise ValueError("Business and checkpoint databases must be separate")


SCHEMA_SQL = """
CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE learning_projects (
 id TEXT PRIMARY KEY, thread_id TEXT NOT NULL UNIQUE CHECK(thread_id=id),
 create_request_id TEXT NOT NULL UNIQUE, create_fingerprint TEXT NOT NULL,
 goal TEXT NOT NULL, profile_json TEXT NOT NULL, draft_revision INTEGER NOT NULL CHECK(draft_revision>=1),
 candidate_plan_json TEXT, candidate_revision INTEGER,
 policy_json TEXT, frozen_snapshot_json TEXT, frozen_at TEXT,
 profile_confirmation_hash TEXT, candidate_policy_json TEXT, candidate_input_id TEXT, planning_feedback TEXT NOT NULL DEFAULT '',
 capability_json TEXT, operation_id TEXT, retry_token TEXT, error_type TEXT, last_confirmation_id TEXT,
 lifecycle TEXT NOT NULL, pending_input_id TEXT UNIQUE,
 derived_from_project_id TEXT REFERENCES learning_projects(id),
 limits_json TEXT NOT NULL, created_at TEXT NOT NULL,
 graph_version TEXT NOT NULL, contract_version TEXT NOT NULL
);
CREATE TABLE knowledge_nodes (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), node_id TEXT NOT NULL,
 plan_version INTEGER NOT NULL CHECK(plan_version>=1), node_json TEXT NOT NULL,
 PRIMARY KEY(project_id,node_id)
);
CREATE TABLE assessments (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL, node_id TEXT NOT NULL,
 prepare_request_id TEXT NOT NULL, snapshot_json TEXT NOT NULL,
 quiz_json TEXT, answers_json TEXT, evaluation_json TEXT, diagnosis_json TEXT,
 status TEXT NOT NULL CHECK(status IN ('prepared','awaiting_answer','submitted','graded','needs_review','invalid_item','abandoned')),
 previous_assessment_id TEXT, created_at TEXT NOT NULL,
 UNIQUE(project_id,node_id,prepare_request_id), UNIQUE(project_id,node_id,id),
 FOREIGN KEY(project_id,node_id) REFERENCES knowledge_nodes(project_id,node_id),
 FOREIGN KEY(project_id,node_id,previous_assessment_id) REFERENCES assessments(project_id,node_id,id)
);
CREATE TABLE learning_progress (
 project_id TEXT NOT NULL, node_id TEXT NOT NULL, started_at TEXT,
 completed_at TEXT, completion_assessment_id TEXT, pass_policy_json TEXT, pass_basis_json TEXT,
 PRIMARY KEY(project_id,node_id),
 FOREIGN KEY(project_id,node_id) REFERENCES knowledge_nodes(project_id,node_id),
 FOREIGN KEY(project_id,node_id,completion_assessment_id) REFERENCES assessments(project_id,node_id,id),
 CHECK((completed_at IS NULL AND completion_assessment_id IS NULL) OR
       (completed_at IS NOT NULL AND completion_assessment_id IS NOT NULL AND pass_basis_json IS NOT NULL))
);
CREATE TABLE source_documents (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), source_id TEXT NOT NULL,
 source_version INTEGER NOT NULL CHECK(source_version>=1), import_request_id TEXT NOT NULL,
 document_json TEXT NOT NULL, content_bytes INTEGER NOT NULL CHECK(content_bytes>=0),
 visibility TEXT NOT NULL CHECK(visibility IN ('teaching','assessment_private')),
 PRIMARY KEY(project_id,source_id,source_version), UNIQUE(project_id,import_request_id)
);
CREATE TABLE source_chunks (
 project_id TEXT NOT NULL, chunk_id TEXT NOT NULL, source_id TEXT NOT NULL,
 source_version INTEGER NOT NULL, chunk_json TEXT NOT NULL,
 PRIMARY KEY(project_id,chunk_id),
 FOREIGN KEY(project_id,source_id,source_version) REFERENCES source_documents(project_id,source_id,source_version)
);
CREATE TABLE source_import_requests (
 project_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 source_id TEXT NOT NULL, source_version INTEGER NOT NULL,
 PRIMARY KEY(project_id,request_id),
 FOREIGN KEY(project_id,source_id,source_version) REFERENCES source_documents(project_id,source_id,source_version)
);
CREATE TABLE preparation_inputs (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, PRIMARY KEY(project_id,request_id)
);
CREATE TABLE node_material_links (
 project_id TEXT NOT NULL, node_id TEXT NOT NULL, objective_id TEXT NOT NULL,
 chunk_id TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN ('teaching','assessment','grading')),
 PRIMARY KEY(project_id,node_id,objective_id,chunk_id,purpose),
 FOREIGN KEY(project_id,node_id) REFERENCES knowledge_nodes(project_id,node_id),
 FOREIGN KEY(project_id,chunk_id) REFERENCES source_chunks(project_id,chunk_id)
);
CREATE TABLE model_operations (
 operation_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES learning_projects(id),
 request_id TEXT NOT NULL, kind TEXT NOT NULL, root_operation_id TEXT NOT NULL,
 parent_operation_id TEXT, retry_token TEXT NOT NULL,
 request_limit INTEGER NOT NULL CHECK(request_limit>0), reserved_requests INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL CHECK(status IN ('pending','running','completed','failed','budget_exhausted')),
 created_at TEXT NOT NULL, UNIQUE(project_id,request_id), UNIQUE(parent_operation_id),
 UNIQUE(project_id,operation_id), CHECK(reserved_requests>=0 AND reserved_requests<=request_limit),
 FOREIGN KEY(project_id,parent_operation_id) REFERENCES model_operations(project_id,operation_id),
 FOREIGN KEY(project_id,root_operation_id) REFERENCES model_operations(project_id,operation_id)
);
""" + RECOVERY_SCHEMA_SQL


def validate_existing(path: Path, kind: str):
    """Read-only inspection runs BEFORE either file is changed."""
    if not path.exists():
        return False
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        if not tables:
            return False
        if "runtime_metadata" not in tables:
            raise ValueError(f"Refusing a non-V3 {kind} database")
        meta = dict(conn.execute("SELECT key,value FROM runtime_metadata"))
        expected = {"db_schema_version": SCHEMA_VERSION, "graph_version": GRAPH_VERSION,
                    "contract_version": CONTRACT_VERSION, "store_kind": kind}
        if any(meta.get(k) != v for k, v in expected.items()):
            raise ValueError(f"Unsupported V3 {kind} versions; explicit migration required")
    return True


def initialize_storage(paths: V3Paths = V3Paths()):
    from datetime import datetime, timezone
    paths.validate()
    existing = {"business": validate_existing(paths.learning, "business"),
                "checkpoint": validate_existing(paths.checkpoints, "checkpoint")}
    paths.root.mkdir(parents=True, exist_ok=True)
    for kind, path in (("business", paths.learning), ("checkpoint", paths.checkpoints)):
        if existing[kind]:
            continue
        with sqlite3.connect(path) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            if kind == "business":
                conn.executescript(SCHEMA_SQL)
                conn.execute("INSERT INTO schema_migrations VALUES (?,?)", (SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()))
            else:
                conn.execute("CREATE TABLE runtime_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                SqliteSaver(conn).setup()
            conn.executemany("INSERT INTO runtime_metadata VALUES (?,?)", (
                ("db_schema_version", SCHEMA_VERSION), ("graph_version", GRAPH_VERSION),
                ("contract_version", CONTRACT_VERSION), ("store_kind", kind),
            ))
            if kind=='business':conn.execute("INSERT INTO runtime_metadata VALUES ('preparation_recovery_seeded','1')")
    return paths


@contextmanager
def open_v3_checkpointer(paths: V3Paths = V3Paths()):
    paths.validate()
    if not validate_existing(paths.checkpoints, "checkpoint"):
        raise ValueError("Initialize V3 checkpoint storage explicitly first")
    conn = sqlite3.connect(paths.checkpoints, check_same_thread=False)
    try:
        yield SqliteSaver(conn)
    finally:
        conn.close()


def migrate_day9_storage(paths: V3Paths):
    """Explicit offline additive upgrade of Day9 or compatible Day10 stores.

    Caller must stop writers and make paired backups first. Each store has its
    own transaction; if interrupted after business commit, rerunning completes
    the checkpoint metadata change. Incompatible Day9 Graphs are refused;
    Day10 checkpoints remain usable. No V2 tables or checkpoint payloads change.
    """
    from datetime import datetime, timezone
    paths.validate()
    metadata = {}
    for kind,path in (("business",paths.learning),("checkpoint",paths.checkpoints)):
        with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as conn:
            try:
                meta = dict(conn.execute("SELECT key,value FROM runtime_metadata"))
            except sqlite3.DatabaseError as exc:
                raise ValueError("Only explicit Day9 V3 stores can migrate") from exc
            if meta.get("store_kind") != kind or meta.get("contract_version") != CONTRACT_VERSION:
                raise ValueError("Store identity/contract mismatch")
            if (meta.get("db_schema_version"),meta.get("graph_version")) not in {
                ("v3-day9-1","v3-day9-foundation"),("v3-day10-1",GRAPH_VERSION),(SCHEMA_VERSION,GRAPH_VERSION)}:
                raise ValueError("Unknown migration source version")
            if kind == "checkpoint" and meta["graph_version"] != GRAPH_VERSION:
                if conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]:
                    raise ValueError("Old Graph checkpoints exist; preserve them and initialize a new V3 directory")
            metadata[kind] = meta
    if metadata["business"]["db_schema_version"] != SCHEMA_VERSION:
        with sqlite3.connect(paths.learning) as conn:
            conn.execute("BEGIN IMMEDIATE")
            columns={r[1] for r in conn.execute("PRAGMA table_info(learning_projects)")}
            additions={"profile_confirmation_hash":"TEXT","candidate_policy_json":"TEXT","candidate_input_id":"TEXT",
                       "planning_feedback":"TEXT NOT NULL DEFAULT ''","capability_json":"TEXT",
                       "operation_id":"TEXT","retry_token":"TEXT","error_type":"TEXT","last_confirmation_id":"TEXT"}
            for column,definition in additions.items():
                if column not in columns:conn.execute(f"ALTER TABLE learning_projects ADD COLUMN {column} {definition}")
            conn.execute("""CREATE TABLE IF NOT EXISTS source_import_requests (
                project_id TEXT NOT NULL,request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,
                source_id TEXT NOT NULL,source_version INTEGER NOT NULL,PRIMARY KEY(project_id,request_id),
                FOREIGN KEY(project_id,source_id,source_version) REFERENCES source_documents(project_id,source_id,source_version))""")
            conn.execute("UPDATE learning_projects SET graph_version=? WHERE frozen_snapshot_json IS NULL",(GRAPH_VERSION,))
            conn.execute("CREATE TABLE IF NOT EXISTS preparation_inputs (project_id TEXT NOT NULL REFERENCES learning_projects(id),request_id TEXT NOT NULL,fingerprint TEXT NOT NULL,PRIMARY KEY(project_id,request_id))")
            for statement in RECOVERY_SCHEMA_SQL.split(';'):
                if statement.strip():conn.execute(statement)
            conn.execute("UPDATE runtime_metadata SET value=? WHERE key='db_schema_version'",(SCHEMA_VERSION,))
            conn.execute("UPDATE runtime_metadata SET value=? WHERE key='graph_version'",(GRAPH_VERSION,))
            conn.execute("INSERT OR IGNORE INTO schema_migrations VALUES (?,?)",(SCHEMA_VERSION,datetime.now(timezone.utc).isoformat()))
    if metadata["checkpoint"]["db_schema_version"] != SCHEMA_VERSION:
        with sqlite3.connect(paths.checkpoints) as conn:
            conn.execute("UPDATE runtime_metadata SET value=? WHERE key='db_schema_version'",(SCHEMA_VERSION,))
            conn.execute("UPDATE runtime_metadata SET value=? WHERE key='graph_version'",(GRAPH_VERSION,))
    # Same Graph version: recover already interrupted Day10-1 work without
    # rewriting serialized checkpoints. Only this explicit offline migration
    # inspects old Graph state; GET never does.
    with sqlite3.connect(paths.learning) as conn:
        seeded=conn.execute("SELECT 1 FROM runtime_metadata WHERE key='preparation_recovery_seeded'").fetchone()
    if not seeded:
        from .preparation import PreparationService
        from .repository import V3Repository, encode
        with V3Repository(paths) as repo:
            projects=repo.list_projects()
            demo=repo.conn.execute("SELECT 1 FROM runtime_metadata WHERE key='demo_only'").fetchone()
        if not demo:
            service=PreparationService(paths)
            with service._graph() as graph,V3Repository(paths) as repo:
                for project in projects:
                    if not project['operation_id']:continue
                    snapshot=graph.get_state(service._config(project['id']))
                    event=snapshot.values.get('preparation_event')
                    if snapshot.next and not snapshot.interrupts and event:
                        with repo.transaction():
                            repo.conn.execute('INSERT OR IGNORE INTO preparation_execution VALUES (?,?,NULL)',(project['id'],encode(event)))
        with sqlite3.connect(paths.learning) as conn:
            conn.execute("INSERT INTO runtime_metadata VALUES ('preparation_recovery_seeded','1')")
    return paths
