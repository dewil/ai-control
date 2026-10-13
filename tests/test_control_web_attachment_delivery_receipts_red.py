"""Contract regressions: transformed native image delivery and common recovery."""
import base64
from copy import deepcopy
import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
import struct
import uuid
import unittest
import zlib
import test_control_web_attachments_author as h
import native_queue_blind_support as s


def png(pixel=b'\xaa\xbb\xcc'):
    def chunk(k,v):return struct.pack('>I',len(v))+k+v+struct.pack('>I',zlib.crc32(k+v)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+pixel))+chunk(b'IEND',b'')


def inline(raw=None):
    return dict(type='image',url='data:image/png;base64,'+base64.b64encode(png() if raw is None else raw).decode())


class TransformingNative(h.Native):
    queue_filter=None
    history_probe=None
    def __call__(self,method,params):
        if method=='thread/turns/list' and params.get('itemsView')=='full' and self.history_probe:self.history_probe()
        result=super().__call__(method,params)
        if method=='thread/queue/add':
            parts=result['queuedSubmission']['input']
            for index,part in enumerate(parts):
                if part['type']=='image':parts[index]=inline()
            if self.queue_filter:result['queuedSubmission']['input']=self.queue_filter(deepcopy(parts))
        return result


class AttachmentDeliveryReceiptsRED(unittest.TestCase):
    login=h.AttachmentAuthor.login
    upload=h.AttachmentAuthor.upload
    send=h.AttachmentAuthor.send
    def setUp(self):
        h.AttachmentAuthor.setUp(self)
        self.rpc.__class__=TransformingNative

    def status(self,mid=s.MID,dedicated=False):
        path='/api/session-attachments-receipt' if dedicated else '/api/session-send-status'
        response=self.client.get(path,params=dict(project='demo',sid=s.SID,message_id=mid),headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def history(self,mid,parts,duplicate=False):
        item=dict(id='synthetic-user-A',type='userMessage',clientId=mid,content=parts)
        items=[item]
        if duplicate:items.append(dict(item,id='synthetic-user-B'))
        self.rpc.pages={None:dict(data=[dict(id=s.TURN,status='completed',items=items)],nextCursor=None)}

    def assert_original(self,raw):
        blobs=list((self.base/'web-attachments').glob('b-*'))
        self.assertTrue(any(p.read_bytes()==raw for p in blobs),'Original pinned bytes must survive transformation/recovery')

    def test_transformed_queue_ack_proves_delivery_without_changing_exact_pin_projection(self):
        # INV-WATT-DELIVERY-01: native transformed pixels are not original-byte identity.
        original=h.png();aid=self.upload(original,'original.png')
        response=self.send([aid],'enqueue',text='caption')
        self.assertEqual(response.json()['status'],'queued',response.text)
        self.assertEqual(self.status()['status'],'queued')
        self.assert_original(original)
        manifest=self.chat._attachment_record(str(self.project),s.SID,s.MID)['manifest']
        self.assertEqual(manifest[0]['sha256'],hashlib.sha256(original).hexdigest())
        with self.assertRaises(h.Refusal):h.normalized_input([inline()],manifest)
        before=len([m for m,_ in self.rpc.calls if m=='thread/queue/add'])
        self.send([aid],'enqueue',text='caption')
        self.assertEqual(len([m for m,_ in self.rpc.calls if m=='thread/queue/add']),before)

    def test_common_status_recovers_unique_transformed_history_without_new_native_mutation(self):
        # INV-WATT-DELIVERY-02/03: durable kind chooses reconciliation after lost ACK.
        original=h.png();aid=self.upload(original,'original.png');self.rpc.start_error=TimeoutError('synthetic lost ACK')
        response=self.send([aid],text='caption');self.assertEqual(response.json()['status'],'delivery_unknown')
        self.history(s.MID,[dict(type='text',text='caption'),inline()])
        before=len(self.rpc.starts())
        self.assertEqual(self.status()['status'],'accepted')
        self.assertEqual(self.status(dedicated=True)['status'],'accepted')
        self.assertEqual(self.status()['status'],'accepted')
        self.assertEqual(len(self.rpc.starts()),before);self.assert_original(original)

    def test_duplicate_same_mid_and_conflicting_history_remain_unknown(self):
        # INV-WATT-DELIVERY-02: exact UUID without a unique complete input is insufficient.
        for label,parts,duplicate in (
            ('duplicate',[dict(type='text',text='caption'),inline()],True),
            ('wrong_text',[dict(type='text',text='other'),inline()],False),
            ('text_only',[dict(type='text',text='caption')],False),
            ('order',[inline(),dict(type='text',text='caption')],False),
            ('unknown_image_field',[dict(type='text',text='caption'),dict(inline(),unexpected=True)],False)):
            with self.subTest(label=label):
                mid=str(uuid.uuid4());aid=self.upload(h.png(),label+'.png',upload=str(uuid.uuid4()),mid=mid)
                self.rpc.start_error=TimeoutError('synthetic lost ACK')
                response=self.send([aid],mid=mid,text='caption');self.assertEqual(response.json()['status'],'delivery_unknown')
                self.history(mid,parts,duplicate);before=len(self.rpc.starts())
                self.assertEqual(self.status(mid,True)['status'],'delivery_unknown')
                self.assertEqual(self.status(mid)['status'],'delivery_unknown')
                self.assertEqual(len(self.rpc.starts()),before)

    def test_queue_ack_wrong_text_order_count_media_or_generic_path_never_proves_delivery(self):
        # INV-WATT-DELIVERY-01: only image-byte transformation is permitted.
        payload=b'x'*(2*1024*1024)
        ancillary=struct.pack('>I',len(payload))+b'tEXt'+payload+struct.pack('>I',zlib.crc32(b'tEXt'+payload)&0xffffffff)
        oversized=png()[:-12]+ancillary+png()[-12:]
        filters={
            'detail_high':lambda p:[*p[:-1],dict(p[-1],detail='high')],
            'oversize':lambda p:[*p[:-1],inline(oversized)],
            'mime_bytes':lambda p:[*p[:-1],dict(type='image',url=p[-1]['url'].replace('image/png','image/jpeg'))],
            'text':lambda p:[dict(p[0],text='other'),*p[1:]],
            'order':lambda p:list(reversed(p)),
            'count':lambda p:p[:-1],
            'fields':lambda p:[*p[:-1],dict(p[-1],unexpected=True)],
            'media':lambda p:[*p[:-1],dict(type='image',url='data:image/png;base64,AAAA')],
            'path':lambda p:[p[0],dict(type='text',text=p[1]['text'].replace('Attached file','Changed file')),*p[2:]],
        }
        for label,transform in filters.items():
            with self.subTest(label=label):
                mid=str(uuid.uuid4());image=self.upload(h.png(),'image.png',upload=str(uuid.uuid4()),mid=mid)
                file=self.upload(b'generic bytes','generic.bin',upload=str(uuid.uuid4()),mid=mid)
                self.rpc.queue_filter=transform
                response=self.send([file,image],'enqueue',mid=mid,text='caption')
                self.assertEqual(response.json()['status'],'delivery_unknown',response.text)
                self.assert_original(h.png())

    def test_reencoded_jpeg_ack_and_history_accept_delivery_with_original_png_pins(self):
        # INV-WATT-DELIVERY-01: PNG-to-JPEG transport is delivery, not pixel identity.
        import test_control_web_jpeg_sef_trailer_red as jpeg
        original=h.png();aid=self.upload(original,'original.png')
        transformed=dict(type='image',url='data:image/jpeg;base64,'+base64.b64encode(jpeg.JPEG).decode(),detail='auto')
        self.rpc.queue_filter=lambda parts:[parts[0],deepcopy(transformed)]
        self.assertEqual(self.send([aid],'enqueue',text='caption').json()['status'],'queued')
        self.history(s.MID,[dict(type='text',text='caption'),transformed])
        self.assertEqual(self.status()['status'],'accepted');self.assert_original(original)

    def test_unauthenticated_common_status_cannot_read_or_reconcile_receipt(self):
        # INV-WATT-DELIVERY-03: common route retains ordinary auth boundary.
        aid=self.upload(h.png(),'original.png');self.rpc.start_error=TimeoutError('synthetic')
        self.send([aid],text='caption');self.history(s.MID,[dict(type='text',text='caption'),inline()])
        self.client.cookies.clear();before=len(self.rpc.calls)
        response=self.client.get('/api/session-send-status',params=dict(project='demo',sid=s.SID,message_id=s.MID))
        self.assertEqual(response.status_code,401);self.assertEqual(len(self.rpc.calls),before)

    def test_shared_receipt_corruption_and_commitment_digest_mismatch_refuse_acceptance(self):
        # INV-WATT-DELIVERY-03: durable authority must agree before reconciliation.
        aid=self.upload(h.png(),'original.png');self.rpc.start_error=TimeoutError('synthetic')
        self.send([aid],text='caption');self.history(s.MID,[dict(type='text',text='caption'),inline()])
        namespace=hashlib.sha256((str(self.project)+'\0'+s.SID).encode()).hexdigest()
        path=self.base/'receipts'/namespace/(s.MID+'.json');original=json.loads(path.read_text())
        before=len(self.rpc.starts())
        for field,value in (('schema',4.0),('digest','0'*64),('spool_digest','0'*64)):
            with self.subTest(field=field):
                self.assertIn(field,original)
                path.write_text(json.dumps({**original,field:value}))
                response=self.client.get('/api/session-send-status',params=dict(project='demo',sid=s.SID,message_id=s.MID),headers=self.headers)
                self.assertNotEqual(response.json().get('status'),'accepted','Corrupt shared authority cannot be bypassed by spool/history proof')
                self.assertEqual(len(self.rpc.starts()),before)
                path.write_text(json.dumps(original))

    def test_common_reconciliation_releases_namespace_lock_before_native_history_read(self):
        # INV-WATT-DELIVERY-03: no lock spans RPC; acceptance still requires history.
        aid=self.upload(h.png(),'original.png');self.rpc.start_error=TimeoutError('synthetic')
        self.send([aid],text='caption');self.history(s.MID,[dict(type='text',text='caption'),inline()])
        active=[0];observed=[];original=self.chat.receipts.namespace
        @contextmanager
        def tracked(*args,**kwargs):
            with original(*args,**kwargs) as namespace:
                active[0]+=1
                try:yield namespace
                finally:active[0]-=1
        self.chat.receipts.namespace=tracked
        self.rpc.history_probe=lambda:observed.append(active[0])
        self.assertEqual(self.status()['status'],'accepted')
        self.assertTrue(observed,'Reconciliation must query authoritative native history')
        self.assertEqual(observed,[0]*len(observed),'Namespace lock must not cover native history RPC')
