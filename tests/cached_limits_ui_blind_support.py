"""Synthetic exact public V2 DTOs; never reads real caches or provider state."""
from copy import deepcopy

import limits_dashboard_blind_support as native

NOW = native.NOW
DAY = native.DAY
ALP_REF = 'b' * 64


def window(provider, bucket, remaining=75, duration=300):
    start = NOW - (DAY if duration == 10080 else 3600)
    return dict(id=provider + ':' + bucket, bucket=bucket,
                duration_minutes=duration, remaining_percent=remaining,
                resets_at=start + duration * 60 if duration else None,
                window_started_at=start if duration else None,
                anchor='derived_reset_and_duration' if duration else None)


def source(provider, *, node='llm', kind='quota', age=120, status='ok', reason=None):
    return dict(node_id=node, provider=provider, kind=kind,
                identity='unbound' if node == 'llm' else 'collector_mapped',
                account_ref=None if node == 'llm' else ALP_REF,
                origin='bot_cache' if node == 'llm' else 'alp_export',
                status=status, reason=reason, observed_at=NOW-age,
                observation_basis='provider_capture' if kind == 'prepaid' else 'snapshot_tick',
                age_seconds=age, max_age_seconds=2700,
                windows=[], prepaid=None, last_known=None)


def kimi(age=120):
    value = source('kimi', age=age)
    value['windows'] = [window('kimi', bucket, remaining, duration)
                        for bucket, remaining, duration in (
                            ('five_hour', 100, 300), ('seven_day', 75, 10080),
                            ('month_total', 40, None), ('month_code', 0, None))]
    return value


def prepaid(provider='openrouter', balance=75, scale=100, age=240):
    value = source(provider, kind='prepaid', age=age)
    value['prepaid'] = dict(currency='USD' if provider == 'openrouter' else 'RUB',
                           balance=balance, scale=scale, scale_at=NOW-DAY if scale else None,
                           spend_day=1.25, spend_week=8.5, burn_per_day=2,
                           forecast_days=4.5)
    return value


def alp(provider='codex', missing=False):
    value = source(provider, node='alp', age=420)
    if missing:
        value.update(identity='unknown', account_ref=None, status='unavailable',
                     reason='missing_source', observed_at=None,
                     observation_basis='unknown', age_seconds=None)
    else:
        value['windows'] = [window(provider, 'secondary' if provider == 'codex' else 'seven_day',
                                   60, 10080)]
    return value


def overview(sources=None, native_value=None):
    return dict(schema=2, server_now=NOW,
                native=deepcopy(native_value if native_value is not None else native.overview()),
                cached_sources=deepcopy(sources if sources is not None else [
                    kimi(), prepaid(), prepaid('yandex', balance=375, scale=500, age=420),
                    alp('claude', missing=True), alp(missing=True)]))
