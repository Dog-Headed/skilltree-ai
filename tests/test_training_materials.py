"""Real four-format parsers and HTTP permissions; model calls are Fake here."""
import base64
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4
import zipfile

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from app.v3.materials import MaterialInputError, validate_chunk_origin
from app.v3.contracts import SourceChunk, SourceDocument
from app.v3.office_files import parse_file
from app.v3.learning_repository import LearningRepository
from deploy import training_demo as demo
from tests.test_training_demo import runtime, login, visit, GuestFlowFake

SAMPLES=Path(__file__).resolve().parents[1]/'docs/training-demo/samples'
CASES=[('岗位手册.pdf',['30 分钟','2 个工作日','17:30'],'page'),
       ('培训制度.docx',['5 个工作日','16:00','180 天'],'paragraph'),
       ('岗位职责表.xlsx',['服务专员 | 工单首次响应 | 30','交付专员 | 交付检查 | 60','记录保留 | 180'],'range'),
       ('入职流程.pptx',['09:00','10:00','17:00'],'slide')]


def upload(client,headers,name,unit=False,data=None,request_id=None):
    return client.post('/training/api/'+('admin/' if unit else '')+'materials',headers=headers,
        json={'request_id':request_id or str(uuid4()),'filename':name,'title':name,
              'data_base64':base64.b64encode(data if data is not None else (SAMPLES/name).read_bytes()).decode()})


@pytest.mark.parametrize('name,facts,location',CASES)
def test_real_files_exact_facts_locations_and_canonical_lines(name,facts,location):
    parsed=parse_file((SAMPLES/name).read_bytes(),name)
    assert all(fact in parsed['content'] for fact in facts)
    assert any(location in block['location'] for block in parsed['blocks'])
    lines=parsed['content'].splitlines()
    for block in parsed['blocks']:
        assert lines[block['line_start']-1] == '## '+block['label']
        assert block['line_start']<=block['line_end']<=len(lines)
    if name.endswith('xlsx'):
        assert parsed['blocks'][0]['rows'][0]==['岗位','职责','响应时限（分钟）','复核频率']
        assert parsed['blocks'][0]['location']['range']=='A1:D4'


def test_formula_is_not_executed_and_never_fabricates_cached_value():
    from openpyxl import Workbook
    book=Workbook();book.active.append(['金额','公式']);book.active.append([7,'=A2*3'])
    stream=BytesIO();book.save(stream)
    parsed=parse_file(stream.getvalue(),'formula.xlsx')
    assert '=A2*3 [未计算；缓存：无]' in parsed['content']
    assert '21' not in parsed['content']


def test_pdf_permission_encryption_without_opening_password_is_readable():
    from pypdf import PdfReader
    writer=PdfWriter()
    for page in PdfReader(SAMPLES/'岗位手册.pdf').pages:writer.add_page(page)
    writer.encrypt(user_password='',owner_password='export-owner-password')
    stream=BytesIO();writer.write(stream)
    parsed=parse_file(stream.getvalue(),'permission-restricted.pdf')
    assert '30 分钟' in parsed['content'] and len(parsed['blocks'])==2


@pytest.mark.parametrize('kind',['scan','encrypted','pages','corrupt','old','empty','large','text_limit','macro','expanded'])
def test_unsupported_and_over_limit_files_fail_without_truncation(kind):
    name='invalid.pdf';data=b'invalid'
    if kind in {'scan','encrypted','pages'}:
        writer=PdfWriter()
        for _ in range(11 if kind=='pages' else 1):writer.add_blank_page(100,100)
        if kind=='encrypted':writer.encrypt('password')
        stream=BytesIO();writer.write(stream);data=stream.getvalue()
    if kind=='old':name='old.doc'
    if kind=='empty':name='empty.txt';data=b'  '
    if kind=='large':data=b'x'*(8*1024*1024+1)
    if kind=='text_limit':
        from docx import Document
        doc=Document();doc.add_paragraph('原文'*7000);stream=BytesIO();doc.save(stream);data=stream.getvalue();name='large.docx'
    if kind in {'macro','expanded'}:
        stream=BytesIO()
        with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/vbaProject.bin' if kind=='macro' else 'word/document.xml',b'x'*(9*1024*1024 if kind=='expanded' else 10))
        data=stream.getvalue();name='invalid.docx'
    with pytest.raises(MaterialInputError):parse_file(data,name)


