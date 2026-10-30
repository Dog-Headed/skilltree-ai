"""One normalization rule for wire diagnostics and the final quiz guard."""
import json
import re


def prompt_fingerprint(prompt):
    return re.sub(r"[\W_]+", "", prompt.casefold())


def validate_content_prompts(content, previous_question_prompts):
    """Reject reuse while identifiers still match the model's q1/q2 slots.

    Report paths rather than copying learner/source text into instructions.
    The final assembled quiz must still pass the independent business guard.
    """
    prior = {}
    for index, prompt in enumerate(previous_question_prompts):
        prior.setdefault(prompt_fingerprint(prompt), index)
    seen, conflicts = {}, []
    for key, question in content.items():
        fingerprint = prompt_fingerprint(question['prompt'])
        path = key + '.prompt'
        if not fingerprint:
            conflicts.append(path + ' has no meaningful question text')
        elif fingerprint in prior:
            conflicts.append(f'{path} repeats previous_question_prompts[{prior[fingerprint]}]')
        elif fingerprint in seen:
            preview = json.dumps(question['prompt'][:120], ensure_ascii=False)
            conflicts.append(f'{path} repeats {seen[fingerprint]} (rejected text: {preview})')
        seen.setdefault(fingerprint, path)
    if conflicts:
        raise ValueError('Duplicate question prompts: ' + '; '.join(conflicts) +
            '. Replace each listed prompt with a different supported task or unused example, '
            'and update its answer/options/rubric consistently. Changes to punctuation, spacing '
            'or IDs do not count. Return the complete corrected quiz.')
