"""Split oversize PDF, DOCX, and PPTX uploads without raising the text cap.

DOCX and PPTX keep Docling's declarative headings. PDF uses the model-free
NativePdfPipeline, which emits text cells and provenance but no heading
labels. This module then promotes a line to a heading only when a short
chapter pattern or a clearly larger font size is sparse enough to trust.
Otherwise the file is segmented by page or by length and each chapter says
so. Nothing here adds a vector index. Upload and offline pack generation
both call ``split_document``.

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
    split_basis: str = 'heading'
    page_start: int | None = None
    page_end: int | None = None


@dataclass(frozen=True)
class _SourceLine:
    text: str
    page: int | None = None
    height: float | None = None


@dataclass(frozen=True)
class _Segment:
    title: str
    lines: tuple
    basis: str


_BASIS_TEXT = {
    'heading': '标题',
    'heading-length': '标题；本段因超过 12,000 字符按长度续分，未并入其他标题',
    'page': '按页（未能可靠识别标题，不是按标题拆章）',
    'length': '按长度（未能可靠识别标题，不是按标题拆章）',
}
_STRICT_HEADING = re.compile(
    r'^(?:Chapter\s+\d+\b[ \w\-—:：]{0,40}|第[0-9０-９一二三四五六七八九十百千]+[章节篇部][^\n]{0,40})$'
)


def split_document(data: bytes, filename: str) -> list[Chapter]:
    """Return chapters whose text each fits ``MAX_TEXT``.

    PDF chapters are heading groups when NativePdf cell heights or a sparse
    chapter pattern make the boundaries reliable. Otherwise they are marked
    page or length segments and are not described as heading splits.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise MaterialInputError('没有可拆分的文件内容。')
    if not isinstance(filename, str) or PurePath(filename).suffix.lower().lstrip('.') not in {'pdf', 'docx', 'pptx'}:
        raise MaterialInputError('仅 PDF、DOCX、PPTX 可按标题自动拆分。')
    try:
        document = _convert(bytes(data), filename)
        chapters = _chapters(document, filename)
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
        # Production hosts here are ~1.6Gi RAM. Docling's default layout models
        # OOM-kill the process even with OCR/tables off. NativePdfPipeline keeps
        # Docling's Document + HybridChunker path without loading those models.
        # DOCX/PPTX still use Docling's declarative SimplePipeline (headings intact).
        from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import NativePdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.pipeline.native_pdf_pipeline import NativePdfPipeline
        options = NativePdfPipelineOptions()
        options.generate_page_images = False
        _CONVERTER = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.PPTX],
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_cls=NativePdfPipeline,
                    pipeline_options=options,
                    backend=PyPdfiumDocumentBackend,
                )
            },
        )
    return _CONVERTER


def split_notice(chapters: list[Chapter]) -> str:
    """One pack-level sentence that does not call a page split a heading split."""
    bases = {chapter.split_basis for chapter in chapters}
    limit = '各段正文不超过 12,000 字符，页数和字数上限未提高。'
    if bases and bases <= {'heading', 'heading-length'}:
        extra = '超长标题已按长度续分，没有并入其他标题。' if 'heading-length' in bases else ''
        return f'原文件超过现有页数、幻灯片或 12,000 字符上限，已按标题拆分为 {len(chapters)} 段。{extra}{limit}'
    if bases <= {'page', 'length'}:
        return f'原文件超过现有上限，但未能可靠识别标题，已按页或长度分为 {len(chapters)} 段，不是按标题拆章。{limit}'
    return f'原文件超过现有上限，已分为 {len(chapters)} 段，并在每段标明拆分依据。{limit}'


def chapter_notice(chapter: Chapter) -> str:
    if chapter.split_basis == 'heading':
        return '本章由超限原件按标题拆出，正文不超过 12,000 字符。'
    if chapter.split_basis == 'heading-length':
        return '本章标题可识别，但该标题正文超过 12,000 字符，因此按长度续分；未并入其他标题。'
    if chapter.split_basis == 'page':
        return '未能可靠识别标题，本段按页分段，不是按标题拆章。正文不超过 12,000 字符。'
    return '未能可靠识别标题，本段按长度分段，不是按标题拆章。正文不超过 12,000 字符。'


