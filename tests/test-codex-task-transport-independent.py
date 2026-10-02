"""Independent contract tests derived solely from the transport specification."""
import asyncio
import copy
import importlib
import json
from pathlib import Path
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
CodexTaskTransport = importlib.import_module("_codex_task_transport").CodexTaskTransport

SECRET = "PRIVATE_FRAME_CONTENT_DO_NOT_EXPOSE"


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.frames = []
        self.close_count = 0
        self.stall_send = False
        self.stall_recv = False
        self.send_error = False
        self.on_request = None

    async def send(self, frame):
        if self.stall_send:
            await asyncio.Event().wait()
        if self.send_error:
            raise OSError(SECRET)
        message = json.loads(frame)
        self.sent.append(message)
        if message.get("method") == "initialize":
            self.frames.append(json.dumps({"id": message["id"], "result": {}}))
        elif "id" in message and self.on_request:
            self.on_request(message, self)

    async def recv(self):
        if self.stall_recv or not self.frames:
            await asyncio.Event().wait()
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    async def close(self):
        self.close_count += 1


class FakeConnector:
    def __init__(self, socket, *, stall=False):
        self.socket = socket
        self.calls = 0
        self.stall = stall

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        if self.stall:
            await asyncio.Event().wait()
        return self.socket


def response(message, socket):
    socket.frames.append(json.dumps({"id": message["id"], "result": {"ok": True}}))


