"""Explicit preparation choices for private references, without public source IDs.

Opaque handles expose neither document names nor content. They are scoped to a
project/version, are not read permissions, and disappear from frozen views.
"""
import json
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, model_validator

from .contracts import ContractModel, Identity
from .repository import ConflictError


class PrivateReferenceChoice(ContractModel):
    reference_id: Identity
    action: Literal['bind', 'exclude']
    node_ids: list[Identity] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def selected_nodes(self):
        if (self.action == 'bind') != bool(self.node_ids):
            raise ValueError('Select nodes for a binding, or explicitly exclude the reference')
        if len(self.node_ids) != len(set(self.node_ids)):
            raise ValueError('Repeated reference target')
        return self


def reference_id(document):
    return 'reference_' + uuid5(NAMESPACE_URL, ':'.join(str(document[k]) for k in
        ('project_id', 'source_id', 'source_version'))).hex


def _latest(repo, project_id):
    latest = {}
    for row in repo.conn.execute("SELECT rowid,document_json FROM source_documents WHERE project_id=? ORDER BY rowid", (project_id,)):
        document = json.loads(row[1])
        previous = latest.get(document['source_id'])
        if previous is None or previous[1]['source_version'] < document['source_version']:
            latest[document['source_id']] = (row[0], document)
    return [d for _, d in sorted(latest.values()) if d['visibility'] == 'assessment_private']


def public_references(repo, project_id):
    return [{'reference_id': reference_id(d), 'label': f'评价参考 {i + 1}'}
            for i, d in enumerate(_latest(repo, project_id))]


def resolve_choices(repo, project_id, plan, choices):
    """Validate before journaling; resolve again inside the frozen write path."""
    documents = {reference_id(d): d for d in _latest(repo, project_id)}
    parsed = [PrivateReferenceChoice.model_validate(item) for item in (choices or [])]
    selected = [item.reference_id for item in parsed]
    if len(selected) != len(set(selected)):
        raise ValueError('Repeated private reference choice')
    if set(selected) != set(documents):
        raise ConflictError('Choose or explicitly exclude every current private reference; refresh the draft')
    nodes = {node['node_id']: node for node in plan['nodes']}
    links = []
    for choice in parsed:
        if not set(choice.node_ids) <= set(nodes):
            raise ValueError('Unknown reference target node')
        document = documents[choice.reference_id]
        if choice.action == 'exclude':
            continue
        chunks = repo.list_source_chunks(project_id, document['source_id'], document['source_version'], include_private=True)
        for node_id in choice.node_ids:
            for objective in nodes[node_id]['objectives']:
                for chunk in chunks:
                    for purpose in ('assessment', 'grading'):
                        links.append({'project_id': project_id, 'node_id': node_id,
                            'objective_id': objective['objective_id'], 'chunk_id': chunk['chunk_id'], 'purpose': purpose})
    from .context import ContextBuilder
    policy = json.loads(repo.get_project(project_id)['candidate_policy_json'])
    ContextBuilder(repo).validate_candidate_bindings(project_id, links, policy=policy)
    return links
