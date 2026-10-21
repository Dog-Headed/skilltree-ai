"""Explicit additive learning extension; preparation checkpoints stay intact."""
from contextlib import contextmanager
from datetime import datetime,timezone
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from .config import DB_SCHEMA_VERSION,CONTRACT_VERSION
from .storage import V3Paths,validate_existing

RUNTIME_SCHEMA_VERSION='v3-day11-1'
LEARNING_GRAPH_VERSION='v3-day11-learning'
RUNTIME_SQL="""
CREATE UNIQUE INDEX IF NOT EXISTS assessments_project_identity ON assessments(project_id,id);
CREATE TABLE IF NOT EXISTS learning_sessions (
 project_id TEXT PRIMARY KEY REFERENCES learning_projects(id),
 current_node_id TEXT, current_assessment_id TEXT, mode TEXT NOT NULL DEFAULT 'normal',
 review_node_id TEXT, last_tutor_json TEXT, last_guard_json TEXT,
 pause_reason TEXT, question TEXT, tutor_request_id TEXT NOT NULL,
 next_previous_assessment_id TEXT
);
CREATE TABLE IF NOT EXISTS node_runtime (
 project_id TEXT NOT NULL, node_id TEXT NOT NULL, effective_rounds INTEGER NOT NULL DEFAULT 0,
 round_limit INTEGER NOT NULL DEFAULT 3, extension_used INTEGER NOT NULL DEFAULT 0,
 replacements INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(project_id,node_id),
 FOREIGN KEY(project_id,node_id) REFERENCES knowledge_nodes(project_id,node_id),
 CHECK(effective_rounds>=0 AND round_limit BETWEEN 1 AND 6 AND extension_used IN (0,1) AND replacements BETWEEN 0 AND 2)
);
CREATE TABLE IF NOT EXISTS learning_commands (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, event_json TEXT NOT NULL,
 PRIMARY KEY(project_id,request_id)
);
CREATE TABLE IF NOT EXISTS learning_execution (
 project_id TEXT PRIMARY KEY REFERENCES learning_projects(id), event_json TEXT NOT NULL,
 kind TEXT NOT NULL, retry_request_id TEXT
);
CREATE TABLE IF NOT EXISTS learning_retries (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), request_id TEXT NOT NULL,
 fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(project_id,request_id)
);
CREATE TABLE IF NOT EXISTS model_tasks (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), task_key TEXT NOT NULL,
 root_operation_id TEXT NOT NULL, input_hash TEXT NOT NULL,
 requests INTEGER NOT NULL DEFAULT 0, network_retries INTEGER NOT NULL DEFAULT 0,
 output_repairs INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
 result_json TEXT, repair_json TEXT, error_type TEXT,
 PRIMARY KEY(project_id,task_key),
 FOREIGN KEY(project_id,root_operation_id) REFERENCES model_operations(project_id,operation_id),
 CHECK(requests BETWEEN 0 AND 3 AND network_retries BETWEEN 0 AND 1 AND output_repairs BETWEEN 0 AND 1)
);
CREATE TABLE IF NOT EXISTS tutor_turns (
 project_id TEXT NOT NULL REFERENCES learning_projects(id), node_id TEXT NOT NULL,
 request_id TEXT NOT NULL, question TEXT, reply_json TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(project_id,request_id)
);
CREATE TABLE IF NOT EXISTS assessment_annotations (
 project_id TEXT NOT NULL, assessment_id TEXT NOT NULL, request_id TEXT NOT NULL,
 text TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(project_id,request_id),
 FOREIGN KEY(project_id,assessment_id) REFERENCES assessments(project_id,id)
);
CREATE TABLE IF NOT EXISTS learning_transitions (
 project_id TEXT NOT NULL, assessment_id TEXT NOT NULL, result_json TEXT NOT NULL,
 PRIMARY KEY(project_id,assessment_id),
 FOREIGN KEY(project_id,assessment_id) REFERENCES assessments(project_id,id)
);
"""


def learning_checkpoint_path(paths):return paths.root/'learning-checkpoints.sqlite'


def _checkpoint_metadata():
    return {'db_schema_version':DB_SCHEMA_VERSION,'contract_version':CONTRACT_VERSION,
            'graph_version':LEARNING_GRAPH_VERSION,'store_kind':'learning_checkpoint'}


def initialize_learning_storage(paths=V3Paths()):
    """Call after idle-store backup and base V3 initialization/migration."""
    paths.validate()
    if not validate_existing(paths.learning,'business') or not validate_existing(paths.checkpoints,'checkpoint'):
        raise ValueError('Initialize compatible V3 preparation stores first')
    target=learning_checkpoint_path(paths)
    if target.exists():
        with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as conn:
            meta=dict(conn.execute('SELECT key,value FROM runtime_metadata'))
            if meta!=_checkpoint_metadata():
                raise ValueError('Learning checkpoint versions require explicit migration')
    with sqlite3.connect(paths.learning) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        current=conn.execute("SELECT value FROM runtime_metadata WHERE key='learning_schema_version'").fetchone()
        if current and current[0]!=RUNTIME_SCHEMA_VERSION:raise ValueError('Unsupported learning extension')
        if not current:
            conn.execute('BEGIN IMMEDIATE')
            for statement in RUNTIME_SQL.split(';'):
                if statement.strip():conn.execute(statement)
            conn.execute('INSERT INTO runtime_metadata VALUES (?,?)',('learning_schema_version',RUNTIME_SCHEMA_VERSION))
            conn.execute('INSERT INTO schema_migrations VALUES (?,?)',(RUNTIME_SCHEMA_VERSION,datetime.now(timezone.utc).isoformat()))
    if not target.exists():
        with sqlite3.connect(target) as conn:
            conn.execute('CREATE TABLE runtime_metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            conn.executemany('INSERT INTO runtime_metadata VALUES (?,?)',(
                ('db_schema_version',DB_SCHEMA_VERSION),('contract_version',CONTRACT_VERSION),
                ('graph_version',LEARNING_GRAPH_VERSION),('store_kind','learning_checkpoint')))
            SqliteSaver(conn).setup()
    return paths


def validate_learning_storage(paths):
    paths.validate()
    if not validate_existing(paths.learning,'business'):raise ValueError('Initialize V3 stores first')
    with sqlite3.connect(paths.learning.as_uri()+'?mode=ro',uri=True) as conn:
        row=conn.execute("SELECT value FROM runtime_metadata WHERE key='learning_schema_version'").fetchone()
        if not row or row[0]!=RUNTIME_SCHEMA_VERSION:raise ValueError('Initialize learning extension explicitly')
    target=learning_checkpoint_path(paths)
    try:
        with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as conn:
            meta=dict(conn.execute('SELECT key,value FROM runtime_metadata'))
            if meta!=_checkpoint_metadata():raise ValueError('Invalid learning checkpoint versions')
    except sqlite3.DatabaseError as exc:
        raise ValueError('Initialize a compatible learning checkpoint explicitly') from exc


@contextmanager
def open_learning_checkpointer(paths):
    validate_learning_storage(paths)
    conn=sqlite3.connect(learning_checkpoint_path(paths),check_same_thread=False)
    try:yield SqliteSaver(conn)
    finally:conn.close()
