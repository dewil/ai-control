"""Blind RED for pure bound-session record and DTO validation."""

import hashlib
import importlib
import json
import pathlib
import socket
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "bin" / "_control_web_bound_session_records.py"
SESSION = "123e4567-e89b-42d3-a456-426614174000"
OPERATION = "123e4567-e89b-42d3-a456-426614174001"
HOST = "123e4567-e89b-42d3-a456-426614174002"
INSTANCE = "123e4567-e89b-42d3-a456-426614174003"


def fullref(account="alpha"):
    return {
        "schema": 2,
        "provider_id": "codex",
        "account_id": account,
        "profile_instance_id": INSTANCE,
        "adapter_revision": "codex-chatgpt-external-auth-host-v2",
        "registration_snapshot": {
            "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "a" * 64,
        },
    }


def canonical(value):
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def create_record(ref=None, project="Project_9", root="/work/project", session=SESSION, op=OPERATION):
    record = {
        "schema": 1,
        "kind": "bound_session_create",
        "context_ref": fullref() if ref is None else ref,
        "project": project,
        "root": root,
        "session_ref": session,
        "operation_id": op,
        "created": 123456789,
    }
    record["digest"] = digest(record)
    return record


def commitment(filename):
    return {"filename": filename, "dev": 1, "ino": 2, "ctime_ns": 3, "sha256": "b" * 64}


def create_parents(record):
    key = digest({key: record[key] for key in ("context_ref", "project", "root", "operation_id")})
    session = record["session_ref"]
    return {
        "R": commitment(f"BC-{key}.R.json"),
        "G": commitment(f"BG-S-{session}.json"),
        "C": commitment(f"BC-{key}.C.json"),
        "I_session": commitment(f"BI-S-{session}.json"),
        "I_native": commitment(f"BI-N-{'c' * 64}.json"),
        "A": commitment(f"BC-{key}.A.json"),
    }


def stop_record(origin, ref=None, op=OPERATION):
    record = {
        "schema": 1,
        "kind": "bound_session_stop",
        "context_ref": fullref() if ref is None else ref,
        "root": origin.record["root"],
        "session_ref": origin.record["session_ref"],
        "operation_id": op,
        "created": 123456790,
        "host_id": HOST,
        "invocation_id": "d" * 32,
        "origin_parent": origin.parents["A"],
    }
    record["digest"] = digest(record)
    return record


def stop_parents(record):
    key = digest({key: record[key] for key in ("context_ref", "root", "session_ref", "operation_id")})
    return {"S": commitment(f"BS-{key}.S.json"), "T": commitment(f"BS-{key}.T.json")}


class BoundRecordsContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE.is_file(), f"contract module unavailable: {MODULE.name}")
        sys.path.insert(0, str(MODULE.parent))
        self.addCleanup(lambda: sys.path.remove(str(MODULE.parent)))
        self.records = importlib.import_module("_control_web_bound_session_records")
        self.ref = fullref()
        self.codec = self.records.BoundRecordCodec(self.ref)

    def assert_code(self, code, call):
        try:
            result = call()
        except Exception as exc:
            self.assertIsInstance(exc, self.records.BoundRecordError)
            self.assertEqual(exc.code, code)
            self.assertEqual(str(exc), code)
            self.assertNotIn("fixture-marker", repr(exc))
        else:
            self.fail(f"unexpected success: {type(result).__name__}")

    def prepared(self, **changes):
        args = dict(
            context_ref=self.ref, project="Project_9", root="/work/project",
            session_ref=SESSION, operation_id=OPERATION, created_ns=123456789,
        )
        args.update(changes)
        return self.codec.prepare_create(**args)

    def accepted_origin(self):
        record = create_record()
        return self.records.BoundCreateReceipt(record, "accepted", create_parents(record))

    def test_error_codes_are_closed_and_secret_free(self):
        error = self.records.BoundRecordError("fixture-marker")
        self.assertEqual(error.code, "invalid_request")
        self.assertEqual(str(error), "invalid_request")
        self.assertNotIn("fixture-marker", repr(error))

    def test_fullref_exact_schema_and_constructor_copy(self):
        original = fullref()
        codec = self.records.BoundRecordCodec(original)
        original["registration_snapshot"]["sha256"] = "f" * 64
        prepared = codec.prepare_create(fullref(), "Project_9", "/work/project", SESSION, OPERATION, 7)
        self.assertEqual(prepared.record["context_ref"]["registration_snapshot"]["sha256"], "a" * 64)
        malformed = []
        for key, value in (("schema", True), ("provider_id", "other"), ("account_id", "Bad"),
                           ("profile_instance_id", SESSION.upper()), ("adapter_revision", "old")):
            ref = fullref()
            ref[key] = value
            malformed.append(ref)
        for key, value in (("dev", True), ("ino", 0), ("ctime_ns", -1), ("sha256", "a" * 63)):
            ref = fullref()
            ref["registration_snapshot"][key] = value
            malformed.append(ref)
        ref = fullref()
        ref["extra"] = 1
        malformed.append(ref)
        for ref in malformed:
            with self.subTest(ref=ref):
                self.assert_code("context_invalid", lambda: self.records.BoundRecordCodec(ref))

    def test_fullref_first_precedence_even_with_hostile_later_inputs(self):
        foreign = fullref("beta")
        self.assert_code(
            "context_drift",
            lambda: self.codec.prepare_create(foreign, object(), object(), object(), object(), object()),
        )
        bad = fullref()
        bad["schema"] = True
        self.assert_code(
            "context_invalid",
            lambda: self.codec.validate_create(
                bad, object(), project=object(), root=object(), session_ref=object(), operation_id=object()
            ),
        )

    def test_nested_foreign_reference_precedes_expected_identity_validation(self):
        foreign_codec = self.records.BoundRecordCodec(fullref("beta"))
        foreign = foreign_codec.prepare_create(fullref("beta"), "Project_9", "/work/project", SESSION, OPERATION, 7)
        self.assert_code(
            "context_drift",
            lambda: self.codec.validate_create(
                self.ref, foreign, project=object(), root=object(), session_ref=object(), operation_id=object()
            ),
        )

    def test_prepare_create_digest_is_exact_and_revalidated(self):
        prepared = self.prepared()
        record = dict(prepared.record)
        received = record.pop("digest")
        self.assertEqual(received, digest(record))
        self.assertEqual(set(prepared.record), set(record) | {"digest"})
        changed = dict(prepared.record)
        changed["digest"] = "0" * 64
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(changed))
        changed = dict(prepared.record)
        changed["unexpected"] = 1
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(changed))

    def test_valid_configured_project_names_are_preserved(self):
        for project in ("Project_9", "9start", "_leading", "A" * 32):
            with self.subTest(project=project):
                prepared = self.prepared(project=project)
                self.assertEqual(prepared.record["project"], project)
        for project in ("", "A" * 33, "name.dot", "path/name"):
            with self.subTest(project=project):
                self.assert_code("invalid_request", lambda: self.prepared(project=project))

    def test_root_validation_is_lexical_and_does_no_filesystem_lookup(self):
        for root in ("/", "/work/project", "/ümlaut"):
            with self.subTest(root=root):
                self.assertEqual(self.prepared(root=root).record["root"], root)
        bad_roots = ("relative", "//work", "/a//b", "/a/", "/a/./b", "/a/../b",
                     "/a\x00b", "/a\x85b", "/a\ud800", "/" + "a" * 4096)
        for root in bad_roots:
            with self.subTest(root=repr(root)[:50]):
                self.assert_code("invalid_request", lambda: self.prepared(root=root))

    def test_uuid_clock_and_plain_numeric_limits(self):
        for field, value in (("session_ref", SESSION.upper()), ("session_ref", "not-uuid"),
                             ("operation_id", "123e4567-e89b-12d3-a456-426614174000"),
                             ("created_ns", True), ("created_ns", 0),
                             ("created_ns", 2 ** 63)):
            with self.subTest(field=field, value=value):
                self.assert_code("invalid_request", lambda: self.prepared(**{field: value}))
        self.assertEqual(self.prepared(created_ns=2 ** 63 - 1).record["created"], 2 ** 63 - 1)

    def test_record_encoding_cap_applies_below_root_byte_cap(self):
        large_root = "/" + "a" * 3500
        self.assertLess(len(large_root.encode("utf-8")), 4096)
        self.assertGreater(len(canonical(create_record(root=large_root))), 4096)
        self.assert_code("invalid_request", lambda: self.prepared(root=large_root))

    def test_dto_deep_freezes_and_codec_returns_independent_capture(self):
        record = create_record()
        prepared = self.records.PreparedBoundCreate(record)
        record["context_ref"]["account_id"] = "beta"
        record["project"] = "Other"
        self.assertEqual(prepared.record["context_ref"]["account_id"], "alpha")
        self.assertEqual(prepared.record["project"], "Project_9")
        with self.assertRaises((TypeError, AttributeError)):
            prepared.record["project"] = "Other"
        with self.assertRaises((TypeError, AttributeError)):
            prepared.record = {}
        copy_value = self.codec.validate_create(
            self.ref, prepared, project="Project_9", root="/work/project",
            session_ref=SESSION, operation_id=OPERATION,
        )
        self.assertIsNot(copy_value, prepared)
        self.assertEqual(copy_value.record["project"], "Project_9")
        self.assertNotIn("Project_9", repr(prepared))

    def test_hostile_plain_values_and_keys_return_closed_errors(self):
        class Hostile:
            def __eq__(self, other):
                raise RuntimeError("fixture-marker")

            def __hash__(self):
                return 0

        record = create_record()
        record["project"] = Hostile()
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(record))
        record = create_record()
        record[Hostile()] = 1
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundCreate(record))
        ref = fullref()
        ref["provider_id"] = Hostile()
        self.assert_code("context_invalid", lambda: self.records.BoundRecordCodec(ref))

    def test_receipt_unknown_parent_stages_and_diagnostic_r_only(self):
        record = create_record()
        all_parents = create_parents(record)
        parents = {key: None for key in all_parents}
        parents["R"] = all_parents["R"]
        r_only = self.records.BoundCreateReceipt(record, "unknown", parents)
        self.assertIsNone(r_only.parents["G"])
        self.codec.validate_create(
            self.ref, r_only, project="Project_9", root="/work/project",
            session_ref=SESSION, operation_id=OPERATION,
        )
        invalid = dict(parents)
        invalid["C"] = all_parents["C"]
        self.assert_code("invalid_request", lambda: self.records.BoundCreateReceipt(record, "unknown", invalid))
        valid = dict(parents)
        valid["G"] = all_parents["G"]
        valid["C"] = all_parents["C"]
        valid["I_session"] = all_parents["I_session"]
        self.records.BoundCreateReceipt(record, "unknown", valid)
        invalid = dict(valid)
        invalid["A"] = all_parents["A"]
        self.assert_code("invalid_request", lambda: self.records.BoundCreateReceipt(record, "unknown", invalid))

    def test_receipt_copies_nested_parent_inputs(self):
        record = create_record()
        parents = create_parents(record)
        receipt = self.records.BoundCreateReceipt(record, "accepted", parents)
        parents["R"]["sha256"] = "f" * 64
        parents["G"] = None
        self.assertEqual(receipt.parents["R"]["sha256"], "b" * 64)
        self.assertIsNotNone(receipt.parents["G"])
        with self.assertRaises((TypeError, AttributeError)):
            receipt.parents["R"]["sha256"] = "f" * 64
        copy_value = self.codec.validate_create(
            self.ref, receipt, project="Project_9", root="/work/project",
            session_ref=SESSION, operation_id=OPERATION,
        )
        self.assertIsNot(copy_value, receipt)
        self.assertIsNot(copy_value.parents, receipt.parents)

    def test_accepted_receipt_is_only_syntactic_and_requires_six_parents(self):
        record = create_record()
        parents = create_parents(record)
        receipt = self.records.BoundCreateReceipt(record, "accepted", parents)
        self.assertEqual(set(receipt.parents), {"R", "G", "C", "I_session", "I_native", "A"})
        self.codec.validate_create(
            self.ref, receipt, project="Project_9", root="/work/project",
            session_ref=SESSION, operation_id=OPERATION,
        )
        missing = dict(parents)
        missing["I_native"] = None
        self.assert_code("invalid_request", lambda: self.records.BoundCreateReceipt(record, "accepted", missing))

    def test_role_filenames_are_exact_case_sensitive_and_basenames(self):
        record = create_record()
        parents = create_parents(record)
        for role, filename in (("R", parents["R"]["filename"].replace(".R.json", ".r.json")),
                               ("G", "../" + parents["G"]["filename"]),
                               ("I_session", parents["I_session"]["filename"].replace("BI-S-", "bi-s-")),
                               ("I_native", "BI-N-" + "D" * 64 + ".json")):
            with self.subTest(role=role):
                changed = {key: dict(value) for key, value in parents.items()}
                changed[role]["filename"] = filename
                self.assert_code("invalid_request", lambda: self.records.BoundCreateReceipt(record, "accepted", changed))

    def test_commitment_types_and_digest_are_exact(self):
        record = create_record()
        parents = create_parents(record)
        for field, value in (("dev", True), ("ino", 0), ("ctime_ns", 0),
                             ("sha256", "B" * 64), ("extra", 1)):
            with self.subTest(field=field):
                changed = {key: dict(item) for key, item in parents.items()}
                changed["R"][field] = value
                self.assert_code("invalid_request", lambda: self.records.BoundCreateReceipt(record, "accepted", changed))

    def test_validate_create_checks_expected_operation_identity(self):
        prepared = self.prepared()
        expected = dict(project="Project_9", root="/work/project", session_ref=SESSION, operation_id=OPERATION)
        for field, value in (("project", "Other"), ("root", "/other"),
                             ("session_ref", HOST), ("operation_id", HOST)):
            with self.subTest(field=field):
                changed = dict(expected)
                changed[field] = value
                self.assert_code("invalid_request", lambda: self.codec.validate_create(self.ref, prepared, **changed))

    def test_prepare_stop_links_syntactic_accepted_origin_and_exact_digest(self):
        origin = self.accepted_origin()
        prepared = self.codec.prepare_stop(self.ref, origin, OPERATION, HOST, "d" * 32, 123456790)
        self.assertIsInstance(prepared, self.records.PreparedBoundStop)
        self.assertEqual(prepared.record["origin_parent"], origin.parents["A"])
        record = dict(prepared.record)
        expected = record.pop("digest")
        self.assertEqual(expected, digest(record))
        self.assertEqual(prepared.record["root"], origin.record["root"])
        self.assertEqual(prepared.record["session_ref"], origin.record["session_ref"])

    def test_prepare_stop_rejects_unknown_or_foreign_origin(self):
        record = create_record()
        parents = create_parents(record)
        parents["A"] = None
        unknown = self.records.BoundCreateReceipt(record, "unknown", parents)
        self.assert_code(
            "invalid_request",
            lambda: self.codec.prepare_stop(self.ref, unknown, OPERATION, HOST, "d" * 32, 123456790),
        )
        foreign_record = create_record(ref=fullref("beta"))
        foreign = self.records.BoundCreateReceipt(foreign_record, "accepted", create_parents(foreign_record))
        self.assert_code(
            "context_drift",
            lambda: self.codec.prepare_stop(self.ref, foreign, OPERATION, HOST, "d" * 32, 123456790),
        )

    def test_stop_record_and_parent_stage_validation(self):
        origin = self.accepted_origin()
        record = stop_record(origin)
        parents = stop_parents(record)
        self.records.PreparedBoundStop(record)
        self.records.BoundStopReceipt(record, "accepted", parents)
        unknown = dict(parents)
        unknown["T"] = None
        self.records.BoundStopReceipt(record, "unknown", unknown)
        self.assert_code("invalid_request", lambda: self.records.BoundStopReceipt(record, "unknown", parents))
        self.assert_code("invalid_request", lambda: self.records.BoundStopReceipt(record, "accepted", unknown))
        bad_role = {key: dict(value) for key, value in parents.items()}
        bad_role["T"]["filename"] = bad_role["T"]["filename"].replace(".T.json", ".t.json")
        self.assert_code("invalid_request", lambda: self.records.BoundStopReceipt(record, "accepted", bad_role))
        changed = dict(record)
        changed["digest"] = "0" * 64
        self.assert_code("invalid_request", lambda: self.records.PreparedBoundStop(changed))

    def test_stop_inputs_uuid_invocation_and_expected_identity(self):
        origin = self.accepted_origin()
        for field, value in (("operation_id", OPERATION.upper()), ("host_id", HOST.upper()),
                             ("invocation_id", "D" * 32), ("invocation_id", "d" * 31),
                             ("created_ns", True), ("created_ns", 0)):
            with self.subTest(field=field):
                args = dict(context_ref=self.ref, origin=origin, operation_id=OPERATION,
                            host_id=HOST, invocation_id="d" * 32, created_ns=123456790)
                args[field] = value
                self.assert_code("invalid_request", lambda: self.codec.prepare_stop(**args))
        prepared = self.codec.prepare_stop(self.ref, origin, OPERATION, HOST, "d" * 32, 123456790)
        self.assert_code("invalid_request", lambda: self.codec.validate_stop(
            self.ref, prepared, root="/other", session_ref=SESSION, operation_id=OPERATION
        ))

    def test_pure_preparation_uses_no_clock_files_or_network(self):
        origin = self.accepted_origin()
        with mock.patch("builtins.open", side_effect=AssertionError("unexpected file IO")), \
             mock.patch("time.time_ns", side_effect=AssertionError("unexpected clock")), \
             mock.patch("time.monotonic", side_effect=AssertionError("unexpected clock")), \
             mock.patch.object(socket, "socket", side_effect=AssertionError("unexpected network")):
            prepared = self.prepared()
            self.codec.prepare_stop(self.ref, origin, OPERATION, HOST, "d" * 32, 123456790)
            self.codec.validate_create(
                self.ref, prepared, project="Project_9", root="/work/project",
                session_ref=SESSION, operation_id=OPERATION,
            )


if __name__ == "__main__":
    unittest.main()