def chapter_source_text(content: str) -> str:
    """Source lines under the provenance header, without the header itself."""
    head, separator, body = content.partition('\n\n')
    if separator and head.startswith('# ') and '拆分依据：' in head:
        return body
    return content


def _chapters(document, filename):
    if PurePath(filename).suffix.lower() == '.pdf':
        return _pdf_chapters(document)
    return _office_chapters(document)


def _pdf_chapters(document):
    lines = _pdf_source_lines(document)
    return _chapters_from_segments(_segment_source_lines(lines))


def _pdf_source_lines(document):
    rows = []
    order = 0
    for item, _level in document.iterate_items():
        text = getattr(item, 'text', None)
        if not isinstance(text, str) or not text.strip():
            continue
        label = str(getattr(item, 'label', '') or '').lower()
        if 'picture' in label or 'table' in label:
            continue
        prov = list(getattr(item, 'prov', None) or [])
        page = height = None
        top = left = 0.0
        origin = ''
        if prov:
            box = prov[0].bbox
            page = getattr(prov[0], 'page_no', None)
            if box is not None:
                height = abs(float(box.t) - float(box.b))
                top = float(box.t)
                left = float(box.l)
                origin = str(getattr(box, 'coord_origin', '') or '')
        top_key = -top if 'BOTTOM' in origin.upper() else top
        for piece in text.splitlines():
            cleaned = piece.strip()
            if not cleaned:
                continue
            rows.append((page if page is not None else 10**9, top_key, left, order, _SourceLine(cleaned, page, height)))
            order += 1
    rows.sort(key=lambda row: row[:4])
    return [row[-1] for row in rows]


def _segment_source_lines(lines):
    usable = [line for line in lines if line.text and line.text.strip()]
    if not usable:
        return []
    spans = _heading_spans(usable)
    if not spans:
        return _page_segments(usable)
    segments = []
    if spans[0][0] > 0:
        segments.append(_Segment('正文', tuple(usable[:spans[0][0]]), 'length'))
    for index, (start, end, title) in enumerate(spans):
        next_start = spans[index + 1][0] if index + 1 < len(spans) else len(usable)
        chunk = tuple(usable[start:next_start])
        if segments and segments[-1].basis == 'heading' and _norm(segments[-1].title) == _norm(title):
            previous = segments[-1]
            segments[-1] = _Segment(previous.title, previous.lines + chunk, 'heading')
        else:
            segments.append(_Segment(title, chunk, 'heading'))
    return segments


def _heading_spans(lines):
    indexes = _candidate_indexes(lines)
    if not indexes:
        return []
    chosen = set(indexes)
    spans = []
    cursor = 0
    while cursor < len(indexes):
        start = indexes[cursor]
        end = start
        pos = cursor
        while pos + 1 < len(indexes):
            nxt = indexes[pos + 1]
            if any(lines[point].text.strip() for point in range(end + 1, nxt)):
                break
            nxt_text = lines[nxt].text.strip()
            if _STRICT_HEADING.match(nxt_text) and _norm(nxt_text) != _norm(lines[start].text):
                break
            if len(nxt_text) > 80:
                break
            end = nxt
            pos += 1
        parts = []
        seen = set()
        for point in range(start, end + 1):
            if point not in chosen:
                continue
            title = _norm(lines[point].text)
            if title not in seen:
                parts.append(title)
                seen.add(title)
        spans.append((start, end, ' '.join(parts)))
        cursor = pos + 1
    return spans


