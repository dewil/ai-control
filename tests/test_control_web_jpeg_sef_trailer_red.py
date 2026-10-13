"""Contract regressions for bounded metadata-only Samsung SEF JPEG trailers."""
import base64
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import test_control_web_attachments_spool_red as h

JPEG=base64.b64decode('/9j/4AAQSkZJRgABAQAAAQABAAD/4gHYSUNDX1BST0ZJTEUAAQEAAAHIAAAAAAQwAABtbnRyUkdCIFhZWiAH4AABAAEAAAAAAABhY3NwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAA9tYAAQAAAADTLQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAlkZXNjAAAA8AAAACRyWFlaAAABFAAAABRnWFlaAAABKAAAABRiWFlaAAABPAAAABR3dHB0AAABUAAAABRyVFJDAAABZAAAAChnVFJDAAABZAAAAChiVFJDAAABZAAAAChjcHJ0AAABjAAAADxtbHVjAAAAAAAAAAEAAAAMZW5VUwAAAAgAAAAcAHMAUgBHAEJYWVogAAAAAAAAb6IAADj1AAADkFhZWiAAAAAAAABimQAAt4UAABjaWFlaIAAAAAAAACSgAAAPhAAAts9YWVogAAAAAAAA9tYAAQAAAADTLXBhcmEAAAAAAAQAAAACZmYAAPKnAAANWQAAE9AAAApbAAAAAAAAAABtbHVjAAAAAAAAAAEAAAAMZW5VUwAAACAAAAAcAEcAbwBvAGcAbABlACAASQBuAGMALgAgADIAMAAxADb/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAACAAIDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAABwj/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCQCswY/9k=')


def sef(blocks=((0x0a01,b'SyntheticName',b'opaque'),(0x0a02,b'Other',b'bytes')),version=107):
    data=bytearray();entries=[]
    for kind,name,payload in blocks:
        raw=struct.pack('<HHI',0,kind,len(name))+name+payload
        entries.append((kind,len(data),len(raw)));data.extend(raw)
    directory=b'SEFH'+struct.pack('<II',version,len(entries))
    directory+=b''.join(struct.pack('<HHII',0,kind,len(data)-start,size) for kind,start,size in entries)
    return bytes(data)+directory+struct.pack('<I',len(directory))+b'SEFT'


class SamsungJpegTrailerRegression(unittest.TestCase):
    setUp=h.AttachmentSpoolRed.setUp
    new_spool=h.AttachmentSpoolRed.new_spool
    metadata=h.AttachmentSpoolRed.metadata
    begin=h.AttachmentSpoolRed.begin
    seal=h.AttachmentSpoolRed.seal
    reserve=h.AttachmentSpoolRed.reserve

    def bounds(self,raw):
        with tempfile.TemporaryFile() as f:
            f.write(raw);f.flush()
            return self.module.image_bounds(f.fileno(),len(raw))

    def test_metadata_only_sef_accepts_valid_jpeg_without_changing_original_bytes(self):
        # INV-WATT-JPEG-SEF: same ordinary JPEG, trailing metadata, exact original identity.
        self.assertTrue(self.bounds(JPEG))
        for version in (101,107):
            with self.subTest(version=version):self.assertTrue(self.bounds(JPEG+sef(version=version)))
        original=JPEG+sef();stage=self.begin(original);aid=stage['attachment_id']
        self.assertNotIn('error',self.spool.chunk(self.target,aid,0,original))
        finished=self.spool.finish(self.target,aid)
        self.assertNotIn('error',finished,'Valid metadata-only SEF JPEG must seal as image')
        dto=self.spool.status(self.target,aid)
        self.assertEqual(dto['mode'],'image');self.assertEqual(dto['size'],len(original))
        self.assertEqual(dto['sha256'],hashlib.sha256(original).hexdigest())
        result=self.reserve([aid]);self.assertNotIn('error',result)
        manifest=result['manifest'];self.assertEqual(len(manifest),1)
        self.assertEqual(Path(manifest[0]['path']).read_bytes(),original)
        self.assertEqual(manifest[0]['sha256'],hashlib.sha256(original).hexdigest())

    def test_arbitrary_corrupt_unbounded_or_embedded_jpeg_tail_is_rejected(self):
        # INV-WATT-JPEG-SEF: explicit narrow container support, existing fences retained.
        good=sef();header=good.index(b'SEFH')
        variants={'arbitrary':b'extra','truncated_footer':good[:-1],
            'extra_suffix':good+b'x','version':sef(version=999),
            'empty_table':sef(blocks=()),'oversize':sef(blocks=((1,b'N',b'x'*65536),)),
            'extra_jpeg':sef(blocks=((1,b'N',JPEG),))}
        def changed(offset,value):
            raw=bytearray(good);struct.pack_into('<I',raw,offset,value);return bytes(raw)
        variants.update(count=changed(header+8,257),offset_escape=changed(header+16,header+1),
            block_overflow=changed(header+20,header+1),name_overflow=changed(4,65535),
            footer_length=changed(len(good)-8,12),overlap=changed(header+28,header))
        for label,tail in variants.items():
            with self.subTest(label=label):
                with self.assertRaises(self.module.Refusal):self.bounds(JPEG+tail)
