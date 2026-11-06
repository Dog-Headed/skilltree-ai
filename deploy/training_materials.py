"""Personal and unit material libraries; no publication or assignment on Day 2."""
import asyncio
from contextlib import contextmanager
import base64
import binascii
from hashlib import sha256
import json
from pathlib import Path, PurePath
import re
import shutil
import sqlite3
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi.responses import FileResponse
from app.v3.office_files import MAX_TEXT, parse_file
from app.v3.materials import MaterialInputError, MaterialLimitExceeded, MaterialService
from app.v3.split_policy import chapter_notice, split_document, split_notice
from app.v3.execution import project_execution
from app.v3.learning_repository import LearningRepository
from app.v3.project_management import require_visible
from app.v3.repository import ConflictError
from .jobs import AdmissionError


class TrainingMaterials:
    def __init__(self, root, database, store):
        self.root, self.database, self.store = Path(root)/'materials', Path(database), store
        self.root.mkdir(parents=True, exist_ok=True)
        self.slots = asyncio.Semaphore(2)
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS training_assets(
                id TEXT PRIMARY KEY, account TEXT NOT NULL, unit_id TEXT, scope TEXT NOT NULL,
                request_id TEXT NOT NULL, fingerprint TEXT NOT NULL, title TEXT NOT NULL,
                filename TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(account,scope,request_id))''')
            self._ensure_asset_columns(conn)
            conn.execute("UPDATE training_assets SET status='failed',error='服务在解析完成前重启，请重新上传。' WHERE status='processing'")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def allowed(self, row, member, scope):
        return row['scope'] == scope and (row['account'] == member['account'] if scope == 'private'
            else member['role'] == 'admin' and row['unit_id'] == member['unit_id'])

    def get(self, identity, member, scope):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM training_assets WHERE id=?', (identity,)).fetchone()
        if not row or not self.allowed(row, member, scope):
            raise KeyError(identity)
        return dict(row)

    def filename_for(self, material_id):
        with self.connect() as conn:
            row = conn.execute('SELECT filename FROM training_assets WHERE id=?', (material_id,)).fetchone()
        return row['filename'] if row else None

    def _ensure_asset_columns(self, conn):
        cols = {row[1] for row in conn.execute('PRAGMA table_info(training_assets)')}
        if 'parent_id' not in cols:
            conn.execute('ALTER TABLE training_assets ADD COLUMN parent_id TEXT')
        if 'asset_role' not in cols:
            conn.execute("ALTER TABLE training_assets ADD COLUMN asset_role TEXT NOT NULL DEFAULT 'document'")
        if 'split_count' not in cols:
            conn.execute('ALTER TABLE training_assets ADD COLUMN split_count INTEGER')
        if 'chapter_index' not in cols:
            conn.execute('ALTER TABLE training_assets ADD COLUMN chapter_index INTEGER')

    def _field(self, row, name, default=None):
        if name not in row.keys():
            return default
        value = row[name]
        return default if value is None else value

    def public(self, row, detail=False):
        result = {k: row[k] for k in ('id','title','filename','scope','status','error','created_at')}
        role = self._field(row, 'asset_role', 'document')
        result['kind'] = role
        if role == 'pack':
            result['auto_split'] = True
            result['chapter_count'] = self._field(row, 'split_count', 0)
        elif role == 'chapter':
            result['parent_id'] = self._field(row, 'parent_id')
            result['chapter_index'] = self._field(row, 'chapter_index')
        if detail and row['status'] == 'ready':
            parsed_path = self.root/row['id']/'parsed.json'
            if parsed_path.is_file():
                result['parsed'] = json.loads(parsed_path.read_text(encoding='utf-8'))
            if role == 'pack':
                result['chapters'] = self._chapters(row['id'])
        return result

    def _chapters(self, parent_id):
        with self.connect() as conn:
            rows = conn.execute('''SELECT id,title,chapter_index FROM training_assets
                WHERE parent_id=? ORDER BY chapter_index,id''', (parent_id,)).fetchall()
        return [{'id': row['id'], 'title': row['title'], 'index': row['chapter_index']} for row in rows]

    def upload(self, payload, member, scope):
        if set(payload) != {'request_id', 'filename', 'title', 'data_base64'}:
            raise MaterialInputError('请提供文件、标题及上传请求编号。')
        request = str(UUID(str(payload['request_id'])))
        title, filename, raw = payload['title'], payload['filename'], payload['data_base64']
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 256 or not isinstance(filename,str) or len(filename)>255:
            raise MaterialInputError('请提供有效文件名和 1–256 字符的标题。')
        if not isinstance(raw, str) or len(raw) > 11184812:
            raise MaterialInputError('文件超过 8 MiB，请拆分后上传。')
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise MaterialInputError('文件编码无效，请重新选择原件。') from exc
        fingerprint = sha256(json.dumps([filename,title,sha256(data).hexdigest()],ensure_ascii=False).encode()).hexdigest()
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM training_assets WHERE account=? AND scope=? AND request_id=?',
                               (member['account'], scope, request)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint:
                    raise ConflictError('Upload request changed')
                return self.public(dict(row), True)
            identity = 'material_' + uuid4().hex
            conn.execute('''INSERT INTO training_assets(id,account,unit_id,scope,request_id,fingerprint,title,filename,status)
                         VALUES (?,?,?,?,?,?,?,?, 'processing')''',
                         (identity,member['account'],member['unit_id'],scope,request,fingerprint,title.strip(),filename))
        try:
            ext = PurePath(filename).suffix.lower().lstrip('.')
            try:
                parsed = parse_file(data, filename)
            except MaterialLimitExceeded:
                if ext not in {'pdf', 'docx', 'pptx'}:
                    raise
                self._store_split(identity, data, filename, title.strip(), member, scope, request)
            else:
                self._store_parsed(identity, data, parsed, title.strip(), member, scope)
        except MaterialInputError as exc:
            with self.connect() as conn:
                conn.execute("UPDATE training_assets SET status='failed',error=? WHERE id=?",(str(exc),identity))
        return self.public(self.get(identity,member,scope), True)

    def _store_parsed(self, identity, data, parsed, title, member, scope):
        folder = self.root / identity
        folder.mkdir()
        (folder/'original').write_bytes(data)
        (folder/'parsed.json').write_text(json.dumps(parsed,ensure_ascii=False),encoding='utf-8')
        if scope == 'unit':
            with self.store.connect() as conn:
                self._insert_unit_version(conn, identity, member, title, folder, parsed['blocks'])
        with self.connect() as conn:
            conn.execute("UPDATE training_assets SET status='ready' WHERE id=?",(identity,))

    def _insert_unit_version(self, conn, identity, member, title, folder, blocks):
        conn.execute('''INSERT INTO training_material_versions
            (id,unit_id,owner_account,visibility,version,title,original_path,parsed_path,locations_json)
            VALUES (?,?,?,'unit',1,?,?,?,?)''',
            (identity,member['unit_id'],member['account'],title,str(folder/'original'),
             str(folder/'parsed.json'),json.dumps(blocks,ensure_ascii=False)))

    def _store_split(self, identity, data, filename, title, member, scope, request):
        chapters = split_document(data, filename)
        prepared, created = [], []
        try:
            for chapter in chapters:
                child_id = 'material_' + uuid4().hex
                child_name = _chapter_filename(filename, chapter.index)
                raw = chapter.content.encode('utf-8')
                folder = self.root / child_id
                folder.mkdir()
                created.append(child_id)
                parsed = parse_file(raw, child_name)
                if len(parsed['content']) > MAX_TEXT:
                    raise MaterialInputError('拆分章节仍超过 12,000 字符，未导入。')
                parsed['warnings'].append(chapter_notice(chapter))
                parsed['split_basis'] = chapter.split_basis
                parsed['page_start'] = chapter.page_start
                parsed['page_end'] = chapter.page_end
                (folder/'original').write_bytes(raw)
                (folder/'parsed.json').write_text(json.dumps(parsed,ensure_ascii=False),encoding='utf-8')
                prepared.append({'id': child_id, 'title': _chapter_asset_title(title, chapter.title),
                    'filename': child_name, 'index': chapter.index, 'parsed': parsed,
                    'split_basis': chapter.split_basis, 'page_start': chapter.page_start,
                    'page_end': chapter.page_end,
                    'request_id': str(uuid5(NAMESPACE_URL, f'{request}:chapter:{chapter.index}')),
                    'fingerprint': sha256(raw).hexdigest()})
            folder = self.root / identity
            folder.mkdir()
            (folder/'original').write_bytes(data)
            manifest = {'filename': filename, 'format': PurePath(filename).suffix.lower().lstrip('.'),
                'original_sha256': sha256(data).hexdigest(), 'original_bytes': len(data),
                'parser': 'docling NativePdfPipeline/HybridChunker',
                'warnings': [split_notice(chapters)],
                'blocks': [], 'content': '', 'auto_split': True, 'chapter_count': len(prepared),
                'split_bases': sorted({chapter.split_basis for chapter in chapters}),
                'chapters': [{'id': item['id'], 'title': item['title'], 'index': item['index'],
                    'split_basis': item['split_basis'], 'page_start': item['page_start'], 'page_end': item['page_end']}
                    for item in prepared]}
            (folder/'parsed.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            with self.connect() as conn:
                for item in prepared:
                    conn.execute('''INSERT INTO training_assets(
                        id,account,unit_id,scope,request_id,fingerprint,title,filename,status,
                        parent_id,asset_role,chapter_index)
                        VALUES (?,?,?,?,?,?,?,?, 'ready', ?, 'chapter', ?)''',
                        (item['id'], member['account'], member['unit_id'], scope, item['request_id'],
                         item['fingerprint'], item['title'], item['filename'], identity, item['index']))
                conn.execute("UPDATE training_assets SET status='ready', asset_role='pack', split_count=? WHERE id=?",
                             (len(prepared), identity))
            if scope == 'unit':
                with self.store.connect() as conn:
                    for item in prepared:
                        self._insert_unit_version(conn, item['id'], member, item['title'], self.root/item['id'], item['parsed']['blocks'])
        except Exception as exc:
            with self.connect() as conn:
                conn.execute('DELETE FROM training_assets WHERE parent_id=?', (identity,))
            for child_id in created:
                shutil.rmtree(self.root/child_id, ignore_errors=True)
            if isinstance(exc, MaterialInputError):
                raise
            raise MaterialInputError('超限文件无法按标题拆分，请按章节拆分后重新上传。') from exc

    def _fail_if_pack(self, row):
        if self._field(row, 'asset_role', 'document') == 'pack':
            raise MaterialInputError('该文件已按章节拆分，请选择其中一个章节再准备课程。')

    def attach(self, row, payload, gateway, member):
        if set(payload) != {'project_id','request_id'} or row['status'] != 'ready':
            raise MaterialInputError('请先完成解析并选择自己的待准备课程。')
        self._fail_if_pack(row)
        pid = payload['project_id']
        if not isinstance(pid,str) or pid not in gateway.ownership.owned(member['account']):
            raise KeyError('Project unavailable')
        request = str(UUID(str(payload['request_id'])))
        with project_execution(pid,gateway.paths), LearningRepository(gateway.paths) as repo:
            require_visible(repo,pid)
            if repo.session(pid) or repo.conn.execute('SELECT 1 FROM learning_execution WHERE project_id=?',(pid,)).fetchone() or repo.conn.execute('SELECT 1 FROM preparation_execution WHERE project_id=?',(pid,)).fetchone():
                raise ConflictError('Active or frozen course')
            raw = (self.root/row['id']/'original').read_bytes()
            result = MaterialService(repo).import_upload(pid,data=raw,filename=row['filename'],title=row['title'],
                source_description='用户上传原件：'+row['filename'],request_id=request,source_id=row['id'])
            return {'imported':True,'source_id':result.document.source_id,'source_version':result.document.source_version,
                    'draft_revision':result.draft_revision,'reused':result.reused}

    async def handle(self, scope, receive, send, gateway, member):
        path, method = scope['path'], scope['method']
        match = re.fullmatch(r'/training/api/(admin/)?materials(?:/(material_[a-f0-9]{32})(?:/(original|attach))?)?',path)
        if not match:
            return False
        kind = 'unit' if match[1] else 'private'
        identity, action = match[2], match[3]
        try:
            if method in {'GET','HEAD'} and not identity:
                with self.connect() as conn:
                    rows=conn.execute('SELECT * FROM training_assets ORDER BY created_at DESC,id DESC').fetchall()
                await gateway.reply(send,200,{'materials':[self.public(r) for r in rows if self.allowed(r,member,kind)]})
            elif method == 'POST' and not identity:
                payload=json.loads(await gateway.body(receive,11250000))
                async with self.slots:
                    result=await asyncio.to_thread(self.upload,payload,member,kind)
                await gateway.reply(send,201 if result['status']=='ready' else 422 if result['status']=='failed' else 202,result)
            elif identity:
                row=await asyncio.to_thread(self.get,identity,member,kind)
                if method in {'GET','HEAD'} and action == 'original' and row['status']=='ready':
                    await FileResponse(self.root/identity/'original',filename=row['filename'],media_type='application/octet-stream',
                        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})(scope,receive,send)
                elif method in {'GET','HEAD'} and not action:
                    await gateway.reply(send,200,self.public(row,True))
                elif method == 'POST' and action == 'attach':
                    payload=json.loads(await gateway.body(receive,4096))
                    await gateway.reply(send,200,await asyncio.to_thread(self.attach,row,payload,gateway,member))
                else:
                    await gateway.reply(send,405,{'error':{'message':'请使用资料列表中的可用操作。'}})
            else:
                await gateway.reply(send,405,{'error':{'message':'不支持该操作。'}})
        except KeyError:
            await gateway.reply(send,404,{'error':{'code':'not_found','message':'资料或课程不存在。'}})
        except ConflictError:
            await gateway.reply(send,409,{'error':{'code':'state_conflict','message':'课程或请求已变化，请刷新后重试。'}})
        except AdmissionError as exc:
            await gateway.reply(send,exc.status,{'error':{'code':exc.code,'message':exc.message}})
        except MaterialInputError as exc:
            await gateway.reply(send,422,{'error':{'code':'invalid_material','message':str(exc)}})
        except (ValueError,TypeError):
            await gateway.reply(send,422,{'error':{'code':'invalid_material','message':'资料输入不完整或格式无效，请重新选择文件。'}})
        return True


def _chapter_filename(filename, index):
    suffix = f'-第{index}章.md'
    stem = PurePath(filename).stem
    if len(stem) + len(suffix) > 255:
        stem = stem[:255 - len(suffix)]
    return (stem or '章节') + suffix


def _chapter_asset_title(parent, heading):
    heading = (heading or '正文').strip() or '正文'
    suffix = ' · ' + heading
    if len(parent) + len(suffix) <= 256:
        return parent + suffix
    room = 256 - len(suffix)
    if room < 1:
        return heading[:256]
    return parent[:room].rstrip() + suffix
