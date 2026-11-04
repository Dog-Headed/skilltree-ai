"""Personal and unit material libraries; no publication or assignment on Day 2."""
import asyncio
from contextlib import contextmanager
import base64
import binascii
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from uuid import UUID, uuid4

from fastapi.responses import FileResponse
from app.v3.office_files import parse_file
from app.v3.materials import MaterialInputError, MaterialService
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

    def public(self, row, detail=False):
        result = {k: row[k] for k in ('id','title','filename','scope','status','error','created_at')}
        if detail and row['status'] == 'ready':
            result['parsed'] = json.loads((self.root/row['id']/'parsed.json').read_text(encoding='utf-8'))
        return result

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
            parsed = parse_file(data, filename)
            folder = self.root / identity
            folder.mkdir()
            (folder/'original').write_bytes(data)
            (folder/'parsed.json').write_text(json.dumps(parsed,ensure_ascii=False),encoding='utf-8')
            if scope == 'unit':
                with self.store.connect() as conn:
                    conn.execute('''INSERT INTO training_material_versions
                        (id,unit_id,owner_account,visibility,version,title,original_path,parsed_path,locations_json)
                        VALUES (?,?,?,'unit',1,?,?,?,?)''',
                        (identity,member['unit_id'],member['account'],title.strip(),str(folder/'original'),
                         str(folder/'parsed.json'),json.dumps(parsed['blocks'],ensure_ascii=False)))
            with self.connect() as conn:
                conn.execute("UPDATE training_assets SET status='ready' WHERE id=?",(identity,))
        except MaterialInputError as exc:
            with self.connect() as conn:
                conn.execute("UPDATE training_assets SET status='failed',error=? WHERE id=?",(str(exc),identity))
        return self.public(self.get(identity,member,scope), True)

    def attach(self, row, payload, gateway, member):
        if set(payload) != {'project_id','request_id'} or row['status'] != 'ready':
            raise MaterialInputError('请先完成解析并选择自己的待准备课程。')
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
