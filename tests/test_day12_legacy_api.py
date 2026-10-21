"""V2 history is available only through the explicit legacy GET routes."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.v3.learning_api import create_learning_app
from app.v3.runtime_storage import learning_checkpoint_path
from tests.day11_support import build_frozen_project
from tests.test_day12_legacy import fingerprint, legacy_files


@pytest.fixture
def legacy_api(tmp_path, legacy_files):
    frozen = build_frozen_project(tmp_path / "v3", node_count=1)
    business, checkpoint = legacy_files
    client = TestClient(create_learning_app(
        frozen["paths"], llm=frozen["model"],
        legacy_business_path=business, legacy_checkpoint_path=checkpoint,
    ))
    return client, frozen, legacy_files


def all_stores(frozen, legacy_files):
    paths = frozen["paths"]
    return (*legacy_files, paths.learning, paths.checkpoints, learning_checkpoint_path(paths))


def test_explicit_legacy_reads_are_safe_and_default_v3_read_cannot_open_old_checkpoint(legacy_api):
    client, frozen, files = legacy_api
    before = fingerprint(all_stores(frozen, files))
    calls = len(frozen["model"].calls)
    for _ in range(2):
        summaries = client.get("/legacy/projects")
        assert summaries.status_code == 200
        assert {item["project_id"] for item in summaries.json()} == {"old_1", "old_2", "checkpoint_only"}
        for project_id in ("old_1", "old_2", "checkpoint_only"):
            response = client.get("/legacy/projects/" + project_id)
            assert response.status_code == 200
            result = response.json()
            assert result["version"] == "v2" and result["read_only"] is True
            assert result["page_state"] == "legacy_readonly" and result["allowed_actions"] == []
            assert "PRIVATE" not in response.text and "SECRET_INTERNAL_STATE" not in response.text
            assert client.get("/projects/" + project_id).status_code == 404
        assert client.get("/legacy/projects/deleted").status_code == 404
        assert client.get("/legacy/projects/unknown").status_code == 404
    assert len(frozen["model"].calls) == calls
    assert fingerprint(all_stores(frozen, files)) == before


@pytest.mark.parametrize("project_id", ["old_1", "checkpoint_only"])
@pytest.mark.parametrize("operation", ["resume", "begin", "retry", "sources", "rename", "delete"])
def test_all_v3_writes_reject_legacy_identity_before_model_or_business_change(legacy_api, operation, project_id):
    client, frozen, files = legacy_api
    before = fingerprint(all_stores(frozen, files))
    calls = len(frozen["model"].calls)
    request_id = str(uuid4())
    payloads = {
        "resume": {"request_id": request_id, "pending_input_id": "old_waiting_input",
                   "draft_revision": 1, "action": "ask", "question": "为什么？"},
        "begin": {"request_id": request_id},
        "retry": {"request_id": request_id, "retry_token": "old_retry_token"},
        "sources": {"request_id": request_id, "source_id": "material", "title": "新资料",
                    "source_description": "不能写入旧项目", "visibility": "teaching", "content": "资料正文"},
        "rename": {"display_name": "不能更改旧名称"},
        "delete": {"confirm_project_id": project_id},
    }
    suffix = "" if operation in {"rename", "delete"} else "/" + operation
    method = "PATCH" if operation == "rename" else "DELETE" if operation == "delete" else "POST"
    for _ in range(2):
        response = client.request(method, "/projects/" + project_id + suffix, json=payloads[operation])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "legacy_readonly", response.text
    assert len(frozen["model"].calls) == calls
    assert fingerprint(all_stores(frozen, files)) == before


def test_legacy_missing_files_are_not_created_by_api_reads_or_rejected_writes(tmp_path):
    frozen = build_frozen_project(tmp_path / "v3", node_count=1)
    legacy_directory = tmp_path / "missing-v2"
    client = TestClient(create_learning_app(
        frozen["paths"], llm=frozen["model"],
        legacy_business_path=legacy_directory / "learning.sqlite",
        legacy_checkpoint_path=legacy_directory / "checkpoints.sqlite",
    ))
    assert client.get("/legacy/projects").json() == []
    assert client.get("/legacy/projects/old_missing").status_code == 404
    assert client.post("/projects/old_missing/begin", json={"request_id": str(uuid4())}).status_code == 404
    assert not legacy_directory.exists()
