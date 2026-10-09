"""Counter rollover and retained queue bytes on the actual LIVE module."""
import sys
from pathlib import Path
import unittest
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import _control_web_live as live
from live_sse_blind_support import history, SID


class LiveBounds(unittest.TestCase):
    def test_failure_is_one_unavailable_even_after_writer_pops_it(self):
        entry = live.Entry(('demo', SID), '1'*64)
        entry.observe(history())
        subscriber = live.Subscriber(entry)
        subscriber.fail()
        self.assertIn(b'event: unavailable', subscriber.queue.popleft())
        subscriber.fail()
        self.assertEqual(list(subscriber.queue), [])

    def test_rejected_envelope_does_not_mutate_retained_observation(self):
        entry = live.Entry(('demo', SID), '1'*64)
        entry.observe(history())
        before = deepcopy(vars(entry))
        invalid = history('x'*live.WIRE_LIMIT)
        with self.assertRaises(ValueError):
            entry.observe(invalid)
        self.assertEqual(vars(entry), before)

    # INV-WSESS-51/52: the unobservable 2^53 limit needs a source-level unit.
    def test_observation_and_revision_rollover_rotate_epoch_before_wire(self):
        for counter in ('observation', 'revision'):
            with self.subTest(counter=counter):
                entry = live.Entry(('demo', SID), '1' * 64)
                entry.observe(history())
                epoch = entry.epoch
                setattr(entry, counter, live.SAFE_INTEGER)
                entry.observe(history('changed'))
                self.assertNotEqual(entry.epoch, epoch)
                self.assertEqual((entry.value['revision'], entry.value['observation']), (1, 1))
                self.assertLessEqual(len(live.event_frame('snapshot', entry.value,
                    entry.epoch + ':1')), live.WIRE_LIMIT)

    # INV-WSESS-52: queues retain at most two bounded wire frames, including recovery.
    def test_queue_bytes_stay_bounded_through_overflow_and_recovery(self):
        entry = live.Entry(('demo', SID), '1' * 64)
        value = history()
        item = value['turns'][0]['items'][0]
        value['turns'][0]['items'] = [dict(item, id='item-'+str(index), text='é'*3900)
                                    for index in range(12)]
        self.assertTrue(live.history_valid(value))
        entry.observe(value)
        subscriber = live.Subscriber(entry)
        for _ in range(5):
            entry.observe(value)
            subscriber.publish()
            self.assertLessEqual(len(subscriber.queue), 2)
            self.assertLessEqual(sum(map(len, subscriber.queue)), 200 * 1024)
        self.assertTrue(subscriber.closed)  # A second overflow while recovering closes.
        self.assertEqual(len(subscriber.queue), 1)
        self.assertIn(b'event: unavailable', subscriber.queue[0])

    # INV-WSESS-52: age fields alone are volatile, caller-owned DTOs stay intact.
    def test_canonical_hash_does_not_mutate_original_projection(self):
        value = history()
        original = live.encoded(value)
        digest = live.canonical_hash(value)
        self.assertEqual(live.encoded(value), original)
        value['session_settings']['age_ms'] = 123
        value['session_settings']['expires_in_ms'] = 14877
        self.assertEqual(live.canonical_hash(value), digest)
        value['turns'][0]['items'][0]['timestamp'] += 1
        self.assertNotEqual(live.canonical_hash(value), digest)


class LiveAdmissionRaces(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        class Backend:
            def session_live_snapshot(self, *key):
                return {'schema':1, 'scope_id':'1'*64, 'history':history()}
        self.manager = live.Manager(Backend(), None)
        self.manager.running = True
        self.manager.executor = ThreadPoolExecutor(max_workers=1)

    async def asyncTearDown(self):
        await self.manager.stop()

    async def admission(self, key=('demo', SID), check=lambda:None, stream=False):
        task = asyncio.create_task(self.manager.admit(key, check, stream))
        await asyncio.sleep(0)
        return task

    async def test_cancel_after_proof_before_handoff_never_registers_subscriber(self):
        task = await self.admission(stream=True)
        await self.manager.read(('demo', SID), list(self.manager.pending))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        entry = self.manager.entries[('demo', SID)]
        self.assertFalse(entry.subscribers)
        self.assertEqual(entry.due, float('inf'))

    async def test_revoked_request_only_read_does_not_retain_or_extend_entry(self):
        permitted = True
        task = await self.admission(check=lambda:None if permitted else {'error':'unavailable'})
        permitted = False
        await self.manager.read(('demo', SID), list(self.manager.pending))
        self.assertEqual(await task, {'error':'unavailable'})
        self.assertFalse(self.manager.entries)
        task = await self.admission()
        await self.manager.read(('demo', SID), list(self.manager.pending))
        await task
        entry = self.manager.entries[('demo', SID)]
        before = (entry.value, entry.last_success, entry.last_used)
        task = await self.admission(check=lambda:{'error':'unavailable'})
        await self.manager.read(('demo', SID), list(self.manager.pending))
        await task
        self.assertEqual((entry.value, entry.last_success, entry.last_used), before)

    async def test_invalid_new_envelope_does_not_evict_valid_idle_entries(self):
        for index in range(2):
            key=('demo', str(index))
            entry=live.Entry(key, '1'*64)
            entry.observe(history())
            self.manager.entries[key]=entry
        original=dict(self.manager.entries)
        task=await self.admission(('x'*5000, SID))
        await self.manager.read(('x'*5000, SID), list(self.manager.pending))
        self.assertEqual(await task, {'error':'unavailable'})
        self.assertEqual(self.manager.entries, original)

    async def test_expired_request_only_proof_does_not_establish_retained_entry(self):
        original = self.manager.backend.session_live_snapshot
        def late(*key):
            time.sleep(6.1)
            return original(*key)
        self.manager.backend.session_live_snapshot=late
        task=await self.admission()
        await self.manager.read(('demo', SID),list(self.manager.pending))
        self.assertEqual(await task,{'error':'unavailable'})
        self.assertFalse(self.manager.entries)

    async def test_check_exception_resolves_row_and_scheduler_keeps_reading(self):
        def broken():
            raise RuntimeError('Synthetic admission check failure')
        task=await self.admission(check=broken)
        self.manager.scheduler=asyncio.create_task(self.manager.schedule())
        self.assertEqual(await asyncio.wait_for(task, 1), {'error':'unavailable'})
        task=await self.admission()
        result=await asyncio.wait_for(task, 2)
        self.assertEqual(result['schema'], 1)
        self.assertFalse(self.manager.scheduler.done())
