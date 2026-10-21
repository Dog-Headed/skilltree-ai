"""Versioned text materials; this service never invokes a Graph or a model.

The repository owns request deduplication and version allocation in one write
transaction. Upload names are labels, never local paths to open.
"""

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from uuid import NAMESPACE_URL, UUID, uuid5

from app.v3.config import SERVER_LIMITS, ServerLimits
from app.v3.contracts import SourceChunk, SourceDocument


class MaterialInputError(ValueError):
    pass


class ContextBudgetExceeded(ValueError):
    pass


def json_data(value) -> str:
    """A stable data representation, without treating source text as prompts."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def chunk_document(document: SourceDocument) -> list[SourceChunk]:
    """Deterministic complete-line chunks; preserve exact source line locations.

    A long single line remains intact. If it cannot fit a later context budget,
    that stage refuses explicitly instead of producing a misleading fragment.
    CRLF remains in the stored original; chunk text uses the source line model's
    canonical LF joining. Raw-document and chunk hashes are stored separately.
    """
    document = SourceDocument.model_validate(document)
    lines = document.content.splitlines()
    chunks = []
    start = 0
    heading = None
    current_heading = None
    characters = 0

    def append(end):
        content = "\n".join(lines[start:end])
        if not content.strip():
            return
        digest = sha256(content.encode("utf-8")).hexdigest()
        identity = f"{document.project_id}:{document.source_id}:{document.source_version}:{start + 1}:{end}:{digest}"
        chunks.append(SourceChunk(
            chunk_id="chunk_" + uuid5(NAMESPACE_URL, identity).hex,
            project_id=document.project_id, source_id=document.source_id,
            source_version=document.source_version, content=content,
            content_hash=digest, heading=current_heading,
            line_start=start + 1, line_end=end,
        ))

    for index, line in enumerate(lines):
        match = re.match(r"^\ufeff?#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match:
            heading = match.group(1).strip()[:256]
        if index > start and (match or characters + 1 + len(line) > 2000):
            append(index)
            start = index
            characters = 0
            current_heading = heading
        if index == start:
            current_heading = heading
        characters += len(line) + (1 if index > start else 0)
    if lines:
        append(len(lines))
    if not chunks:
        raise MaterialInputError("资料正文为空，无法建立可引用片段")
    return chunks


def validate_chunk_origin(chunk: SourceChunk, source: SourceDocument) -> None:
    chunk = SourceChunk.model_validate(chunk)
    source = SourceDocument.model_validate(source)
    if (chunk.project_id, chunk.source_id, chunk.source_version) != (source.project_id, source.source_id, source.source_version):
        raise ValueError("片段与实际来源的项目或版本不一致")
    lines = source.content.splitlines()
    if chunk.line_end > len(lines) or "\n".join(lines[chunk.line_start - 1:chunk.line_end]) != chunk.content:
        raise ValueError("片段无法通过实际资料行号定位")


@dataclass(frozen=True)
class MaterialImportResult:
    document: SourceDocument
    chunks: tuple[SourceChunk, ...]
    reused: bool
    draft_revision: int

    def model_dump(self):
        return {"document": self.document.model_dump(), "chunks": [chunk.model_dump() for chunk in self.chunks],
                "reused": self.reused, "draft_revision": self.draft_revision}


class MaterialService:
    def __init__(self, repository):
        self.repository = repository
        self.limits = ServerLimits.model_validate(getattr(repository, "limits", SERVER_LIMITS))

    def import_text(self, project_id: str, *, content: str, title: str,
                    source_description: str, request_id: UUID | str,
                    source_id: str | None = None, visibility: str = "teaching") -> MaterialImportResult:
        if not isinstance(content, str) or not content.strip("\ufeff \t\r\n"):
            raise MaterialInputError("请提供非空文字资料")
        if not isinstance(title, str) or not title.strip() or not isinstance(source_description, str) or not source_description.strip():
            raise MaterialInputError("资料需要标题与来源说明")
        try:
            raw = content.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise MaterialInputError("资料必须是合法 UTF-8 文字") from exc
        if len(raw) > self.limits.max_file_bytes:
            raise MaterialInputError("资料超过服务端单文件字节上限")
        try:
            key = str(UUID(str(request_id)))
        except (ValueError, TypeError, AttributeError) as exc:
            raise MaterialInputError("资料导入 request_id 必须是 UUID") from exc
        if source_id is None:
            identity = json_data([project_id, title, source_description])
            source_id = "source_" + uuid5(NAMESPACE_URL, identity).hex
        # Validate before crossing the persistence boundary. Version 1 is only
        # a validation placeholder; the repository allocates the actual version.
        proposed = SourceDocument(
            project_id=project_id, source_id=source_id, source_version=1,
            title=title, source_description=source_description, content=content,
            content_hash=sha256(raw).hexdigest(), visibility=visibility,
        )
        document_kwargs = proposed.model_dump(exclude={"source_version"})
        saved = self.repository.import_source_version(document_kwargs, chunk_document, request_id=key)
        document = SourceDocument.model_validate(saved["document"])
        chunks = tuple(SourceChunk.model_validate(chunk) for chunk in saved["chunks"])
        if document.model_dump(exclude={"source_version"}) != document_kwargs:
            raise ValueError("已保存资料与导入请求内容不一致")
        if not chunks:
            raise ValueError("已保存资料没有可引用片段")
        for chunk in chunks:
            validate_chunk_origin(chunk, document)
        if type(saved["reused"]) is not bool or type(saved["draft_revision"]) is not int or saved["draft_revision"] < 1:
            raise ValueError("资料导入结果的复用标记或草稿版本无效")
        return MaterialImportResult(document, chunks, saved["reused"], saved["draft_revision"])

    def import_upload(self, project_id: str, *, data: bytes, filename: str,
                      title: str, source_description: str, request_id: UUID | str,
                      source_id: str | None = None, visibility: str = "teaching") -> MaterialImportResult:
        if type(data) is not bytes:
            raise MaterialInputError("上传入口只接受文件字节，不接受本机路径")
        if not isinstance(filename, str) or not filename or any(char in filename for char in "/\\:\x00"):
            raise MaterialInputError("文件名必须是名称，不能是本机路径")
        if len(filename) > 255 or filename.rsplit(".", 1)[-1].lower() not in {"txt", "md", "markdown"} or "." not in filename:
            raise MaterialInputError("首版仅支持 UTF-8 TXT 或 Markdown")
        if len(data) > self.limits.max_file_bytes:
            raise MaterialInputError("上传超过服务端单文件字节上限")
        try:
            # Preserve a UTF-8 BOM and CRLF in the original document/hash.
            content = data.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise MaterialInputError("上传文件不是合法 UTF-8") from exc
        return self.import_text(project_id, content=content, title=title,
                                source_description=source_description, request_id=request_id,
                                source_id=source_id, visibility=visibility)

    def catalog(self, project_id: str) -> list[dict]:
        """Latest selected public sources, never answer-only/private material.

        The complete catalog either fits the server budget or is refused. A
        planner must never receive fabricated references to omitted content.
        """
        if self.repository.get_project(project_id) is None:
            raise KeyError(project_id)
        latest = {}
        for raw in self.repository.list_sources(project_id, include_private=True):
            source = SourceDocument.model_validate(raw)
            if source.project_id != project_id:
                raise ValueError("资料目录返回跨项目来源")
            previous = latest.get(source.source_id)
            if previous is None or source.source_version > previous.source_version:
                latest[source.source_id] = source
        catalog = []
        for source_id in sorted(latest):
            source = latest[source_id]
            if source.visibility != "teaching":
                continue
            chunks = self.repository.list_source_chunks(project_id, source_id, source.source_version, include_private=False)
            if not chunks:
                raise ValueError("资料目录存在来源但没有实际持久化片段")
            for raw in sorted(chunks, key=lambda value: (value["line_start"], value["chunk_id"])):
                chunk = SourceChunk.model_validate(raw)
                validate_chunk_origin(chunk, source)
                catalog.append({
                    "chunk_id": chunk.chunk_id, "project_id": chunk.project_id,
                    "source_id": chunk.source_id, "source_version": chunk.source_version,
                    "content_hash": chunk.content_hash, "content": chunk.content,
                    "title": source.title, "heading": chunk.heading, "visibility": "teaching",
                })
        if len(json_data(catalog)) > self.limits.max_context_characters:
            raise ContextBudgetExceeded("完整资料目录超过服务端上下文上限，请缩小或拆分学习范围")
        return catalog
