"""Learning checkpoints and runtime facts remain separate from preparation."""

import sqlite3
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.v3.config import CONTRACT_VERSION, DB_SCHEMA_VERSION
from app.v3.contracts import LearningProfile
from app.v3.repository import V3Repository
from app.v3.runtime_storage import (
    LEARNING_GRAPH_VERSION, RUNTIME_SCHEMA_VERSION, initialize_learning_storage,
    learning_checkpoint_path, open_learning_checkpointer, validate_learning_storage,
)
from app.v3.storage import V3Paths, initialize_storage, open_v3_checkpointer
from tests.test_v3_storage import candidate, freeze


class CheckpointState(TypedDict):
    value: str


def graph_builder(wait=False):
    builder = StateGraph(CheckpointState)
    def remember(state):
        return {"value": interrupt({"question": "原等待点"}) if wait else state["value"]}
    builder.add_node("remember", remember)
    builder.add_edge(START, "remember")
    builder.add_edge("remember", END)
    return builder


def test_runtime_initialization_is_explicit_separate_and_idempotent(tmp_path):
    paths = initialize_storage(V3Paths(tmp_path / "v3"))
    preparation_before = paths.checkpoints.read_bytes()
    initialize_learning_storage(paths)
    target = learning_checkpoint_path(paths)
    assert len({paths.learning, paths.checkpoints, target}) == 3
    assert paths.checkpoints.read_bytes() == preparation_before
    with sqlite3.connect(paths.learning) as conn:
        assert conn.execute("SELECT value FROM runtime_metadata WHERE key='learning_schema_version'").fetchone()[0] == RUNTIME_SCHEMA_VERSION
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version=?", (RUNTIME_SCHEMA_VERSION,)).fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    with sqlite3.connect(target) as conn:
        assert dict(conn.execute("SELECT key,value FROM runtime_metadata")) == {"db_schema_version": DB_SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION, "graph_version": LEARNING_GRAPH_VERSION, "store_kind": "learning_checkpoint"}
    before = {path: path.read_bytes() for path in (paths.learning, paths.checkpoints, target)}
    initialize_learning_storage(paths)
    validate_learning_storage(paths)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_learning_checkpoint_reopens_without_resuming_or_changing_preparation_wait(tmp_path):
    paths = initialize_storage(V3Paths(tmp_path / "v3"))
    config = {"configurable": {"thread_id": "same-project"}, "recursion_limit": 30}
    with open_v3_checkpointer(paths) as saver:
        preparation = graph_builder(wait=True).compile(checkpointer=saver)
        preparation.invoke({"value": "awaiting-answer"}, config, durability="sync")
        assert preparation.get_state(config).interrupts
    before = paths.checkpoints.read_bytes()
    initialize_learning_storage(paths)
    with open_learning_checkpointer(paths) as saver:
        learning = graph_builder().compile(checkpointer=saver)
        assert not learning.get_state(config).values
        learning.invoke({"value": "independent-learning"}, config, durability="sync")
    assert paths.checkpoints.read_bytes() == before
    with open_learning_checkpointer(paths) as saver:
        assert graph_builder().compile(checkpointer=saver).get_state(config).values["value"] == "independent-learning"
    with open_v3_checkpointer(paths) as saver:
        preparation = graph_builder(wait=True).compile(checkpointer=saver)
        assert preparation.get_state(config).values["value"] == "awaiting-answer"
        assert preparation.invoke(Command(resume="original-answer"), config, durability="sync")["value"] == "original-answer"
    with open_learning_checkpointer(paths) as saver:
        assert graph_builder().compile(checkpointer=saver).get_state(config).values["value"] == "independent-learning"


@pytest.mark.parametrize("key", ["db_schema_version", "contract_version", "graph_version", "store_kind"])
def test_incompatible_learning_checkpoint_is_refused_before_any_business_write(tmp_path, key):
    paths = initialize_storage(V3Paths(tmp_path / "v3"))
    initialize_learning_storage(paths)
    target = learning_checkpoint_path(paths)
    with sqlite3.connect(target) as conn:
        conn.execute("UPDATE runtime_metadata SET value='future-incompatible' WHERE key=?", (key,))
    before = {path: path.read_bytes() for path in (paths.learning, paths.checkpoints, target)}
    with pytest.raises(ValueError):
        initialize_learning_storage(paths)
    with pytest.raises(ValueError):
        validate_learning_storage(paths)
    assert all(path.read_bytes() == content for path, content in before.items())


def test_missing_base_or_learning_initialization_does_not_create_query_side_effects(tmp_path):
    paths = V3Paths(tmp_path / "not-initialized")
    with pytest.raises(ValueError):
        initialize_learning_storage(paths)
    assert not paths.root.exists()
    initialize_storage(paths)
    before = paths.learning.read_bytes()
    with pytest.raises(ValueError):
        validate_learning_storage(paths)
    assert paths.learning.read_bytes() == before and not learning_checkpoint_path(paths).exists()


def test_composite_assessment_references_work_and_cannot_cross_project(tmp_path):
    paths = initialize_storage(V3Paths(tmp_path / "v3"))
    initialize_learning_storage(paths)
    with V3Repository(paths) as repo:
        project = freeze(repo, candidate(repo))
        other = repo.create_project(uuid4(), LearningProfile(subject_label="另一主题", topic="文字", goal="阅读"))
        assessment = repo.prepare_assessment(project["id"], "common-node", request_id=uuid4())
        with repo.transaction():
            repo.conn.execute("INSERT INTO assessment_annotations VALUES (?,?,?,?,?)", (project["id"], assessment["id"], str(uuid4()), "附加说明", "now"))
            repo.conn.execute("INSERT INTO learning_transitions VALUES (?,?,?)", (project["id"], assessment["id"], "{}"))
        for table in ("assessment_annotations", "learning_transitions"):
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                with repo.transaction():
                    if table == "assessment_annotations":
                        repo.conn.execute("INSERT INTO assessment_annotations VALUES (?,?,?,?,?)", (other["id"], assessment["id"], str(uuid4()), "不得串项目", "now"))
                    else:
                        repo.conn.execute("INSERT INTO learning_transitions VALUES (?,?,?)", (other["id"], assessment["id"], "{}"))
        assert repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_model_task_operation_reference_cannot_cross_project(tmp_path):
    paths = initialize_storage(V3Paths(tmp_path / "v3"))
    initialize_learning_storage(paths)
    with V3Repository(paths) as repo:
        first = repo.create_project(uuid4(), LearningProfile(subject_label="甲", topic="文字", goal="阅读"))
        other = repo.create_project(uuid4(), LearningProfile(subject_label="乙", topic="文字", goal="阅读"))
        operation = repo.create_operation(first["id"], uuid4(), kind="tutor")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            with repo.transaction():
                repo.conn.execute("INSERT INTO model_tasks(project_id,task_key,root_operation_id,input_hash) VALUES (?,?,?,?)",
                                  (other["id"], "same-task", operation["operation_id"], "hash"))
