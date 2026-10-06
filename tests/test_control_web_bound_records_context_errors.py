"""Black-box RED for nested fullref error precedence in pure record DTOs."""

import importlib.util
import os
import pathlib
import sys
import unittest
from collections import UserDict
from types import MappingProxyType

from test_control_web_bound_session_records import (
    HOST,
    OPERATION,
    SESSION,
    create_parents,
    create_record,
    fullref,
    stop_parents,
    stop_record,
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


class ContextErrorsRed(unittest.TestCase):
    def setUp(self):
        path = pathlib.Path(os.environ.get("BOUND_RECORDS_FAULT_MODULE", str(DEFAULT_MODULE)))
        self.assertTrue(path.is_file(), f"fault target unavailable: {path.name}")
        name = "_control_web_bound_session_records_context_error_target"
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(lambda: sys.modules.pop(name, None))
        spec.loader.exec_module(module)
        self.records = module
        self.ref = fullref()
        self.codec = module.BoundRecordCodec(self.ref)

    def assert_code(self, code, call):
        try:
            value = call()
        except Exception as exc:
            self.assertIsInstance(exc, self.records.BoundRecordError)
            self.assertEqual(exc.code, code)
            self.assertEqual(str(exc), code)
        else:
            self.fail(f"unexpected accepted value: {type(value).__name__}")

    def accepted_origin(self):
        record = create_record()
        return self.records.BoundCreateReceipt(record, "accepted", create_parents(record))

    def test_create_dto_constructors_report_malformed_nested_ref_first(self):
        for nested in (None, 7, [], {"schema": True}, {"provider_id": "codex"}):
            with self.subTest(nested=repr(nested)):
                record = create_record()
                parents = create_parents(record)
                record["context_ref"] = nested
                record["project"] = "invalid.name"
                record["digest"] = "0" * 64
                self.assert_code("context_invalid", lambda: self.records.PreparedBoundCreate(record))
                self.assert_code(
                    "context_invalid",
                    lambda: self.records.BoundCreateReceipt(record, "accepted", parents),
                )

    def test_stop_dto_constructors_report_malformed_nested_ref_first(self):
        origin = self.accepted_origin()
        for nested in (None, 7, [], {"schema": True}, {"provider_id": "codex"}):
            with self.subTest(nested=repr(nested)):
                record = stop_record(origin)
                parents = stop_parents(record)
                record["context_ref"] = nested
                record["host_id"] = "not-a-uuid"
                record["digest"] = "0" * 64
                self.assert_code("context_invalid", lambda: self.records.PreparedBoundStop(record))
                self.assert_code(
                    "context_invalid",
                    lambda: self.records.BoundStopReceipt(record, "accepted", parents),
                )

    def test_codec_reports_valid_foreign_nested_ref_as_context_drift(self):
        foreign = fullref("beta")
        create = create_record(ref=foreign)
        create_dto = self.records.PreparedBoundCreate(create)
        self.assert_code("context_drift", lambda: self.codec.validate_create(
            self.ref, create_dto, project=object(), root=object(),
            session_ref=object(), operation_id=object(),
        ))
        origin = self.accepted_origin()
        stop = stop_record(origin, ref=foreign)
        stop_dto = self.records.PreparedBoundStop(stop)
        self.assert_code("context_drift", lambda: self.codec.validate_stop(
            self.ref, stop_dto, root=object(), session_ref=object(), operation_id=object()
        ))

    def test_missing_nested_ref_key_is_invalid_request(self):
        origin = self.accepted_origin()
        for record, constructor in (
            (create_record(), self.records.PreparedBoundCreate),
            (stop_record(origin), self.records.PreparedBoundStop),
        ):
            with self.subTest(kind=record["kind"]):
                del record["context_ref"]
                record["digest"] = "0" * 64
                self.assert_code("invalid_request", lambda: constructor(record))

    def test_external_nested_proxy_is_context_invalid_without_backing_reads(self):
        origin = self.accepted_origin()
        for record, constructor in (
            (create_record(), self.records.PreparedBoundCreate),
            (stop_record(origin), self.records.PreparedBoundStop),
        ):
            with self.subTest(kind=record["kind"]):
                backing = ReadTrap(fullref())
                record["context_ref"] = MappingProxyType(backing)
                backing.reads = 0
                self.assert_code("context_invalid", lambda: constructor(record))
                self.assertEqual(backing.reads, 0, "foreign nested ref backing was inspected")

    def test_unsupported_outer_record_is_invalid_request_without_reads(self):
        backing = ReadTrap(create_record())
        proxy = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(proxy))
        self.assertEqual(backing.reads, 0)
        backing = ReadTrap(stop_record(self.accepted_origin()))
        proxy = MappingProxyType(backing)
        backing.reads = 0
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundStop(proxy))
        self.assertEqual(backing.reads, 0)

    def test_codec_revalidates_mutated_create_nested_ref_before_expected_identity(self):
        create = self.codec.prepare_create(
            self.ref, "Project_9", "/work/project", SESSION, OPERATION, 123456789
        )
        changed = dict(create.record)
        changed["context_ref"] = None
        changed["project"] = "invalid.name"
        object.__setattr__(create, "record", changed)  # simulated retained alias fault
        self.assert_code(
            "context_invalid",
            lambda: self.codec.validate_create(
                self.ref, create, project=object(), root=object(),
                session_ref=object(), operation_id=object(),
            ),
        )

    def test_codec_revalidates_mutated_stop_nested_ref_before_expected_identity(self):
        origin = self.accepted_origin()
        stop = self.codec.prepare_stop(self.ref, origin, OPERATION, HOST, "d" * 32, 123456790)
        changed = dict(stop.record)
        changed["context_ref"] = None
        changed["host_id"] = "not-a-uuid"
        object.__setattr__(stop, "record", changed)
        self.assert_code(
            "context_invalid",
            lambda: self.codec.validate_stop(
                self.ref, stop, root=object(), session_ref=object(), operation_id=object()
            ),
        )

    def test_top_fullref_precedes_nested_error_without_proxy_reads(self):
        create = self.codec.prepare_create(
            self.ref, "Project_9", "/work/project", SESSION, OPERATION, 123456789
        )
        backing = ReadTrap(fullref())
        changed = dict(create.record)
        changed["context_ref"] = MappingProxyType(backing)
        object.__setattr__(create, "record", changed)
        backing.reads = 0
        self.assert_code(
            "context_invalid",
            lambda: self.codec.validate_create(
                None, create, project=object(), root=object(),
                session_ref=object(), operation_id=object(),
            ),
        )
        self.assertEqual(backing.reads, 0)
        self.assert_code(
            "context_drift",
            lambda: self.codec.validate_create(
                fullref("beta"), create, project=object(), root=object(),
                session_ref=object(), operation_id=object(),
            ),
        )
        self.assertEqual(backing.reads, 0)

    def test_stop_top_fullref_precedes_mutated_nested_error(self):
        origin = self.accepted_origin()
        stop = self.codec.prepare_stop(self.ref, origin, OPERATION, HOST, "d" * 32, 123456790)
        backing = ReadTrap(fullref())
        changed = dict(stop.record)
        changed["context_ref"] = MappingProxyType(backing)
        object.__setattr__(stop, "record", changed)
        backing.reads = 0
        self.assert_code(
            "context_invalid",
            lambda: self.codec.validate_stop(
                None, stop, root=object(), session_ref=object(), operation_id=object()
            ),
        )
        self.assertEqual(backing.reads, 0)
        self.assert_code(
            "context_drift",
            lambda: self.codec.validate_stop(
                fullref("beta"), stop, root=object(),
                session_ref=object(), operation_id=object(),
            ),
        )
        self.assertEqual(backing.reads, 0)


if __name__ == "__main__":
    unittest.main()
