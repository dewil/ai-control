#!/usr/bin/env python3
"""Emit a local review candidate from the single pinned devbus source version."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat


UPSTREAM_SHA256 = "bb871ccb80d7fbf6b620ba40d2521ed65dc8ac6eca8a469606b59f8b9b2bb70e"

CONNECT = '''    @classmethod
    async def connect(cls, config):
        url = os.environ.get("DEVBUS_NATS_URL")
        if not url or not url.strip():
            raise ValueError("DEVBUS_NATS_URL required")
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise ValueError("invalid NATS URL") from None
        if (parsed.username is not None or parsed.password is not None
                or "?" in url or "#" in url or not parsed.hostname
                or parsed.scheme not in {"nats", "tls", "ws", "wss"}):
            raise ValueError("invalid NATS URL")
        token = os.environ.get("DEVBUS_NATS_TOKEN") or None
        creds = os.environ.get("DEVBUS_NATS_CREDS") or None
        user = os.environ.get("DEVBUS_NATS_USER") or None
        password = os.environ.get("DEVBUS_NATS_PASSWORD") or None
        mode = os.environ.get("DEVBUS_NATS_AUTH_MODE")
        if mode is None:
            if user or password or bool(token) == bool(creds):
                raise ValueError("unambiguous token or credentials file required")
            mode = "token" if token else "creds"
        if mode == "token" and token and not any((creds, user, password)):
            auth = {"token": token}
        elif mode == "creds" and creds and not any((token, user, password)):
            auth = {"user_credentials": creds}
        elif mode == "user_password" and user and password and not any((token, creds)):
            auth = {"user": user, "password": password}
        else:
            raise ValueError("invalid NATS authentication configuration")
        if any(not value.strip() for value in auth.values()):
            raise ValueError("nonblank NATS credentials required")
        async def quiet_error(_error):
            # Transport exceptions may contain credential details.
            pass
        options = {"servers": [url], "error_cb": quiet_error, "connect_timeout": 2,
                   "max_reconnect_attempts": 2, "reconnect_time_wait": 1, **auth}
        if mode == "user_password":
            options["inbox_prefix"] = b"_INBOX.alp_codex_runner"
        try:
            connection = await nats.connect(**options)
        except Exception:
            raise RuntimeError("NATS connection failed") from None
        return cls(connection, connection.jetstream(), config, auth_mode=mode)

'''

STRICT_COMMANDS = '''        if self.auth_mode == "user_password":
            if agent != self.config.agent_id:
                raise ValueError("unexpected command agent")
            if agent not in self.subscriptions:
                durable = "dispatcher-" + agent
                info = await self.js.consumer_info(self.config.stream, durable)
                consumer = getattr(info, "config", None)
                if (getattr(info, "stream_name", None) != self.config.stream
                        or getattr(info, "name", None) != durable
                        or getattr(consumer, "ack_policy", None) != AckPolicy.EXPLICIT
                        or getattr(consumer, "filter_subject", None) != "devbus.commands." + agent):
                    raise ValueError("existing consumer does not meet command binding policy")
                self.subscriptions[agent] = await self.js.pull_subscribe_bind(
                    stream=self.config.stream, consumer=durable,
                    inbox_prefix=b"_INBOX.alp_codex_runner.")
        else:
'''


def _replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("unexpected pinned source context")
    return source.replace(old, new, 1)


def _candidate(source):
    # Bounded textual patch for this SHA only; a new upstream requires review.
    source = _replace_once(source,
        "    def __init__(self, connection, js, config):\n",
        '    def __init__(self, connection, js, config, auth_mode="legacy"):\n'
        '        self.auth_mode = auth_mode\n')
    start = source.index("    @classmethod\n")
    end = source.index("    async def ensure_stream(self):\n", start)
    source = _replace_once(source, source[start:end], CONNECT)
    source = _replace_once(source, "        except NotFoundError:\n",
        '        except NotFoundError:\n'
        '            if self.auth_mode == "user_password":\n'
        '                raise\n')
    start = source.index("        if agent not in self.subscriptions:\n")
    end = source.index("        try:\n", start)
    legacy = source[start:end]
    source = _replace_once(source, legacy,
        STRICT_COMMANDS + "".join("    " + line for line in legacy.splitlines(keepends=True)))
    compile(source, "candidate_transport.py", "exec")
    return source.encode("utf-8")


def _parent_fd(path):
    """Walk the supplied ancestry without accepting or resolving symlinks."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("parent traversal forbidden")
    path = Path(os.path.abspath(path))
    if not path.name:
        raise ValueError("file path required")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return path, fd
    except OSError:
        os.close(fd)
        raise ValueError("invalid path ancestry") from None


def generate(source: Path, output: Path) -> dict:
    """Create one new candidate under /tmp or /var/tmp; never apply it."""
    source_path, source_parent = _parent_fd(source)
    try:
        try:
            fd = os.open(source_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=source_parent)
        except OSError:
            raise ValueError("invalid source file") from None
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("regular source file required")
            original = stream.read()
    finally:
        os.close(source_parent)
    if hashlib.sha256(original).hexdigest() != UPSTREAM_SHA256:
        raise ValueError("source SHA256 mismatch")
    candidate = _candidate(original.decode("utf-8"))
    output_path, output_parent = _parent_fd(output)
    try:
        if (output_path == source_path
                or not any(root in output_path.parents for root in (Path("/tmp"), Path("/var/tmp")))):
            raise ValueError("destination must be a new local temporary artifact")
        try:
            fd = os.open(output_path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=output_parent)
        except FileExistsError:
            raise FileExistsError("candidate already exists") from None
        except OSError:
            raise ValueError("cannot create candidate") from None
        with os.fdopen(fd, "wb") as stream:
            stream.write(candidate)
    finally:
        os.close(output_parent)
    return {"upstream_sha256": UPSTREAM_SHA256,
            "candidate_sha256": hashlib.sha256(candidate).hexdigest(), "artifact_schema": 1}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.source, args.output)
    except (OSError, ValueError):
        parser.exit(1, "transport candidate generation failed\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
