"""Only synthetic public HTTP DTOs for INV-USN; no native/provider IO."""
from copy import deepcopy
import hashlib
import importlib
import os
from pathlib import Path
import sys

import live_sse_blind_support as live
import participation_blind_support as part
import pinned_activity_blind_support as pins
from test_control_web_navigation_start_browser_blind import NavigationBackend

ROOT = Path(os.environ.get('CONTROL_USN_QA_REPO', Path(__file__).resolve().parents[1])).resolve()
NOW = pins.NOW
B = '88888888-8888-4888-8888-888888888888'
C = '99999999-9999-4999-8999-999999999999'
NEW = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
PIN_A = '22222222-2222-4222-8222-222222222222'
PIN_C = '33333333-3333-4333-8333-333333333333'
A_TITLE = 'Navigator question A'
READY_TITLE = 'Navigator ready B'
WORK_TITLE = 'Navigator working C'
C_TITLE = 'Navigator pinned Charlie'
B_TITLE = 'Navigator project Bravo'
NEW_TITLE = 'Navigator new result'


def overview_row(sid, title, project='demo', *, kind='idle', index=1):
    value = dict(session_key=hashlib.sha256((project+sid).encode()).hexdigest(),
        project=project, sid=sid, label=title, vendor='codex',
        activity='active' if kind == 'work' else 'idle',
        running='confirmed' if kind == 'work' else 'unconfirmed',
        waits=['question'] if kind == 'attention' else [],
        questions=[dict(interaction_id=part.HANDLE, state='native_only', blocking=True)]
            if kind == 'attention' else [], result=None,
        freshness=dict(state='fresh', observed_at=NOW))
    if kind == 'ready':
        value['result'] = dict(turn_id=part.TURN, item_id='unified-final-item',
            status='completed', ready=True, completed_at=NOW-index*100)
    return value


def history():
    value = live.history()
    value['turns'][0]['items'] = [dict(id='unified-reader-'+str(i), role='assistant',
        text='Unified reader %02d\n'%i + 'Synthetic reading line\n'*9,
        truncated=False, timestamp=1770000000+i, time_precision='item') for i in range(22)]
    return value


class Backend(NavigationBackend):
    def __init__(self):
        super().__init__()
        self.overview = part.overview_dto()
        self.overview['rows'] = [overview_row(live.SID, A_TITLE, kind='attention'),
            overview_row(live.OTHER, READY_TITLE, kind='ready'),
            overview_row(live.THIRD, WORK_TITLE, kind='work')]
        self.pin_value = pins.dto([pins.item(PIN_A, 'demo', live.SID, A_TITLE,
            last_activity=NOW-300), pins.item(PIN_C, 'charlie', C, C_TITLE,
            last_activity=NOW-100)])
        self.pages = {'demo': [dict(sid=s, title=t, vendor='codex', status='idle')
            for s,t in ((live.SID,A_TITLE),(live.OTHER,READY_TITLE),(live.THIRD,WORK_TITLE))],
            'bravo': [dict(sid=B, title=B_TITLE, vendor='codex', status='idle')],
            'charlie': [dict(sid=C, title=C_TITLE, vendor='codex', status='idle')]}
        self.unavailable = set()
        self.reads = []
        self.writes = []
        self.value = history()

    def session_projects(self):
        self.reads.append(('projects',))
        return dict(projects=[dict(name=p, **({'unavailable': True} if p in self.unavailable else {}))
                              for p in self.pages])

    def session_project_summary(self):
        return dict(projects=[dict(name=p,session_count=len(rows),last_activity=NOW-100,
            summary_state='fresh',as_of=NOW) for p,rows in self.pages.items()])

    def session_list(self, project, page):
        self.reads.append(('list',project,page))
        return dict(rows=deepcopy(self.pages.get(project,[])) if page == 0 else [], has_more=False)

    def participation_overview(self):
        self.reads.append(('overview',))
        return deepcopy(self.overview)

    def session_pins(self, principal):
        self.reads.append(('pins',))
        return deepcopy(self.pin_value)

    def session_questions(self, project, sid):
        self.reads.append(('questions',project,sid))
        return part.questions_dto(rows=[])

    def session_history(self, project, sid, cursor):
        self.reads.append(('history',project,sid,cursor))
        if sid == live.OTHER:
            return dict(turns=[dict(id=part.TURN,status='completed',items=[dict(
                id='unified-final-item',role='assistant',text='Unified exact final result',
                truncated=False,timestamp=NOW-100,time_precision='item')])],
                next_cursor=None,truncated=False,recent_sends=[],session_settings=live.settings())
        return deepcopy(self.value)

    def session_create_options(self, project):
        self.reads.append(('create-options',project))
        return dict(schema=1,project=project,options=[dict(context_mode='configured',
            provider_id='codex',available=True,reason=None)])

    def session_create(self, project, operation_id, context_mode, provider_id):
        self.writes.append(('create',project,operation_id,context_mode,provider_id))
        return dict(operation_id=operation_id,status='delivery_unknown')

    def session_unpin(self, principal, pin_id):
        self.writes.append(('unpin',pin_id))
        self.pin_value['items'] = [v for v in self.pin_value['items'] if v['pin_id'] != pin_id]
        return dict(schema=1,pin_id=pin_id,pinned=False)


def pin_actual_app():
    """Fail loudly if any imported support silently selects another worktree."""
    sys.path.insert(0,str(ROOT/'bin'))
    web = importlib.import_module('_control_web')
    if Path(web.__file__).resolve() != ROOT/'bin/_control_web.py':
        raise AssertionError('Synthetic app imported from a different source root')
    return web


def asset_digests():
    # Bytes only: no runtime logic is used as an oracle.
    return {url:hashlib.sha256((ROOT/'bin'/name).read_bytes()).hexdigest()
            for url,name in (('/web.js','_control_web.js'),('/web.css','_control_web.css'))}
