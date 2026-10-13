"""Independent real-FS WATT spool tests. Public seam documented beside spec.

No native calls or production paths. Loss/corruption is injected into the private
commitment paths returned by reserve, never by guessing implementation layout.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from test_control_web_session_chat_contract import SID, MID, OTHER, ROOT

CHUNK=49152
UPLOAD='55555555-5555-4555-8555-555555555555'


class AttachmentSpoolRed(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT/'bin/_control_web_attachments.py').is_file(),
                        'INV-WATT-02 durable AttachmentSpool is not implemented')
        self.module=importlib.import_module('_control_web_attachments')
        self.temp=tempfile.TemporaryDirectory(prefix='watt-spool-',dir='/var/tmp');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.base.chmod(0o700)
        self.project=self.base/'project';self.project.mkdir(mode=0o700)
        self.root=self.base/'spool';self.now=1800000000
        self.target=dict(owner_uid=os.getuid(),root=str(self.project.resolve()),sid=SID,
            context='synthetic-context',mapping_version=1,login_scope='synthetic-login-A',
            auth_expires_at=self.now+3600,message_id=MID,process_generation=3,
            context_generation=7,grant_generation=2)
        self.limits=dict(owner_bytes=200000,owner_objects=8,receiving_uploads=2,
                         message_bytes=200000,message_files=8,file_bytes=200000,tombstones=10000)
        self.spool=self.new_spool()
    def new_spool(self):
        return self.module.AttachmentSpool(str(self.root),clock=lambda:self.now,limits=self.limits)
    def metadata(self,data=b'opaque bytes',upload=UPLOAD):
        return dict(upload_id=upload,size=len(data),filename='fixture.bin',media_hint='application/octet-stream')
    def begin(self,data=b'opaque bytes',target=None,upload=UPLOAD):
        return self.spool.begin(target or self.target,self.metadata(data,upload))
    def seal(self,data=b'opaque bytes',upload=UPLOAD):
        stage=self.begin(data,upload=upload);aid=stage['attachment_id']
        for index,offset in enumerate(range(0,len(data),CHUNK)):
            self.assertNotIn('error',self.spool.chunk(self.target,aid,index,data[offset:offset+CHUNK]))
        result=self.spool.finish(self.target,aid)
        self.assertEqual(result['state'],'sealed');self.assertEqual(result['sha256'],hashlib.sha256(data).hexdigest())
        return aid
    def reserve(self,ids,operation='send',text=''):
        return self.spool.reserve(self.target,operation,text,ids)
    def error(self,result,expected=None):
        self.assertIn('error',result,result)
        if expected:self.assertEqual(result['error'],expected)

    def test_chunks_exact_replay_gap_conflict_finish_and_sealed_are_immutable(self):
        # INV-WATT-02: binary NUL/high bytes are opaque, not text extraction.
        data=bytes(range(256))*193
        stage=self.begin(data);aid=stage['attachment_id'];first=data[:CHUNK]
        self.error(self.spool.chunk(self.target,aid,1,b'x'))
        self.assertNotIn('error',self.spool.chunk(self.target,aid,0,first))
        self.assertNotIn('error',self.spool.chunk(self.target,aid,0,first))
        self.error(self.spool.chunk(self.target,aid,0,b'z'*CHUNK))
        self.error(self.spool.finish(self.target,aid))
        self.assertNotIn('error',self.spool.chunk(self.target,aid,1,data[CHUNK:]))
        sealed=self.spool.finish(self.target,aid)
        self.assertEqual((sealed['bytes'],sealed['sha256']),(len(data),hashlib.sha256(data).hexdigest()))
        self.error(self.spool.chunk(self.target,aid,2,b'extra'))
        self.assertEqual(self.spool.finish(self.target,aid),sealed)
        self.assertNotIn(str(self.root),json.dumps(sealed))

    def test_begin_replay_bound_to_metadata_and_all_target_fences(self):
        # INV-WATT-01 INV-WATT-03
        first=self.begin();self.assertEqual(self.begin(),first)
        changed=self.metadata();changed['filename']='different.bin'
        self.error(self.spool.begin(self.target,changed))
        for key,value in dict(owner_uid=os.getuid()+1,root=str(self.base),sid=OTHER,
            context='other',login_scope='new-login',message_id=OTHER,context_generation=8,
            process_generation=4,grant_generation=3).items():
            with self.subTest(key=key):
                target={**self.target,key:value}
                self.error(self.spool.status(target,first['attachment_id']))
                self.error(self.spool.chunk(target,first['attachment_id'],0,b'opaque bytes'))
        self.assertEqual(self.spool.status(self.target,first['attachment_id'])['bytes'],0)

    def test_absolute_expiry_no_renewal_restart_or_clock_rollback(self):
        # INV-WATT-01 INV-WATT-05
        stage=self.begin();expiry=stage['expires_at'];self.assertEqual(expiry,self.now+1800)
        self.now+=900
        self.assertEqual(self.begin()['expires_at'],expiry)
        self.assertEqual(self.spool.status(self.target,stage['attachment_id'])['expires_at'],expiry)
        self.spool=self.new_spool();self.now=expiry
        self.error(self.spool.chunk(self.target,stage['attachment_id'],0,b'opaque bytes'))
        self.now=expiry-1;self.spool=self.new_spool()
        self.error(self.spool.chunk(self.target,stage['attachment_id'],0,b'opaque bytes'))

    def test_parallel_reservations_count_declared_bytes_before_any_chunk(self):
        # INV-WATT-02: real shared FS, two independent instances.
        self.limits['owner_bytes']=10;self.spool=self.new_spool();other=self.new_spool()
        def begin(spool,upload):return spool.begin(self.target,self.metadata(b'123456',upload))
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(begin,self.spool,UPLOAD),pool.submit(begin,other,OTHER)]
            results=[f.result() for f in futures]
        self.assertEqual(sum('attachment_id' in r for r in results),1,results)
        self.assertEqual([r.get('error') for r in results].count('attachment_storage_full'),1)

    def test_reserve_commits_real_ordered_bytes_unknown_and_cross_kind_conflict(self):
        # INV-WATT-03 INV-WATT-04 INV-WATT-06
        a=self.seal(b'first\x00file');b=self.seal(b'second\xfffile',OTHER)
        reserved=self.reserve([a,b],text='user text')
        self.assertEqual(reserved['status'],'delivery_unknown')
        self.assertEqual([m['id'] for m in reserved['manifest']],[a,b])
        for entry,data in zip(reserved['manifest'],[b'first\x00file',b'second\xfffile']):
            path=Path(entry['path']);self.assertEqual(path.read_bytes(),data)
            self.assertEqual(path.stat().st_nlink,1);self.assertEqual(path.stat().st_mode&0o222,0)
        record=json.loads(Path(reserved['receipt_path']).read_text())
        self.assertEqual(record['schema'],4);self.assertEqual(record['status'],'delivery_unknown')
        self.assertTrue(all(Path(path).is_file() for path in reserved['pin_paths']))
        self.assertEqual(self.reserve([a,b],text='user text'),reserved)
        self.error(self.reserve([b,a],text='user text'))
        self.error(self.reserve([a,b],operation='enqueue',text='user text'))
        self.spool=self.new_spool()
        self.assertEqual(self.spool.receipt(self.target,MID)['status'],'delivery_unknown')

    def test_inode_symlink_hardlink_and_hash_drift_never_reserve_changed_bytes(self):
        # INV-WATT-02 INV-WATT-04: each mutation has identical name/size where feasible.
        for kind in ('hash','inode','symlink','hardlink'):
            with self.subTest(kind=kind):
                self.root=self.base/('spool-'+kind);self.spool=self.new_spool()
                aid=self.seal(b'original')
                blobs=[p for p in self.root.rglob('*') if p.is_file() and p.read_bytes()==b'original']
                self.assertEqual(len(blobs),1,'sealed fixture bytes must exist once in spool')
                path=blobs[0]
                if kind=='hash':path.chmod(0o600);path.write_bytes(b'modified')
                elif kind=='inode':path.unlink();path.write_bytes(b'original');path.chmod(0o400)
                elif kind=='symlink':
                    external=self.base/'external';external.write_bytes(b'original');path.unlink();path.symlink_to(external)
                else:os.link(path,self.base/'extra-link')
                self.error(self.reserve([aid]))
                self.assertNotEqual(self.spool.receipt(self.target,MID).get('status'),'accepted')

    def test_terminal_and_unknown_pins_survive_discard_logout_expiry_two_restarts(self):
        # INV-WATT-04 INV-WATT-05: ACK cannot establish consumption/reclaim eligibility.
        for status in ('delivery_unknown','accepted','queued','rejected'):
            with self.subTest(status=status):
                self.root=self.base/('pins-'+status);self.spool=self.new_spool()
                aid=self.seal();reserved=self.reserve([aid])
                if status!='delivery_unknown':
                    self.spool.complete(self.target,MID,status)
                self.error(self.spool.discard(self.target,aid))
                self.now+=4000
                for _ in range(2):
                    self.spool=self.new_spool();self.spool.sweep()
                    self.assertTrue(Path(reserved['manifest'][0]['path']).exists())
                    self.assertEqual(self.spool.receipt({**self.target,'login_scope':'fresh-login','auth_expires_at':self.now+60},MID)['status'],status)
                self.now=1800000000

    def test_missing_corrupt_receipt_or_pin_quarantines_without_losing_terminal(self):
        # INV-WATT-04 INV-WATT-05 WATT-REC-10/11/03; two restart fixed point.
        for damage in ('missing_receipt','corrupt_receipt','missing_pin'):
            with self.subTest(damage=damage):
                self.root=self.base/damage;self.spool=self.new_spool();aid=self.seal()
                reserved=self.reserve([aid]);expected='delivery_unknown'
                if damage=='missing_pin':
                    self.spool.complete(self.target,MID,'accepted');expected='accepted'
                    Path(reserved['pin_paths'][0]).unlink()
                elif damage=='missing_receipt':Path(reserved['receipt_path']).unlink()
                else:Path(reserved['receipt_path']).write_text('{"partial":')
                for _ in range(2):
                    self.spool=self.new_spool();self.spool.sweep()
                    receipt=self.spool.receipt(self.target,MID)
                    self.assertIn(receipt['status'],[expected,'quarantined_unknown'] if expected=='delivery_unknown' else [expected])
                    self.assertTrue(Path(reserved['manifest'][0]['path']).exists())
                    self.error(self.spool.begin({**self.target,'message_id':OTHER},self.metadata(upload=OTHER)))
                    self.error(self.reserve([aid]))

    def test_complete_rejects_invented_status_and_cannot_replace_committed_manifest(self):
        # INV-WATT-03 INV-WATT-04
        aid=self.seal();reserved=self.reserve([aid])
        self.error(self.spool.complete(self.target,MID,'consumed'))
        self.error(self.spool.complete(self.target,MID,'accepted',manifest=[]))
        self.assertEqual(self.spool.receipt(self.target,MID)['status'],'delivery_unknown')
        self.assertTrue(Path(reserved['manifest'][0]['path']).is_file())

    def test_pinned_bytes_still_charge_quota_after_expiry_without_eviction(self):
        # INV-WATT-02 INV-WATT-05 WATT-QUOTA-HELD
        self.limits['owner_bytes']=13;self.spool=self.new_spool()
        aid=self.seal(b'123456789012');reserved=self.reserve([aid])
        self.now+=4000;self.spool=self.new_spool();self.spool.sweep()
        fresh={**self.target,'message_id':OTHER,'login_scope':'fresh-login','auth_expires_at':self.now+3600}
        result=self.spool.begin(fresh,self.metadata(b'12',OTHER))
        self.error(result,'attachment_storage_full')
        self.assertEqual(Path(reserved['manifest'][0]['path']).read_bytes(),b'123456789012')
