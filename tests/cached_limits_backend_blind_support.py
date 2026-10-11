"""Synthetic cached-limits fixtures; no production files or provider requests."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import limits_dashboard_blind_support as native

NOW = native.NOW
PRIVATE = native.PRIVATE
REF = 'abcdefab-cdef-4abc-8def-abcdefabcdef'
SOURCE_KEYS = {'node_id', 'provider', 'kind', 'identity', 'account_ref', 'origin',
               'status', 'reason', 'observed_at', 'observation_basis', 'age_seconds',
               'max_age_seconds', 'windows', 'prepaid', 'last_known'}
PREPAID_KEYS = {'currency', 'balance', 'scale', 'scale_at', 'spend_day', 'spend_week',
                'burn_per_day', 'forecast_days'}


def stamp(epoch=NOW):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace('+00:00', 'Z')


def bot():
    kimi = {'status': 'ok', 'private': PRIVATE}
    for key, remaining in zip(('five_hour', 'seven_day', 'month_total', 'month_code'),
                              (75, 50, 25, 0)):
        kimi[key] = {'remaining': remaining, 'resets_at': stamp(NOW + 3600)}
    money = dict(status='ok', captured_at=stamp(NOW-20), balance=9.25,
                 scale=10, scale_at=stamp(NOW-86400), spend_day=.5, spend_week=2,
                 burn_per_day=.25, forecast_days=37, details=PRIVATE)
    return dict(received_at=stamp(), snapshot=dict(captured_at=stamp(NOW-10),
                kimi=kimi, openrouter=deepcopy(money), yandex=deepcopy(money),
                claude={'private': PRIVATE}, codex={'private': PRIVATE}))


def alp_account(provider='codex', ref=REF, **extra):
    value = dict(account_ref=ref, provider=provider, status='ok',
                 observed_at=stamp(NOW-30), observed_at_semantics='tick_start',
                 windows=[dict(slot='primary_window', used_percent=25,
                               reset=stamp(NOW+3600), duration_seconds=604800)])
    value.update(extra)
    return value


def alp(*accounts):
    return dict(schema_version=1, node_id='alp', exported_at=stamp(),
                accounts=list(accounts or (alp_account(),)))


def hashed(provider='codex', ref=REF):
    return hashlib.sha256(('alp-limits-account:'+provider+':'+ref).encode()).hexdigest()


def source(provider='openrouter', **extra):
    value = dict(node_id='llm', provider=provider, kind='prepaid', identity='unbound',
                 account_ref=None, origin='bot_cache', status='ok', reason=None,
                 observed_at=NOW-20, observation_basis='provider_capture', age_seconds=20,
                 max_age_seconds=2700, windows=[], prepaid=dict(currency='USD',
                 balance=9.25, scale=10, scale_at=NOW-86400, spend_day=.5,
                 spend_week=2, burn_per_day=.25, forecast_days=37), last_known=None)
    if provider == 'kimi':
        value.update(kind='quota', prepaid=None, observation_basis='snapshot_tick',
                     windows=[dict(id='five_hour', bucket='five_hour', duration_minutes=300,
                     remaining_percent=75, resets_at=NOW+3600,
                     window_started_at=NOW+3600-18000, anchor='derived_reset_and_duration')])
    value.update(extra)
    return value


def wrapper(*sources):
    return dict(schema=2, server_now=NOW, native=native.overview(),
                cached_sources=list(sources or (source(), source('kimi'))))
