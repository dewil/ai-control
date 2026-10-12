"""INV-DEVBUS-10: strict startup-only private ingress, synthetic files/syscalls."""
from contextlib import ExitStack
import importlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import live_devbus_blind_support as s


class DevbusLoaderBlind(unittest.TestCase):
    def setUp(self):
        self.load = s.seam(self, "_control_web_broker", "load_devbus_config")
        self.module = importlib.import_module("_control_web_broker")
        self.assertTrue(hasattr(self.module, "DEVBUS_CONFIG_PATH"), "PUBLIC-SEAM PREREQUISITE: DEVBUS_CONFIG_PATH absent")
        self.temp = tempfile.TemporaryDirectory(prefix="bus-config-blind-", dir="/var/tmp"); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "observer.json"
        self.mapping = dict(schema=2, enabled=True, url="nats://127.0.0.1:4222",
                           stream="OBS_EVENTS", stream_created="2026-10-12T00:02:00Z",
                           user="control_observer", password="synthetic-obs-password")
        self.legacy_token_mapping = dict(CONTROL_DEVBUS_ENABLED="1", CONTROL_DEVBUS_STREAM="DEVBUS",
                                         DEVBUS_NATS_URL="nats://127.0.0.1:4222",
                                         DEVBUS_NATS_TOKEN="synthetic-private-token")
        self.real_stat, self.real_fstat = os.stat, os.fstat

    def synthetic_stat(self, value):
        fields = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
        fields["st_uid"] = 1000
        return SimpleNamespace(**fields)

    def invoke(self, raw=None, *, pointer="exact", uid=1000, patches=()):
        if raw is not None:
            self.path.write_bytes(raw); self.path.chmod(0o600)
        ambient = dict(CONTROL_DEVBUS_ENABLED="0", DEVBUS_NATS_TOKEN="synthetic-ambient-token",
                       DEVBUS_NATS_CREDS="/synthetic/never-read.creds")
        if pointer is not None: ambient["CONTROL_DEVBUS_CONFIG"] = str(self.path) if pointer == "exact" else pointer
        with ExitStack() as stack:
            stack.enter_context(patch.object(self.module, "DEVBUS_CONFIG_PATH", self.path))
            stack.enter_context(patch.dict(self.module.os.environ, ambient, clear=True))
            stack.enter_context(patch.object(self.module.os, "geteuid", return_value=uid))
            stack.enter_context(patch.object(self.module.os, "fstat", side_effect=lambda fd: self.synthetic_stat(self.real_fstat(fd))))
            stack.enter_context(patch.object(self.module.os, "stat", side_effect=lambda *a, **k: self.synthetic_stat(self.real_stat(*a, **k))))
            for item in patches: stack.enter_context(item)
            return self.load()

    def disabled(self, result, reason):
        config, actual_reason = result; self.assertFalse(config.enabled); self.assertEqual(actual_reason, reason)
        self.assertNotIn("synthetic-private-token", repr(config)); self.assertNotIn("synthetic-ambient-token", repr(config))

    def test_absent_empty_mismatched_pointer_has_no_file_access(self):
        for pointer, reason in ((None, None), ("", "invalid_config"), ("/not/the/constant", "invalid_config")):
            with self.subTest(pointer=pointer), patch.object(self.module.os, "open", side_effect=AssertionError("Forbidden open")):
                self.disabled(self.invoke(pointer=pointer), reason)

    def test_wrong_effective_uid_before_file_access(self):
        with patch.object(self.module.os, "open", side_effect=AssertionError("Forbidden nonowner open")):
            self.disabled(self.invoke(uid=0), "invalid_config")

    def test_wrong_file_owner_and_nonregular_device_metadata(self):
        self.path.write_bytes(s.canonical(self.mapping)); self.path.chmod(0o600)
        original = self.synthetic_stat(self.real_stat(self.path))
        wrong_owner = SimpleNamespace(**vars(original)); wrong_owner.st_uid = 1001
        device = SimpleNamespace(**vars(original)); device.st_mode = 0o20600
        for metadata in (wrong_owner, device):
            self.disabled(self.invoke(patches=(patch.object(self.module.os, "fstat", return_value=metadata),)), "invalid_config")

    def test_missing_file_disabled_without_error(self): self.disabled(self.invoke(), None)

    def test_valid_file_exact_schema2_obs_mapping_and_bounded_read(self):
        real_open, real_read = os.open, os.read
        opened = []; read_sizes = []
        def record_open(path, flags, *args, **kwargs):
            opened.append((path, flags)); return real_open(path, flags, *args, **kwargs)
        def record_read(fd, size): read_sizes.append(size); return real_read(fd, size)
        result = self.invoke(s.canonical(self.mapping), patches=(
            patch.object(self.module.os, "open", side_effect=record_open),
            patch.object(self.module.os, "read", side_effect=record_read)))
        self.assertTrue(result[0].enabled); self.assertIsNone(result[1])
        self.assertEqual(result[0].url, self.mapping["url"])
        self.assertEqual(result[0].stream, "OBS_EVENTS")
        self.assertEqual(result[0].stream_created, self.mapping["stream_created"])
        self.assertEqual(result[0].user, self.mapping["user"])
        self.assertEqual(result[0].password, self.mapping["password"])
        self.assertEqual(result[0].token, ""); self.assertEqual(result[0].creds, "")
        self.assertTrue(opened); flags = opened[0][1]
        self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
        self.assertTrue(flags & os.O_NOFOLLOW); self.assertTrue(flags & os.O_NONBLOCK)
        self.assertTrue(read_sizes); self.assertTrue(all(size <= 16385 for size in read_sizes))

    def test_strict_json_and_private_auth_keys_rejected(self):
        bad = [b"{", b'{"x":NaN}', b'{"schema":2,"schema":2}',
               b"\xff", s.canonical(self.mapping | {"DEVBUS_NATS_CREDS": "/synthetic/private"}),
               s.canonical(self.mapping | {"extra_jwt": "synthetic"}),
               s.canonical(self.mapping | {"token": "synthetic-origin-token"}),
               s.canonical(self.mapping | {"source": {"token": "synthetic-origin-token"}}),
               s.canonical(self.mapping | {"schema": True}),
               s.canonical(self.mapping | {"password": ""}),
               s.canonical(self.mapping | {"url": "nats://remote.invalid:4222"}),
               s.canonical(self.mapping | {"stream": "DEVBUS_V1"}),
               s.canonical(self.mapping | {"password": "synthetic\x80"}),
               json.dumps(self.mapping | {"password": "bad\ud800"}).encode(),
               s.canonical(self.legacy_token_mapping)]
        for raw in bad:
            with self.subTest(length=len(raw)): self.disabled(self.invoke(raw), "invalid_config")

    def test_disabled_schema2_config_with_valid_obs_endpoint_allowed(self):
        self.disabled(self.invoke(s.canonical(self.mapping | {"enabled": False})), None)

    def test_unsafe_mode_and_hardlink_rejected_without_repair(self):
        self.path.write_bytes(s.canonical(self.mapping)); self.path.chmod(0o644)
        self.disabled(self.invoke(), "invalid_config"); self.assertEqual(self.path.stat().st_mode & 0o777, 0o644)
        self.path.chmod(0o600); other = self.path.with_name("other.json"); os.link(self.path, other)
        self.disabled(self.invoke(), "invalid_config"); self.assertEqual(self.path.stat().st_nlink, 2)

    def test_symlink_fifo_and_overflow_rejected_without_block(self):
        target = self.path.with_name("target.json"); target.write_bytes(s.canonical(self.mapping)); target.chmod(0o600)
        self.path.symlink_to(target); self.disabled(self.invoke(), "invalid_config"); self.assertTrue(self.path.is_symlink())
        self.path.unlink(); os.mkfifo(self.path, 0o600)
        self.disabled(self.invoke(), "invalid_config"); self.path.unlink()
        self.disabled(self.invoke(b" " * 16385), "invalid_config")

    def test_changed_metadata_or_swapped_leaf_rejected(self):
        self.path.write_bytes(s.canonical(self.mapping)); self.path.chmod(0o600)
        original = self.synthetic_stat(self.real_stat(self.path))
        changed = self.synthetic_stat(self.real_stat(self.path)); changed.st_mtime_ns += 1
        self.disabled(self.invoke(patches=(patch.object(self.module.os, "fstat", side_effect=[original, changed]),)), "invalid_config")
        def swapped(*args, **kwargs):
            value = self.synthetic_stat(self.real_stat(*args, **kwargs)); value.st_ino += 1; return value
        self.disabled(self.invoke(patches=(patch.object(self.module.os, "stat", side_effect=swapped),)), "invalid_config")
