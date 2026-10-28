"""Optional model-facing preparation content; persisted V3 contracts stay intact."""
from typing import Annotated
from pydantic import Field, create_model

from .contracts import ContractModel

GENERATION_MODES = {'legacy', 'content-v1', 'notes-outline-v1'}
CONTENT_VERSION = 'guided-content-1-positional'


class NoteSection(ContractModel):
    core: str = Field(min_length=20, max_length=700)
    example: str = Field(min_length=8, max_length=350)
    misconception: str = Field(min_length=6, max_length=200)
    practice: str = Field(min_length=8, max_length=200)


def compact_schema(schema):
    """Omit display annotations, never structural rules or enum restrictions."""
    if isinstance(schema, dict):
        return {k: compact_schema(v) for k, v in schema.items() if k not in {'title', 'description', 'default'}}
    if isinstance(schema, list):
        return [compact_schema(v) for v in schema]
    return schema


def scope_payload(payload):
    # Source ownership/version/content were checked by MaterialService.catalog.
    # Keep every public chunk's full body and provenance; no private references.
    return {'intent': payload['intent'], 'adjustment': payload.get('adjustment', ''),
            'user_material_catalog': [
                {k: item[k] for k in ('title', 'heading', 'content', 'source_description', 'trust_note') if k in item}
                for item in payload['user_material_catalog']],
            'available_evaluators': payload.get('available_evaluators', ['choice_exact', 'numeric_scalar', 'text_rubric']),
            **({'prompt_version':payload['prompt_version']} if 'prompt_version' in payload else {})}


def notes_contract(payload):
    profile = payload['profile']
    branches = profile['scope_in']
    if not branches or len(branches) > 12 or any(not b.strip() for b in branches):
        raise ValueError('Notes require every confirmed scope branch')
    schema = create_model('StudyNotesContent', __base__=ContractModel,
        sections=(list[Annotated[list[str],Field(min_length=4,max_length=4)]],
                  Field(min_length=len(branches),max_length=len(branches))))
    # Fixed headings and slot count are owned by the confirmed scope, not LLM.
    data = {'goal': profile['goal'], 'bounded_goal': profile['bounded_goal'],
            'scope_out': profile['scope_out'], 'target_level': profile.get('target_level', '入门'),
            'prior_knowledge': profile.get('prior_knowledge', {}).get('self_reported', []),
            'time_budget_minutes': profile['time_budget_minutes'], 'session_minutes': profile['session_minutes'],
            'sections': branches}
    return schema, data


def assemble_notes(content, payload):
    from .onboarding import StudyNotes
    sections = content.model_dump()['sections']
    branches = payload['profile']['scope_in']
    if len(sections) != len(branches):
        raise ValueError('All confirmed scope sections must be present exactly once')
    parts = []
    for i, branch in enumerate(branches, 1):
        values=sections[i-1]
        if len(values)!=4:raise ValueError(f's{i}: exactly four content parts are required')
        item = NoteSection.model_validate(dict(zip(NoteSection.model_fields,values))).model_dump()
        if any(not v.strip() for v in item.values()):
            raise ValueError(f's{i}: teaching content cannot be whitespace')
        # Newlines in a scope label cannot create a new Markdown section.
        heading = ' '.join(branch.splitlines()).strip()
        parts.append(f'## {heading}\n{item["core"]}\n\n'
                     f'例子：{item["example"]}\n\n'
                     f'常见误解：{item["misconception"]}\n\n'
                     f'练习方向：{item["practice"]}')
    # The original public notes contract still caps the complete document.
    # Overflow is a repairable model error, never silently truncate a branch.
    return StudyNotes(content='\n\n'.join(parts))
