"""Independent WATT HTTP contract; real ASGI body/auth, synthetic broker only.

Source: docs/dev/2026-10-13-spec-web-chat-attachments.md. No implementation reads.
The recorder deliberately accepts any adapter signature: these tests constrain the
public HTTP boundary, not private Python forwarding names.
"""
import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from test_control_web_session_chat_contract import feature, ORIGIN, PASSWORD, SECRET, SID, MID, OTHER

AID = '77777777-7777-4777-8777-777777777777'
BASE = '/api/session-attachment-'
BEGIN = dict(project='demo', sid=SID, message_id=MID, upload_id=OTHER,
             size=1, name='fixture.bin', media_hint='application/octet-stream')
SEND = dict(project='demo', sid=SID, message_id=MID, text='', attachment_ids=[AID])
ROUTES = [
    ('GET', BASE+'options', dict(project='demo', sid=SID)),
    ('POST', BASE+'begin', BEGIN),
    ('PUT', BASE+'chunk', dict(attachment_id=AID, index=0)),
    ('POST', BASE+'finish', dict(attachment_id=AID)),
    ('POST', BASE+'status', dict(attachment_id=AID)),
    ('POST', BASE+'discard', dict(attachment_id=AID)),
    ('POST', '/api/session-send-attachments', SEND),
    ('POST', '/api/session-enqueue-attachments', SEND),
    ('GET', '/api/session-attachments-receipt', dict(project='demo', sid=SID, message_id=MID)),
]


class Recorder:
    def __init__(self): self.calls=[]
    def snapshot(self): return dict(tasks=[])
    def __getattr__(self, name):
        if 'attachment' not in name: raise AttributeError(name)
        def invoke(*args, **kwargs):
            self.calls.append((name,args,kwargs))
            return dict(attachment_id=AID,state='receiving',size=1,bytes=0,sha256=None,expires_at=1800000060,mode='file')
        return invoke


class AttachmentHTTPRed(unittest.TestCase):
    def setUp(self):
        self.web=feature(self,'_control_web');self.backend=Recorder();self.now=1800000000
        self.temp=tempfile.TemporaryDirectory(prefix='watt-http-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        replay=Path(self.temp.name)/'totp.json';replay.write_text('{"last_step":-1}');replay.chmod(0o600)
        config=dict(origin=ORIGIN,username='owner',password_hash=self.web.hash_password(PASSWORD),
                    totp_secret=SECRET,session_ttl=60,secure_cookie=True,totp_state_path=str(replay))
        self.client=TestClient(self.web.create_app(config,self.backend,clock=lambda:self.now),base_url=ORIGIN)
        self.addCleanup(self.client.close)
    def login(self):
        result=self.client.post('/api/login',json=dict(username='owner',password=PASSWORD,
            totp=self.web.totp_code(SECRET,self.now)),headers={'Origin':ORIGIN})
        self.assertEqual(result.status_code,200,result.text)
        self.csrf=self.client.get('/api/session').json()['csrf']
    def headers(self): return {'Origin':ORIGIN,'X-CSRF-Token':self.csrf}
    def request(self,method,path,data,headers=None):
        if method=='GET': return self.client.get(path,params=data,headers=headers)
        if method=='PUT': return self.client.put(path,params=data,content=b'x',headers={**(headers or {}),'Content-Type':'application/octet-stream'})
        return self.client.post(path,json=data,headers=headers)

    def test_all_nine_routes_require_live_auth_before_broker(self):
        # INV-WATT-01: a missing route (404) is substantive RED, never a passing denial.
        for method,path,data in ROUTES:
            with self.subTest(path=path):
                response=self.request(method,path,data,{'Origin':ORIGIN})
                self.assertEqual(response.status_code,401,response.text)
        self.assertEqual(self.backend.calls,[])

    def test_every_mutation_requires_origin_and_csrf_before_forwarding(self):
        # INV-WATT-01
        self.login()
        for method,path,data in ROUTES:
            if method=='GET': continue
            for headers in ({},{'Origin':ORIGIN},{'X-CSRF-Token':self.csrf},
                            {**self.headers(),'Origin':'https://foreign.example.test'}):
                with self.subTest(path=path,headers=list(headers)):
                    self.assertEqual(self.request(method,path,data,headers).status_code,403)
        self.assertEqual(self.backend.calls,[])

    def test_private_authority_and_unknown_keys_rejected_on_each_route(self):
        # INV-WATT-01: browser cannot manufacture owner/root/native path/login scope.
        self.login()
        for method,path,data in ROUTES:
            for key in ('root','owner_uid','context','login_scope','lease','path','unexpected'):
                with self.subTest(path=path,key=key):
                    response=self.request(method,path,{**data,key:'forged'},self.headers())
                    self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.backend.calls,[])

    def test_duplicate_query_and_json_keys_rejected_before_broker(self):
        # INV-WATT-01 INV-WATT-03
        self.login()
        for method,path,data in ROUTES:
            key=next(iter(data));value=data[key]
            with self.subTest(path=path):
                if method in ('GET','PUT'):
                    params=list(data.items())+[(key,value)]
                    response=self.client.request(method,path,params=params,content=b'x' if method=='PUT' else None,headers=self.headers())
                else:
                    raw=json.dumps(data)[:-1]+','+json.dumps(key)+':'+json.dumps(value)+'}'
                    response=self.client.post(path,content=raw,headers={**self.headers(),'Content-Type':'application/json'})
                self.assertEqual(response.status_code,422,response.text)
        self.assertEqual(self.backend.calls,[])

    def test_expiry_after_last_body_read_blocks_every_post_and_raw_chunk(self):
        # INV-WATT-01 WATT-AUTH-EACH-ROUTE: TOCTOU after complete request read.
        self.login();start=self.now
        for method,path,data in ROUTES:
            if method=='GET': continue
            self.now=start
            body=b'x' if method=='PUT' else json.dumps(data).encode()
            def expires_on_last_read():
                yield body
                self.now=start+60  # exact absolute expiry; no sliding renewal
            with self.subTest(path=path):
                response=self.client.request(method,path,params=data if method=='PUT' else None,
                    content=expires_on_last_read(),headers={**self.headers(),'Content-Type':
                        'application/octet-stream' if method=='PUT' else 'application/json'})
                self.assertEqual(response.status_code,401,response.text)
        self.assertEqual(self.backend.calls,[])

    def test_raw_chunk_overflow_without_content_length_never_reaches_broker(self):
        # INV-WATT-02: bounded chunk route cannot fall back to whole-body JSON.
        self.login()
        def stream():
            yield b'a'*24576
            yield b'b'*24576
            yield b'c'
        response=self.client.put(BASE+'chunk',params=dict(attachment_id=AID,index=0),content=stream(),
            headers={**self.headers(),'Content-Type':'application/octet-stream'})
        self.assertEqual(response.status_code,413,response.text)
        self.assertEqual(self.backend.calls,[])

    def test_expired_get_is_auth_failure_not_empty_options(self):
        # INV-WATT-01: protected options and historical receipts are not anonymous DTOs.
        self.login();self.now+=60
        for method,path,data in ROUTES:
            if method!='GET': continue
            with self.subTest(path=path):
                self.assertEqual(self.request(method,path,data,self.headers()).status_code,401)
        self.assertEqual(self.backend.calls,[])
