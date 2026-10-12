"""Optional read-only JetStream transport; no broker provisioning or publishing."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import stat
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

try:
    from _control_web_devbus import decode_event, valid_id
except ModuleNotFoundError:
    import importlib.util
    _spec = importlib.util.spec_from_file_location('_control_web_devbus', Path(__file__).with_name('_control_web_devbus.py'))
    _module = importlib.util.module_from_spec(_spec)
    sys.modules['_control_web_devbus'] = _module
    _spec.loader.exec_module(_module)
    from _control_web_devbus import decode_event, valid_id

BRIDGE_CONFIG_PATH = Path('/home/dwl/.config/ai-control/devbus-bridge.json')
BRIDGE_STATUS_PATH = Path('/home/dwl/.local/state/ai-control/devbus-bridge.json')
_BRIDGE_REASONS = {'invalid_config', 'unavailable', 'invalid_event', 'id_conflict', 'retention_gap'}


@dataclass(frozen=True)
class NatsConfig:
    enabled: bool = False
    url: str = field(default='', repr=False)
    token: str = field(default='', repr=False)
    creds: str = field(default='', repr=False)
    stream: str = 'DEVBUS_V1'
    user: str = field(default='', repr=False)
    password: str = field(default='', repr=False)
    stream_created: str = field(default='', repr=False)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        enabled = env.get('CONTROL_DEVBUS_ENABLED','0')
        if enabled not in ('0','1'):
            raise ValueError('invalid_config')
        if enabled == '0':
            return cls()
        url = env.get('DEVBUS_NATS_URL','')
        token, creds = env.get('DEVBUS_NATS_TOKEN',''), env.get('DEVBUS_NATS_CREDS','')
        stream = env.get('CONTROL_DEVBUS_STREAM','DEVBUS_V1')
        try:
            parsed = urlsplit(url)
            port = parsed.port
            valid = (parsed.scheme in {'nats','tls'} and parsed.hostname and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment
                and parsed.path in ('','/') and (port is None or 0 < port <= 65535)
                and (parsed.scheme == 'tls' or parsed.hostname in {'localhost','127.0.0.1','::1'}))
        except (ValueError, TypeError):
            valid = False
        if not valid or (token and creds) or type(stream) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',stream):
            raise ValueError('invalid_config')
        return cls(True,url,token,creds,stream)


class BusUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('unavailable')


class _Message:
    __slots__ = ('_message','subject','data','sequence')
    def __init__(self, message):
        self._message = message
        self.subject, self.data = message.subject, message.data
        self.sequence = message.metadata.sequence.stream

    async def ack(self):
        try:
            await asyncio.wait_for(self._message.ack_sync(timeout=5),5)
        except Exception:
            raise BusUnavailable() from None


class _Transport:
    def __init__(self, config):
        self._config = config
        self._nc = self._js = self._sub = None
        self._consumer = None
        self._lost = False
        self._closed = False

    async def _disconnect(self):
        self._lost = True

    async def _quiet(self, _):
        self._lost = True

    def _ready(self):
        if self._lost or self._closed:
            raise BusUnavailable()

    async def _info(self):
        info = await self._js.stream_info(self._config.stream)
        cfg = info.config
        from nats.js.api import RetentionPolicy, StorageType
        required = {'devbus.events.*'} if self._config.stream == 'OBS_EVENTS' else {'devbus.commands.*','devbus.events.*'}
        if (cfg.retention != RetentionPolicy.LIMITS or cfg.storage != StorageType.FILE
            or not required.issubset(set(cfg.subjects or []))
            or not math.isfinite(cfg.max_age) or not 0 < cfg.max_age <= 86400
            or not 0 < cfg.max_bytes <= 104857600
            or (self._config.stream_created and info.created != self._config.stream_created)
            or not 0 < cfg.max_msg_size <= 131072):
            raise BusUnavailable()
        return dict(first_seq=info.state.first_seq,last_seq=info.state.last_seq,
                    ttl_seconds=cfg.max_age,max_bytes=cfg.max_bytes)

    async def info(self):
        self._ready()
        try:
            return await asyncio.wait_for(self._info(),5)
        except Exception:
            raise BusUnavailable() from None

    async def _subscribe(self, sequence=None):
        from nats.js.api import ConsumerConfig, AckPolicy, DeliverPolicy
        name = 'control_' + uuid.uuid4().hex
        cfg = ConsumerConfig(name=name, ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.ALL if sequence is None else DeliverPolicy.BY_START_SEQUENCE,
            opt_start_seq=sequence, filter_subject='devbus.events.*', max_ack_pending=64,
            inactive_threshold=30)
        # Record our identity before creation: cancellation can lose the reply.
        self._consumer = name
        await self._js.add_consumer(self._config.stream, config=cfg)
        self._sub = await self._js.pull_subscribe_bind(name=name,stream=self._config.stream,
            pending_msgs_limit=64,pending_bytes_limit=8*1024*1024)

    async def _delete(self):
        sub, name = self._sub, self._consumer
        self._sub = self._consumer = None
        try:
            if name is not None:
                await self._js.delete_consumer(self._config.stream,name)
        finally:
            if sub is not None:
                await sub.unsubscribe()

    async def fetch(self):
        self._ready()
        from nats.errors import TimeoutError
        try:
            messages = await asyncio.wait_for(self._sub.fetch(batch=32,timeout=1),5)
            self._ready()
            return [_Message(m) for m in messages]
        except TimeoutError:
            self._ready()
            return []
        except Exception:
            raise BusUnavailable() from None

    async def pending(self):
        self._ready()
        try:
            info = await asyncio.wait_for(self._sub.consumer_info(),5)
            return info.num_pending + info.num_ack_pending
        except Exception:
            raise BusUnavailable() from None

    async def skip_to(self, sequence):
        self._ready()
        if type(sequence) is not int or sequence <= 0:
            raise ValueError('invalid sequence')
        try:
            await asyncio.wait_for(self._delete(),5)
            await asyncio.wait_for(self._subscribe(sequence),5)
        except Exception:
            raise BusUnavailable() from None

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.wait_for(self._delete(),5)
        except Exception:
            pass
        finally:
            if self._nc is not None:
                try:
                    await asyncio.wait_for(self._nc.close(),5)
                except Exception:
                    pass


async def connect(config, *, secrets=()):
    if not config.enabled:
        raise ValueError('disabled')
    transport = _Transport(config)
    try:
        import nats
        options = dict(servers=[config.url],connect_timeout=5,max_reconnect_attempts=0,
            allow_reconnect=False,disconnected_cb=transport._disconnect,
            error_cb=transport._quiet)
        if config.token:
            options['token'] = config.token
        if config.creds:
            options['user_credentials'] = config.creds
        if config.user:
            options['user'], options['password'] = config.user, config.password
        transport._nc = await asyncio.wait_for(nats.connect(**options),5)
        transport._js = transport._nc.jetstream(timeout=5)
        await transport.info()
        await asyncio.wait_for(transport._subscribe(),5)
        return transport
    except asyncio.CancelledError:
        await transport.close()
        raise
    except Exception:
        await transport.close()
        raise BusUnavailable() from None


def _bridge_url(value, *, loopback=False):
    if type(value) is not str or not value or len(value) > 512:
        return False
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return (parsed.scheme in {'nats', 'tls'} and bool(parsed.hostname)
                and not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in ('', '/')
                and (port is None or 0 < port <= 65535)
                and (not loopback or parsed.hostname in {'localhost', '127.0.0.1', '::1'}))
    except (ValueError, TypeError):
        return False


def _epoch(value):
    if type(value) is not str or len(value) > 40:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.tzinfo is not None
    except (ValueError, OverflowError):
        return False


def _safe_text(value, limit=8192):
    return (type(value) is str and 0 < len(value) <= limit
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xd800 <= ord(c) <= 0xdfff for c in value))


def _validate_bridge_config(config):
    if type(config) is not dict or set(config) != {'schema', 'source', 'destination', 'agents'} or config.get('schema') != 1 or type(config.get('schema')) is not int:
        raise ValueError('invalid_config')
    source, dest, agents = config['source'], config['destination'], config['agents']
    if (type(source) is not dict or set(source) != {'url', 'stream', 'consumer', 'stream_created', 'consumer_created', 'auth'}
            or source.get('stream') != 'DEVBUS_V1' or not _bridge_url(source.get('url'))
            or not _safe_text(source.get('consumer'), 80) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', source['consumer'])
            or not _epoch(source.get('stream_created')) or not _epoch(source.get('consumer_created'))):
        raise ValueError('invalid_config')
    auth = source.get('auth')
    if type(auth) is not dict or auth.get('mode') not in {'token', 'creds', 'user_password'}:
        raise ValueError('invalid_config')
    auth_fields = {'token': {'mode', 'token'}, 'creds': {'mode', 'creds'},
                   'user_password': {'mode', 'user', 'password'}}[auth['mode']]
    if set(auth) != auth_fields:
        raise ValueError('invalid_config')
    if auth['mode'] == 'token' and not _safe_text(auth.get('token'), 8192):
        raise ValueError('invalid_config')
    if auth['mode'] == 'creds' and (not _safe_text(auth.get('creds'), 4096) or not auth['creds'].startswith('/')):
        raise ValueError('invalid_config')
    if auth['mode'] == 'user_password' and (not _safe_text(auth.get('user'), 256) or not _safe_text(auth.get('password'), 8192)):
        raise ValueError('invalid_config')
    if (type(dest) is not dict or set(dest) != {'url', 'stream', 'stream_created', 'user', 'password'}
            or not _bridge_url(dest.get('url'), loopback=True) or dest.get('stream') != 'OBS_EVENTS'
            or not _epoch(dest.get('stream_created')) or not _safe_text(dest.get('user'), 256)
            or not _safe_text(dest.get('password'), 8192)):
        raise ValueError('invalid_config')
    if (type(agents) is not list or not 1 <= len(agents) <= 256
            or any(not valid_id(agent) for agent in agents) or len(set(agents)) != len(agents)):
        raise ValueError('invalid_config')
    return config


def load_bridge_config():
    """Read the one fixed bridge config, rejecting unsafe file identity changes."""
    if os.geteuid() != 1000:
        raise ValueError('invalid_config')
    fd = os.open(BRIDGE_CONFIG_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != 1000 or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_nlink != 1 or not 0 <= before.st_size <= 16384):
            raise ValueError('invalid_config')
        chunks = bytearray()
        while len(chunks) <= 16384:
            block = os.read(fd, 16385-len(chunks))
            if not block:
                break
            chunks.extend(block)
        after = os.fstat(fd)
        leaf = os.stat(BRIDGE_CONFIG_PATH, follow_symlinks=False)
        fields = ('st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        identity = lambda item: tuple(getattr(item, name) for name in fields)
        if identity(before) != identity(after) or identity(after) != identity(leaf) or len(chunks) != before.st_size or len(chunks) > 16384:
            raise ValueError('invalid_config')
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('invalid_config')
                result[key] = value
            return result
        value = json.loads(chunks.decode('utf-8'), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        return _validate_bridge_config(value)
    finally:
        os.close(fd)


def _stream_created(info):
    return getattr(info, 'created', None)


def _policy_value(value):
    return getattr(value, 'value', value)



async def _bridge_stream_info(js, name, expected_created, *, source):
    info = await asyncio.wait_for(js.stream_info(name), 5)
    cfg = info.config
    storage, retention = _policy_value(cfg.storage), _policy_value(cfg.retention)
    if storage not in {'file', 'File'} or retention not in {'limits', 'Limits'} or _stream_created(info) != expected_created:
        raise RuntimeError('unavailable')
    subjects = set(cfg.subjects or ())
    required = {'devbus.commands.*', 'devbus.events.*'} if source else {'devbus.events.*'}
    if not required.issubset(subjects):
        raise RuntimeError('unavailable')
    if (not math.isfinite(cfg.max_age) or not 0 < cfg.max_age <= 86400
            or not 0 < cfg.max_bytes <= 104857600 or not 0 < cfg.max_msg_size <= 131072):
        raise RuntimeError('unavailable')
    return info


async def _bridge_consumer_info(js, source):
    info = await asyncio.wait_for(js.consumer_info('DEVBUS_V1', source['consumer']), 5)
    cfg = info.config
    def value(name): return _policy_value(getattr(cfg, name, None))
    if (getattr(info, 'created', None) != source['consumer_created']
            or getattr(info, 'name', source['consumer']) != source['consumer']
            or getattr(info, 'stream_name', 'DEVBUS_V1') != 'DEVBUS_V1'
            or value('durable_name') != source['consumer']
            or value('filter_subject') != 'devbus.events.>'
            or value('ack_policy') not in {'explicit', 'Explicit'}
            or value('deliver_policy') not in {'all', 'All'}
            or getattr(cfg, 'max_ack_pending', None) != 32
            or getattr(cfg, 'ack_wait', None) not in (30, 30.0)
            or getattr(cfg, 'max_deliver', None) not in (-1, None)
            or getattr(cfg, 'deliver_subject', None) not in (None, '')
            or getattr(cfg, 'deliver_group', None) not in (None, '')):
        raise RuntimeError('unavailable')
    return info


def _status_record(config, *, state='starting', observed_at=None, ack_floor=None, first_seq=None, pending=None, reason=None):
    return {'schema': 1, 'state': state,
            'observed_at': (observed_at or datetime.now(timezone.utc)).isoformat().replace('+00:00', 'Z'),
            'source_stream_created': config['source']['stream_created'],
            'consumer_created': config['source']['consumer_created'],
            'ack_floor': ack_floor, 'first_seq': first_seq, 'pending': pending,
            'reason': reason if reason in _BRIDGE_REASONS else None}


def _write_bridge_status(record):
    raw = json.dumps(record, separators=(',', ':'), sort_keys=True, allow_nan=False).encode()
    if len(raw) > 4096:
        return
    path = BRIDGE_STATUS_PATH
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb', closefd=False) as handle:
            handle.write(raw); handle.flush(); os.fsync(fd)
        os.replace(temp, path)
        os.chmod(path, 0o600)
    finally:
        try: os.close(fd)
        except OSError: pass
        try: os.unlink(temp)
        except FileNotFoundError: pass


async def _bridge_connect(factory, url, auth):
    options = {'servers': [url], 'connect_timeout': 5, 'max_reconnect_attempts': 0,
               'allow_reconnect': False}
    if auth is not None:
        if auth['mode'] == 'token': options['token'] = auth['token']
        elif auth['mode'] == 'creds': options['user_credentials'] = auth['creds']
        else: options.update(user=auth['user'], password=auth['password'])
    result = factory(**options)
    return await asyncio.wait_for(result, 5)


async def _bridge_session(config, nats_factory):
    """Run one connection generation; failures return to the bounded reconnect loop."""
    source_cfg, dest_cfg = config['source'], config['destination']
    state = _status_record(config)
    last_write = 0.0
    def report(**changes):
        nonlocal state, last_write
        state = dict(state, **changes)
        now = time.monotonic()
        if now - last_write >= 5 or changes.get('state') in {'starting', 'live', 'disconnected'}:
            try: _write_bridge_status(state)
            except Exception: pass
            last_write = now
    src = dst = None
    delay = 1
    try:
        src = await _bridge_connect(nats_factory, source_cfg['url'], source_cfg['auth'])
        dst = await _bridge_connect(nats_factory, dest_cfg['url'], {'mode': 'user_password', 'user': dest_cfg['user'], 'password': dest_cfg['password']})
        sjs, djs = src.jetstream(), dst.jetstream()
        await _bridge_stream_info(sjs, 'DEVBUS_V1', source_cfg['stream_created'], source=True)
        await _bridge_stream_info(djs, 'OBS_EVENTS', dest_cfg['stream_created'], source=False)
        cinfo = await _bridge_consumer_info(sjs, source_cfg)
        ack = getattr(cinfo, 'ack_floor', None)
        ack_floor = getattr(ack, 'stream_seq', 0) or 0
        sinfo = await _bridge_stream_info(sjs, 'DEVBUS_V1', source_cfg['stream_created'], source=True)
        first_seq = sinfo.state.first_seq
        pending = getattr(cinfo, 'num_pending', 0) + getattr(cinfo, 'num_ack_pending', 0)
        reason = 'retention_gap' if type(first_seq) is int and first_seq > ack_floor + 1 else None
        retention_gap = reason is not None
        # The just-completed stream/consumer checks fence this first batch before binding.
        sub = await asyncio.wait_for(sjs.pull_subscribe_bind(name=source_cfg['consumer'], stream='DEVBUS_V1'), 5)
        report(state='degraded' if reason else 'live', ack_floor=ack_floor, first_seq=first_seq, pending=pending, reason=reason)
        delay = 1
        first_batch = True
        while True:
            try:
                # Recheck the captured server generations before every subsequent batch.
                if not first_batch:
                    sinfo = await _bridge_stream_info(sjs, 'DEVBUS_V1', source_cfg['stream_created'], source=True)
                    cinfo = await _bridge_consumer_info(sjs, source_cfg)
                    await _bridge_stream_info(djs, 'OBS_EVENTS', dest_cfg['stream_created'], source=False)
                    first_seq = sinfo.state.first_seq
                    ack_floor = getattr(getattr(cinfo, 'ack_floor', None), 'stream_seq', ack_floor)
                    pending = (getattr(cinfo, 'num_pending', 0) or 0) + (getattr(cinfo, 'num_ack_pending', 0) or 0)
                    retention_gap = retention_gap or (type(first_seq) is int and first_seq > (ack_floor or 0) + 1)
                    if retention_gap:
                        report(state='degraded', reason='retention_gap', ack_floor=ack_floor, first_seq=first_seq, pending=pending)
                first_batch = False
                messages = await asyncio.wait_for(sub.fetch(batch=32, timeout=1), 5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception:
                report(state='degraded', reason='unavailable')
                raise
            for message in messages:
                try:
                    data = message.data
                    sequence = message.metadata.sequence.stream
                    event = decode_event(data, message.subject, sequence, require_created_at=True)
                    if event['source'] not in config['agents']:
                        raise ValueError('invalid_event')
                except Exception:
                    report(state='degraded', reason='invalid_event', ack_floor=ack_floor, first_seq=first_seq)
                    continue
                try:
                    # Epoch fences bracket destination publish and actual SDK ACK.
                    sinfo = await _bridge_stream_info(sjs, 'DEVBUS_V1', source_cfg['stream_created'], source=True)
                    await _bridge_consumer_info(sjs, source_cfg)
                    await _bridge_stream_info(djs, 'OBS_EVENTS', dest_cfg['stream_created'], source=False)
                    dedupe = hashlib.sha256(source_cfg['stream_created'].encode() + str(sequence).encode() + data).hexdigest()
                    headers = {'Nats-Msg-Id': dedupe}
                    puback = await asyncio.wait_for(djs.publish('devbus.events.' + event['source'], data, headers=headers, timeout=5), 5)
                    if getattr(puback, 'stream', None) != 'OBS_EVENTS':
                        raise RuntimeError('unavailable')
                    await _bridge_stream_info(sjs, 'DEVBUS_V1', source_cfg['stream_created'], source=True)
                    await _bridge_consumer_info(sjs, source_cfg)
                    await _bridge_stream_info(djs, 'OBS_EVENTS', dest_cfg['stream_created'], source=False)
                    await asyncio.wait_for(message.ack_sync(timeout=5), 5)
                    ack_floor = max(ack_floor or 0, sequence)
                    pending = max(0, (pending or 0) - 1)
                    report(state='degraded' if retention_gap else 'live', ack_floor=ack_floor, first_seq=sinfo.state.first_seq, pending=pending, reason='retention_gap' if retention_gap else None)
                    delay = 1
                except asyncio.CancelledError:
                    raise
                except Exception:
                    report(state='degraded', reason='unavailable', ack_floor=ack_floor, first_seq=first_seq)
                    raise
            if not messages:
                report(observed_at=datetime.now(timezone.utc))
                await asyncio.sleep(.01)
    except asyncio.CancelledError:
        report(state='disconnected', reason='unavailable')
        raise
    except Exception:
        report(state='degraded', reason='unavailable')
        raise
    finally:
        for connection in (dst, src):
            if connection is not None:
                try: await asyncio.wait_for(connection.close(), 5)
                except Exception: pass



async def run_bridge(config, *, nats_factory=None):
    """Forward validated origin events through PubAck into the bounded OBS copy."""
    _validate_bridge_config(config)
    if nats_factory is None:
        import nats
        nats_factory = nats.connect
    delay = 1
    while True:
        try:
            await _bridge_session(config, nats_factory)
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            try:
                _write_bridge_status(_status_record(config, state='degraded', reason='unavailable'))
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv != ['--bridge']:
        raise SystemExit(2)
    try:
        config = load_bridge_config()
        asyncio.run(run_bridge(config))
    except KeyboardInterrupt:
        return 0
    except Exception:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
