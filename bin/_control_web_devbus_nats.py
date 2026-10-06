"""Optional read-only JetStream transport; no broker provisioning or publishing."""
import asyncio
from dataclasses import dataclass, field
import math
import os
import re
import uuid
from urllib.parse import urlsplit


@dataclass(frozen=True)
class NatsConfig:
    enabled: bool = False
    url: str = field(default='', repr=False)
    token: str = field(default='', repr=False)
    creds: str = field(default='', repr=False)
    stream: str = 'DEVBUS_V1'

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
        if (cfg.retention != RetentionPolicy.LIMITS or cfg.storage != StorageType.FILE
            or not {'devbus.commands.*','devbus.events.*'}.issubset(set(cfg.subjects or []))
            or not math.isfinite(cfg.max_age) or not 0 < cfg.max_age <= 86400
            or not 0 < cfg.max_bytes <= 104857600):
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
