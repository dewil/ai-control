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


# Independent synthetic state authority. Nothing below extends the legacy
# coordinator or treats its capabilities as admission/durability evidence.
@dataclass(frozen=True, repr=False)
class ReserveOutcome:
    attempt_id: object
    disposition: object


class ReservationGuard:
    __slots__ = ()


class _StateLease:
    __slots__ = ()


class ProvisionalPublication:
    __slots__ = ()


class _StateAccount:
    def __init__(self, scope):
        self.scope = scope
        self.refresh = threading.Lock()
        self.state = threading.RLock()
        self.intent = threading.Lock()
        self.poison = False
        self.owner_generation = 1
        self.credential_generation = 0
        self.reservation = None
        self.terminal = None


@dataclass(repr=False)
class _ValidatorRecord:
    binding: object
    account: object = None
    closed: bool = False


@dataclass(repr=False)
class _ReservationRecord:
    lease: object
    validator: object
    attempt_id: str
    deadline: float
    active: bool = True
    durable: bool = False
    exchange: bool = False
    enqueue: bool = False


@dataclass(repr=False)
class _StateGuardRecord:
    lease: object
    scope: object
    window: float
    generation: int
    active: bool = True
    begun: bool = False
    confirmed: bool = False
    published: bool = False
    completed: bool = False
    reservation: object = None
    publication: object = None


class _StateDeliveryGuard:
    __slots__ = ('_coordinator',)

    def __init__(self, coordinator):
        self._coordinator = coordinator

    def begin_enqueue(self, *, reservation_guard, deadline):
        self._coordinator._begin_enqueue(self, reservation_guard, deadline)

    def confirm(self, *, deadline=None):
        self._coordinator._confirm(self, deadline)

    def validate_current(self, *, deadline):
        detail, record = self._coordinator._guard_preflight(self, deadline)
        with record.account.intent:
            self._coordinator._guard_live(detail, record)


