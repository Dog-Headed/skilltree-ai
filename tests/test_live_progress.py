"""Public text projection across chunk boundaries, not partial business results."""
import json
import time
from types import SimpleNamespace
import httpx
from langchain_openai import ChatOpenAI
import pytest

from app.services.live_progress import LiveProgress, reporting, tutor_preview, tutor_callback, text_prefix, discard_preview
from app.v3.tutor import has_completion_claim
from deploy.provider import StrictProvider
from app.v3.contracts import ContractModel
from pydantic import create_model


@pytest.mark.parametrize('text', ['中文换行\n第二段','C 的 "x" 与 \\0','emoji 🌱 和 😀','<img src=x onerror=alert(1)>'])
@pytest.mark.parametrize('ascii_only',[True,False])
def test_every_chunk_boundary_preserves_only_public_string_characters(text,ascii_only):
    raw=json.dumps({'citation_refs':['b1'],'text':text},ensure_ascii=ascii_only)
    for end in range(len(raw)+1):
        value=text_prefix(raw[:end])
        assert value is None or text.startswith(value)
    assert text_prefix(raw)==text


def test_nested_fields_reasoning_and_non_text_are_not_exposed():
    assert text_prefix('{"citations":[{"text":"PRIVATE"}],"text":"public"}')=='public'
    for raw in ['{"reasoning":"PRIVATE","text":"answer"}','{"answer_key":{"text":"PRIVATE"}}',
                '{{"text":"PRIVATE"}}','["PRIVATE"]','{"text":123}',r'{"text":"bad\0"}']:
        assert text_prefix(raw) is None


def test_preview_permissions_are_explicit_and_scope_is_restored():
    values=[];reporter=LiveProgress(values.append)
    with reporting(reporter):
        assert tutor_callback() is None
        with tutor_preview(False,has_completion_claim):assert tutor_callback() is None
        with tutor_preview(True,has_completion_claim):assert tutor_callback() is not None
        assert tutor_callback() is None
    assert tutor_callback() is None


def test_retry_clears_partial_text_and_uses_a_new_generation():
    values=[];reporter=LiveProgress(values.append)
    with reporting(reporter),tutor_preview(True,has_completion_claim):
        first=tutor_callback();first.on_llm_new_token(json.dumps({'text':'公开教学内容。'*30},ensure_ascii=False))
        reporter.flush(True);assert values[-1]['text']
        discard_preview();assert values[-1]['text']==''
        tutor_callback();assert values[-1]['generation']==2 and values[-1]['text']==''


def test_forbidden_claims_and_private_mode_do_not_become_preview():
    values=[];reporter=LiveProgress(values.append)
    with reporting(reporter),tutor_preview(True,has_completion_claim):
        callback=tutor_callback();callback.on_llm_new_token(json.dumps({'text':'你已经通过本节点。'+'继续学习。'*50},ensure_ascii=False))
    assert all(not row['text'] for row in values)
    with reporting(reporter),tutor_preview(False,has_completion_claim):
        assert tutor_callback() is None


def test_progress_sink_failure_never_fails_business_call():
    def broken(value):raise RuntimeError('disconnected')
    reporter=LiveProgress(broken)
    reporter.phase('notes');reporter.begin_text();reporter.update('内容',True);reporter.discard()


def test_private_output_validator_disables_provisional_text_but_still_validates():
    from tests import test_v3_tutor as case
    called=[];values=[]
    class Probe(case.FakeModel):
        def invoke(self,messages):
            assert tutor_callback() is None
            return super().invoke(messages)
    with reporting(LiveProgress(values.append)):
        result=case.generate(Probe(case.reply()),validate_public_reply=lambda reply:called.append(reply.text))
    assert called==[result.text] and all(not row['text'] for row in values)


def test_stream_prefix_normalizes_leading_whitespace_like_final_tutor():
    values=[];reporter=LiveProgress(values.append)
    text='\n\n  '+('解释变量与赋值。'*30)
    with reporting(reporter),tutor_preview(True,has_completion_claim):
        tutor_callback().on_llm_new_token(json.dumps({'text':text},ensure_ascii=False));reporter.flush(True)
    assert values[-1]['text'] and text.strip().startswith(values[-1]['text'])


def test_real_sdk_stream_callback_receives_text_before_final_structured_reply():
    text='这是公开的讲解，逐步说明变量与循环。'*20
    raw=json.dumps({'text':text,'citation_refs':['b1']},ensure_ascii=False)
    chunks=[]
    for i in range(0,len(raw),32):
        body={'id':'chatcmpl-test','object':'chat.completion.chunk','created':0,'model':'test',
              'choices':[{'index':0,'delta':{'content':raw[i:i+32],**({'role':'assistant'} if i==0 else {})},'finish_reason':None}]}
        chunks.append(('data: '+json.dumps(body,ensure_ascii=False)+'\n\n').encode())
    chunks.append(b'data: {"id":"chatcmpl-test","object":"chat.completion.chunk","created":0,"model":"test","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
    class Bytes(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in chunks:time.sleep(.055);yield chunk
    def handle(request):
        assert json.loads(request.content)['stream'] is True
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Bytes())
    schema=create_model('TutorContent',__base__=ContractModel,text=(str,...),citation_refs=(list[str],...))
    values=[];reporter=LiveProgress(values.append)
    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        model=ChatOpenAI(api_key='local-test-placeholder',model='test',base_url='http://test.invalid/v1',streaming=True,http_client=transport)
        with reporting(reporter),tutor_preview(True,has_completion_claim):
            result=StrictProvider(model).with_structured_output(schema,method='json_mode').invoke('Explain a concept')
    streamed=[row['text'] for row in values if row['text']]
    assert len(set(streamed))>=2 and all(text.startswith(prefix) and prefix!=text for prefix in streamed)
    assert result.text==text and result.citation_refs==['b1']
