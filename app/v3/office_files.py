"""Bounded text extraction. No OCR, model, office process or formula execution."""
from hashlib import sha256
from importlib.metadata import version
from io import BytesIO
from pathlib import PurePath
import zipfile

from .materials import MaterialInputError, MaterialLimitExceeded

MAX_BYTES = 8 * 1024 * 1024
MAX_TEXT = 12000
EXTENSIONS = {'pdf', 'docx', 'xlsx', 'pptx', 'txt', 'md', 'markdown'}


def parse_file(data, filename):
    if type(data) is not bytes or not isinstance(filename, str) or not filename or len(filename) > 255 or any(c in filename for c in '/\\:\x00'):
        raise MaterialInputError('请上传文件字节和有效文件名，不能提供本机路径。')
    ext = PurePath(filename).suffix.lower().lstrip('.')
    if ext not in EXTENSIONS:
        raise MaterialInputError('支持 PDF、DOCX、XLSX、PPTX 和 UTF-8 TXT/Markdown；不支持旧版 Office、宏或扫描件。')
    if not data or len(data) > MAX_BYTES:
        raise MaterialInputError('文件为空或超过 8 MiB，请拆分资料后上传。')
    result = {'filename': filename, 'format': ext, 'original_sha256': sha256(data).hexdigest(),
              'original_bytes': len(data), 'warnings': [], 'blocks': []}
    lines = []

    def block(label, text, location, rows=None):
        if not text.strip():
            return
        start = len(lines) + 1
        lines.extend(['## ' + label, text, ''])
        # Count canonical lines, including multiline text, exactly as SourceChunk does.
        flattened = '\n'.join(lines).splitlines()
        lines[:] = flattened + ([''] if lines[-1] == '' else [])
        entry = {'label': label, 'location': location, 'line_start': start, 'line_end': len(lines) - 1}
        if rows is not None:
            entry['rows'] = rows
        result['blocks'].append(entry)
        if len('\n'.join(lines)) > MAX_TEXT:
            raise MaterialLimitExceeded('解析全文超过 12,000 字符，请缩小范围；未截断或导入任何片段。')

    def table_text(rows):
        return '\n'.join(' | '.join(str(c).replace('\n', ' / ').replace('|', '\\|') for c in row) for row in rows)

    try:
        if ext in {'txt', 'md', 'markdown'}:
            if len(data) > 128 * 1024:
                raise MaterialInputError('TXT / Markdown 超过 128 KiB，请拆分后上传。')
            result['parser'] = 'UTF-8 strict'
            result['content'] = data.decode('utf-8', errors='strict')
            if not result['content'].strip('\ufeff \t\r\n'):
                raise MaterialInputError('资料没有可学习的文字。')
            result['blocks'] = [{'label': '原文', 'location': {'type': 'text'}, 'line_start': 1,
                                 'line_end': len(result['content'].splitlines())}]
            return result
        if ext != 'pdf':
            with zipfile.ZipFile(BytesIO(data)) as archive:
                entries = archive.infolist()
                if len(entries) > 512 or sum(i.file_size for i in entries) > 8 * 1024 * 1024:
                    raise MaterialInputError('Office 解压内容超过 8 MiB 或 512 项限制，请缩小资料。')
                if any('vbaproject' in i.filename.lower() or i.flag_bits & 1 for i in entries):
                    raise MaterialInputError('不支持含宏或加密的 Office 文件。')
        if ext == 'pdf':
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            result['parser'] = 'pypdf ' + version('pypdf')
            # Exporters often set permission encryption with an empty opening
            # password. These PDFs can be read normally without a password.
            if reader.is_encrypted and not reader.decrypt(''):
                raise MaterialInputError('PDF 需要打开密码，暂不支持；请提供可直接打开的文字版。')
            if not 1 <= len(reader.pages) <= 10:
                raise MaterialLimitExceeded('PDF 超过 10 页，请按章节拆分后上传。')
            result['warnings'].append('仅提取文字层；多栏阅读顺序及复杂表格需对照原件，未做 OCR 或图片理解。')
            for number, page in enumerate(reader.pages, 1):
                stream = page.get('/Contents')
                streams = stream if isinstance(stream, list) else [stream] if stream else []
                if sum(len(s.get_object().get_data()) for s in streams) > 2 * 1024 * 1024:
                    raise MaterialInputError('PDF 单页文字流过大，请拆分文件。')
                text = page.extract_text(extraction_mode='layout') or ''
                if not text.strip():
                    raise MaterialInputError(f'PDF 第 {number} 页无文字层，可能为扫描或空白页；请提供文字版。')
                block(f'PDF 第 {number} 页', text.strip(), {'type': 'pdf', 'page': number})
        elif ext == 'docx':
            from docx import Document
            from docx.text.paragraph import Paragraph
            document = Document(BytesIO(data))
            result['parser'] = 'python-docx ' + version('python-docx')
            result['warnings'].append('解析正文段落与表格；页眉页脚、批注、文本框和图片未纳入学习正文。')
            heading, paragraph, table = '正文', 0, 0
            for item in document.iter_inner_content():
                if isinstance(item, Paragraph):
                    paragraph += 1
                    if item.style and item.style.name.startswith('Heading'):
                        heading = item.text[:120]
                    block(f'DOCX {heading} · 段落 {paragraph}', item.text,
                          {'type': 'docx', 'heading': heading, 'paragraph': paragraph})
                else:
                    table += 1
                    rows = [[cell.text for cell in row.cells] for row in item.rows]
                    if sum(len(row) for row in rows) > 500:
                        raise MaterialInputError('DOCX 表格超过 500 单元格，请缩小资料。')
                    block(f'DOCX {heading} · 表 {table}', table_text(rows),
                          {'type': 'docx', 'heading': heading, 'table': table}, rows)
        elif ext == 'xlsx':
            from openpyxl import load_workbook
            book = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
            cached = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
            result['parser'] = 'openpyxl ' + version('openpyxl')
            result['warnings'].append('公式只显示原式及文件已有缓存值，未执行、未重算；图表和图片未解析。')
            try:
                if len(book.worksheets) > 8:
                    raise MaterialInputError('XLSX 最多支持 8 个工作表。')
                total = 0
                for sheet in book.worksheets:
                    size = sheet.max_row * sheet.max_column
                    total += size
                    if total > 500:
                        raise MaterialInputError('XLSX 有效范围超过 500 单元格（含空格和格式范围），请缩小资料。')
                    rows = []
                    for row in sheet.iter_rows():
                        values = []
                        for cell in row:
                            value = cell.value
                            if cell.data_type == 'f':
                                stored = cached[sheet.title][cell.coordinate].value
                                value = f'{value} [未计算；缓存：{stored if stored is not None else "无"}]'
                            values.append('' if value is None else str(value))
                        rows.append(values)
                    if any(any(c for c in row) for row in rows):
                        from openpyxl.utils import get_column_letter
                        area = f'A1:{get_column_letter(sheet.max_column)}{sheet.max_row}'
                        block(f'XLSX {sheet.title}!{area}', table_text(rows),
                              {'type': 'xlsx', 'sheet': sheet.title, 'range': area}, rows)
            finally:
                book.close()
                cached.close()
        elif ext == 'pptx':
            from pptx import Presentation
            presentation = Presentation(BytesIO(data))
            result['parser'] = 'python-pptx ' + version('python-pptx')
            result['warnings'].append('按幻灯片形状顺序提取文字和表格；图片、图表、讲者备注及动画未解析。')
            if not 1 <= len(presentation.slides) <= 15:
                raise MaterialLimitExceeded('PPTX 必须为 1–15 张幻灯片。')
            def shapes(items):
                for shape in items:
                    if hasattr(shape, 'shapes'):
                        yield from shapes(shape.shapes)
                    else:
                        yield shape
            for number, slide in enumerate(presentation.slides, 1):
                before = len(result['blocks'])
                for index, shape in enumerate(shapes(slide.shapes), 1):
                    rows = [[c.text for c in row.cells] for row in shape.table.rows] if shape.has_table else None
                    text = table_text(rows) if rows is not None else shape.text if shape.has_text_frame else ''
                    block(f'PPTX 第 {number} 张 · 文本/表格 {index}', text,
                          {'type': 'pptx', 'slide': number, 'shape': index}, rows)
                if before == len(result['blocks']):
                    raise MaterialInputError(f'PPTX 第 {number} 张没有可提取文字，请提供文字版。')
        result['content'] = '\n'.join(lines).rstrip()
        if not result['content']:
            raise MaterialInputError('文件没有可学习的正文文字，请提供文字版。')
        # Locations use the exact persisted canonical text, never a summarized copy.
        for entry in result['blocks']:
            entry['line_end'] = min(entry['line_end'], len(result['content'].splitlines()))
        return result
    except MaterialInputError:
        raise
    except Exception as exc:
        raise MaterialInputError('文件无法解析：可能已损坏、加密或格式与扩展名不符；请重新导出为支持的文字文件。') from exc
