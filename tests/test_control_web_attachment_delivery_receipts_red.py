"""Contract regressions: transformed native image delivery and common recovery."""
import base64
from copy import deepcopy
import hashlib
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
    def __call__(self,method,params):
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
        filters={
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
