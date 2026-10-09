"""Counter rollover and retained queue bytes on the actual LIVE module."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'bin'))
import _control_web_live as live
from live_sse_blind_support import history, SID


class LiveBounds(unittest.TestCase):
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
