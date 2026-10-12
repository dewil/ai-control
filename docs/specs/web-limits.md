# Web subscription limits

## Scope
Control has two distinct contracts: the original pure projection of externally account-bound cached records, and the owner-only native Codex limits dashboard. Native source identity is reported by the fixed owned App Server at snapshot receipt time; it is not an alias or admission proof for a selected vendor profile. Native account activation and remote collectors remain separate obligations.

## Invariants
- INV-WLIM-01: Expected provider/account identity must match the cache record. Unbound legacy snapshots or foreign records never provide usage for another account. Identity equality does not attest provenance or authorize access.
- INV-WLIM-02: Unknown or invalid remaining is null, distinct from known zero. Expired windows cannot imply replenished capacity. Collector owns clamping; projection never alters it.
- INV-WLIM-03: Cache freshness and source errors are explicit. Age-stale last-known successful data retains its age marker; failed/locked/unavailable source has no current windows.
- INV-WLIM-04: Only allowlisted DTO fields reach consumers. Projection is bounded and pure, with no provider/credential/file/process calls, untrusted callbacks or mutable input/output aliases.

## Contract
Feature docs/dev/done/2026-10-06-spec-web-limits-projection.md gives exact types, clock limits, statuses, fields and public project_limits function. tests/test_control_web_limits.py traces these invariants.

## Known gaps
The existing digest cache has one section per provider and no account attestation. Integration cannot assign it to an arbitrary account. Account-aware legacy/remote collector routing remains in CONTROL-SUBSCRIPTIONS-LIMITS. The native LLM/Codex dashboard is a separate implementation; it does not assign this legacy cache to an account. A green pure projection alone still does not enable a dashboard.

## Decisions
06.10.2026: cached-only pure component proceeds independently of Mac account runtime, with synthetic tests and no production IO. Current fixed14 deployment scope unchanged.


## Native dashboard invariants (11.10.2026)

- INV-WLIM-10: owned source, response-bound identity, generation-fenced read/cache; no vendor-auth or session mutation.
- INV-WLIM-11: bounded allowlisted projection, real source age, expiration/rollback cannot invent fresh or replenished quota.
- INV-WLIM-12: owner-only API/broker, fixed operation, strict DTO, no-store and no raw errors.
- INV-WLIM-13: honest local-only coverage; unsupported vendors/nodes and legacy unbound cache never masquerade as known accounts.
- INV-WLIM-14: compact accessible quota display; unknown differs from known zero, keyboard/touch and 320px geometry preserved.
- INV-WLIM-15: Codex weekly scale stays7days with distinct normal×1 and primary×2 markers; no alteration of API reset/remaining.
- INV-WLIM-16: foreground-only polling, generation/abort fences, server+monotonic display clock; no background battery work.

Exact contract: docs/dev/done/2026-10-11-spec-limits-dashboard.md.
Traceability: tests/test_control_web_limits_dashboard_red.py (10..13,16),
tests/test_control_web_limits_dashboard_browser_red.py (11,14..16).
Pure helper tests and INV01..04 remain unchanged. Native runtime uses existing
installed sessions/broker/web files, with no deployment-scope expansion.


## Расход и общая шкала (11.10.2026)
- INV-WLIM-17: основное число и progressbar — расход=100−remaining_percent;
  остаток вторичен. Unknown/expired не становятся расходом0/100.
- INV-WLIM-18: для недельного Codex заполнение расхода и маркеры×1/×2
  расположены на общей шкале0–100%=7дней. Время и расход независимы;
  без якоря остаётся полоса расхода без выдуманных временных маркеров.
Семантика переиспользует ai-agent-limits-digest _bar/_elapsed_percent:
расход и прошедшее время движутся слева направо; Telegram glyph renderer
не переносится в HTML. Это текущий снимок, не история измерений.
Трассировка: tests/test_control_web_limits_spend_overlay_browser_red.py.


## Cached sources and delivery (11.10.2026)
- INV-WLIM-20: schema2 composes valid legacy nativev1 with cached sources;
  owner auth and independent source failure isolation remain mandatory.
- INV-WLIM-21: owner-only bounded nofollow reads; bot0664 legacy/unbound and
  localALP0600; no provider/auth/network/process from the reader or HTTP.
- INV-WLIM-22: Kimi fixed quota buckets; OpenRouterUSD/YandexCloudRUB prepaid
  metrics; native money is not subscription capacity, nodata != zero/current.
- INV-WLIM-23: only closed safeALPexport, mappedpseudonymousUUID refs,
  tickstarttime, no raw source metadata; bad clock isolated per account.
- INV-WLIM-24: spent quota/commonweeklyCodexmarkers and currency/prepaid
  scales are distinct; mobile320/360, stale/lastknown and lifecycle visible.
- INV-WLIM-25: separate fixed ownerSSH syncCLI, validated before transfer/write,
  bounded transport and atomicprivatecache. No worker viaHTTP. User timer
  is inactive until owner-approved export publication and read-only smoke.
Feature contract docs/dev/2026-10-11-spec-cached-limits-sources.md remains
active for externalALProllout. Code/bot delivery does not claim liveALPdata.
Tests test_control_web_cached_limits_backend_red.py,
 test_control_web_cached_limits_browser_red.py and
 test_control_web_alp_limits_sync_red.py trace these invariants.

## INV-WLIM26 — группы источников

Карточки сгруппированы: «Локальные» (LLM Codex/Claude/Kimi), «Облачные» (LLM OpenRouter/YandexGPT), «ALP» (ALP Codex/Claude). Все карточки, статусы и метрики сохраняются. Пустые группы скрыты; неизвестные сочетания отклоняются существующим закрытым валидатором.
Трассируемость: tests/test_control_web_limits_groups_browser_blind.py; подробности docs/dev/2026-10-11-spec-limits-navigation.md.

## INV-WLIM-27 — пользовательский экспорт выделенных ALP аккаунтов

SSH receiver читает только `/home/dwl/.local/state/ai-control/limits-export/limits-v1.json` на fixed alias `alp-ai-dev-1-dwl`. NSS user dwl должен совпадать с real/effective UID, конечный parent — owned directory0700 без symlink, файл — owned regular0600 без symlink/hardlink. Bounded read и проверки неизменности обязательны; отказ сохраняет старый cache без освежения квоты. DTO не содержит private identity/auth. Общий customer snapshot исключён.
Трассируемость: tests/test_control_web_alp_limits_sync_red.py; docs/dev/2026-10-12-spec-alp-owned-receiver.md.
