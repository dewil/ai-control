"""Synthetic-only auth orchestration. No provider, file, native or runtime adapter.

Injected envelopes and local capabilities prove ordering and data consistency,
never authenticated TLS, durable storage, native ownership or production admission.
"""
from contextlib import ExitStack
from dataclasses import dataclass
import json
import math
import threading
import time
from types import MappingProxyType
import uuid

from _control_codex_auth_authority import (
    AuthError, AuthScope, AuthStateCoordinator, ReserveOutcome, ReservationGuard,
    _keys, _require, _snapshot, _text,
)
from _control_codex_token_response import parse_token_response, TokenResponseError


AuthCoordinator = AuthStateCoordinator
_ISSUER = 'https://auth.openai.com'
_ENDPOINT = _ISSUER + '/api/accounts/oauth/token'
_CLIENT = 'app_EMoamEEZ73f0CkXaXp7hrann'
_UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0)
    return value


def _request_id(value):
    return ((type(value) is int and value >= 0)
            or (type(value) is str and 1 <= len(value) <= 128 and value.isascii()))


def _safe(call):
    # Never retain dependency/parser diagnostic exception chains.
    code = None
    try:
        return call()
    except AuthError as error:
        code = error.code
    except Exception:
        code = 'authority_stale'
    raise AuthError(code)


@dataclass(frozen=True, repr=False, init=False, slots=True)
class AuthContext:
    reference: object
    expected_native_principal: object
    execution_identity: object

    def __init__(self, reference, expected_native_principal, execution_identity):
        scope = AuthScope(reference, expected_native_principal)
        _require(_keys(execution_identity, 'kind id'))
        _require(type(execution_identity['kind']) is str
                 and execution_identity['kind'] in ('interactive_session', 'task')
                 and _text(execution_identity['id'], _UUID))
        object.__setattr__(self, 'reference', scope._reference)
        object.__setattr__(self, 'expected_native_principal', scope._principal)
        object.__setattr__(self, 'execution_identity', MappingProxyType(dict(execution_identity)))


def capture_auth_context(reference, expected_native_principal, execution_identity):
    return _safe(lambda: AuthContext(reference, expected_native_principal, execution_identity))


def _context(ctx):
    _require(type(ctx) is AuthContext)
    _require(type(ctx.reference) is MappingProxyType
             and type(ctx.expected_native_principal) is MappingProxyType
             and type(ctx.execution_identity) is MappingProxyType)
    reference = dict(ctx.reference)
    _require(type(reference['registration_snapshot']) is MappingProxyType)
    reference['registration_snapshot'] = dict(reference['registration_snapshot'])
    validated = AuthContext(reference, dict(ctx.expected_native_principal), dict(ctx.execution_identity))
    scope = AuthScope(reference, dict(validated.expected_native_principal))
    return scope, (_snapshot(scope), tuple(sorted(validated.execution_identity.items())))


@dataclass(frozen=True, repr=False, slots=True)
class OAuthRequest:
    attempt_id: object
    context: object
    started_monotonic: object
    started_wall: object
    deadline: object


@dataclass(frozen=True, repr=False, slots=True)
class TLSExchange:
    attempt_id: object
    context: object
    endpoint: object
    client_id: object
    peer_hostname: object
    ca_verified: object
    redirected: object
    proxy_used: object
    status: object
    body: object
    received_monotonic: object
    received_wall: object


@dataclass(frozen=True, repr=False, slots=True)
class OwnedChannel:
    context: object
    invocation_id: object
    channel_id: object
    transport_generation: object


@dataclass(frozen=True, repr=False, init=False, slots=True)
class CapturedCallback:
    channel: object
    request_id: object
    params: object
    received_monotonic: object

    def __init__(self, channel, request_id, params, received_monotonic):
        _require(type(channel) is OwnedChannel and _request_id(request_id))
        _require(_keys(params, 'reason previousAccountId'))
        _require(type(params['reason']) is str and params['reason'] == 'unauthorized')
        previous = params['previousAccountId']
        _require(previous is None or type(previous) is str)
        _number(received_monotonic)
        object.__setattr__(self, 'channel', channel)
        object.__setattr__(self, 'request_id', request_id)
        object.__setattr__(self, 'params', MappingProxyType(dict(params)))
        object.__setattr__(self, 'received_monotonic', received_monotonic)


