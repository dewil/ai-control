"""INV-DEPLOY-23 independently verifies portable archive data, never imports nats."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import unittest
import zipfile
import deploy22_blind_support as s

EXPECTED={'LICENSE','README.md','SHA256SUMS','build-a-proof.json','build-b-proof.json','build-wheel.py',
 'download-provenance.json','nats_py-2.9.0-py3-none-any.whl','provenance.json','validate-wheel.py',
 'wheel-inventory.json','wheel-validation-proof.json'}

class PortableDependencyProofBlind(unittest.TestCase):
    def test_final_checkout_exact12tracked_index_and_all_blob_hashes(self):
        tracked=subprocess.run(['/usr/bin/git','-C',str(s.ROOT),'ls-files','tests/fixtures/deploy22-nats'],
            check=True,capture_output=True,timeout=10).stdout.decode().splitlines()
        self.assertEqual({Path(path).name for path in tracked},EXPECTED);self.assertEqual(len(tracked),12)
        index=(s.FIXTURE/'SHA256SUMS').read_bytes();self.assertEqual(s.sha(index),s.INDEX_SHA)
        entries={line.split('  ',1)[1]:line.split('  ',1)[0] for line in index.decode().splitlines()}
        self.assertEqual(set(entries),EXPECTED-{'SHA256SUMS'})
        for name,digest in entries.items():self.assertEqual(s.sha((s.FIXTURE/name).read_bytes()),digest,name)

    def test_frozen_wheel_and_independent_full_fivefield_canonical_digest(self):
        raw=s.WHEEL.read_bytes();self.assertEqual(len(raw),82408);self.assertEqual(s.sha(raw),s.WHEEL_SHA)
        inventory=(s.FIXTURE/'wheel-inventory.json').read_bytes()
        self.assertEqual(s.sha(inventory),'a90f99cd99a013e157185d15e0dd0b7d93a6a2e23aa89dbff100a3c3450c279e')
        declared=s.rows();self.assertEqual(len(declared),29)
        for row in declared:self.assertEqual(set(row),{'path','sha256','size','archive_mode','install_mode'})
        self.assertEqual(s.sha(s.canonical(sorted(declared,key=lambda row:row['path']))),s.INVENTORY_SHA)
        # Recompute sha/size/mode from the archive, not just compare two declarations.
        observed=[]
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(len(archive.infolist()),29);self.assertIsNone(archive.testzip())
            for info in archive.infolist():
                data=archive.read(info.filename)
                observed.append(dict(path=info.filename,sha256=s.sha(data),size=len(data),
                    archive_mode=(info.external_attr>>16)&0o777,install_mode=0o644))
        self.assertEqual(sorted(observed,key=lambda row:row['path']),declared)
        self.assertEqual(s.sha(s.canonical(sorted(observed,key=lambda row:row['path']))),s.INVENTORY_SHA)
        self.assertEqual(sum(row['size'] for row in observed),308765)

    def test_RECORD_hash_size_fullcoverage_and_archive0664_install0644(self):
        with zipfile.ZipFile(s.WHEEL) as archive:
            record='nats_py-2.9.0.dist-info/RECORD';declared=list(csv.reader(io.StringIO(archive.read(record).decode())))
            self.assertEqual({row[0] for row in declared},set(archive.namelist()))
            self.assertEqual(len(declared),29)
            for path,digest,size in declared:
                if path==record:self.assertEqual((digest,size),('',''));continue
                data=archive.read(path)
                self.assertEqual(digest,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode())
                self.assertEqual(size,str(len(data)))
        row=next(row for row in s.rows() if row['path']==record)
        self.assertEqual((row['archive_mode'],row['install_mode']),(0o664,0o644))
        self.assertTrue(all(row['install_mode']==0o644 for row in s.rows()))

    def test_license_and_safe_member_names_no_hooks_native_or_extra(self):
        self.assertEqual(s.sha((s.FIXTURE/'LICENSE').read_bytes()),'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4')
        for row in s.rows():
            path=Path(row['path']);self.assertFalse(path.is_absolute());self.assertNotIn('..',path.parts)
            self.assertNotIn('\\',row['path']);self.assertNotIn(':',row['path'])
            self.assertFalse(row['path'].endswith(('.pth','.so','.pyd','.pyc')))
            self.assertNotIn('__pycache__',path.parts);self.assertNotIn('.data',row['path'])
            self.assertTrue(row['path'].startswith(('nats/','nats_py-2.9.0.dist-info/')))
