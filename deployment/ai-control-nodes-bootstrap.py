#!/usr/bin/python3
"""Pinned, fixed-path nodes25 helper/unit bootstrap; no service restart or config access."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import types

EXPECTED_PACKET_SHA256 = None  # Set only by the separately reviewed immutable carrier.
ARTIFACTS = ('helper.before', 'helper.after', 'broker-unit.before', 'broker-unit.after',
             'accepted.before', 'live-receipt.before', 'attachments-receipt.before')
NODE_LINE = b'Environment=CONTROL_NODE_TASKS_CONFIG=/home/dwl/.config/ai-control/node-tasks.json\n'
ROOT = Path('/var/lib/ai-control-deploy')
PATHS = dict(HELPER=Path('/usr/local/sbin/ai-control-deploy'),
    BROKER_UNIT=Path('/etc/systemd/system/ai-control-web-broker.service'),
    ACCEPTED=ROOT/'accepted.json', LIVE_RECEIPT=ROOT/'live-bootstrap-complete.json',
    ATTACHMENT_RECEIPT=ROOT/'attachments-bootstrap-complete.json',
    NODE_RECEIPT=ROOT/'nodes-bootstrap-complete.json', LOCK=ROOT/'checkpoints/lock',
    CHECKPOINTS=ROOT/'checkpoints', PENDING=ROOT/'nodes-bootstrap-pending.json',
    PACKAGE_PENDING=ROOT/'checkpoints/pending.json', CONFIG_PENDING=ROOT/'config-pending.json')


class RollbackFailed(Exception):
    """Known rollback failed; retain recovery artifacts for review."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def decode(raw):
    def unique(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError()
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def hex_digest(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError()


def identity(info):
    return tuple(getattr(info, key) for key in ('st_dev', 'st_ino', 'st_mode', 'st_uid',
        'st_gid', 'st_nlink', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))


class NodesBootstrap:
    def __init__(self, packet_dir, *, paths=None, runner=None, owner_uid=0,
                 helper_api=None, deploy=None, checkpoint_hook=None):
        if helper_api is None and (os.geteuid() != 0 or owner_uid != 0
                or any(v is not None for v in (paths, runner, deploy, checkpoint_hook))):
            raise ValueError('Invalid bootstrap context')
        self.packet = Path(packet_dir)
        self.paths = PATHS if paths is None else {k: Path(v) for k, v in paths.items()}
        if set(self.paths) != set(PATHS):
            raise ValueError('Invalid bootstrap paths')
        self.uid, self.api, self.deploy = owner_uid, helper_api, deploy
        self.runner, self.hook = runner, checkpoint_hook or (lambda _: None)
        self.rollback_used = False

    def _directory(self, path, private=False):
        path = Path(path)
        if '..' in path.parts:
            raise ValueError()
        path = Path(os.path.abspath(path))
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for i, part in enumerate(path.parts[1:]):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = child
                st = os.fstat(fd)
                last = i == len(path.parts) - 2
                sticky = not last and st.st_uid == 0 and st.st_mode & stat.S_ISVTX and Path(*path.parts[:i+2]) in (Path('/tmp'), Path('/var/tmp'))
                if st.st_uid not in ((self.uid,) if last else (0, self.uid)) or (st.st_mode & 0o022 and not sticky):
                    raise ValueError()
                if last and private and stat.S_IMODE(st.st_mode) != 0o700:
                    raise ValueError()
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _read(self, path, mode, limit, private=False, return_stat=False):
        parent = self._directory(Path(path).parent, private)
        try:
            fd = os.open(Path(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                st = os.fstat(fd)
                if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != self.uid
                        or (self.uid == 0 and st.st_gid != 0)
                        or stat.S_IMODE(st.st_mode) != mode or st.st_size > limit):
                    raise ValueError()
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    raw = stream.read(limit+1)
                if (len(raw) != st.st_size or identity(st) != identity(os.fstat(fd))
                        or identity(st) != identity(os.stat(Path(path).name, dir_fd=parent, follow_symlinks=False))):
                    raise ValueError()
                return (raw, st) if return_stat else raw
            finally:
                os.close(fd)
        finally:
            os.close(parent)

    def _packet(self, directory):
        fd = self._directory(directory, True)
        try:
            before = identity(os.fstat(fd))
            if set(os.listdir(fd)) != {'manifest.json', *ARTIFACTS}:
                raise ValueError()
            raw = self._read(directory/'manifest.json', 0o600, 16384, True)
            if not hex_digest(EXPECTED_PACKET_SHA256) or sha(raw) != EXPECTED_PACKET_SHA256:
                raise ValueError()
            m = decode(raw)
            if (type(m) is not dict or set(m) != {'schema', 'operation', 'accepted_release_id', 'files'}
                    or type(m['schema']) is not int or m['schema'] != 1 or m['operation'] != 'nodes25-bootstrap'
                    or type(m['accepted_release_id']) is not int or not 1 <= m['accepted_release_id'] <= 2**63-1
                    or type(m['files']) is not dict or set(m['files']) != set(ARTIFACTS)):
                raise ValueError()
            for name, row in m['files'].items():
                limit = 1048576 if name.startswith('helper.') else 65536
                if (type(row) is not dict or set(row) != {'sha256', 'size'} or not hex_digest(row['sha256'])
                        or type(row['size']) is not int or not 0 <= row['size'] <= limit):
                    raise ValueError()
            if len(raw) + sum(row['size'] for row in m['files'].values()) > 2304*1024:
                raise ValueError()
            data = {'manifest.json': raw}
            for name, row in m['files'].items():
                value = self._read(directory/name, 0o600, 1048576 if name.startswith('helper.') else 65536, True)
                if len(value) != row['size'] or sha(value) != row['sha256']:
                    raise ValueError()
                data[name] = value
            if identity(os.fstat(fd)) != before:
                raise ValueError()
            unit = data['broker-unit.before']
            if (unit.count(b'[Service]\n') != 1 or b'CONTROL_NODE_TASKS_CONFIG' in unit
                    or data['broker-unit.after'] != unit.replace(b'[Service]\n', b'[Service]\n'+NODE_LINE, 1)):
                raise ValueError()
            return m, data
        finally:
            os.close(fd)

    def _prepare(self):
        self.manifest, self.data = self._packet(self.packet)
        live, attachment = (decode(self.data[n]) for n in ('live-receipt.before', 'attachments-receipt.before'))
        keys(live, ('schema', 'operation', 'packet_sha256', 'accepted_before_sha256', 'helper_sha256',
                            'unit_sha256', 'wheel_sha256', 'dependency_inventory_sha256'))
        keys(attachment, ('schema', 'operation', 'prior_helper_sha256', 'helper_sha256',
                                  'prior_receipt_sha256', 'accepted_before_sha256', 'packet_sha256'))
        for value, operation in ((live, 'live22-bootstrap'), (attachment, 'attachments23-bootstrap')):
            if type(value['schema']) is not int or value['schema'] != 1 or value['operation'] != operation:
                raise ValueError()
            if any(not hex_digest(value[k]) for k in set(value)-{'schema', 'operation'}):
                raise ValueError()
        if (attachment['prior_receipt_sha256'] != sha(self.data['live-receipt.before'])
                or attachment['prior_helper_sha256'] != live['helper_sha256']
                or attachment['helper_sha256'] != sha(self.data['helper.before'])
                or live['unit_sha256'] != sha(self.data['broker-unit.before'])):
            raise ValueError()
        for key, leaf in (('LIVE_RECEIPT', 'live-receipt.before'),
                          ('ATTACHMENT_RECEIPT', 'attachments-receipt.before')):
            if self._read(self.paths[key], 0o600, 65536, True) != self.data[leaf]:
                raise ValueError()
        if self.api is None:
            self.api = types.ModuleType('reviewed_nodes_helper')
            self.api.__file__ = str(self.paths['HELPER'])
            exec(compile(self.data['helper.after'], self.api.__file__, 'exec'), self.api.__dict__)
        if self.runner is None:
            self.runner = self.api.runner
        if self.deploy is None:
            self.deploy = self.api.Deploy(runner=self.runner)
        self.before = self.api.state_value(decode(self.data['accepted.before']))
        if self.before['schema'] != 5 or self.before['release_id'] != self.manifest['accepted_release_id']:
            raise ValueError()
        if (live['wheel_sha256'] != self.api.WHEEL_SHA256
                or live['dependency_inventory_sha256'] != self.api.WHEEL_INVENTORY_SHA256):
            raise ValueError()
        self.receipt = self.api.encode(dict(schema=1, operation='nodes25-bootstrap',
            prior_receipt_sha256=sha(self.data['attachments-receipt.before']),
            prior_helper_sha256=sha(self.data['helper.before']), helper_sha256=sha(self.data['helper.after']),
            prior_unit_sha256=sha(self.data['broker-unit.before']), unit_sha256=sha(self.data['broker-unit.after']),
            accepted_before_sha256=sha(self.data['accepted.before']), packet_sha256=sha(self.data['manifest.json'])))

    def _sync(self, path):
        fd = self._directory(path)
        try: os.fsync(fd)
        finally: os.close(fd)

    def _remove(self, key, expected):
        path = self.paths[key]
        raw, st = self._read(path, 0o600, 65536, True, return_stat=True)
        if raw != expected:
            raise ValueError()
        parent = self._directory(path.parent, True)
        try:
            if identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != identity(st):
                raise ValueError()
            os.unlink(path.name, dir_fd=parent)
            os.fsync(parent)
        finally:
            os.close(parent)

    def _anchors(self, repeat=False):
        for key, leaf, mode in (('LIVE_RECEIPT','live-receipt.before',0o600), ('ATTACHMENT_RECEIPT','attachments-receipt.before',0o600)):
            if self._read(self.paths[key], mode, 65536, True) != self.data[leaf]: raise ValueError()
        state = self.deploy.read_state()
        if not repeat and self.deploy.accepted_raw != self.data['accepted.before']: raise ValueError()
        if repeat and (state['schema'] not in (5,6) or state['release_id'] < self.before['release_id']): raise ValueError()
        self.deploy.match(state['files'])
        self.api.dependency_inventory(self.api.SITE_PACKAGES, owner_uid=self.uid)
        for key, stem, mode in (('HELPER','helper',0o755), ('BROKER_UNIT','broker-unit',0o644)):
            raw = self._read(self.paths[key], mode, 1048576)
            if raw not in (self.data[stem+'.before'],self.data[stem+'.after']): raise ValueError()
        if os.path.lexists(self.paths['NODE_RECEIPT']) and self._read(self.paths['NODE_RECEIPT'],0o600,65536,True) != self.receipt:
            raise ValueError()

    def _reload(self):
        self.runner(['/usr/bin/systemctl', 'daemon-reload'])

    def _recover(self):
        if not os.path.lexists(self.paths['PENDING']): return {'status':'no_pending'}
        raw = self._read(self.paths['PENDING'],0o600,65536,True)
        journal = decode(raw)
        self.api.keys(journal, ('schema','operation','packet_sha256','checkpoint'))
        if (type(journal['schema']) is not int or journal['schema'] != 1 or journal['operation'] != 'nodes25-bootstrap'
                or journal['packet_sha256'] != EXPECTED_PACKET_SHA256 or type(journal['checkpoint']) is not str
                or re.fullmatch('nodes-helper-[A-Za-z0-9_-]+',journal['checkpoint']) is None): raise ValueError()
        _, backup = self._packet(self.paths['CHECKPOINTS']/journal['checkpoint'])
        if backup != self.data: raise ValueError()
        self._anchors()
        if self.rollback_used: raise RollbackFailed('Rollback budget exhausted')
        self.rollback_used = True
        try:
            for key, leaf, mode in (('HELPER','helper.before',0o755),('BROKER_UNIT','broker-unit.before',0o644)):
                self._anchors()
                self.api.atomic_write(self.paths[key],self.data[leaf],mode,self.uid)
            self._reload()
            self._anchors()
            if os.path.lexists(self.paths['NODE_RECEIPT']): self._remove('NODE_RECEIPT',self.receipt)
            self.deploy.live_gate(); self.deploy.services()
            self._anchors()
            self._remove('PENDING',raw)
        except Exception:
            raise RollbackFailed('Bootstrap rollback failed; pending retained') from None
        return {'status':'recovered'}

    def _locked(self, recover_only):
        self.rollback_used = False
        self._prepare()
        path = self.paths['LOCK']; parent = self._directory(path.parent,True)
        try:
            fd = os.open(path.name,os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            try:
                st = os.fstat(fd)
                if (not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != self.uid
                        or (self.uid == 0 and st.st_gid != 0) or stat.S_IMODE(st.st_mode) != 0o600): raise ValueError()
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                if identity(st) != identity(os.stat(path.name,dir_fd=parent,follow_symlinks=False)): raise ValueError()
                for key in ('PACKAGE_PENDING','CONFIG_PENDING'):
                    if os.path.lexists(self.paths[key]): raise ValueError()
                result = self._recover()
                if recover_only: return result
                if os.path.lexists(self.paths['NODE_RECEIPT']):
                    self._anchors(repeat=True)
                    for key,leaf,mode in (('HELPER','helper.after',0o755),('BROKER_UNIT','broker-unit.after',0o644)):
                        if self._read(self.paths[key],mode,1048576) != self.data[leaf]: raise ValueError()
                    self.deploy.live_gate(); self.deploy.services()
                    return {'status':'already_extended'}
                self._anchors()
                for key,leaf,mode in (('HELPER','helper.before',0o755),('BROKER_UNIT','broker-unit.before',0o644)):
                    if self._read(self.paths[key],mode,1048576) != self.data[leaf]: raise ValueError()
                self.deploy.live_gate(); self.deploy.services()
                checkpoint_parent = self._directory(self.paths['CHECKPOINTS'],True)
                try:
                    if sum(n.startswith('nodes-helper-') for n in os.listdir(checkpoint_parent)) >= 16: raise ValueError()
                finally: os.close(checkpoint_parent)
                checkpoint = Path(tempfile.mkdtemp(prefix='nodes-helper-',dir=self.paths['CHECKPOINTS']))
                for leaf,data in self.data.items(): self.api.atomic_write(checkpoint/leaf,data,0o600,self.uid)
                self._sync(checkpoint); self._sync(self.paths['CHECKPOINTS'])
                self._anchors()
                journal = self.api.encode(dict(schema=1,operation='nodes25-bootstrap',packet_sha256=EXPECTED_PACKET_SHA256,checkpoint=checkpoint.name))
                self.api.atomic_write(self.paths['PENDING'],journal,0o600,self.uid)
                try:
                    self.hook('journal')
                    for key,leaf,mode,phase in (('HELPER','helper.after',0o755,'helper'),('BROKER_UNIT','broker-unit.after',0o644,'unit')):
                        self._anchors(); self.api.atomic_write(self.paths[key],self.data[leaf],mode,self.uid); self.hook(phase)
                    self._reload(); self._anchors()
                    parent_receipt = self._directory(self.paths['NODE_RECEIPT'].parent,True)
                    try:
                        child = os.open(self.paths['NODE_RECEIPT'].name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent_receipt)
                        with os.fdopen(child,'wb') as out: out.write(self.receipt); out.flush(); os.fsync(out.fileno())
                        os.fsync(parent_receipt)
                    finally: os.close(parent_receipt)
                    self.hook('receipt'); self._anchors(); self.deploy.live_gate(); self.deploy.services(); self.hook('verified')
                    self._anchors(); self._remove('PENDING',journal)
                except Exception:
                    try:
                        self._recover()
                    except Exception:
                        raise RollbackFailed('Bootstrap rollback refused or failed; pending retained') from None
                    raise ValueError('Bootstrap forward operation failed') from None
                return {'status':'extended'}
            finally: os.close(fd)
        finally: os.close(parent)

    def run(self):
        try: return self._locked(False)
        except RollbackFailed: raise
        except Exception: raise ValueError('Bootstrap validation or operation failed') from None

    def recover(self):
        try: return self._locked(True)
        except RollbackFailed: raise
        except Exception: raise ValueError('Bootstrap recovery validation failed') from None
