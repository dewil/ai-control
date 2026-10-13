"""Only this module imports official nats-py; unit tests do not require it."""
import os
import nats
from nats.errors import TimeoutError
from nats.js.api import AckPolicy, ConsumerConfig, DeliverPolicy, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError


class Broker:
    def __init__(self, connection, js, config):
        self.connection, self.js, self.config = connection, js, config
        self.subscriptions = {}

    @classmethod
    async def connect(cls, config):
        url = os.environ.get("DEVBUS_NATS_URL")
        if not url:
            raise ValueError("DEVBUS_NATS_URL required")
        # Auth only via local env/credentials file, never CLI arguments.
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.username or parsed.password:
            raise ValueError("credentials in URL are forbidden")
        async def quiet_error(_error):
            # Do not automatically print transport exceptions or credential details.
            pass
        options = {"servers": [url], "error_cb": quiet_error, "connect_timeout": 2,
                   "max_reconnect_attempts": 2, "reconnect_time_wait": 1}
        token = os.environ.get("DEVBUS_NATS_TOKEN")
        creds = os.environ.get("DEVBUS_NATS_CREDS")
        if token and creds:
            raise ValueError("choose token or credentials file")
        if token:
            options["token"] = token
        if creds:
            options["user_credentials"] = creds
        connection = await nats.connect(**options)
        return cls(connection, connection.jetstream(), config)

    async def ensure_stream(self):
        cfg = self.config
        try:
            info = await self.js.stream_info(cfg.stream)
        except NotFoundError:
            await self.js.add_stream(config=StreamConfig(name=cfg.stream,
                subjects=["devbus.commands.*", "devbus.events.*"], storage=StorageType.FILE,
                retention=RetentionPolicy.LIMITS, max_age=cfg.ttl_seconds,
                max_bytes=cfg.max_stream_bytes, max_msg_size=131072, duplicate_window=min(120, cfg.ttl_seconds)))
        else:
            stream = info.config
            if (stream.storage != StorageType.FILE or stream.retention != RetentionPolicy.LIMITS
                    or not 0 < stream.max_age <= cfg.ttl_seconds
                    or not 0 < stream.max_bytes <= cfg.max_stream_bytes
                    or set(stream.subjects or []) != {"devbus.commands.*", "devbus.events.*"}):
                raise ValueError("existing stream does not meet local storage policy")

    async def publish(self, subject, data, message_id):
        ack = await self.js.publish(subject, data, headers={"Nats-Msg-Id": message_id}, timeout=5)
        if ack.stream != self.config.stream:
            raise ValueError("unexpected PubAck stream")
        return ack

    async def commands(self, agent):
        if agent not in self.subscriptions:
            self.subscriptions[agent] = await self.js.pull_subscribe("devbus.commands." + agent,
                durable="dispatcher-" + agent, stream=self.config.stream,
                config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, deliver_policy=DeliverPolicy.ALL,
                                      ack_wait=30, max_ack_pending=64))
            info = await self.subscriptions[agent].consumer_info()
            if info.config.ack_policy != AckPolicy.EXPLICIT or info.config.filter_subject != "devbus.commands." + agent:
                self.subscriptions.pop(agent)
                raise ValueError("existing consumer does not meet command ACK policy")
        try:
            return await self.subscriptions[agent].fetch(batch=1, timeout=1)
        except TimeoutError:
            return []

    async def events(self, agent=None, follow=False):
        # Ephemeral history consumer: replay available TTL-limited events for each CLI invocation.
        subject = "devbus.events." + (agent or "*")
        subscription = await self.js.pull_subscribe(subject, stream=self.config.stream,
            config=ConsumerConfig(ack_policy=AckPolicy.EXPLICIT, deliver_policy=DeliverPolicy.ALL,
                                  inactive_threshold=30))
        try:
            while True:
                try:
                    messages = await subscription.fetch(batch=1, timeout=1)
                except TimeoutError:
                    if follow:
                        continue
                    break
                for message in messages:
                    yield message
                    await message.ack()
        finally:
            await subscription.unsubscribe()

    async def close(self):
        await self.connection.close()
