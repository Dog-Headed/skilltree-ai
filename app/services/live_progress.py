"""Job-scoped public previews. They never update learning state or model budgets."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import threading
import time

STAGES = {'working','scope','notes','plan','teaching','quiz','grade','diagnosis','review','checking'}
_reporter = ContextVar('skilltree_live_reporter', default=None)
_preview = ContextVar('skilltree_tutor_preview', default=None)


class LiveProgress:
    def __init__(self, publish):
        self.publish = publish
        self.lock = threading.RLock()
        self.stage, self.text, self.generation = 'working', '', 0
        self.last, self.dirty = 0.0, False

    def flush(self, force=False):
        with self.lock:
            if not force and (not self.dirty or time.monotonic()-self.last < .2):
                return
            self.last = time.monotonic(); self.dirty = False
            # A broken progress channel must not spend a model retry or fail a
            # valid learning operation. The canonical job remains authoritative.
            try:
                self.publish({'stage':self.stage,'text':self.text,'generation':self.generation})
            except Exception:
                pass

    def phase(self, stage):
        if stage not in STAGES:
            return
        with self.lock:
            if stage != self.stage:
                self.stage, self.text, self.dirty = stage, '', True
                self.flush(True)

    def begin_text(self):
        with self.lock:
            self.stage, self.text = 'teaching', ''
            self.generation += 1; self.dirty = True; self.flush(True)

    def update(self, text, force=False):
        if not isinstance(text,str) or len(text)>8000 or any(0xD800<=ord(c)<=0xDFFF for c in text):
            return
        with self.lock:
            if text != self.text:
                self.text, self.dirty = text, True
                self.flush(force)

    def discard(self):
        with self.lock:
            if self.text or self.stage=='teaching':
                self.text, self.stage, self.dirty = '', 'checking', True
                self.flush(True)


@contextmanager
def reporting(reporter):
    token=_reporter.set(reporter)
    try:yield
    finally:_reporter.reset(token)


@contextmanager
def tutor_preview(allowed, reject):
    token=_preview.set(reject if allowed else None)
    try:yield
    finally:_preview.reset(token)


def phase_for_task(key):
    stage={'scope':'scope','notes':'notes','guided_plan':'plan','plan':'plan','tutor':'teaching',
           'quiz':'quiz','grade':'grade','diagnosis':'diagnosis','quality_review':'review'}.get(key.split(':')[0])
    reporter=_reporter.get()
    if reporter and stage:reporter.phase(stage)


def phase_for_schema(name):
    key={'LearningPreparation':'scope','LearningPreparationContent':'scope','ScopeContent':'scope',
         'StudyNotes':'notes','StudyNotesContent':'notes','LearningPlan':'plan','PlanContent':'plan',
         'TutorReply':'tutor','TutorContent':'tutor','AssessmentQuiz':'quiz','QuizContent':'quiz','QuizContentWire':'quiz',
         'TextBatchScore':'grade','TextGradeContent':'grade','DiagnosisDecision':'diagnosis','DiagnosisContent':'diagnosis',
         'QualityReview':'quality_review','QualityReviewContent':'quality_review'}.get(name)
    if key:phase_for_task(key)


def discard_preview():
    reporter=_reporter.get()
    if reporter:reporter.discard()


def validated_tutor(text):
    reporter=_reporter.get()
    if reporter and _preview.get() is not None:reporter.update(text,True)


def text_prefix(document):
    """Decode only a root public text string; never inspect nested text fields.

    This is display-only parsing. It never closes a JSON object or provides a
    substitute for strict parsing and business validation of the final reply.
    """
    s=document.lstrip()
    if s.startswith('```json\n'):s=s[8:]
    elif s.startswith('```\n'):s=s[4:]
    if not s.startswith('{'):return None
    decoder=json.JSONDecoder();i=1
    def whitespace(pos):
        while pos<len(s) and s[pos].isspace():pos+=1
        return pos
    while True:
        i=whitespace(i)
        try:key,end=decoder.raw_decode(s[i:])
        except ValueError:return None
        if not isinstance(key,str) or key not in {'text','citation_refs','citations','exploration'}:return None
        i=whitespace(i+end)
        if s[i:i+1]!=':':return None
        i=whitespace(i+1)
        if key=='text':break
        try:_,end=decoder.raw_decode(s[i:])
        except ValueError:return None
        i=whitespace(i+end)
        if s[i:i+1]!=',':return None
        i+=1
    if s[i:i+1]!='"':return None
    i+=1;out=[];escapes={'"':'"','\\':'\\','/':'/','b':'\b','f':'\f','n':'\n','r':'\r','t':'\t'}
    while i<len(s):
        c=s[i]
        if c=='"':return ''.join(out)
        if ord(c)<32 or 0xD800<=ord(c)<=0xDFFF:return None
        if c!='\\':out.append(c);i+=1;continue
        if i+1>=len(s):break
        kind=s[i+1]
        if kind in escapes:out.append(escapes[kind]);i+=2;continue
        if kind!='u':return None
        if i+6>len(s):break
        try:value=int(s[i+2:i+6],16)
        except ValueError:return None
        size=6
        if 0xD800<=value<=0xDBFF:
            if i+12>len(s):break
            try:low=int(s[i+8:i+12],16)
            except ValueError:return None
            if s[i+6:i+8]!='\\u' or not 0xDC00<=low<=0xDFFF:return None
            value=0x10000+((value-0xD800)<<10)+(low-0xDC00);size=12
        elif 0xDC00<=value<=0xDFFF:return None
        out.append(chr(value));i+=size
    return ''.join(out)


def tutor_callback():
    reporter,reject=_reporter.get(),_preview.get()
    if reporter is None or reject is None:return None
    from langchain_core.callbacks import BaseCallbackHandler
    reporter.begin_text()
    class PublicTextCallback(BaseCallbackHandler):
        run_inline=True
        def __init__(self):self.document='';self.disabled=False;self.last_parse=0.0
        def on_llm_new_token(self, token, **kwargs):
            if self.disabled or not isinstance(token,str):return
            self.document+=token
            if len(self.document)>131072:
                self.disabled=True;reporter.discard();return
            now=time.monotonic()
            if now-self.last_parse<.05:return
            self.last_parse=now
            text=text_prefix(self.document)
            if text is None:return
            text=text.lstrip()
            if len(text)>8000 or reject(text):
                self.disabled=True;reporter.discard();return
            # Keep a small suffix until validation so a forbidden completion
            # claim spanning chunks is detected before its full phrase appears.
            reporter.update(text[:-64].rstrip() if len(text)>64 else '')
    return PublicTextCallback()
