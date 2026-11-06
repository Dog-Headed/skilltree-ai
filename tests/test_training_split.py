"""Oversize office uploads split by Docling headings; limits stay unchanged."""
import base64
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from docx import Document
from pptx import Presentation

from app.v3.materials import MaterialLimitExceeded
from app.v3.office_files import MAX_TEXT, parse_file
from app.v3.split_policy import _convert, _pdf_source_lines, chapter_source_text, split_document
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
            if isinstance(line, tuple):
                text, size = line
            else:
                text, size = line, (18 if index == 0 else 11)
            escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
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


def _source_blob(chapters):
    return '\n'.join(chapter_source_text(chapter.content) for chapter in chapters)


def _pdf_text(data, filename):
    return '\n'.join(line.text for line in _pdf_source_lines(_convert(data, filename)))


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
    assert all(chapter.split_basis.startswith('heading') for chapter in chapters)
    assert all('拆分依据：标题' in chapter.content for chapter in chapters)
    assert all(chapter.page_start and chapter.page_end for chapter in chapters)
    assert [chapter.page_start for chapter in chapters] == sorted(chapter.page_start for chapter in chapters)
    assert chapters[0].page_start == 1 and chapters[-1].page_end == 12
    blob = _source_blob(chapters)
    assert blob == _pdf_text(data, '办法.pdf')
    assert blob.index('CHAPTERONE') < blob.index('CHAPTERTWO')


def test_pdf_heading_split_across_pages_stays_one_chapter():
    pages = [
        [('Chapter 1', 18)],
        [('Overview', 18), ('ALPHABODY stays with the first heading', 11)],
        [('Chapter 2', 18), ('BETABODY starts the next heading', 11)],
    ]
    data = text_pdf(pages)
    chapters = split_document(data, 'cross-page.pdf')
    assert_within_limit(chapters)
    first = next(chapter for chapter in chapters if 'ALPHABODY' in chapter.content)
    second = next(chapter for chapter in chapters if 'BETABODY' in chapter.content)
    assert first is not second
    assert 'Chapter 1' in first.title and 'Overview' in first.title
    assert 'BETABODY' not in first.content and 'ALPHABODY' not in second.content
    assert first.split_basis.startswith('heading') and first.page_start == 1 and first.page_end == 2
    assert second.page_start == 3
    assert _source_blob(chapters) == _pdf_text(data, 'cross-page.pdf')


def test_chinese_heading_continued_on_the_next_page_merges():
    """PDF latin-1 fixtures cannot carry 第N章. The grouper itself must."""
    from app.v3.split_policy import _SourceLine, _segment_source_lines
    lines = [
        _SourceLine('第一章', 1, 18),
        _SourceLine('总则', 2, 18),
        _SourceLine('甲正文', 2, 11),
        _SourceLine('第二章', 3, 18),
        _SourceLine('乙正文', 3, 11),
    ]
    segments = _segment_source_lines(lines)
    assert segments[0].title == '第一章 总则' and segments[0].basis == 'heading'
    assert [line.text for line in segments[0].lines] == ['第一章', '总则', '甲正文']
    assert segments[1].title == '第二章'
    assert [line.text for line in segments[1].lines] == ['第二章', '乙正文']


def test_pdf_body_continues_until_the_next_heading():
    pages = [
        [('Chapter 1 Service', 18), ('KEEPONE alpha', 11)],
        [('KEEPONE beta', 11)],
        [('KEEPONE gamma', 11)],
        [('Chapter 2 Review', 18), ('KEEPTWO only', 11)],
    ]
    data = text_pdf(pages)
    chapters = split_document(data, 'body-continues.pdf')
    assert_within_limit(chapters)
    first = next(chapter for chapter in chapters if 'KEEPONE' in chapter.content)
    assert 'KEEPONE alpha' in first.content and 'KEEPONE beta' in first.content and 'KEEPONE gamma' in first.content
    assert 'KEEPTWO' not in first.content
    assert first.page_start == 1 and first.page_end == 3
    assert first.split_basis.startswith('heading')
    assert _source_blob(chapters) == _pdf_text(data, 'body-continues.pdf')


def test_pdf_without_reliable_headings_is_marked_page_or_length():
    pages = [[('PLAINTEXT uniform line', 11), ('still no chapter pattern', 11)] for _ in range(12)]
    data = text_pdf(pages)
    chapters = split_document(data, '无标题.pdf')
    assert_within_limit(chapters)
    assert chapters
    assert all(chapter.split_basis in {'page', 'length'} for chapter in chapters)
    assert all('不是按标题拆章' in chapter.content for chapter in chapters)
    assert all(not chapter.split_basis.startswith('heading') for chapter in chapters)
    assert all('拆分依据：标题' not in chapter.content for chapter in chapters)
    assert _source_blob(chapters) == _pdf_text(data, '无标题.pdf')
    assert chapters[0].page_start == 1 and chapters[-1].page_end == 12


def test_pdf_overlong_single_heading_stays_inside_limit():
    token = 'LONGWORD '
    body = token * 2000
    cut_a, cut_b = len(token) * 400, len(token) * 800
    pages = [
        [('Chapter 1', 18), (body[:cut_a], 11)],
        [(body[cut_a:cut_b], 11)],
        [(body[cut_b:], 11)],
    ]
    data = text_pdf(pages)
    chapters = split_document(data, '超长单章.pdf')
    assert_within_limit(chapters)
    assert len(chapters) >= 2
    assert all(chapter.title.startswith('Chapter 1') for chapter in chapters)
    assert all(chapter.split_basis == 'heading-length' for chapter in chapters)
    assert all('未并入其他标题' in chapter.content for chapter in chapters)
    assert _source_blob(chapters) == _pdf_text(data, '超长单章.pdf')
    assert chapters[0].page_start == 1 and chapters[-1].page_end == 3


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
