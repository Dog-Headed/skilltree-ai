"""Split oversize PDF, DOCX, and PPTX uploads by Docling headings.

The page, slide, and character caps stay in ``office_files``. This module does
not raise them and does not add a vector index. Upload and offline pack
generation both call ``split_document``.

Curated demo packs, when present under ``samples/yanan-policy-packs/``, are
left untouched. To build chapters offline::

    from pathlib import Path
    from app.v3.split_policy import split_document

    source = Path("源文件.pdf")
    for chapter in split_document(source.read_bytes(), source.name):
        target = Path("chapters") / f"{chapter.index:02d}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(chapter.content, encoding="utf-8")
"""
from dataclasses import dataclass
from pathlib import PurePath
import re
import threading

from .materials import MaterialInputError
from .office_files import MAX_TEXT

_LOCK = threading.Lock()
_CONVERTER = None
# Room for the markdown heading added around a Docling chunk.
_HEADING_ROOM = 80


@dataclass(frozen=True)
class Chapter:
    index: int
    title: str
    content: str


def split_document(data: bytes, filename: str) -> list[Chapter]:
    """Return heading chapters whose text each fits ``MAX_TEXT``."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise MaterialInputError('没有可拆分的文件内容。')
    if not isinstance(filename, str) or PurePath(filename).suffix.lower().lstrip('.') not in {'pdf', 'docx', 'pptx'}:
        raise MaterialInputError('仅 PDF、DOCX、PPTX 可按标题自动拆分。')
    try:
        document = _convert(bytes(data), filename)
        chapters = _chapters(document)
    except MaterialInputError:
        raise
    except ImportError as exc:
        raise MaterialInputError('服务器未安装文档拆分组件，超限文件请按章节拆分后上传。') from exc
    except Exception as exc:
        raise MaterialInputError('超限文件无法按标题拆分，请按章节拆分后重新上传。') from exc
    if not chapters:
        raise MaterialInputError('文件没有可学习的正文文字，可能为扫描件或空白页；请提供文字版。')
    for chapter in chapters:
        if not chapter.content.strip() or len(chapter.content) > MAX_TEXT:
            raise MaterialInputError('拆分章节未落在 12,000 字符上限内，未导入。')
    return chapters


def _convert(data, filename):
    with _LOCK:
        converter = _converter()
        from docling.datamodel.base_models import DocumentStream
        from io import BytesIO
        result = converter.convert(DocumentStream(name=filename, stream=BytesIO(data)))
    status = getattr(result.status, 'name', str(result.status))
    if status == 'FAILURE' or result.document is None:
        raise MaterialInputError('超限文件无法按标题拆分，请按章节拆分后重新上传。')
    return result.document


def _converter():
    global _CONVERTER
    if _CONVERTER is None:
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        options = PdfPipelineOptions()
        options.do_ocr = False
        options.do_table_structure = False
        options.do_code_enrichment = False
        options.do_formula_enrichment = False
        if hasattr(options, 'force_backend_text'):
            options.force_backend_text = True
        _CONVERTER = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options, backend=PyPdfiumDocumentBackend)},
        )
    return _CONVERTER


def _chapters(document):
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer

    class CharBudgetTokenizer(BaseTokenizer):
        """Count characters so a chapter cannot pass the existing text cap."""
        limit: int

        def count_tokens(self, text: str) -> int:
            return len(text or '')

        def get_max_tokens(self) -> int:
            return self.limit

        def get_tokenizer(self):
            return lambda text: len(text or '')

    # HybridChunker starts from HierarchicalChunker, then keeps same-title
    # pieces together only while they stay inside the existing character cap.
    budget = max(200, MAX_TEXT - _HEADING_ROOM)
    chunker = HybridChunker(tokenizer=CharBudgetTokenizer(limit=budget), merge_peers=True)
    grouped = []
    for chunk in chunker.chunk(document):
        if not (chunk.text or '').strip():
            continue
        title = _title(_headings(chunk))
        if grouped and grouped[-1][0] == title:
            grouped[-1][1].append(chunk)
        else:
            grouped.append((title, [chunk]))
    return _number(grouped)


def _number(grouped):
    chapters = []
    for title, chunks in grouped:
        pieces = _pack(title, chunks)
        for offset, content in enumerate(pieces, 1):
            shown = title if len(pieces) == 1 else f'{title}（{offset}）'
            chapters.append(Chapter(len(chapters) + 1, shown, content))
    return chapters


def _headings(chunk):
    raw = getattr(getattr(chunk, 'meta', None), 'headings', None) or []
    headings = []
    for item in raw:
        text = re.sub(r'\s+', ' ', str(item)).strip()
        if text:
            headings.append(text[:80])
    return headings


def _title(headings):
    return headings[0] if headings else '正文'


def _render(title, chunks):
    lines = [f'# {title}']
    previous = None
    for chunk in chunks:
        subs = [heading for heading in _headings(chunk) if heading != title]
        marker = tuple(subs)
        if marker != previous:
            lines.extend(f'## {heading}' for heading in subs)
            previous = marker
        text = (chunk.text or '').strip()
        if text:
            lines.append(text)
    return '\n\n'.join(lines).strip()


def _pack(title, chunks):
    pieces = []
    buffer = []

    def flush():
        if buffer:
            pieces.append(_render(title, buffer))
            buffer.clear()

    for chunk in chunks:
        alone = _render(title, [chunk])
        if len(alone) > MAX_TEXT:
            flush()
            pieces.extend(_windows(title, (chunk.text or '').strip()))
            continue
        if buffer and len(_render(title, buffer + [chunk])) > MAX_TEXT:
            flush()
        buffer.append(chunk)
    flush()
    return pieces


def _windows(title, text):
    header = f'# {title}\n\n'
    room = MAX_TEXT - len(header)
    if room < 1:
        raise MaterialInputError('章节标题过长，无法在 12,000 字符内成章。')
    pieces = []
    start = 0
    while start < len(text):
        end = min(len(text), start + room)
        if end < len(text):
            newline = text.rfind('\n', start + room // 2, end)
            if newline != -1:
                end = newline
        if end <= start:
            end = min(len(text), start + room)
        piece = text[start:end].strip()
        if not piece:
            break
        content = header + piece
        if len(content) > MAX_TEXT:
            piece = piece[:room]
            content = header + piece
        pieces.append(content)
        start = end
    return pieces