def test_guests_private_employees_unit_permissions_restart_and_adoption(runtime):
    client,gateway,model=runtime
    guest,account=visit(client)
    first=upload(client,guest,'岗位职责表.xlsx');assert first.status_code==201,first.text
    asset=first.json();aid=asset['id']
    assert asset['status']=='ready' and len(asset['parsed']['blocks'])==2
    # Login adopts both course ownership and un-attached private materials atomically.
    response=client.post('/auth/login',json={'account':demo.ACCOUNTS[1][0],'password':demo.DEMO_PASSWORD},headers={'X-SkillTree-Login':'1','Cookie':guest['Cookie']})
    a={'Cookie':response.headers['set-cookie'].split(';')[0],'X-CSRF-Token':response.json()['csrf_token']}
    assert client.get('/training/api/materials/'+aid,headers=a).status_code==200
    created=client.post('/projects',headers=a,json={'request_id':str(uuid4()),'intent':{'goal':'依据岗位职责表学习工单响应规则'}}).json()
    pid=created['project_id'];key=str(uuid4());path='/training/api/materials/'+aid+'/attach'
    payload={'project_id':pid,'request_id':key}
    attached=client.post(path,headers=a,json=payload)
    assert attached.status_code==200,attached.text
    assert client.post(path,headers=a,json=payload).json()['reused']
    source=attached.json();url=f'/projects/{pid}/sources/{source["source_id"]}/versions/1'
    detail=client.get(url,headers=a).json()
    assert detail['file']['blocks'][0]['location']['range']=='A1:D4'
    assert any(c['locations'] for c in detail['chunks'])
    assert client.get(url+'/original',headers=a).content==(SAMPLES/'岗位职责表.xlsx').read_bytes()
    with LearningRepository(gateway.paths) as repo:
        document=SourceDocument.model_validate(repo.list_sources(pid)[0])
        for chunk in repo.list_source_chunks(pid,document.source_id,1):validate_chunk_origin(SourceChunk.model_validate(chunk),document)
    b=login(client,2)
    assert client.get('/training/api/materials',headers=b).json()['materials']==[]
    for suffix in ('','/original'):
        assert client.get('/training/api/materials/'+aid+suffix,headers=b).status_code==404
        assert client.get(url+suffix,headers=b).status_code==404
    assert client.post('/training/api/admin/materials?role=admin',headers={**b,'X-Role':'admin'},json={}).status_code==403
    admin=login(client,0)
    assert client.get('/training/api/materials/'+aid,headers=admin).status_code==404
    assert client.get(url,headers=admin).status_code==404
    unit=upload(client,admin,'培训制度.docx',unit=True);assert unit.status_code==201,unit.text
    uid=unit.json()['id']
    assert client.get('/training/api/admin/materials/'+uid,headers=b).status_code==403
    assert client.get('/training/api/materials/'+uid,headers=b).status_code==404
    with gateway.training.store.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM training_material_versions').fetchone()[0]==1
    restarted=demo.create_app(root=gateway.paths.root.parent,llm=GuestFlowFake())
    client.portal.call(gateway.runner.stop)
    with TestClient(restarted,base_url='http://127.0.0.1:18780') as again:
        assert again.get('/training/api/materials/'+aid,headers=a).json()['status']=='ready'
        assert again.get(url+'/original',headers=a).content==(SAMPLES/'岗位职责表.xlsx').read_bytes()
        assert again.get('/training/api/admin/materials/'+uid,headers=admin).json()['status']=='ready'


def test_failed_upload_no_project_and_deduplicated_valid_upload(runtime):
    client,gateway,_=runtime;guest,_=visit(client)
    assert client.post('/training/api/materials',json={},headers={'Cookie':guest['Cookie']}).status_code==403
    before=client.get('/projects',headers=guest).json()
    failed=upload(client,guest,'broken.pdf',data=b'not pdf')
    assert failed.status_code==422 and failed.json()['status']=='failed'
    assert '无法解析' in failed.json()['error']
    assert client.get('/projects',headers=guest).json()==before
    asset=failed.json()['id']
    assert client.post('/training/api/materials/'+asset+'/attach',headers=guest,json={'project_id':'missing','request_id':str(uuid4())}).status_code==422
    key=str(uuid4())
    good=upload(client,guest,'培训制度.docx',request_id=key)
    assert upload(client,guest,'培训制度.docx',request_id=key).json()['id']==good.json()['id']
    assert upload(client,guest,'changed.docx',data=(SAMPLES/'培训制度.docx').read_bytes(),request_id=key).status_code==409


def test_direct_existing_course_office_upload_over_old_body_limit(runtime):
    client,gateway,_=runtime;a=login(client,1)
    pid=client.post('/projects',headers=a,json={'request_id':str(uuid4()),'intent':{'goal':'学习新员工制度'}}).json()['project_id']
    stream=BytesIO((SAMPLES/'培训制度.docx').read_bytes())
    with zipfile.ZipFile(stream,'a',zipfile.ZIP_STORED) as archive:archive.writestr('padding.bin',b'0'*300000)
    raw=stream.getvalue();assert len(raw)>262144
    result=client.post('/projects/'+pid+'/sources',headers=a,json={'request_id':str(uuid4()),'filename':'制度.docx','title':'制度','source_description':'实际上传原件','data_base64':base64.b64encode(raw).decode()})
    assert result.status_code==200,result.text
    doc=client.get('/projects/'+pid+'/sources',headers=a).json()[0]
    url=f'/projects/{pid}/sources/{doc["source_id"]}/versions/1'
    assert client.get(url,headers=a).json()['file']['format']=='docx'
    assert client.get(url+'/original',headers=a).content==raw
