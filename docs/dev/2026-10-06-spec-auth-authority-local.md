# Local auth authority — bounded first Mac codeunit

SOURCE PREPARATION ONLY. New bin/_control_codex_auth_authority.py, stdlib only.
No token/OAuth/TLS/native/filesystem/process/network or production Admission.
Purpose: account-local refresh serialization, generations and quarantine; dependencies
must supply external delivery guards before this authority is integrated into native.
Parent auth5d29129 + Mac final fence amendment; INV-ACCOUNT04/05/09/13/14.

## Exact API

AuthError(code): ValueError, closed authority_stale/refresh_busy/refresh_unknown/
unsupported_auth_profile/auth_expired/auth_unavailable/auth_response_invalid/
identity_mismatch/owned_host_unproven/issuer_semantics_unproven. str/code safe code;
invalid unknown code sanitized to authority_stale, never arbitrary exception text.
AuthScope(reference,principal) frozen, repr=False, deep immutable private mapping.
Exact V2 reference fields schema2/provider_idcodex/account_id/profile_instance_id/
adapter_revision/registration_snapshot; snapshot dev>=0/ino>0/ctime_ns>0/hash64hex.
Account grammar [a-z][a-z0-9_-]{0,31}; instance canonicalUUIDv4; schema ints notbool;
adapter_revision codex-chatgpt-external-auth-host-v2. principal exact kind
openid_subject_workspace, issuer https://auth.openai.com, subject printableASCII1..255,
workspace_id ASCII[A-Za-z0-9_-]{1,128}. Extra/invalid keys reject authority_stale.
Scope constructor does no IO, path or native admission; callers cannot override scope.

AuthCoordinator(*,clock=time.monotonic): one shared object per Control owner.
open(scope,*,deadline)->opaque AuthorityLease; exact account key provider/account.
First capture freezes ref/principal, generation1/credential0. Later different
ref/principal sameaccount authority_stale permanently (no automatic rebind/reset).
Other account independent. Refresh mutex wait<=min(remaining,0.5s), busy refresh_busy.
check(lease,scope,*,deadline): exact owner/thread/active lease, scope unchanged,
notquarantined/deadline future, else authority_stale; no secret/native access.
release(lease): sameowner/thread; idempotent; foreign/cross-thread reject, never
unlock another account/owner lock. Released lease unusable except own quarantine.
quarantine(lease,code): exact owner/thread capability (active or released), closed
code required; once freezes quarantine and increments owner_generation, denies ALL
further account checks/open/stamps; repeated quarantine no extra generation/reset.
Unknown code authority_stale and no state mutation. Other account unchanged.

Guard coordinator.delivery_guard(lease,scope,*,deadline): context manager holding
peraccount RLock; wait min(remaining,1s). Captures lease/thread/fullscope/generation;
window=min(caller deadline,entryclock+1s), never renews. Same-thread quarantine is
allowed with RLock and invalidates guard immediately. Other-thread open independent
accounts must work; sameaccount mutation waits bound then can invalidate.
guard.begin_enqueue(): once, verifies live guard/thread/lease/scope/generation and
window; duplicate authority_stale; local marker only, DOES NOT send native.
guard.confirm(): only after begin, once, checks same live authority/window; local
caller-attested confirmed marker, not native proof. Duplicate/refused authority_stale.
publish_delivery(lease,*,guard,deadline)->AuthorityStamp requires same active guard,
begun+confirmed, once; deadline<=guard original window and strictlyfuture. Returns
frozen reprFalse stamp(owner_generation,credential_generation), increments account
credential once only. Out-ofguard/foreign/expired/unconfirmed/duplicate rejects.
Guard expires/exit no auto publication/redelivery/quarantine, because pure unit
cannot know nativeeffects; real caller must quarantine unknown effect outcomes.
Release during guard refuses before unlock (caller cannot free refresh lease early).
All capability classes opaque reprFalse: no public fileno/index/FD/lock attributes,
no accepted deserialized/fabricated lookalike, identity registry rejects copy/foreign.

## Test obligations (independent blind RED before source)

Scope exact/plainint/deepfreeze/secret-free repr; A/B keys; sameaccount changed
reference/principal refusal; bounded busy; wrongowner/thread/released lease; duplicate
release; reentrant quarantine beforebegin/duringconfirm/publish; no stamp after
invalidation; guard wrongthread/foreign/expired/outofscope; begin+confirm+publish
order/duplicate; releasewhileguard refusal; credential increments onlypublication;
concurrentA-held Bprogress; deadlinefinite/bool/expired; no IO constructor.
Synthetic tests prove local authority ONLY; no native login, production account
access or server capability is advertised by this module. Full callback/validator
and Linux launcher/store remain separate slices.
