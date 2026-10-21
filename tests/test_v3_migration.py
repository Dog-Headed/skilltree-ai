"""Explicit Day9 -> Day10 migration; never relabel serialized old Graphs."""
import re
import sqlite3
from uuid import uuid4

import pytest

from app.v3.config import CONTRACT_VERSION, DB_SCHEMA_VERSION, GRAPH_VERSION
from app.v3.contracts import LearningProfile
from app.v3.repository import V3Repository
from app.v3.storage import SCHEMA_SQL, V3Paths, initialize_storage, migrate_day9_storage


def old_store(tmp_path):
    paths=initialize_storage(V3Paths(tmp_path/'v3'))
    with sqlite3.connect(paths.learning) as conn:
        for column in ('profile_confirmation_hash','candidate_policy_json','candidate_input_id','planning_feedback',
                       'capability_json','operation_id','retry_token','error_type','last_confirmation_id'):
            conn.execute('ALTER TABLE learning_projects DROP COLUMN '+column)
        conn.execute('DROP TABLE preparation_inputs')
        conn.execute('DROP TABLE source_import_requests')
        conn.execute("UPDATE schema_migrations SET version='v3-day9-1'")
    for path in (paths.learning,paths.checkpoints):
        with sqlite3.connect(path) as conn:
            conn.execute("UPDATE runtime_metadata SET value='v3-day9-1' WHERE key='db_schema_version'")
            conn.execute("UPDATE runtime_metadata SET value='v3-day9-foundation' WHERE key='graph_version'")
    return paths


def test_additive_migration_is_explicit_preserves_content_and_is_idempotent(tmp_path):
    paths=old_store(tmp_path)
    with pytest.raises(ValueError,match='migration'):initialize_storage(paths)
    original_cp=sqlite3.connect(paths.checkpoints)
    assert original_cp.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0]==0
    original_cp.close()
    migrate_day9_storage(paths)
    with V3Repository(paths) as repo:
        p=repo.create_project(uuid4(),LearningProfile(subject_label='历史',topic='史料阅读',goal='比较叙述'))
        assert p['draft_revision']==1 and p['graph_version']==GRAPH_VERSION
        assert p['planning_feedback']==''
    before={p:p.read_bytes() for p in (paths.learning,paths.checkpoints)}
    migrate_day9_storage(paths)
    assert all(p.read_bytes()==raw for p,raw in before.items())


def test_old_checkpoint_payload_blocks_both_store_changes(tmp_path):
    paths=old_store(tmp_path)
    with sqlite3.connect(paths.checkpoints) as conn:
        conn.execute("INSERT INTO checkpoints(thread_id,checkpoint_ns,checkpoint_id,type,checkpoint,metadata) VALUES ('old','','old','json',?,?)",(b'{}',b'{}'))
    before={p:p.read_bytes() for p in (paths.learning,paths.checkpoints)}
    with pytest.raises(ValueError,match='Old Graph'):migrate_day9_storage(paths)
    assert all(p.read_bytes()==raw for p,raw in before.items())


def test_migration_rejects_v2_and_unknown_versions_before_writing(tmp_path):
    paths=old_store(tmp_path)
    with sqlite3.connect(paths.checkpoints) as conn:conn.execute('DROP TABLE runtime_metadata')
    before=paths.learning.read_bytes()
    with pytest.raises(ValueError):migrate_day9_storage(paths)
    assert paths.learning.read_bytes()==before


def test_interrupted_metadata_pair_can_finish_on_rerun(tmp_path):
    paths=old_store(tmp_path);migrate_day9_storage(paths)
    # Simulate interruption between the two independent SQLite commits.
    with sqlite3.connect(paths.checkpoints) as conn:
        conn.execute("UPDATE runtime_metadata SET value='v3-day9-1' WHERE key='db_schema_version'")
        conn.execute("UPDATE runtime_metadata SET value='v3-day9-foundation' WHERE key='graph_version'")
    before=paths.learning.read_bytes();migrate_day9_storage(paths)
    assert paths.learning.read_bytes()==before
    with sqlite3.connect(paths.checkpoints) as conn:
        assert dict(conn.execute('SELECT key,value FROM runtime_metadata'))['graph_version']==GRAPH_VERSION
