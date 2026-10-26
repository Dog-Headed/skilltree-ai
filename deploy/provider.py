"""Keep strict schemas while giving the model concise, actionable repair errors."""
import json

from langchain_core.exceptions import OutputParserException


def compact_parse_error(error):
    current = error
    for _ in range(8):
        if current is None:
            break
        if hasattr(current, 'errors'):
            issues = current.errors(include_input=False, include_url=False)
            return json.dumps({'schema_errors': [
                {'field': '.'.join(map(str, issue['loc'])), 'type': issue['type'], 'message': issue['msg'][:180]}
                for issue in issues[:12]], 'instruction': 'Return the complete corrected JSON. Preserve all supplied identities and frozen values.'}, ensure_ascii=False)
        if isinstance(current, json.JSONDecodeError):
            return json.dumps({'json_error': current.msg, 'line': current.lineno, 'column': current.colno,
                               'instruction': 'Return complete valid JSON with correctly escaped string values and no surrounding commentary.'})
        current = current.__cause__
    return 'Structured JSON did not match the supplied schema. Return one complete JSON object, preserving the supplied identities and frozen values.'


class StructuredReply:
    def __init__(self, runnable):
        self.runnable = runnable

    def invoke(self, messages, *args, **kwargs):
        result = self.runnable.invoke(messages, *args, **kwargs)
        error = result.get('parsing_error')
        if error is not None:
            raise OutputParserException(compact_parse_error(error)) from error
        if result.get('parsed') is None:
            raise OutputParserException('A complete schema-valid JSON object is required.')
        return result['parsed']


class StrictProvider:
    def __init__(self, model):
        self.model = model

    def __getattr__(self, name):
        return getattr(self.model, name)

    def invoke(self, *args, **kwargs):
        return self.model.invoke(*args, **kwargs)

    def with_structured_output(self, *args, **kwargs):
        # Parsing and validation remain in LangChain/Pydantic. Raw output is
        # never returned to the business layer or copied into repair prompts.
        kwargs['include_raw'] = True
        return StructuredReply(self.model.with_structured_output(*args, **kwargs))

    def bind_tools(self, *args, **kwargs):
        return self.model.bind_tools(*args, **kwargs)
