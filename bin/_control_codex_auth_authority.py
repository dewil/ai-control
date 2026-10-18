"""Pure local authority bookkeeping; no external authentication or delivery proof.

Guard bodies must cooperate and exit: expiry refuses operations, but does not
preempt a caller holding the account lock. Unknown external effects must be
handled by the integrating caller, including explicit quarantine.
"""

from contextlib import contextmanager
from dataclasses import dataclass
import math
import re
import threading
import time
from types import MappingProxyType
import uuid


_CODES = frozenset(('authority_stale', 'refresh_busy', 'refresh_unknown',
                    'unsupported_auth_profile', 'auth_expired', 'auth_unavailable',
                    'auth_response_invalid', 'identity_mismatch',
                    'owned_host_unproven', 'issuer_semantics_unproven'))


class AuthError(ValueError):
    def __init__(self, code):
        self.code = code if type(code) is str and code in _CODES else 'authority_stale'
        super().__init__(self.code)


def _require(condition):
    if not condition:
        raise AuthError('authority_stale')


def _text(value, pattern):
    return type(value) is str and re.fullmatch(pattern, value, flags=re.ASCII) is not None


def _keys(value, keys):
    return (type(value) is dict and all(type(key) is str for key in value)
            and value.keys() == set(keys.split()))


