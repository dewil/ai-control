"""INV-WSESS-53 migration of historical synthetic sources to actual SSE."""
from copy import deepcopy
import hashlib
import json
import uuid


def replay_path(evidence):
    # Synthetic private state only. No runtime/user authentication files.
    evidence.chmod(0o700)
    path = evidence / 'live-replay.json'
    path.write_text(json.dumps({'last_step': -1}))
    path.chmod(0o600)
    return str(path)


class LiveHistoryFixture:
    """Public backend seam; the real app owns admission/scheduling/streaming."""
    def session_live_snapshot(self, project, sid):
        value = deepcopy(self.session_history(project, sid, None))
        if 'error' in value:
            return {'error': 'unavailable'}
        remaining = 24
        turns = []
        for turn in value.get('turns', []):
            items = turn['items'][-remaining:] if remaining else []
            if items:
                turns.append(dict(turn, items=items))
                remaining -= len(items)
            if not remaining:
                break
        value['turns'] = turns
        for turn in turns:
            for item in turn['items']:
                item.setdefault('timestamp', None)
                item.setdefault('time_precision', 'unknown')
                if 'client_id' in item:
                    try:
                        valid = str(uuid.UUID(item['client_id'])) == item['client_id']
                    except (ValueError, TypeError, AttributeError):
                        valid = False
                    # The existing native producer exports only valid user UUIDs.
                    if item['role'] != 'user' or not valid:
                        item.pop('client_id')
        value['recent_sends'] = [row for row in value['recent_sends']
                                if row['status'] in ('accepted', 'delivery_unknown', 'rejected')]
        evidence = self._live_evidence
        with (evidence/'live-observations.jsonl').open('a') as stream:
            stream.write(json.dumps({'sid':sid,'recent_ids':[row['message_id'] for row in value['recent_sends']]})+'\n')
        scope = hashlib.sha256((project+'|'+sid).encode()).hexdigest()
        return {'schema': 1, 'scope_id': scope, 'history': value}
