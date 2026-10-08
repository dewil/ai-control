import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile
from email.parser import BytesParser

root = Path('/var/tmp/control-live-nats-build')
filename = 'nats_py-2.9.0-py3-none-any.whl'
a, b = (root / ('build-' + x) / 'wheelhouse' / filename for x in ('a', 'b'))
raw = a.read_bytes()
assert raw == b.read_bytes() and len(raw) <= 2 * 1024 * 1024
inventory = []
with zipfile.ZipFile(io.BytesIO(raw)) as z:
    entries = z.infolist()
    names = [i.filename for i in entries]
    assert len(entries) <= 256 and len(set(names)) == len(entries)
    assert z.testzip() is None
    assert sum(i.file_size for i in entries) <= 8 * 1024 * 1024
    for info in entries:
        name = info.filename
        path = PurePosixPath(name)
        assert not path.is_absolute() and '..' not in path.parts and '.' not in path.parts
        assert '\\' not in name and ':' not in name and '\x00' not in name
        assert str(path) == name and len(path.parts) <= 8
        mode = info.external_attr >> 16
        assert stat.S_ISREG(mode) and not mode & 0o111 and not mode & 0o002
        assert info.file_size <= 2 * 1024 * 1024
        assert not info.is_dir() and not info.flag_bits & 1
        assert not name.endswith(('.pth', '.so', '.dll', '.dylib', '.exe', '.pyc', '.pyo'))
        assert '__pycache__' not in path.parts and not any(part.endswith('.data') for part in path.parts)
        if name.startswith('nats/'):
            assert name.endswith('.py') or name == 'nats/py.typed'
        else:
            assert name in {'nats_py-2.9.0.dist-info/' + n for n in
                           ('LICENSE', 'METADATA', 'WHEEL', 'top_level.txt', 'zip-safe', 'RECORD')}
        payload = z.read(name)
        inventory.append({'path': name, 'sha256': hashlib.sha256(payload).hexdigest(),
                          'size': len(payload), 'archive_mode': stat.S_IMODE(mode), 'install_mode': 0o644})
    record_name = 'nats_py-2.9.0.dist-info/RECORD'
    records = list(csv.reader(io.StringIO(z.read(record_name).decode('utf-8'))))
    assert len(records) == len(entries) and len({r[0] for r in records}) == len(records)
    assert {r[0] for r in records} == set(names)
    for name, digest, size in records:
        if name == record_name:
            assert digest == '' and size == ''
        else:
            payload = z.read(name)
            expected = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b'=').decode()
            assert digest == expected and int(size) == len(payload)
    metadata = BytesParser().parsebytes(z.read('nats_py-2.9.0.dist-info/METADATA'))
    wheel = BytesParser().parsebytes(z.read('nats_py-2.9.0.dist-info/WHEEL'))
    assert metadata['Name'] == 'nats-py' and metadata['Version'] == '2.9.0'
    assert metadata['Requires-Python'] == '>=3.7'
    assert all('extra ==' in dep for dep in metadata.get_all('Requires-Dist', []))
    assert wheel['Root-Is-Purelib'] == 'true' and wheel.get_all('Tag') == ['py3-none-any']
inventory.sort(key=lambda x: x['path'])
canonical = json.dumps(inventory, sort_keys=True, separators=(',', ':')).encode()
(root / 'wheel-inventory.json').write_bytes(canonical + b'\n')
artifact = root / filename
shutil.copyfile(a, artifact)
artifact.chmod(0o644)
summary = {'filename': filename, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw),
           'member_count': len(inventory), 'uncompressed_bytes': sum(x['size'] for x in inventory),
           'inventory_sha256': hashlib.sha256(canonical).hexdigest(), 'inventory_encoding': 'UTF-8 canonical JSON, sorted keys, compact separators, no terminal newline',
           'inventory_file_sha256': hashlib.sha256((root / 'wheel-inventory.json').read_bytes()).hexdigest(),
           'record_validated': True, 'purelib': True, 'wheel_tag': 'py3-none-any', 'two_build_bytes_identical': True,
           'archive_mode_exception': {'path': 'nats_py-2.9.0.dist-info/RECORD', 'archive_mode': 0o664, 'required_install_mode': 0o644},
           'runtime_owner_import_certified': False}
(root / 'wheel-validation-proof.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary, indent=2))
