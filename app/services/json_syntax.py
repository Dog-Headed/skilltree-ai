"""Bounded punctuation recovery; never close, truncate, or invent JSON values."""
import json


def complete_json(text, *, object_pairs_hook=None, repair_punctuation=False):
    try:
        return json.loads(text, object_pairs_hook=object_pairs_hook), ()
    except json.JSONDecodeError as original:
        if not repair_punctuation:
            raise
        error = original
        candidate = text
        repairs = []
        for _ in range(8):
            pos = error.pos
            if error.msg == 'Invalid \\escape' and candidate[pos:pos + 1] == '\\':
                # Preserve the literal backslash plus its following character.
                candidate = candidate[:pos] + '\\' + candidate[pos:]
                repairs.append('literal_backslash')
            elif error.msg == "Expecting ':' delimiter" and candidate[pos:pos + 1] in set('"{[-0123456789tfn'):
                # The decoder is specifically between a complete object key
                # and a value token. Do not infer any missing key or value.
                candidate = candidate[:pos] + ':' + candidate[pos:]
                repairs.append('key_value_colon')
            elif error.msg == "Expecting ',' delimiter" and _next_structural_member(candidate, pos):
                # Separate already-present objects/arrays or a complete next
                # object key. Never split adjacent quoted string values.
                candidate = candidate[:pos] + ',' + candidate[pos:]
                repairs.append('member_comma')
            else:
                raise original
            try:
                return json.loads(candidate, object_pairs_hook=object_pairs_hook), tuple(repairs)
            except json.JSONDecodeError as next_error:
                error = next_error
        raise original


def _next_structural_member(text, pos):
    if text[pos:pos+1] in {'{','['}:
        return True
    if text[pos:pos+1] == '"':
        try:
            _, end = json.JSONDecoder().raw_decode(text[pos:])
            return text[pos+end:].lstrip().startswith(':')
        except json.JSONDecodeError:
            pass
    return False
