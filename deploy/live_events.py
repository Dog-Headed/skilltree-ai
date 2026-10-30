"""Authenticated read-only SSE subscriptions to one durable background job."""
import asyncio
import json
import time
from fastapi.responses import StreamingResponse


async def serve_events(gateway, scope, receive, send, job_id, account, token):
    headers=dict(scope['headers'])
    origin=headers.get(b'origin',b'').decode('latin1')
    if headers.get(b'sec-fetch-site')==b'cross-site' or (origin and origin.rstrip('/')!=gateway.origin):
        return await gateway.reply(send,403,{'error':{'code':'invalid_origin','message':'请从当前页面查看任务。'}})
    job=await asyncio.to_thread(gateway.jobs.public,job_id,account)
    if job is None:
        return await gateway.reply(send,404,{'error':{'code':'not_found','message':'任务不存在。'}})
    connections=gateway.live_connections
    if connections.get(account,0)>=2:
        return await gateway.reply(send,429,{'error':{'code':'stream_limit','message':'请保留最多两个实时查看窗口。'}})
    connections[account]=connections.get(account,0)+1

    async def events():
        start=heartbeat=authenticated=time.monotonic();last=None
        yield 'retry: 1500\n\n'
        while time.monotonic()-start<1200 and not gateway.runner.stopping:
            now=time.monotonic()
            if gateway.auth and now-authenticated>=2:
                if await asyncio.to_thread(gateway.auth.session,token)!=account:
                    yield 'event: closed\ndata: {}\n\n';return
                authenticated=now
            job=await asyncio.to_thread(gateway.jobs.public,job_id,account)
            if job is None:
                yield 'event: closed\ndata: {}\n\n';return
            if job['state'] not in ('queued','running'):
                yield 'event: done\ndata: '+json.dumps({'state':job['state']})+'\n\n';return
            progress=await asyncio.to_thread(gateway.jobs.public_progress,job_id,account)
            value={'state':job['state'],'position':job['position'],**(progress or {})}
            encoded=json.dumps(value,ensure_ascii=False,separators=(',',':'))
            if encoded!=last:
                # Each frame is a full bounded snapshot. Reconnection needs no
                # replay of raw model tokens or a second inference request.
                yield 'event: progress\ndata: '+encoded+'\n\n'
                last=encoded;heartbeat=now
            elif now-heartbeat>=10:
                yield ': keepalive\n\n';heartbeat=now
            await asyncio.sleep(.25)
        yield 'event: closed\ndata: {}\n\n'

    try:
        await StreamingResponse(events(),media_type='text/event-stream',headers={
            'Cache-Control':'no-store, no-transform','X-Accel-Buffering':'no'})(scope,receive,send)
    finally:
        count=connections.get(account,1)-1
        if count:connections[account]=count
        else:connections.pop(account,None)
