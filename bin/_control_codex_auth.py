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
    captured: tuple
    running: bool = False
    result: object = None
    error: object = None
    capturing: bool = False


@dataclass(frozen=True, repr=False)
class _DeliveryRecord:
    delivery: object
    delivery_id: str
    context: object
    context_snapshot: tuple
    channel: object
    channel_snapshot: tuple
    stamp: object
    attempt_id: str


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
        self._callback_records = {}
        self._callback_lock = threading.RLock()
        self._context_lock = threading.Lock()
        self._captured_context = None
        self._owned_channel = None
        self._owned_channel_snapshot = None

    def _remaining(self, deadline):
        _number(deadline)
        now = _number(self._clock())
        _require(deadline > now)
        return now

    def _bound_context(self, ctx):
        scope, captured = _context(ctx)
        _require(captured == self._captured_context)
        return scope

    def _channel_fields(self, channel, ctx):
        scope = self._bound_context(ctx)
        _require(type(channel) is OwnedChannel and channel.context is ctx
                 and _text(channel.invocation_id, _UUID) and _text(channel.channel_id, _UUID)
                 and type(channel.transport_generation) is int and channel.transport_generation >= 1)
        return (id(ctx), _snapshot(scope), self._captured_context[1],
                channel.invocation_id, channel.channel_id, channel.transport_generation)

    def _channel(self, channel, ctx):
        captured = self._channel_fields(channel, ctx)
        if self._owned_channel is not None:
            _require(channel is self._owned_channel and captured == self._owned_channel_snapshot)
        return captured

    def _bound(self, ctx, channel):
        self._bound_context(ctx)
        self._channel(channel, ctx)

    def _workspace(self):
        return dict(self._captured_context[0][-1])['workspace_id']

    def _delivery_baseline(self, delivery, ctx=None):
        _require(type(delivery) is Delivery)
        record = self._deliveries.get(id(delivery))
        _require(record is not None and record.delivery is delivery
                 and delivery.context is record.context and delivery.channel is record.channel
                 and delivery.stamp is record.stamp and type(delivery.delivery_id) is str
                 and delivery.delivery_id == record.delivery_id)
        actual = delivery.context if ctx is None else ctx
        scope = self._bound_context(actual)
        _require(_context(actual)[1] == record.context_snapshot
                 and _context(delivery.context)[1] == record.context_snapshot)
        self._channel(delivery.channel, delivery.context)
        _require(self._channel_fields(delivery.channel, delivery.context) == record.channel_snapshot)
        return record, scope

    def _delivery(self, delivery, ctx=None):
        record, scope = self._delivery_baseline(delivery, ctx)
        self._coordinator._validate_final(record.stamp, self._validator_id, record.attempt_id, scope)
        self._coordinator._check_stamp(delivery.stamp, self._validator_id, scope)
        return scope

    def _callback_fields(self, callback, channel):
        self._bound(channel.context, channel)
        _require(type(callback) is CapturedCallback and callback.channel is channel
                 and _request_id(callback.request_id)
                 and type(callback.params) is MappingProxyType
                 and set(callback.params) == {'reason', 'previousAccountId'}
                 and type(callback.params['reason']) is str
                 and callback.params['reason'] == 'unauthorized')
        previous = callback.params['previousAccountId']
        _require(previous is None or (type(previous) is str
                 and previous == self._workspace()))
        return (id(channel), self._channel_fields(channel, channel.context),
                type(callback.request_id), callback.request_id,
                tuple(sorted(callback.params.items())), _number(callback.received_monotonic))

    def _callback_baseline(self, callback, channel):
        record = self._callback_records.get(id(callback))
        _require(record is not None and record.callback is callback
                 and self._callback_fields(callback, channel) == record.captured)
        return record

    def _callback(self, callback, channel, deadline):
        record = self._callback_baseline(callback, channel)
        now = self._remaining(deadline)
        self._callback_baseline(callback, channel)
        received = record.captured[-1]
        _require(received <= now and now < received + 9)
        self._transport.validate_callback(callback, channel, deadline=deadline)
        self._callback_baseline(callback, channel)

    def _validate(self, ctx, channel, scope, lease, source_lease, deadline, callback=None, *, claimed=False):
        self._remaining(deadline)
        self._bound(ctx, channel)
        try:
            self._coordinator._validator_current(self._validator_id, scope)
            self._coordinator.check(lease, scope, deadline=deadline)
        except AuthError:
            if claimed:
                raise AuthError('refresh_unknown') from None
            raise
        self._bound(ctx, channel)
        self._source.validate_current(ctx, source_lease, deadline=deadline)
        self._bound(ctx, channel)
        self._transport.validate_current(channel, ctx, deadline=deadline)
        self._bound(ctx, channel)
        if callback is not None:
            try:
                self._callback(callback, channel, deadline)
            except AuthError:
                if claimed:
                    raise AuthError('refresh_unknown') from None
                raise
        self._bound(ctx, channel)

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
        self._delivery_baseline(delivery)
        _require(_request_id(request_id) and _keys(params, 'reason previousAccountId'))
        _require(type(params['reason']) is str and params['reason'] == 'unauthorized')
        previous = params['previousAccountId']
        _require(previous is None or (type(previous) is str
                 and previous == self._workspace()))
        channel = delivery.channel
        key = (channel.channel_id, channel.transport_generation, type(request_id), request_id)
        original_params = tuple(sorted(params.items()))
        with self._callback_lock:
            existing = self._callbacks.get(key)
            if existing is not None and existing.error is not None:
                _require(existing.delivery is delivery)
                raise AuthError(existing.error)
            self._current(delivery, delivery.context, deadline)
            self._delivery(delivery)
            if existing is not None:
                try:
                    _require(not existing.capturing)
                    self._callback_baseline(existing.callback, channel)
                    _require(existing.delivery is delivery
                             and tuple(sorted(existing.callback.params.items())) == original_params)
                    return existing.callback
                except Exception as error:
                    existing.error = error.code if isinstance(error, AuthError) else 'authority_stale'
                    raise AuthError(existing.error) from None
            # Reserve the reader identity before its call. A rejected returned
            # capability (or an exceptional capture) leaves a permanent tombstone.
            record = _CallbackRecord(None, delivery, (), capturing=True)
            self._callbacks[key] = record
            code = None
            try:
                callback = self._transport.capture_callback(
                    channel, request_id, dict(original_params), deadline=deadline)
                record.callback = callback
                if type(callback) is CapturedCallback:
                    _require(id(callback) not in self._callback_records)
                    self._callback_records[id(callback)] = record
                record.captured = self._callback_fields(callback, channel)
                _require(type(callback.request_id) is type(request_id)
                         and callback.request_id == request_id
                         and tuple(sorted(callback.params.items())) == original_params)
                self._callback(callback, channel, deadline)
                now = self._remaining(min(deadline, record.captured[-1] + 9))
                _require(record.captured[-1] <= now)
                self._callback_baseline(callback, channel)
                self._delivery(delivery)
            except AuthError as error:
                code = error.code
            except Exception:
                code = 'authority_stale'
            record.capturing = False
            if code is not None:
                record.error = code
                raise AuthError(code)
            # A reentrant attempt may have failed this identity while its reader
            # was running. The original worker cannot revive that tombstone.
            if record.error is not None:
                raise AuthError(record.error)
            return callback

    def refresh(self, delivery, callback, *, deadline):
        return _safe(lambda: self._refresh(delivery, callback, deadline))

    def _refresh(self, delivery, callback, deadline):
        with self._callback_lock:
            _require(type(callback) is CapturedCallback)
            record = self._callback_records.get(id(callback))
            _require(record is not None and record.callback is callback and record.delivery is delivery)
            self._delivery_baseline(delivery)
            if record.error is not None:
                raise AuthError(record.error)
            _require(not record.capturing)
            self._callback_baseline(callback, delivery.channel)
            if record.result is not None:
                self._current(record.result, record.result.context, deadline)
                return record.result
            _require(not record.running)
            record.running = True
        code = None
        try:
            self._delivery(delivery)
            bounded = min(_number(deadline), record.captured[-1] + 9)
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
        # Freeze our request BEFORE handing its forgeable public fields to a seam.
        _require(type(request) is OAuthRequest)
        attempt, ctx = request.attempt_id, request.context
        start_mono, start_wall, budget = (request.started_monotonic,
                                         request.started_wall, request.deadline)
        captured_request = (attempt, start_mono, start_wall, budget)
        captured_types = tuple(type(value) for value in captured_request)

        def request_current():
            current = (request.attempt_id, request.started_monotonic,
                       request.started_wall, request.deadline)
            if (request.context is not ctx or tuple(type(value) for value in current) != captured_types
                    or current != captured_request):
                raise AuthError('refresh_unknown')
            self._bound(ctx, self._owned_channel)

        try:
            self._remaining(budget)
            request_current()
            response = self._oauth.exchange(request, refresh_token, deadline=budget)
        except Exception:
            raise AuthError('refresh_unknown') from None
        if type(response) is not TLSExchange:
            raise AuthError('refresh_unknown')
        # No injected callback runs between receipt and this independent capture.
        (response_attempt, response_context, endpoint, client, peer, ca, redirected,
         proxy, status, body, received_mono, received_wall) = (
            response.attempt_id, response.context, response.endpoint, response.client_id,
            response.peer_hostname, response.ca_verified, response.redirected,
            response.proxy_used, response.status, response.body,
            response.received_monotonic, response.received_wall)
        request_current()
        try:
            now = self._remaining(budget)
        except Exception:
            raise AuthError('refresh_unknown') from None
        request_current()
        invalid = 'auth_response_invalid' if type(status) is int and status == 200 else 'refresh_unknown'

        def response_require(condition):
            if not condition:
                raise AuthError(invalid)

        response_require(type(response_attempt) is str and response_attempt == attempt
                         and response_context is ctx)
        for actual, expected in ((endpoint, _ENDPOINT), (client, _CLIENT), (peer, 'auth.openai.com')):
            response_require(type(actual) is str and actual == expected)
        response_require(ca is True and redirected is False and proxy is False)
        response_require(type(status) is int and type(body) is bytes and len(body) <= 65536)
        response_require(type(received_mono) in (int, float) and math.isfinite(received_mono)
                         and start_mono <= received_mono <= now)
        evaluation = self._wall()
        request_current()
        response_require(type(received_wall) in (int, float) and math.isfinite(received_wall)
                         and received_wall >= 0 and type(evaluation) in (int, float)
                         and math.isfinite(evaluation) and start_wall <= received_wall <= evaluation)
        if status != 200:
            raise AuthError('refresh_unknown')
        code = None
        try:
            parsed = parse_token_response(
                status, body, scope, request_start_wall=start_wall,
                response_end_wall=received_wall, evaluation_wall=evaluation)
        except TokenResponseError as error:
            code = error.code
        if code is not None:
            raise AuthError(code)
        return parsed

    def _make_delivery(self, ctx, channel, stamp, attempt_id, scope):
        self._bound(ctx, channel)
        self._coordinator._validate_final(stamp, self._validator_id, attempt_id, scope)
        result = object.__new__(Delivery)
        for name, value in (('delivery_id', str(uuid.uuid4())), ('context', ctx),
                            ('channel', channel), ('stamp', stamp)):
            object.__setattr__(result, name, value)
        self._deliveries[id(result)] = _DeliveryRecord(
            result, result.delivery_id, ctx, self._captured_context, channel,
            self._owned_channel_snapshot, stamp, attempt_id)
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
                    channel_snapshot = self._channel(channel, ctx)
                    self._owned_channel = channel
                    self._owned_channel_snapshot = channel_snapshot
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
                    self._coordinator._claim_rotation(
                        lease, self._validator_id, reservation_guard=reservation, deadline=deadline)
                    self._bound(ctx, channel)
                    if callback is not None:
                        self._callback_baseline(callback, channel)
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
                            self._bound(ctx, channel)
                            self._coordinator._validator_current(self._validator_id, scope)
                            guard.validate_current(deadline=final)
                            self._bound(ctx, channel)
                            source_guard.validate_current(deadline=final)
                            self._bound(ctx, channel)
                            channel_guard.validate_current(deadline=final)
                            self._bound(ctx, channel)
                            if callback is not None:
                                self._callback(callback, channel, final)
                            self._remaining(final)
                            self._bound(ctx, channel)
                            if callback is not None:
                                self._callback_baseline(callback, channel)

                        final_check()
                        if not parsed.usable_at(self._wall()):
                            raise AuthError('auth_expired')
                        payload = {'accessToken': parsed.access_token,
                                   'chatgptAccountId': self._workspace(),
                                   'chatgptPlanType': None}
                        if callback is None:
                            payload['type'] = 'chatgptAuthTokens'
                        _require(len(json.dumps(payload, separators=(',', ':')).encode('ascii')) <= 32768)
                        final_check()
                        guard.begin_enqueue(reservation_guard=reservation, deadline=final)
                        self._bound(ctx, channel)
                        if callback is not None:
                            self._callback_baseline(callback, channel)
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
                        self._coordinator._claim_finish(
                            lease, guard=guard, publication=publication, deadline=final)
                        self._bound(ctx, channel)
                        if callback is not None:
                            self._callback_baseline(callback, channel)
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