def _candidate_indexes(lines):
    body = _body_height(lines)
    strict, font = [], []
    for index, line in enumerate(lines):
        text = line.text.strip()
        if _STRICT_HEADING.match(text):
            strict.append(index)
        elif _font_heading(line, body):
            font.append(index)
    sparse = max(30, int(len(lines) * 0.2))
    if strict and len(strict) <= sparse:
        extra = font if len(font) <= sparse else []
        return sorted(set(strict + extra))
    if font and not strict and len(font) <= sparse and body is not None:
        return font
    return []


def _body_height(lines):
    """Body size is the smallest height that is used more than once.

    NativePdf cells have no heading label. A short sample can contain more
    heading lines than body lines, so the median is the heading size and the
    continuation line looks ordinary. A one-off footnote stays out of this
    choice. Equal sizes produce no larger heading tier.
    """
    heights = [line.height for line in lines if line.height and line.height > 0]
    if not heights:
        return None
    counts = {}
    for height in (round(value, 1) for value in heights):
        counts[height] = counts.get(height, 0) + 1
    frequent = [height for height, count in counts.items() if count >= 2]
    return min(frequent or counts)


def _font_heading(line, body):
    if body is None or not line.height or line.height <= 0:
        return False
    if len(line.text.strip()) > 80:
        return False
    return line.height >= body * 1.28 and line.height >= body + 2


def _page_segments(lines):
    if all(line.page is None for line in lines):
        return [_Segment('按长度分段', tuple(lines), 'length')]
    groups = []
    for line in lines:
        if not groups or groups[-1][0] != line.page:
            groups.append((line.page, [line]))
        else:
            groups[-1][1].append(line)
    return [_Segment(_page_title(page), tuple(body), 'page') for page, body in groups]


def _page_title(page):
    return f'第{page}页' if page else '按页分段'


def _range_title(lines, basis):
    pages = [line.page for line in lines if line.page]
    if basis == 'page' and pages:
        start, end = min(pages), max(pages)
        return f'第{start}页' if start == end else f'第{start}–{end}页'
    if basis == 'length':
        return '按长度分段'
    return '正文'


def _chapters_from_segments(segments):
    pieces = []
    pending = []

    def flush_pages():
        if pending:
            pieces.extend(_pack_page_run(pending))
            pending.clear()

    for segment in segments:
        if segment.basis == 'page':
            pending.append(segment)
            continue
        flush_pages()
        pieces.extend(_pack_lines(segment.title, segment.lines, segment.basis))
    flush_pages()
    return _numbered(pieces)


def _pack_page_run(segments):
    pieces = []
    bucket = []

    def flush():
        if bucket:
            lines = tuple(line for segment in bucket for line in segment.lines)
            pieces.append(_rendered(_range_title(lines, 'page'), lines, 'page'))
            bucket.clear()

    for segment in segments:
        if len(_render_text(_range_title(segment.lines, 'page'), segment.lines, 'page')) > MAX_TEXT:
            flush()
            pieces.extend(_pack_lines(_page_title(segment.lines[0].page), segment.lines, 'length'))
            continue
        trial_lines = tuple(line for item in bucket + [segment] for line in item.lines)
        if bucket and len(_render_text(_range_title(trial_lines, 'page'), trial_lines, 'page')) > MAX_TEXT:
            flush()
        bucket.append(segment)
    flush()
    return pieces


def _pack_lines(title, lines, basis):
    lines = tuple(lines)
    if not lines:
        return []
    fit_basis = 'heading' if basis == 'heading' else basis
    if len(_render_text(title, lines, fit_basis)) <= MAX_TEXT:
        return [_rendered(title, lines, fit_basis)]
    use_basis = 'heading-length' if basis == 'heading' else basis
    measure = f'{title}（999）'
    expanded = []
    for line in lines:
        if len(_render_text(measure, (line,), use_basis)) <= MAX_TEXT:
            expanded.append(line)
        else:
            expanded.extend(_slice_line(measure, line, use_basis))
    groups = []
    bucket = []

    def flush():
        if bucket:
            groups.append(tuple(bucket))
            bucket.clear()

    for line in expanded:
        trial = tuple(bucket + [line])
        if bucket and len(_render_text(measure, trial, use_basis)) > MAX_TEXT:
            flush()
        bucket.append(line)
    flush()
    pieces = []
    several = len(groups) > 1
    for index, group in enumerate(groups, 1):
        shown = f'{title}（{index}）' if several else title
        actual = use_basis if several else fit_basis
        pieces.append(_rendered(shown, group, actual))
    return pieces


