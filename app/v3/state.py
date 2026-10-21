"""V3 references for the future learning Graph; V2 State remains unchanged."""
from typing import Any, Literal
from typing_extensions import TypedDict


class V3State(TypedDict, total=False):
    project_id: str
    thread_id: str  # Always project_id; never an old V2 thread.
    db_schema_version: Literal["v3-day10-2"]
    graph_version: Literal["v3-day10-preparation"]
    contract_version: Literal["3.0.0"]
    draft_revision: int
    profile_version: int
    plan_version: int
    policy_id: str
    policy_version: str
    source_manifest: list[dict[str, Any]]  # IDs/versions/hashes, never entire books.
    lifecycle: str
    capability_check: dict[str, Any]
    current_node_id: str | None
    assessment_id: str | None
    operation_id: str | None
    pending_input_id: str | None
    retry_token: str | None
    context_chunk_ids: list[str]
    grading_status: str | None
    effective_action: str | None
    passed: bool
    preparation_event: dict[str, Any] | None