@dataclass(frozen=True, repr=False, init=False, slots=True)
class AuthScope:
    _reference: object
    _principal: object

    def __init__(self, reference, principal):
        _require(_keys(reference, 'schema provider_id account_id profile_instance_id adapter_revision registration_snapshot'))
        _require(type(reference['schema']) is int and reference['schema'] == 2)
        _require(type(reference['provider_id']) is str and reference['provider_id'] == 'codex')
        _require(_text(reference['account_id'], r'[a-z][a-z0-9_-]{0,63}'))
        instance = reference['profile_instance_id']
        _require(_text(instance, r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'))
        _require(str(uuid.UUID(instance)) == instance)
        _require(type(reference['adapter_revision']) is str and reference['adapter_revision'] == 'codex-chatgpt-external-auth-host-v2')
        snapshot = reference['registration_snapshot']
        _require(_keys(snapshot, 'dev ino ctime_ns sha256'))
        for key, minimum in (('dev', 0), ('ino', 1), ('ctime_ns', 1)):
            _require(type(snapshot[key]) is int and snapshot[key] >= minimum)
        _require(_text(snapshot['sha256'], r'[0-9a-fA-F]{64}'))
        _require(_keys(principal, 'kind issuer subject workspace_id'))
        _require(type(principal['kind']) is str and principal['kind'] == 'openid_subject_workspace')
        _require(type(principal['issuer']) is str and principal['issuer'] == 'https://auth.openai.com')
        _require(_text(principal['subject'], r'[\x20-\x7e]{1,255}'))
        _require(_text(principal['workspace_id'], r'[A-Za-z0-9_-]{1,128}'))
        frozen_reference = dict(reference)
        frozen_reference['registration_snapshot'] = MappingProxyType(dict(snapshot))
        object.__setattr__(self, '_reference', MappingProxyType(frozen_reference))
        object.__setattr__(self, '_principal', MappingProxyType(dict(principal)))


def _snapshot(scope):
    """Validate and independently capture values, never retaining caller aliases."""
    _require(type(scope) is AuthScope)
    try:
        _require(type(scope._reference) is MappingProxyType
                 and type(scope._principal) is MappingProxyType)
        _require(all(type(key) is str for key in scope._reference)
                 and all(type(key) is str for key in scope._principal))
        reference = dict(scope._reference)
        nested = reference['registration_snapshot']
        _require(type(nested) is MappingProxyType
                 and all(type(key) is str for key in nested))
        reference['registration_snapshot'] = dict(nested)
        validated = AuthScope(reference, dict(scope._principal))
    except Exception:
        raise AuthError('authority_stale') from None
    ref = validated._reference
    return (ref['schema'], ref['provider_id'], ref['account_id'],
            ref['profile_instance_id'], ref['adapter_revision'],
            tuple(sorted(ref['registration_snapshot'].items())),
            tuple(sorted(validated._principal.items())))


class AuthorityLease:
    __slots__ = ()


@dataclass(frozen=True, repr=False)
class AuthorityStamp:
    owner_generation: int
    credential_generation: int


class _Account:
    def __init__(self, captured):
        # Registry key and stored identity come from the same immutable capture.
        self.scope = captured
        self.refresh = threading.Lock()
        self.state = threading.RLock()
        self.owner_generation = 1
        self.credential_generation = 0
        self.quarantined = False


@dataclass(repr=False)
class _LeaseRecord:
    account: _Account
    thread: object
    active: bool = True
    guards: int = 0


@dataclass(repr=False)
class _GuardRecord:
    lease: AuthorityLease
    scope: AuthScope
    caller_deadline: float
    window: float
    generation: int
    active: bool = True
    begun: bool = False
    confirmed: bool = False
    published: bool = False


class _DeliveryGuard:
    __slots__ = ('_coordinator',)

    def __init__(self, coordinator):
        self._coordinator = coordinator

    def begin_enqueue(self):
        self._coordinator._mark(self, 'begun')

    def confirm(self):
        self._coordinator._mark(self, 'confirmed')


class AuthCoordinator:
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._registry_lock = threading.Lock()
        self._accounts = {}
        self._leases = {}
        self._guards = {}

    def _remaining(self, deadline):
        _require(type(deadline) in (int, float))
        try:
            _require(math.isfinite(deadline))
            now = self._clock()
            _require(type(now) in (int, float) and math.isfinite(now))
            remaining = deadline - now
            _require(math.isfinite(remaining) and remaining > 0)
        except Exception:
            raise AuthError('authority_stale') from None
        return remaining

    def _lease(self, lease, *, released=False):
        _require(type(lease) is AuthorityLease)
        with self._registry_lock:
            record = self._leases.get(lease)
        _require(record is not None and record.thread is threading.current_thread())
        _require(released or record.active)
        return record

    @contextmanager
    def _state(self, account, deadline, limit=1.0):
        if not account.state.acquire(timeout=min(self._remaining(deadline), limit)):
            raise AuthError('refresh_busy')
        try:
            self._remaining(deadline)
            yield
        finally:
            account.state.release()

    def _live(self, record, scope):
        captured = _snapshot(scope)
        _require(record.active and not record.account.quarantined
                 and record.account.scope == captured)

    def open(self, scope, *, deadline):
        self._remaining(deadline)
        _require(type(scope) is AuthScope)
        captured = _snapshot(scope)
        key = (captured[1], captured[2])
        with self._registry_lock:
            account = self._accounts.get(key)
            if account is None:
                account = _Account(captured)
                self._accounts[key] = account
        if not account.refresh.acquire(timeout=min(self._remaining(deadline), 0.5)):
            raise AuthError('refresh_busy')
        try:
            with self._state(account, deadline):
                _require(account.scope == _snapshot(scope) and not account.quarantined)
                lease = AuthorityLease()
                with self._registry_lock:
                    self._leases[lease] = _LeaseRecord(account, threading.current_thread())
                return lease
        except BaseException:
            account.refresh.release()
            raise

    def check(self, lease, scope, *, deadline):
        record = self._lease(lease)
        with self._state(record.account, deadline):
            self._live(record, scope)

    def release(self, lease):
        record = self._lease(lease, released=True)
        _require(record.guards == 0)
        if record.active:
            record.active = False
            record.account.refresh.release()

    def quarantine(self, lease, code, *, deadline):
        _require(type(code) is str and code in _CODES)
        record = self._lease(lease, released=True)
        with self._state(record.account, deadline):
            if not record.account.quarantined:
                record.account.quarantined = True
                record.account.owner_generation += 1

    @contextmanager
    def delivery_guard(self, lease, scope, *, deadline):
        record = self._lease(lease)
        with self._state(record.account, deadline):
            self._live(record, scope)
            guard = _DeliveryGuard(self)
            entry = deadline - self._remaining(deadline)
            self._live(record, scope)
            detail = _GuardRecord(lease, scope, deadline, min(deadline, entry + 1),
                                  record.account.owner_generation)
            with self._registry_lock:
                self._guards[guard] = detail
            record.guards += 1
            try:
                yield guard
            finally:
                detail.active = False
                record.guards -= 1
                with self._registry_lock:
                    del self._guards[guard]

    def _guard(self, guard):
        _require(type(guard) is _DeliveryGuard)
        with self._registry_lock:
            detail = self._guards.get(guard)
        _require(detail is not None and detail.active)
        record = self._lease(detail.lease)
        self._remaining(detail.window)
        self._guard_live(detail, record)
        return detail, record

    def _guard_live(self, detail, record):
        _require(detail.active)
        self._live(record, detail.scope)
        _require(record.account.owner_generation == detail.generation)

    def _mark(self, guard, stage):
        detail, _ = self._guard(guard)
        _require(not detail.published)
        if stage == 'begun':
            _require(not detail.begun)
            detail.begun = True
        else:
            _require(detail.begun and not detail.confirmed)
            detail.confirmed = True

    def publish_delivery(self, lease, *, guard, deadline):
        detail, record = self._guard(guard)
        _require(detail.lease is lease and detail.begun and detail.confirmed and not detail.published)
        self._remaining(deadline)
        _require(deadline <= detail.caller_deadline)
        self._remaining(min(deadline, detail.window))
        self._guard_live(detail, record)
        _require(not detail.published)
        record.account.credential_generation += 1
        detail.published = True
        return AuthorityStamp(record.account.owner_generation, record.account.credential_generation)