@dataclass(frozen=True, repr=False, slots=True)
class LoginReceipt:
    channel: object
    request_id: object
    response_id: object
    result_type: object


@dataclass(frozen=True, repr=False, slots=True)
class WriteReceipt:
    channel: object
    request_id: object
    frame_length: object
    accepted_length: object


@dataclass(frozen=True, repr=False, init=False, slots=True)
class Delivery:
    delivery_id: object
    context: object
    channel: object
    stamp: object

    def __init__(self, delivery_id, context, channel, stamp):
        raise AuthError('authority_stale')


@dataclass(repr=False)
class _CallbackRecord:
    callback: object
    delivery: object
    running: bool = False
    result: object = None
    error: object = None


class AuthStateValidator:
    def __init__(self, *, profile_source, oauth_client, owned_transport, coordinator,
                 clock=time.monotonic, wall_clock=time.time):
        _require(isinstance(coordinator, AuthStateCoordinator))
        self._source = profile_source
        self._oauth = oauth_client
        self._transport = owned_transport
        self._coordinator = coordinator
        self._clock = clock
        self._wall = wall_clock
        self._validator_id = str(uuid.uuid4())
        coordinator._validator(self._validator_id)
        self._deliveries = {}
        self._callbacks = {}
        self._callback_lock = threading.RLock()
        self._context_lock = threading.Lock()
        self._captured_context = None
        self._owned_channel = None

    def _remaining(self, deadline):
        _number(deadline)
        now = _number(self._clock())
        _require(deadline > now)
        return now

    def _channel(self, channel, ctx):
        _require(type(channel) is OwnedChannel and channel.context is ctx
                 and _text(channel.invocation_id, _UUID) and _text(channel.channel_id, _UUID)
                 and type(channel.transport_generation) is int and channel.transport_generation >= 1)

    def _delivery(self, delivery, ctx=None):
        _require(type(delivery) is Delivery and self._deliveries.get(id(delivery)) is delivery)
        actual = delivery.context if ctx is None else ctx
        scope, captured = _context(actual)
        _require(captured == _context(delivery.context)[1])
        self._channel(delivery.channel, delivery.context)
        self._coordinator._check_stamp(delivery.stamp, self._validator_id, scope)
        return scope

    def _callback(self, callback, channel, deadline):
        _require(type(callback) is CapturedCallback and callback.channel is channel
                 and _request_id(callback.request_id)
                 and type(callback.params) is MappingProxyType
                 and set(callback.params) == {'reason', 'previousAccountId'}
                 and type(callback.params['reason']) is str
                 and callback.params['reason'] == 'unauthorized')
        previous = callback.params['previousAccountId']
        _require(previous is None or (type(previous) is str
                 and previous == channel.context.expected_native_principal['workspace_id']))
        now = self._remaining(deadline)
        _require(_number(callback.received_monotonic) <= now
                 and now < callback.received_monotonic + 9)
        self._transport.validate_callback(callback, channel, deadline=deadline)

    def _validate(self, ctx, channel, scope, lease, source_lease, deadline, callback=None, *, claimed=False):
        self._remaining(deadline)
        try:
            self._coordinator._validator_current(self._validator_id, scope)
            self._coordinator.check(lease, scope, deadline=deadline)
        except AuthError:
            if claimed:
                raise AuthError('refresh_unknown') from None
            raise
        self._source.validate_current(ctx, source_lease, deadline=deadline)
        self._transport.validate_current(channel, ctx, deadline=deadline)
        if callback is not None:
            try:
                self._callback(callback, channel, deadline)
            except AuthError:
                if claimed:
                    raise AuthError('refresh_unknown') from None
                raise

    def admit(self, ctx, *, deadline):
        return _safe(lambda: self._operation(ctx, deadline, None, None))

    def current(self, delivery, ctx, *, deadline):
        return _safe(lambda: self._current(delivery, ctx, deadline))

    def _current(self, delivery, ctx, deadline):
        self._remaining(deadline)
        scope = self._delivery(delivery, ctx)
        lease = self._coordinator.open(scope, deadline=deadline)
        source_lease = None
        try:
            source_lease = self._source.open_selected(ctx, deadline=deadline)
            self._validate(ctx, delivery.channel, scope, lease, source_lease, deadline)
            self._coordinator._check_stamp(delivery.stamp, self._validator_id, scope)
        finally:
            self._release(source_lease, lease)

    def _release(self, source_lease, lease):
        # Cleanup never supplies an authentication effect or rewrites completion.
        if source_lease is not None:
            try:
                self._source.close_selected(source_lease)
            except Exception:
                pass
        self._coordinator.release(lease)

    def capture_callback(self, delivery, request_id, params, *, deadline):
        return _safe(lambda: self._capture_callback(delivery, request_id, params, deadline))

    def _capture_callback(self, delivery, request_id, params, deadline):
        _require(_request_id(request_id) and _keys(params, 'reason previousAccountId'))
        _require(type(params['reason']) is str and params['reason'] == 'unauthorized')
        previous = params['previousAccountId']
        _require(previous is None or (type(previous) is str
                 and previous == delivery.context.expected_native_principal['workspace_id']))
        self._current(delivery, delivery.context, deadline)
        channel = delivery.channel
        key = (channel.channel_id, channel.transport_generation, type(request_id), request_id)
        with self._callback_lock:
            existing = self._callbacks.get(key)
            if existing is not None:
                _require(existing.delivery is delivery and dict(existing.callback.params) == params)
                return existing.callback
            callback = self._transport.capture_callback(channel, request_id, params, deadline=deadline)
            self._callback(callback, channel, deadline)
            _require(type(callback.request_id) is type(request_id) and callback.request_id == request_id
                     and dict(callback.params) == params)
            self._callbacks[key] = _CallbackRecord(callback, delivery)
            return callback

    def refresh(self, delivery, callback, *, deadline):
        return _safe(lambda: self._refresh(delivery, callback, deadline))

    def _refresh(self, delivery, callback, deadline):
        with self._callback_lock:
            _require(type(callback) is CapturedCallback)
            key = (callback.channel.channel_id, callback.channel.transport_generation,
                   type(callback.request_id), callback.request_id)
            record = self._callbacks.get(key)
            _require(record is not None and record.callback is callback and record.delivery is delivery)
            if record.error is not None:
                raise AuthError(record.error)
            if record.result is not None:
                self._current(record.result, record.result.context, deadline)
                return record.result
            _require(not record.running)
            record.running = True
        code = None
        try:
            self._delivery(delivery)
            bounded = min(_number(deadline), _number(callback.received_monotonic) + 9)
            self._callback(callback, delivery.channel, bounded)
            result = self._operation(delivery.context, bounded, delivery.channel, callback)
        except AuthError as error:
            code = error.code
        except Exception:
            code = 'authority_stale'
        with self._callback_lock:
            record.running = False
            if code is None:
                record.result = result
            else:
                record.error = code
        if code is not None:
            raise AuthError(code)
        return result

    def close(self):
        return _safe(lambda: self._coordinator._close_validator(self._validator_id))

    def _exchange(self, request, refresh_token, scope):
        self._remaining(request.deadline)
        response = self._oauth.exchange(request, refresh_token, deadline=request.deadline)
        _require(type(response) is TLSExchange and response.attempt_id == request.attempt_id
                 and type(response.attempt_id) is str and response.context is request.context)
        for actual, expected in ((response.endpoint, _ENDPOINT), (response.client_id, _CLIENT),
                                 (response.peer_hostname, 'auth.openai.com')):
            if type(actual) is not str or actual != expected:
                raise AuthError('auth_response_invalid')
        if response.ca_verified is not True or response.redirected is not False or response.proxy_used is not False:
            raise AuthError('auth_response_invalid')
        now = self._remaining(request.deadline)
        _require(request.started_monotonic <= _number(response.received_monotonic) <= now)
        if type(response.status) is not int:
            raise AuthError('auth_response_invalid')
        if response.status != 200:
            raise AuthError('auth_expired' if response.status in (400, 401) else 'auth_unavailable')
        code = None
        try:
            parsed = parse_token_response(
                response.status, response.body, scope,
                request_start_wall=request.started_wall,
                response_end_wall=response.received_wall, evaluation_wall=self._wall())
        except TokenResponseError as error:
            code = error.code
        if code is not None:
            raise AuthError(code)
        return parsed

    def _make_delivery(self, ctx, channel, stamp, attempt_id, scope):
        self._coordinator._validate_final(stamp, self._validator_id, attempt_id, scope)
        result = object.__new__(Delivery)
        for name, value in (('delivery_id', str(uuid.uuid4())), ('context', ctx),
                            ('channel', channel), ('stamp', stamp)):
            object.__setattr__(result, name, value)
        self._deliveries[id(result)] = result
        return result

    def _operation(self, ctx, deadline, channel, callback):
        scope, captured = _context(ctx)
        with self._context_lock:
            _require(self._captured_context in (None, captured))
            self._captured_context = captured
        started = self._remaining(deadline)
        deadline = min(deadline, started + (30 if callback is None else 9))
        self._coordinator._bind_validator(self._validator_id, scope)
        lease = self._coordinator.open(scope, deadline=deadline)
        source_lease = None
        attempt_id = str(uuid.uuid4())
        claimed = False
        quarantined = False
        exchange_claimed = False
        completed = False
        result = None

        def poison(code):
            nonlocal quarantined
            if quarantined:
                return
            self._coordinator.poison_intent(scope, code)
            quarantined = True
            try:
                self._coordinator.quarantine(lease, code, deadline=deadline)
            except Exception:
                pass
            if source_lease is not None:
                try:
                    self._source.quarantine_unknown(source_lease, ctx, attempt_id, code, deadline=deadline)
                except Exception:
                    pass

        try:
            source_lease = self._source.open_selected(ctx, deadline=deadline)
            if channel is None:
                channel = self._owned_channel
                if channel is None:
                    channel = self._transport.capture(ctx, validator_id=self._validator_id, deadline=deadline)
                    self._channel(channel, ctx)
                    self._owned_channel = channel
            self._channel(channel, ctx)
            self._validate(ctx, channel, scope, lease, source_lease, deadline, callback)
            refresh_token = self._source.read_refresh(source_lease, deadline=deadline)
            _require(type(refresh_token) is str and 1 <= len(refresh_token) <= 16384
                     and all(33 <= ord(char) <= 126 for char in refresh_token))
            self._validate(ctx, channel, scope, lease, source_lease, deadline, callback)
            reservation = self._coordinator.claim_reservation(
                lease, self._validator_id, attempt_id, deadline=deadline)
            claimed = True
            outcome = self._source.reserve_attempt(source_lease, ctx, attempt_id, deadline=deadline)
            _require(type(outcome) is ReserveOutcome and type(outcome.attempt_id) is str
                     and outcome.attempt_id == attempt_id)
            if outcome.disposition == 'not_written' and type(outcome.disposition) is str:
                self._coordinator.abandon_reservation(lease, guard=reservation, outcome=outcome)
                claimed = False
                raise AuthError('refresh_busy')
            self._coordinator.mark_reservation_durable(lease, guard=reservation, outcome=outcome)
            self._validate(ctx, channel, scope, lease, source_lease, deadline, callback, claimed=True)
            request = OAuthRequest(attempt_id, ctx, self._remaining(deadline),
                                   _number(self._wall()), min(deadline, self._clock() + 6))
            self._coordinator.begin_exchange(lease, self._validator_id, guard=reservation, deadline=request.deadline)
            exchange_claimed = True
            # Once claimed, exactly this bounded exchange may resolve after close.
            parsed = self._exchange(request, refresh_token, scope)
            self._validate(ctx, channel, scope, lease, source_lease, deadline, callback, claimed=True)
            if parsed.refresh_token is not None:
                try:
                    self._source.commit_rotation(source_lease, ctx, attempt_id, parsed.refresh_token, deadline=deadline)
                except Exception:
                    raise AuthError('refresh_unknown') from None
            self._validate(ctx, channel, scope, lease, source_lease, deadline, callback, claimed=True)
            with self._coordinator.delivery_guard(lease, scope, deadline=deadline) as guard:
                final = self._coordinator._guards[guard].window
                with ExitStack() as stack:
                    try:
                        source_guard = stack.enter_context(self._source.delivery_guard(ctx, source_lease, deadline=final))
                        channel_guard = stack.enter_context(self._transport.delivery_guard(
                            channel, ctx, source_guard=source_guard, deadline=final))

                        def final_check():
                            self._remaining(final)
                            self._coordinator._validator_current(self._validator_id, scope)
                            guard.validate_current(deadline=final)
                            source_guard.validate_current(deadline=final)
                            channel_guard.validate_current(deadline=final)
                            if callback is not None:
                                self._callback(callback, channel, final)
                            self._remaining(final)

                        final_check()
                        if not parsed.usable_at(self._wall()):
                            raise AuthError('auth_expired')
                        payload = {'accessToken': parsed.access_token,
                                   'chatgptAccountId': ctx.expected_native_principal['workspace_id'],
                                   'chatgptPlanType': None}
                        if callback is None:
                            payload['type'] = 'chatgptAuthTokens'
                        _require(len(json.dumps(payload, separators=(',', ':')).encode('ascii')) <= 32768)
                        final_check()
                        guard.begin_enqueue(reservation_guard=reservation, deadline=final)
                        if callback is None:
                            receipt = self._transport.login(channel, MappingProxyType(payload), guard=channel_guard, deadline=final)
                            _require(type(receipt) is LoginReceipt and receipt.channel is channel
                                     and _text(receipt.request_id, _UUID)
                                     and type(receipt.response_id) is str and receipt.response_id == receipt.request_id
                                     and type(receipt.result_type) is str and receipt.result_type == 'chatgptAuthTokens')
                        else:
                            receipt = self._transport.write_refresh(channel, callback, MappingProxyType(payload), guard=channel_guard, deadline=final)
                            _require(type(receipt) is WriteReceipt and receipt.channel is channel
                                     and type(receipt.request_id) is type(callback.request_id)
                                     and receipt.request_id == callback.request_id
                                     and type(receipt.frame_length) is int and 1 <= receipt.frame_length <= 32768
                                     and type(receipt.accepted_length) is int
                                     and receipt.accepted_length == receipt.frame_length)
                        guard.confirm(deadline=final)
                        final_check()
                        publication = self._coordinator.publish_delivery(lease, guard=guard, deadline=final)
                        final_check()
                        self._source.finish_confirmed(source_lease, ctx, attempt_id, deadline=final)
                        final_check()
                        stamp = self._coordinator._complete_terminal(lease, guard=guard, publication=publication, deadline=final)
                        result = self._make_delivery(ctx, channel, stamp, attempt_id, scope)
                        completed = True
                        return result
                    except Exception:
                        poison('refresh_unknown')
                        raise AuthError('refresh_unknown') from None
        except Exception as error:
            if completed:
                return result
            if claimed:
                code = error.code if isinstance(error, AuthError) else 'refresh_unknown'
                # Unresolved reservation and callback invalidation are unknown,
                # regardless of an adapter's optimistic exception text.
                if not exchange_claimed or code == 'refresh_busy':
                    code = 'refresh_unknown'
                poison(code)
                raise AuthError(code) from None
            raise
        finally:
            try:
                self._release(source_lease, lease)
            except Exception:
                if not completed:
                    raise