def _slice_line(title, line, basis):
    """Split one oversized source line in order. Slices concatenate to the original."""
    room = MAX_TEXT - len(_header(title, basis, [line.page] if line.page else []))
    if room < 1:
        raise MaterialInputError('章节标题过长，无法在 12,000 字符内成章。')
    pieces = []
    start = 0
    text = line.text
    while start < len(text):
        end = min(len(text), start + room)
        piece = text[start:end]
        if not piece.strip():
            start = end
            continue
        pieces.append(_SourceLine(piece, line.page, line.height))
        start = end
    return pieces


def _rendered(title, lines, basis, content=None):
    pages = [line.page for line in lines if line.page]
    return _Piece(
        title=title,
        content=content if content is not None else _render_text(title, lines, basis),
        basis=basis,
        page_start=min(pages) if pages else None,
        page_end=max(pages) if pages else None,
    )


@dataclass(frozen=True)
class _Piece:
    title: str
    content: str
    basis: str
    page_start: int | None
    page_end: int | None


def _header(title, basis, pages):
    rows = [f'# {title}', f'拆分依据：{_BASIS_TEXT[basis]}']
    usable = [page for page in pages if page]
    if usable:
        start, end = min(usable), max(usable)
        rows.append(f'来源页码：{start}' if start == end else f'来源页码：{start}–{end}')
    return '\n'.join(rows) + '\n\n'


def _render_text(title, lines, basis):
    pages = [line.page for line in lines if line.page]
    body = '\n'.join(line.text for line in lines)
    return _header(title, basis, pages) + body


def _numbered(pieces):
    chapters = []
    for piece in pieces:
        if len(piece.content) > MAX_TEXT:
            raise MaterialInputError('拆分章节未落在 12,000 字符上限内，未导入。')
        chapters.append(Chapter(
            len(chapters) + 1, piece.title, piece.content, piece.basis, piece.page_start, piece.page_end,
        ))
    return chapters


def _norm(text):
    return re.sub(r'\s+', ' ', text).strip()


def _office_chapters(document):
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
        headed = bool(title and title != '正文' and any(_headings(chunk) for chunk in chunks))
        basis = ('heading-length' if len(pieces) > 1 else 'heading') if headed else 'length'
        pages = _chunk_pages(chunks)
        for offset, content in enumerate(pieces, 1):
            shown = title if len(pieces) == 1 else f'{title}（{offset}）'
            content = _annotate_office(content, basis, pages)
            start = min(pages) if pages else None
            end = max(pages) if pages else None
            chapters.append(Chapter(len(chapters) + 1, shown, content, basis, start, end))
    return chapters


def _chunk_pages(chunks):
    pages = []
    try:
        for chunk in chunks:
            meta = getattr(chunk, 'meta', None)
            for item in getattr(meta, 'doc_items', None) or []:
                for prov in getattr(item, 'prov', None) or []:
                    page = getattr(prov, 'page_no', None)
                    if isinstance(page, int):
                        pages.append(page)
    except (TypeError, AttributeError):
        return []
    return pages


def _annotate_office(content, basis, pages):
    note = f'拆分依据：{_BASIS_TEXT[basis]}'
    page_line = ''
    if pages:
        start, end = min(pages), max(pages)
        page_line = '\n' + (f'来源页码：{start}' if start == end else f'来源页码：{start}–{end}')
    addition = '\n' + note + page_line
    if len(content) + len(addition) > MAX_TEXT:
        return content
    if content.startswith('# '):
        first, sep, rest = content.partition('\n')
        return first + addition + (sep + rest if sep else '')
    return content + addition


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
