"""Author integration complements frozen RED; entirely synthetic ASGI/native/FS."""
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile
import time
import threading
import unittest
import zlib
from fastapi.testclient import TestClient
import native_queue_blind_support as s
from test_control_web_session_chat_contract import ORIGIN,PASSWORD,SECRET,OTHER,TURN
from _control_web import create_app,hash_password,totp_code
from _control_web_broker import RegistryBackend,SocketBackend,serve_broker
from _control_web_attachments import image_bounds,Refusal,normalized_input,native_input


def png():
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\x12\x34\x56'))+chunk(b'IEND',b'')


class Native(s.QueueRPC):
    def __init__(self,root):
        super().__init__(root);self.context['native_version']='0.162.1';self.observed=[]
    def __call__(self,method,params):
        if method in ('turn/start','thread/queue/add'):
            for part in params['input']:
                if part['type']=='localImage':self.observed.append(Path(part['path']).read_bytes())
                elif part['type']=='text' and part['text'].startswith('Attached file (untrusted content): '):
                    payload=json.loads(part['text'].split(': ',1)[1]);self.observed.append(Path(payload['path']).read_bytes())
        result=super().__call__(method,params)
        if method=='thread/queue/add':
            for p in result['queuedSubmission']['input']:
                if p['type']=='localImage':p.update(type='image',url='data:image/png;base64,'+base64.b64encode(Path(p.pop('path')).read_bytes()).decode())
        return result


