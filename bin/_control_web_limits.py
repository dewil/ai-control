"""Pure, bounded projection of account-bound cached subscription usage.

This module neither authorizes a caller nor attests a collector. Its caller
must supply the expected account from its approved registry.
"""
import re

_ACCOUNT = re.compile(r"[A-Za-z0-9_-]{1,80}", re.ASCII)
_PROVIDERS = ("codex", "claude")
_STATUSES = ("ok", "stale", "error", "locked", "unavailable")
_PLANS = ("Free", "Plus", "Pro", "Max", "Team", "Business", "Enterprise")
_WINDOWS = ("five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet")
_MAX_EPOCH = 253402300799


def _number(value, maximum):
    # Exact primitives before arithmetic: subclasses can execute callbacks.
    return type(value) in (int, float) and 0 <= value <= maximum


def _mapping(value):
    # Validate keys before get(): even a built-in dict can contain a foreign
    # key whose equality method would run on a colliding known-key lookup.
    return (type(value) is dict and len(value) <= 64
            and all(type(key) is str for key in value))


def project_limits(record, *, provider, account_id, now, stale_after=2700):
    """Return an independent allowlisted DTO (INV-WLIM-01..04)."""
    if (type(provider) is not str or provider not in _PROVIDERS
            or type(account_id) is not str or _ACCOUNT.fullmatch(account_id) is None
            or not _number(now, _MAX_EPOCH)
            or type(stale_after) is not int or stale_after <= 0):
        raise ValueError("invalid limits projection configuration")

    result = {"schema": 1, "provider": provider, "account_id": account_id,
              "status": "unavailable", "plan": None, "captured_at": None,
              "age_seconds": None, "windows": []}
    if not _mapping(record):
        return result
    schema = record.get("schema")
    source_provider = record.get("provider")
    source_account = record.get("account_id")
    status = record.get("status")
    captured = record.get("captured_at")
    if (type(schema) is not int or schema != 1
            or type(source_provider) is not str or source_provider != provider
            or type(source_account) is not str or source_account != account_id
            or type(status) is not str or status not in _STATUSES
            or not _number(captured, _MAX_EPOCH) or captured > now):
        return result

    age = now - captured
    plan = record.get("plan")
    result.update(status=status, captured_at=captured, age_seconds=age,
                  plan=plan if type(plan) is str and plan in _PLANS else None)
    if status != "ok":
        return result
    if age >= stale_after:
        result["status"] = "stale"
    windows = record.get("windows")
    if not _mapping(windows):
        return result
    for window_id in _WINDOWS:
        window = windows.get(window_id)
        if not _mapping(window):
            continue
        remaining = window.get("remaining")
        reset = window.get("resets_at")
        remaining = remaining if _number(remaining, 100) else None
        reset = reset if _number(reset, _MAX_EPOCH) else None
        if reset is not None and reset <= now:
            remaining = None
        result["windows"].append({"id": window_id,
                                  "remaining_percent": remaining,
                                  "resets_at": reset})
    return result