class TransportContract(unittest.TestCase):
    def make_transport(self, **kwargs):
        socket = FakeSocket()
        connector = FakeConnector(socket)
        transport = CodexTaskTransport("/offline/test.sock", deadline=time.monotonic() + 1,
                                       connector=connector, **kwargs)
        self.addCleanup(transport.close)
        socket.on_request = response
        return transport, socket, connector

    def assert_safe_failure(self, action):
        with self.assertRaises(Exception) as caught:
            action()
        self.assertNotIn(SECRET, str(caught.exception))

    def test_handshake_and_exact_parameters(self):
        transport, socket, connector = self.make_transport()
        self.assertEqual([m["method"] for m in socket.sent], ["initialize", "initialized"])
        def contains_experimental(value):
            if isinstance(value, dict):
                return value.get("experimentalApi") is True or any(contains_experimental(v) for v in value.values())
            return False
        self.assertTrue(contains_experimental(socket.sent[0].get("params")))
        params = {"threadId": "t", "input": [{"type": "text", "text": SECRET}], "nested": {"x": [1]}}
        original = copy.deepcopy(params)
        for method in ("thread/read", "turn/start", "turn/interrupt"):
            self.assertEqual(transport.call(method, params, deadline=time.monotonic() + 1), {"ok": True})
            self.assertEqual(socket.sent[-1]["params"], original)
            self.assertEqual(params, original)
        self.assertEqual(connector.calls, 1)

    def test_fifo_preserves_unknown_approvals_and_foreign_threads(self):
        transport, socket, _ = self.make_transport()
        events = [
            {"id": "approval-unknown", "method": "unknown/approval", "params": {"threadId": "foreign"}},
            {"method": "turn/completed", "params": {"threadId": "ours"}},
        ]
        def enqueue(message, ws):
            ws.frames.extend(json.dumps(e) for e in events)
            ws.frames.append(json.dumps({"id": "unrelated", "result": {"wrong": True}}))
            response(message, ws)
        socket.on_request = enqueue
        self.assertEqual(transport.call("turn/start", {}, deadline=time.monotonic() + 1), {"ok": True})
        for event in events:
            self.assertEqual(transport.receive(deadline=time.monotonic() + 1), event)
        self.assertEqual(len(socket.sent), 3, "Server requests must receive no automatic reply")

    def test_receive_skips_unrelated_response(self):
        transport, socket, _ = self.make_transport()
        event = {"method": "turn/completed", "params": {}}
        socket.frames.extend([json.dumps({"id": "late", "result": {}}), json.dumps(event)])
        self.assertEqual(transport.receive(deadline=time.monotonic() + 1), event)

    def test_invalid_deadlines_and_methods_send_nothing(self):
        for deadline in (0, float("nan"), float("inf"), -float("inf"), None, "tomorrow"):
            with self.subTest(deadline=deadline):
                transport, socket, _ = self.make_transport()
                before = len(socket.sent)
                self.assert_safe_failure(lambda: transport.call("turn/start", {}, deadline=deadline))
                self.assertEqual(len(socket.sent), before)
        for method in ("thread/start", "initialize", "initialized", "turn/approve", "unknown"):
            with self.subTest(method=method):
                transport, socket, _ = self.make_transport()
                before = len(socket.sent)
                self.assert_safe_failure(lambda: transport.call(method, {}, deadline=time.monotonic() + 1))
                self.assertEqual(len(socket.sent), before)

    def test_constructor_rejects_expired_deadline_before_send(self):
        socket = FakeSocket()
        connector = FakeConnector(socket)
        self.assert_safe_failure(lambda: CodexTaskTransport("/offline/test.sock", deadline=0, connector=connector))
        self.assertEqual(socket.sent, [])

    def test_connect_deadline(self):
        connector = FakeConnector(FakeSocket(), stall=True)
        start = time.monotonic()
        self.assert_safe_failure(lambda: CodexTaskTransport("/offline/test.sock", deadline=start + .04, connector=connector))
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(connector.calls, 1)

    def test_operation_deadlines_are_independent(self):
        socket = FakeSocket()
        connector = FakeConnector(socket)
        transport = CodexTaskTransport("/offline/test.sock", deadline=time.monotonic() + .04,
                                       connector=connector)
        self.addCleanup(transport.close)
        socket.on_request = response
        time.sleep(.05)  # Constructor's deadline is now in the past.
        for _ in range(2):
            self.assertEqual(transport.call("thread/read", {}, deadline=time.monotonic() + 1), {"ok": True})
        self.assertEqual(len(socket.sent), 4)

    def test_send_and_receive_timeouts_close_without_retry(self):
        for operation in ("send", "recv", "receive"):
            with self.subTest(operation=operation):
                transport, socket, connector = self.make_transport()
                if operation == "send":
                    socket.stall_send = True
                else:
                    socket.stall_recv = True
                start = time.monotonic()
                if operation == "receive":
                    action = lambda: transport.receive(deadline=start + .04)
                else:
                    action = lambda: transport.call("turn/start", {}, deadline=start + .04)
                self.assert_safe_failure(action)
                self.assertLess(time.monotonic() - start, .5)
                self.assertGreaterEqual(socket.close_count, 1)
                self.assertEqual(connector.calls, 1)
                self.assertLessEqual(len(socket.sent), 3)

    def test_errors_close_and_discard_buffered_events(self):
        bad_frames = [
            SECRET,
            json.dumps([SECRET]),
            json.dumps({"id": "SELF", "result": [SECRET]}),
            json.dumps({"id": "SELF", "error": {"code": -1, "message": SECRET}}),
            json.dumps({"unexpected": SECRET}),
            OSError(SECRET),
        ]
        for frame in bad_frames:
            with self.subTest(frame_type=type(frame).__name__):
                transport, socket, connector = self.make_transport()
                def enqueue(message, ws):
                    ws.frames.append(json.dumps({"method": "event/before-failure", "params": {}}))
                    ws.frames.append(frame.replace('"SELF"', json.dumps(message["id"])) if isinstance(frame, str) else frame)
                socket.on_request = enqueue
                self.assert_safe_failure(lambda: transport.call("turn/start", {}, deadline=time.monotonic() + 1))
                self.assertGreaterEqual(socket.close_count, 1)
                before = len(socket.sent)
                self.assert_safe_failure(lambda: transport.receive(deadline=time.monotonic() + 1))
                self.assert_safe_failure(lambda: transport.call("turn/start", {}, deadline=time.monotonic() + 1))
                self.assertEqual(len(socket.sent), before)
                self.assertEqual(connector.calls, 1)

    def test_queue_overflow_closes_and_invalidates_events(self):
        transport, socket, connector = self.make_transport(max_events=1)
        def enqueue(message, ws):
            ws.frames.extend(json.dumps({"method": "approval/unknown", "params": {"text": SECRET}}) for _ in range(2))
            response(message, ws)
        socket.on_request = enqueue
        self.assert_safe_failure(lambda: transport.call("turn/start", {}, deadline=time.monotonic() + 1))
        self.assert_safe_failure(lambda: transport.receive(deadline=time.monotonic() + 1))
        self.assertGreaterEqual(socket.close_count, 1)
        self.assertEqual(connector.calls, 1)
        self.assertEqual(len(socket.sent), 3)

    def test_send_failure_closes_without_retry(self):
        transport, socket, connector = self.make_transport()
        socket.send_error = True
        self.assert_safe_failure(lambda: transport.call("turn/start", {"text": SECRET}, deadline=time.monotonic() + 1))
        self.assertGreaterEqual(socket.close_count, 1)
        self.assertEqual(connector.calls, 1)
        self.assertEqual(len(socket.sent), 2)

    def test_close_is_idempotent_and_prevents_operations(self):
        transport, socket, _ = self.make_transport()
        transport.close()
        count = socket.close_count
        self.assertGreaterEqual(count, 1)
        transport.close()
        self.assertEqual(socket.close_count, count)
        self.assert_safe_failure(lambda: transport.call("thread/read", {}, deadline=time.monotonic() + 1))
        self.assert_safe_failure(lambda: transport.receive(deadline=time.monotonic() + 1))
        self.assertEqual(len(socket.sent), 2)


if __name__ == "__main__":
    unittest.main()