class AttachmentAuthor(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='watt-author-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.base.chmod(0o700);self.project=self.base/'project';self.project.mkdir(mode=0o700)
        self.rpc=Native(self.project)
        from _control_web_sessions import SessionChat
        self.chat=SessionChat(self.rpc,lambda p:str(self.project),lambda:['demo'],str(self.base/'receipts'),model_context=self.rpc.model_context)
        self.registry=self.base/'registry.json';self.registry.write_text('{}');self.registry.chmod(0o600)
        self.backend=RegistryBackend(str(self.registry),str(s.ROOT/'bin'),sessions=self.chat)
        self.config=dict(origin=ORIGIN,username='owner',password_hash=hash_password(PASSWORD),totp_secret=SECRET,session_ttl=3600,secure_cookie=True)
        self.client=TestClient(create_app(self.config,self.backend),base_url=ORIGIN);self.addCleanup(self.client.close)
        self.login()
    def login(self):
        r=self.client.post('/api/login',json=dict(username='owner',password=PASSWORD,totp=totp_code(SECRET,time.time())),headers={'Origin':ORIGIN})
        self.assertEqual(r.status_code,200,r.text);self.headers={'Origin':ORIGIN,'X-CSRF-Token':self.client.get('/api/session').json()['csrf']}
    def upload(self,raw,name,upload=OTHER,mid=s.MID):
        r=self.client.post('/api/session-attachment-begin',json=dict(project='demo',sid=s.SID,message_id=mid,upload_id=upload,size=len(raw),name=name,media_hint='application/octet-stream'),headers=self.headers)
        self.assertEqual(r.status_code,200,r.text);aid=r.json()['attachment_id']
        for index,offset in enumerate(range(0,len(raw),49152)):
            r=self.client.put('/api/session-attachment-chunk',params=dict(attachment_id=aid,index=index),content=raw[offset:offset+49152],headers={**self.headers,'Content-Type':'application/octet-stream'})
            self.assertEqual(r.status_code,200,r.text)
        r=self.client.post('/api/session-attachment-finish',json=dict(attachment_id=aid),headers=self.headers)
        self.assertEqual(r.status_code,200,r.text)
        return aid
    def send(self,ids,mode='send',mid=s.MID,text='Inspect fixtures'):
        return self.client.post('/api/session-'+('enqueue' if mode=='enqueue' else 'send')+'-attachments',json=dict(project='demo',sid=s.SID,message_id=mid,text=text,attachment_ids=ids),headers=self.headers)
    def test_direct_files_images_history_and_text_uuid_collision(self):
        ids=[self.upload(b'actual file\0bytes','sample.bin'),self.upload(png(),'screen.png',s.ACTION)]
        r=self.send(ids);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'accepted')
        self.assertEqual(self.rpc.observed,[b'actual file\0bytes',png()])
        params=self.rpc.starts()[0]
        self.rpc.pages[None]=dict(data=[dict(id=TURN,status='completed',items=[dict(id='u',type='userMessage',clientId=s.MID,content=params['input']),dict(id='a',type='agentMessage',text='unchanged answer')])],nextCursor=None)
        history=self.chat.history('demo',s.SID);self.assertNotIn('error',history,history)
        raw=json.dumps(history);self.assertNotIn('web-attachments',raw);self.assertNotIn('data:image',raw)
        texts=[i['text'] for t in history['turns'] for i in t['items']]
        self.assertIn('unchanged answer',texts);self.assertTrue(any('Inspect fixtures' in x and 'Вложения: 2' in x for x in texts))
        before=len(self.rpc.starts());self.assertIn('error',self.chat.send('demo',s.SID,s.MID,'collision'))
        self.assertEqual(len(self.rpc.starts()),before)
        again=self.send(ids);self.assertEqual(again.json()['status'],'accepted');self.assertEqual(len(self.rpc.starts()),before)
    def test_queue_ack_normalization_and_safe_summary_without_transfer(self):
        ids=[self.upload(png(),'screen.png'),self.upload(b'real text document','doc.txt',s.ACTION)]
        r=self.send(ids,'enqueue',text='');self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'queued')
        result=self.chat.queue('demo',s.SID);self.assertTrue(result.get('supported'),result)
        self.assertEqual(result['rows'][0]['native_summary'],'Вложения: 2')
        self.assertNotIn('web-attachments',json.dumps(result));self.assertNotIn('data:image',json.dumps(result))
        receipt=self.client.get('/api/session-attachments-receipt',params=dict(project='demo',sid=s.SID,message_id=s.MID),headers=self.headers)
        self.assertEqual(receipt.json()['queued_submission_id'],s.QID)
    def test_unknown_ack_never_repeats_and_pins_survive(self):
        aid=self.upload(b'opaque fixture','fixture.bin');self.rpc.start_error=TimeoutError('synthetic')
        r=self.send([aid]);self.assertEqual(r.json()['status'],'delivery_unknown',r.text)
        again=self.send([aid]);self.assertEqual(again.json()['status'],'delivery_unknown');self.assertEqual(len(self.rpc.starts()),1)
        delete=self.client.post('/api/session-attachment-discard',json=dict(attachment_id=aid),headers=self.headers)
        self.assertEqual(delete.status_code,409)
        self.assertTrue(any(p.read_bytes()==b'opaque fixture' for p in (self.base/'web-attachments').glob('b-*')))
    def test_real_unix_broker_roundtrip_preserves_closed_dtos(self):
        sock=str(self.base/'broker.sock');stopped=threading.Event()
        thread=threading.Thread(target=serve_broker,args=(sock,self.backend,os.getuid(),stopped),daemon=True);thread.start()
        def close():stopped.set();thread.join(3)
        self.addCleanup(close)
        end=time.monotonic()+2
        while not os.path.exists(sock) and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(os.path.exists(sock))
        self.client.close();self.client=TestClient(create_app(self.config,SocketBackend(sock)),base_url=ORIGIN);self.addCleanup(self.client.close);self.login()
        aid=self.upload(b'wire binary\0bytes','wire.bin')
        result=self.send([aid]);self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['status'],'accepted')
        self.assertEqual(self.rpc.observed,[b'wire binary\0bytes'])
        raw=json.dumps(result.json());self.assertNotIn('path',raw);self.assertNotIn('manifest',raw)
        before=len(self.rpc.calls)
        invalid=SocketBackend(sock).session_attachment('begin',{'root':'spoofed'},{'scope':'test','expires_at':time.time()+60})
        self.assertEqual(invalid,{'error':'invalid_request'});self.assertEqual(len(self.rpc.calls),before)

    def test_image_payload_limit_before_reservation_and_dispatch(self):
        # Large valid ancillary PNG data must not turn into generic-file fallback.
        raw=png();payload=b'x'*(2*1024*1024)
        extra=struct.pack('>I',len(payload))+b'tEXt'+payload+struct.pack('>I',zlib.crc32(b'tEXt'+payload)&0xffffffff)
        raw=raw[:-12]+extra+raw[-12:]
        aid=self.upload(raw,'large.png');before=len(self.rpc.starts())
        result=self.send([aid]);self.assertEqual(result.status_code,422,result.text)
        self.assertEqual(result.json(),{'error':'image_payload_too_large'})
        self.assertEqual(len(self.rpc.starts()),before)
        self.assertEqual(list((self.base/'web-attachments').glob('p-*')),[])

    def test_image_structure_crc_pixels_and_inline_hash_equivalence(self):
        valid=png()
        for raw,success in [(valid,True),(valid[:-1],False),(valid+b'extra',False),(valid[:32]+bytes([valid[32]^1])+valid[33:],False)]:
            with tempfile.TemporaryFile() as f:
                f.write(raw);f.flush()
                if success:self.assertTrue(image_bounds(f.fileno(),len(raw)))
                else:
                    with self.assertRaises(Refusal):image_bounds(f.fileno(),len(raw))
        m=[dict(id=OTHER,path='/synthetic/pinned',mode='image',sha256=hashlib.sha256(valid).hexdigest(),size=len(valid))]
        expected=normalized_input(native_input('',m),m)
        self.assertEqual(expected,normalized_input([dict(type='image',url='data:image/png;base64,'+base64.b64encode(valid).decode())],m))
        with self.assertRaises(Refusal):normalized_input([dict(type='image',url='data:image/png;base64,'+base64.b64encode(valid+b'x').decode())],m)