class AuthStateCoordinator:
    """Strict in-process ordering only; injected effects remain caller-attested."""
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._registry_lock = threading.Lock()
        self._accounts = {}
        self._leases = {}
        self._guards = {}
        self._reservations = {}
        self._validators = {}
        self._finals = {}

    def _remaining(self, deadline):
        _require(type(deadline) in (int, float) and math.isfinite(deadline))
        now = self._clock()
        _require(type(now) in (int, float) and math.isfinite(now)
                 and deadline > now)
        return deadline - now

    def _account(self, scope):
        captured = _snapshot(scope)
        key = captured[1:3]
        with self._registry_lock:
            account = self._accounts.get(key)
            if account is None:
                account = _StateAccount(captured)
                self._accounts[key] = account
        _require(account.scope == captured)
        return account

    def _validator(self, validator_id):
        _require(_text(validator_id, r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'))
        with self._registry_lock:
            value = self._validators.get(validator_id)
            if value is None:
                value = _ValidatorRecord(threading.Lock())
                self._validators[validator_id] = value
        return value

    def _bind_validator(self, validator_id, scope):
        validator = self._validator(validator_id)
        account = self._account(scope)
        with validator.binding:
            with account.intent:
                _require(not validator.closed and not account.poison
                         and validator.account in (None, account))
                validator.account = account
        return validator

    def _close_validator(self, validator_id):
        validator = self._validator(validator_id)
        with validator.binding:
            account = validator.account
            if account is None:
                validator.closed = True
                return
            with account.intent:
                validator.closed = True
                reservation = account.reservation
                if reservation is not None and reservation.validator is validator:
                    account.poison = True

    def _validator_current(self, validator_id, scope):
        validator = self._bind_validator(validator_id, scope)
        with validator.account.intent:
            _require(not validator.closed and not validator.account.poison)

    def _lease(self, lease, *, released=False):
        _require(type(lease) is _StateLease)
        with self._registry_lock:
            record = self._leases.get(lease)
        _require(record is not None and record.thread is threading.current_thread()
                 and (released or record.active))
        return record

    @staticmethod
    def _ordinary(record, captured):
        account = record.account
        _require(record.active and account.scope == captured
                 and not account.poison and account.terminal is None)

    @contextmanager
    def _state(self, account, deadline):
        if not account.state.acquire(timeout=min(self._remaining(deadline), 1)):
            raise AuthError('refresh_busy')
        try:
            self._remaining(deadline)
            yield
        finally:
            account.state.release()

    def open(self, scope, *, deadline):
        self._remaining(deadline)
        account = self._account(scope)
        with account.intent:
            _require(not account.poison and account.terminal is None)
        if not account.refresh.acquire(timeout=min(self._remaining(deadline), .5)):
            raise AuthError('refresh_busy')
        try:
            with self._state(account, deadline):
                captured = _snapshot(scope)
                with account.intent:
                    _require(account.scope == captured and not account.poison
                             and account.terminal is None)
                lease = _StateLease()
                with self._registry_lock:
                    self._leases[lease] = _LeaseRecord(account, threading.current_thread())
                return lease
        except BaseException:
            account.refresh.release()
            raise

    def check(self, lease, scope, *, deadline):
        record = self._lease(lease)
        captured = _snapshot(scope)
        with self._state(record.account, deadline):
            with record.account.intent:
                self._ordinary(record, captured)

    def release(self, lease):
        record = self._lease(lease, released=True)
        _require(record.guards == 0)
        if record.active:
            record.active = False
            record.account.refresh.release()

    def poison_intent(self, scope, code):
        _require(type(code) is str and code in _CODES)
        captured = _snapshot(scope)
        account = self._accounts.get(captured[1:3])
        _require(account is not None and account.scope == captured)
        with account.intent:
            account.poison = True

    def quarantine(self, lease, code, *, deadline):
        _require(type(code) is str and code in _CODES)
        record = self._lease(lease, released=True)
        with self._state(record.account, deadline):
            with record.account.intent:
                record.account.poison = True
                if record.account.owner_generation == 1:
                    record.account.owner_generation += 1

    def claim_reservation(self, lease, validator_id, attempt_id, *, deadline):
        self._remaining(deadline)
        _require(_text(attempt_id, r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'))
        record = self._lease(lease)
        validator = self._validator(validator_id)
        with validator.binding:
            with record.account.intent:
                self._ordinary(record, record.account.scope)
                _require(not validator.closed and validator.account in (None, record.account)
                         and record.account.reservation is None)
                validator.account = record.account
                guard = ReservationGuard()
                detail = _ReservationRecord(lease, validator, attempt_id, deadline)
                self._reservations[guard] = detail
                record.account.reservation = detail
                return guard

    def _reservation(self, lease, guard):
        record = self._lease(lease)
        _require(type(guard) is ReservationGuard)
        detail = self._reservations.get(guard)
        _require(detail is not None and detail.lease is lease)
        return detail, record

    @staticmethod
    def _reservation_live(detail, record):
        _require(detail.active and record.active
                 and record.account.reservation is detail
                 and not record.account.poison and not detail.validator.closed)

    def mark_reservation_durable(self, lease, *, guard, outcome):
        detail, record = self._reservation(lease, guard)
        _require(type(outcome) is ReserveOutcome and type(outcome.attempt_id) is str
                 and outcome.attempt_id == detail.attempt_id
                 and type(outcome.disposition) is str and outcome.disposition == 'reserved')
        with record.account.intent:
            self._reservation_live(detail, record)
            _require(not detail.durable)
            detail.durable = True

    def abandon_reservation(self, lease, *, guard, outcome):
        detail, record = self._reservation(lease, guard)
        _require(type(outcome) is ReserveOutcome and type(outcome.attempt_id) is str
                 and outcome.attempt_id == detail.attempt_id
                 and type(outcome.disposition) is str and outcome.disposition == 'not_written')
        with record.account.intent:
            self._reservation_live(detail, record)
            _require(not detail.durable and not detail.exchange)
            detail.active = False
            record.account.reservation = None

    def begin_exchange(self, lease, validator_id, *, guard, deadline):
        self._remaining(deadline)
        detail, record = self._reservation(lease, guard)
        validator = self._validator(validator_id)
        _require(deadline <= detail.deadline)
        with record.account.intent:
            self._reservation_live(detail, record)
            _require(detail.validator is validator and detail.durable and not detail.exchange)
            detail.exchange = True

    @contextmanager
    def delivery_guard(self, lease, scope, *, deadline):
        record = self._lease(lease)
        captured = _snapshot(scope)
        with self._state(record.account, deadline):
            window = min(deadline, self._clock() + 1)
            with record.account.intent:
                self._ordinary(record, captured)
            guard = _StateDeliveryGuard(self)
            detail = _StateGuardRecord(lease, scope, window, record.account.owner_generation)
            self._guards[guard] = detail
            record.guards += 1
            try:
                yield guard
            finally:
                with record.account.intent:
                    if detail.begun and not detail.completed:
                        record.account.poison = True
                    detail.active = False
                record.guards -= 1
                del self._guards[guard]

    def _guard_preflight(self, guard, deadline=None):
        _require(type(guard) is _StateDeliveryGuard)
        detail = self._guards.get(guard)
        _require(detail is not None and detail.active)
        record = self._lease(detail.lease)
        self._remaining(detail.window)
        if deadline is not None:
            self._remaining(deadline)
            _require(deadline <= detail.window)
        _require(record.account.scope == _snapshot(detail.scope))
        return detail, record

    @staticmethod
    def _guard_live(detail, record, *, confirmed_effect=False):
        account = record.account
        _require(detail.active and record.active and account.owner_generation == detail.generation)
        _require(account.terminal in (None, detail))
        if not confirmed_effect:
            _require(not account.poison)
            if detail.reservation is not None:
                _require(not detail.reservation.validator.closed)

    def _begin_enqueue(self, guard, reservation, deadline):
        detail, record = self._guard_preflight(guard, deadline)
        attempt, same = self._reservation(detail.lease, reservation)
        _require(same is record)
        with record.account.intent:
            self._guard_live(detail, record)
            self._reservation_live(attempt, record)
            _require(attempt.durable and attempt.exchange and not attempt.enqueue
                     and not detail.begun and record.account.terminal is None)
            detail.reservation = attempt
            attempt.enqueue = detail.begun = True
            record.account.terminal = detail

    def _confirm(self, guard, deadline):
        detail, record = self._guard_preflight(guard, deadline)
        with record.account.intent:
            self._guard_live(detail, record, confirmed_effect=True)
            _require(detail.begun and not detail.confirmed and not detail.published)
            detail.confirmed = True

    def publish_delivery(self, lease, *, guard, deadline):
        detail, record = self._guard_preflight(guard, deadline)
        _require(detail.lease is lease)
        publication = ProvisionalPublication()
        with record.account.intent:
            self._guard_live(detail, record)
            _require(detail.begun and detail.confirmed and not detail.published
                     and record.account.terminal is detail)
            record.account.credential_generation += 1
            detail.published = True
            detail.publication = publication
            return publication

    def _complete_terminal(self, lease, *, guard, publication, deadline):
        # All injected/preflight work precedes the final leaf-mutex transition.
        detail, record = self._guard_preflight(guard, deadline)
        _require(detail.lease is lease and type(publication) is ProvisionalPublication)
        with record.account.intent:
            self._guard_live(detail, record)
            _require(detail.published and not detail.completed
                     and detail.publication is publication
                     and record.account.terminal is detail)
            attempt = detail.reservation
            self._reservation_live(attempt, record)
            stamp = AuthorityStamp(record.account.owner_generation,
                                   record.account.credential_generation)
            self._finals[id(stamp)] = (stamp, record.account, attempt.validator, attempt.attempt_id)
            detail.completed = True
            attempt.active = False
            record.account.reservation = record.account.terminal = None
            return stamp

    def _validate_final(self, stamp, validator_id, attempt_id, scope):
        validator = self._validator(validator_id)
        account = self._account(scope)
        entry = self._finals.get(id(stamp))
        _require(entry is not None and entry[0] is stamp and entry[1] is account
                 and entry[2] is validator and entry[3] == attempt_id)

    def _check_stamp(self, stamp, validator_id, scope):
        validator = self._validator(validator_id)
        account = self._account(scope)
        entry = self._finals.get(id(stamp))
        with account.intent:
            _require(entry is not None and entry[0] is stamp and entry[1] is account
                     and entry[2] is validator and not validator.closed and not account.poison
                     and account.terminal is None and stamp.owner_generation == account.owner_generation
                     and stamp.credential_generation <= account.credential_generation)
