"""Black-box fault RED for foreign proxies and single record capture."""

import importlib.util
import os
import pathlib
import sys
import unittest
from collections import UserDict
from types import MappingProxyType

from test_control_web_bound_session_records import (
    OPERATION,
    SESSION,
    create_parents,
    create_record,
    fullref,
)


DEFAULT_MODULE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "bin"
    / "_control_web_bound_session_records.py"
)


class ReadTrap(UserDict):
    def __init__(self, data):
        super().__init__(data)
        self.reads = 0

    def __getitem__(self, key):
        self.reads += 1
        return super().__getitem__(key)

    def __iter__(self):
        self.reads += 1
        return super().__iter__()

    def __len__(self):
        self.reads += 1
        return super().__len__()


class SwitchingBacking(ReadTrap):
    def __init__(self, data, field, first, later):
        super().__init__(data)
        self.field = field
        self.first = first
        self.later = later
        self.field_reads = 0

    def __getitem__(self, key):
        if key == self.field:
            self.reads += 1
            self.field_reads += 1
            return self.first if self.field_reads == 1 else self.later
        return super().__getitem__(key)


class ProxyFaultContract(unittest.TestCase):
    def setUp(self):
        path = pathlib.Path(os.environ.get("BOUND_RECORDS_FAULT_MODULE", str(DEFAULT_MODULE)))
        self.assertTrue(path.is_file(), f"fault target unavailable: {path.name}")
        name = "_control_web_bound_session_records_proxy_fault_target"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(lambda: sys.modules.pop(name, None))
        spec.loader.exec_module(module)
        self.records = module
        self.ref = fullref()

    def assert_code(self, code, call):
        try:
            result = call()
        except Exception as exc:
            self.assertIsInstance(exc, self.records.BoundRecordError)
            self.assertEqual(exc.code, code)
            self.assertEqual(str(exc), code)
        else:
            self.fail(f"foreign mapping unexpectedly accepted: {type(result).__name__}")

    def test_external_proxy_plain_dict_is_rejected(self):
        proxy = MappingProxyType(fullref())
        self.assert_code("context_invalid", lambda: self.records.BoundRecordCodec(proxy))
        record = create_record()
        self.assert_code(
            "invalid_request",
            lambda: self.records.PreparedBoundCreate(MappingProxyType(record)),
        )

    def test_external_proxy_rejects_before_any_backing_read(self):
        backing = ReadTrap(fullref())
        proxy = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code("context_invalid", lambda: self.records.BoundRecordCodec(proxy))
        self.assertEqual(backing.reads, 0, "foreign reference backing was read")

        record_backing = ReadTrap(create_record())
        record_proxy = MappingProxyType(record_backing)
        record_backing.reads = 0
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(record_proxy))
        self.assertEqual(record_backing.reads, 0, "foreign record backing was read")

    def test_direct_userdict_is_rejected_before_backing_reads(self):
        backing = ReadTrap(fullref())
        backing.reads = 0
        self.assert_code("context_invalid", lambda: self.records.BoundRecordCodec(backing))
        self.assertEqual(backing.reads, 0)
        record_backing = ReadTrap(create_record())
        record_backing.reads = 0
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(record_backing))
        self.assertEqual(record_backing.reads, 0)

    def test_switching_a_filename_cannot_enter_accepted_receipt(self):
        record = create_record()
        parents = create_parents(record)
        valid_filename = parents["A"]["filename"]
        backing = SwitchingBacking(parents["A"], "filename", valid_filename, "outside.json")
        parents["A"] = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code(
            "invalid_request",
            lambda: self.records.BoundCreateReceipt(record, "accepted", parents),
        )
        self.assertEqual(backing.reads, 0, "foreign A commitment was read before rejection")

    def test_switching_project_and_digest_cannot_bypass_record_capture(self):
        invalid = create_record(project="invalid.name")
        backing = SwitchingBacking(invalid, "project", "invalid.name", "Project_9")
        proxy = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(proxy))
        self.assertEqual(backing.reads, 0, "switching record was read before rejection")

    def test_nested_foreign_proxy_rejects_without_backing_reads(self):
        record = create_record()
        backing = ReadTrap(fullref())
        record["context_ref"] = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(record))
        self.assertEqual(backing.reads, 0, "nested foreign reference backing was read")

    def test_fullref_precedence_survives_malformed_nested_data(self):
        codec = self.records.BoundRecordCodec(self.ref)
        backing = ReadTrap(create_record())
        proxy = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code(
            "context_drift",
            lambda: codec.validate_create(
                fullref("beta"), proxy, project=object(), root=object(),
                session_ref=object(), operation_id=object(),
            ),
        )
        self.assertEqual(backing.reads, 0, "foreign record was read before fullref check")
        malformed = fullref()
        malformed["schema"] = True
        self.assert_code(
            "context_invalid",
            lambda: codec.validate_create(
                malformed, proxy, project=object(), root=object(),
                session_ref=object(), operation_id=object(),
            ),
        )
        self.assertEqual(backing.reads, 0, "foreign record was read before malformed fullref")

    def test_module_owned_frozen_dto_still_replays_through_codec(self):
        codec = self.records.BoundRecordCodec(self.ref)
        prepared = codec.prepare_create(
            self.ref, "Project_9", "/work/project", SESSION, OPERATION, 123456789
        )
        replay = codec.validate_create(
            self.ref, prepared, project="Project_9", root="/work/project",
            session_ref=SESSION, operation_id=OPERATION,
        )
        self.assertIsInstance(replay, self.records.PreparedBoundCreate)
        self.assertIsNot(replay, prepared)
        self.assertEqual(replay.record["project"], "Project_9")


if __name__ == "__main__":
    unittest.main()
