"""Oversize office uploads split by Docling headings; limits stay unchanged."""
import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from docx import Document
from pptx import Presentation

from app.v3.materials import MaterialLimitExceeded
from app.v3.office_files import MAX_TEXT, parse_file
from app.v3.split_policy import split_document
from tests.test_training_demo import login, runtime, visit
from tests.test_training_materials import SAMPLES

import pytest


def text_pdf(pages):
    objects = []

    def add(body):
        objects.append(body)
        return len(objects)

    font = add(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    page_ids = []
    for lines in pages:
        commands = ['BT', '50 760 Td']
        for index, line in enumerate(lines):
            size = 18 if index == 0 else 11
            escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
            commands.append(f'/F1 {size} Tf')
            commands.append(('0 -22 Td ' if index else '') + f'({escaped}) Tj')
        commands.append('ET')
        stream = '\n'.join(commands).encode('latin-1')
        content = add(b'<< /Length %d >>\nstream\n' % len(stream) + stream + b'\nendstream')
        page_ids.append(add(
            b'<< /Type /Page /Parent PAGES 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 %d 0 R >> >> >>'
            % (content, font)))
    kids = ' '.join(f'{page_id} 0 R' for page_id in page_ids)
    pages_id = add(f'<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>'.encode())
    catalog = add(f'<< /Type /Catalog /Pages {pages_id} 0 R >>'.encode())
    fixed = [body.replace(b'Parent PAGES 0 R', f'Parent {pages_id} 0 R'.encode()) for body in objects]
    out = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for number, body in enumerate(fixed, 1):
        offsets.append(len(out))
        out += f'{number} 0 obj\n'.encode() + body + b'\nendobj\n'
    xref = len(out)
    out += f'xref\n0 {len(fixed) + 1}\n'.encode() + b'0000000000 65535 f \n'
    for offset in offsets[1:]:
        out += f'{offset:010d} 00000 n \n'.encode()
    out += f'trailer << /Size {len(fixed) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    return bytes(out)


def oversize_pdf():
    pages = []
    for number in range(1, 13):
        heading = 'Chapter 1' if number <= 8 else 'Chapter 2'
        marker = 'CHAPTERONE' if number <= 8 else 'CHAPTERTWO'
        body = (marker + ' ') * 160
        lines = [heading, f'page {number}']
        lines.extend(body[index:index + 66] for index in range(0, len(body), 66))
        pages.append(lines)
    return text_pdf(pages)


def oversize_docx():
    document = Document()
    document.add_heading('第一章 服务响应', level=1)
    document.add_paragraph('甲' * 4000)
    document.add_heading('第二章 交接复核', level=1)
    document.add_paragraph('乙' * 4000)
    document.add_heading('第三章 记录留存', level=1)
    document.add_paragraph('丙' * 5000)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def oversize_pptx():
    deck = Presentation()
    for number in range(1, 17):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = f'第{number}张 要点'
        slide.placeholders[1].text = f'规则{number}'
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def assert_within_limit(chapters):
    assert chapters
    assert all(chapter.content.strip() and len(chapter.content) <= MAX_TEXT for chapter in chapters)
    for chapter in chapters:
        parsed = parse_file(chapter.content.encode(), f'{chapter.index}.md')
        assert len(parsed['content']) <= MAX_TEXT


def test_docx_headings_stay_inside_character_limit():
    data = oversize_docx()
    with pytest.raises(MaterialLimitExceeded):
        parse_file(data, '制度.docx')
    chapters = split_document(data, '制度.docx')
    assert_within_limit(chapters)
    assert len(chapters) == 3
    assert chapters[0].title.startswith('第一章') and '甲' in chapters[0].content and '丙' not in chapters[0].content
    assert '乙' in chapters[1].content and '丙' in chapters[2].content


def test_pdf_over_ten_pages_splits_into_chapters_inside_limit():
    data = oversize_pdf()
    with pytest.raises(MaterialLimitExceeded, match='10 页'):
        parse_file(data, '办法.pdf')
    chapters = split_document(data, '办法.pdf')
    assert_within_limit(chapters)
    assert len(chapters) >= 2
    assert any('CHAPTERONE' in chapter.content for chapter in chapters)
    assert any('CHAPTERTWO' in chapter.content for chapter in chapters)
    assert not any('CHAPTERONE' in chapter.content and 'CHAPTERTWO' in chapter.content for chapter in chapters)


def test_pptx_over_fifteen_slides_splits_by_title():
    data = oversize_pptx()
    with pytest.raises(MaterialLimitExceeded, match='15'):
        parse_file(data, '流程.pptx')
    chapters = split_document(data, '流程.pptx')
    assert_within_limit(chapters)
    assert len(chapters) == 16
    assert any('第16张' in chapter.title for chapter in chapters)


def upload(client, headers, name, data, unit=False, request_id=None):
    return client.post('/training/api/' + ('admin/' if unit else '') + 'materials', headers=headers,
        json={'request_id': request_id or str(uuid4()), 'filename': name, 'title': name,
              'data_base64': base64.b64encode(data).decode()})


def test_existing_material_rows_keep_ready_status_when_columns_are_added(tmp_path):
    import sqlite3
    from deploy.training_materials import TrainingMaterials
    database = tmp_path / 'gateway.sqlite'
    connection = sqlite3.connect(database)
    connection.execute('''CREATE TABLE training_assets(
        id TEXT PRIMARY KEY, account TEXT NOT NULL, unit_id TEXT, scope TEXT NOT NULL,
        request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, title TEXT NOT NULL,
        filename TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(account,scope,request_id))''')
    connection.execute('''INSERT INTO training_assets(id,account,scope,request_id,fingerprint,title,filename,status)
        VALUES ('material_abc','acct','private','11111111-1111-1111-1111-111111111111','fp','旧资料','a.docx','ready')''')
    connection.commit()
    connection.close()
    materials = TrainingMaterials(tmp_path, database, object())
    with materials.connect() as conn:
        row = dict(conn.execute('SELECT * FROM training_assets').fetchone())
    assert row['status'] == 'ready' and row['title'] == '旧资料' and row['asset_role'] == 'document'
    assert materials.public(row)['kind'] == 'document'


def test_upload_creates_parent_pack_and_ready_chapters(runtime):
    client, gateway, _ = runtime
    guest, _ = visit(client)
    key = str(uuid4())
    first = upload(client, guest, '办法.pdf', oversize_pdf(), request_id=key)
    assert first.status_code == 201, first.text
    pack = first.json()
    assert pack['auto_split'] is True and pack['kind'] == 'pack'
    assert pack['chapter_count'] == len(pack['chapters']) >= 2
    assert '已自动拆分为' in Path('app/static/training.js').read_text(encoding='utf-8')
    again = upload(client, guest, '办法.pdf', oversize_pdf(), request_id=key)
    assert again.json()['id'] == pack['id'] and again.json()['chapter_count'] == pack['chapter_count']
    listed = client.get('/training/api/materials', headers=guest).json()['materials']
    assert sum(1 for item in listed if item.get('parent_id') == pack['id']) == pack['chapter_count']
    chapter = client.get('/training/api/materials/' + pack['chapters'][0]['id'], headers=guest)
    assert chapter.status_code == 200
    body = chapter.json()
    assert body['kind'] == 'chapter' and body['status'] == 'ready'
    assert len(body['parsed']['content']) <= MAX_TEXT
    created = client.post('/projects', headers=guest, json={'request_id': str(uuid4()), 'intent': {'goal': '学习办法中的规则'}}).json()
    attached = client.post('/training/api/materials/' + body['id'] + '/attach', headers=guest,
        json={'project_id': created['project_id'], 'request_id': str(uuid4())})
    assert attached.status_code == 200, attached.text
    source = attached.json()
    detail = client.get(f"/projects/{created['project_id']}/sources/{source['source_id']}/versions/1", headers=guest).json()
    assert len(detail['content']) <= MAX_TEXT and detail['content'].strip()
    refused = client.post('/training/api/materials/' + pack['id'] + '/attach', headers=guest,
        json={'project_id': created['project_id'], 'request_id': str(uuid4())})
    assert refused.status_code == 422 and '章节' in refused.json()['error']['message']
    kept = upload(client, guest, '培训制度.docx', (SAMPLES / '培训制度.docx').read_bytes())
    assert kept.status_code == 201 and kept.json()['kind'] == 'document'
    blank = upload(client, guest, '空白.pdf', text_pdf([[' '] for _ in range(11)]))
    assert blank.status_code == 422 and blank.json()['status'] == 'failed'
    assert not any(item.get('parent_id') == blank.json()['id'] for item in client.get('/training/api/materials', headers=guest).json()['materials'])
    other = login(client, 2)
    assert client.get('/training/api/materials/' + pack['id'], headers=other).status_code == 404
    admin = login(client, 0)
    unit = upload(client, admin, '制度.docx', oversize_docx(), unit=True)
    assert unit.status_code == 201, unit.text
    unit_pack = unit.json()
    assert unit_pack['auto_split'] is True and unit_pack['chapter_count'] == 3
    with gateway.training.store.connect() as conn:
        version_ids = {row[0] for row in conn.execute('SELECT id FROM training_material_versions')}
    assert unit_pack['id'] not in version_ids
    assert {item['id'] for item in unit_pack['chapters']} <= version_ids
