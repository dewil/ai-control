"""Synthetic public fixtures for frozen INV-WLIM-10..16; no runtime source reads."""
from copy import deepcopy
import hashlib
import threading
import time
import live_sse_blind_support as live

NOW = 1800000000
DAY = 86400
ACCOUNT = ' synthetic-account-A@example.invalid '
PRIVATE = 'SYNTHETIC-PRIVATE-NEVER-PUBLISH'
CONTEXT = dict(schema=1, vendor='codex', context_kind='legacy_unbound',
               context_id='a'*64, transport_generation=3, context_generation=7,
               native_version='0.162.1')
SOURCE_KEYS = {'node_id','provider','account_id','identity','status','captured_at',
               'age_seconds','plan','windows','error'}
WINDOW_KEYS = {'id','bucket','duration_minutes','remaining_percent','resets_at',
               'window_started_at','anchor'}


def identity(account=ACCOUNT):
    return hashlib.sha256(('codex-account:'+account).encode('utf-8')).hexdigest()


def native_window(used=25, duration=10080, reset=NOW+6*DAY):
    return dict(usedPercent=used, windowDurationMins=duration, resetsAt=reset)


def native(account=ACCOUNT, buckets=None):
    bucket = dict(planType='plus', primary=native_window(),
                  secondary=native_window(used=80, duration=300, reset=NOW+3600))
    return dict(accountId=account, rateLimits=deepcopy(bucket),
                rateLimitsByLimitId=deepcopy(buckets if buckets is not None else {'codex':bucket}))


def unavailable(provider='claude', error='unsupported'):
    return dict(node_id='llm',provider=provider,account_id=None,identity='unknown',
                status='unavailable',captured_at=None,age_seconds=None,plan=None,
                windows=[],error=error)


def overview(elapsed=DAY, remaining=75, duration=10080, anchor=True, status='ok'):
    start = NOW-elapsed
    window = dict(id='codex:primary',bucket='codex',duration_minutes=duration,
                  remaining_percent=remaining,resets_at=start+duration*60,
                  window_started_at=start if anchor else None,
                  anchor='derived_reset_and_duration' if anchor else None)
    codex = dict(node_id='llm',provider='codex',account_id=identity(),identity='native_reported',
                 status=status,captured_at=NOW,age_seconds=0,plan='Plus',windows=[window],error=None)
    return dict(schema=1,server_now=NOW,coverage=dict(scope='llm_native_only',partial=False),
                sources=[codex,unavailable()])


class LimitsRPC:
    """Only documented injected RPC protocol; native methods are allowlisted here."""
    def __init__(self):
        self.context = dict(CONTEXT)
        self.value = native()
        self.calls = []
        self.prepares = 0
        self.context_reads = 0
        self.after_read = None
        self.failure = None
        self.entered = threading.Event()
        self.gate = threading.Event(); self.gate.set()

    def model_context(self):
        self.context_reads += 1
        return dict(self.context)

    def prepare_context(self, timeout=None):
        self.prepares += 1
        return self.model_context()

    def call_in_generation(self, method, params, *, transport_generation,
                           context_generation, timeout=None):
        self.calls.append(dict(method=method,params=deepcopy(params),
                               transport_generation=transport_generation,
                               context_generation=context_generation,timeout=timeout,
                               started=time.monotonic()))
        if method != 'account/rateLimits/read':
            raise AssertionError('Unexpected limits RPC: '+method)
        before = (self.context['transport_generation'],self.context['context_generation'])
        if before != (transport_generation,context_generation):
            raise RuntimeError('Synthetic generation changed')
        self.entered.set()
        if not self.gate.wait(2): raise TimeoutError('Synthetic bounded gate')
        if self.failure: raise self.failure
        value = deepcopy(self.value)
        if self.after_read: self.after_read(self)
        if before != (self.context['transport_generation'],self.context['context_generation']):
            raise RuntimeError('Synthetic generation changed after response')
        return value

    def __call__(self, method, params):
        raise AssertionError('Limits must use fenced native RPC: '+method)


class LimitsBackend(live.Backend):
    def __init__(self):
        super().__init__()
        self.limits_value = overview()
        self.limits_calls = []
        self.limits_failure = None

    def limits_overview(self):
        self.limits_calls.append(time.monotonic())
        if self.limits_failure: raise self.limits_failure
        return deepcopy(self.limits_value)
