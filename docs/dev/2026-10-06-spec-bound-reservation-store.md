# First bound reservation disk store — DRAFT before independent DESIGN

Module `bin/_control_web_bound_session_store.py`. First R+G disk slice of parent
bound-session-store contract, uses reviewed pure records DTO/codec, no duplicated
DTO definitions. No provider/auth/native/project-file effects. Only a caller-owned
private synthetic namespace is used in tests. Actual native admission remains later.

API constructor `BoundSessionStore(path,context_ref,*,clock=None,
monotonic_clock=None)`, no IO/clock sample. Path exact plain absolute POSIX lexical
canonical UTF8<=4096/noC0C1/surrogates, same lexical path rules as records root.
Trusted configured path, owner-shared global namespace, never per-account namespace.
Owner config guarantees outside project/Git/data and current credential directories;
this unit cannot infer current grant or registered project root from a string.
Expected owner uid=os.getuid() when operating; constructors do not probe filesystem.

`locked(context_ref,deadline,create=False)` is context manager yielding opaque base
or None (absent namespace with create=False), invalidated on exit, FD/lock always
closed/released. create plain bool; create=True creates only final namespace when
trusted existing parent available,0700. Every disk operation Linux-only with actual
renameat2(RENAME_NOREPLACE); unsupported platform store_unavailable BEFORE IO.
Pure prepare_create remains portable. No unsafe rename/link/overwrite fallback.

`lookup_create(base,context_ref,project,root,operation_id,deadline)` returns None
for absent base or absent R+G, otherwise BoundCreateReceipt unknown with real fresh
R/G commitments, C/I_session/I_native/A null.
`prepare_create(context_ref,project,root,session_ref,operation_id,deadline)` returns
PreparedBoundCreate; samples wall_ns once only AFTER valid syntax and live deadline,
then codec.prepare_create. No FS.
`publish_create(base,context_ref,prepared,deadline)` requires active base; validates
prepared same exact store scope BEFORE IO; returns unknown fresh R+G receipt only
after both durable/fenced. Matching existing R+G is immutable replay data only;
R-only/G-only/conflicting/foreign global G refuses, no reconstruction/repair.
No other fullstore API or accepted-session capability in this slice.

## Validation and budgets

Every method validates supplied fullref against frozen store capture FIRST. Then
base exact store/token/thread/lifetime identity where applicable BEFORE clock/FS,
then input DTO nested fullref and operation identity before IO. No fileno/index/FD
property on base; copies/foreign/raw/stale/cross-thread tokens refuse. None allowed
only readonly lookup. Base lifecycle never extends beyond locked context.

Use existing AccountError family from provider catalog; methods emit only
context_invalid/context_drift/invalid_request/store_unavailable. Pure codec errors
map exact caller codes; malformed/foreign disk data ALWAYS store_unavailable. Safe
str/repr, no raw path/OS exception messages. No public capability created from
arbitrary inode fields or fixture parents.

Lookup syntactically validates project [a-zA-Z0-9_-]{1,32}, root lexical rules,
operation UUIDv4 locally BEFORE computing K/reading disk (no invented session UUID
or prepare_create/clock to validate lookup). A session_ref is trusted for validation
only after freshly fenced matching R+G, never merely inferred from caller/disk R.
Owner proves current registered-root/grant authority separately immediately before
actual effects; this slice has no launch permission.

Absolute deadline finite plain int/float excluding bool, strictly future against
monotonic_clock default time.monotonic, never renewed. Namespace flock acquired
LOCK_EX|LOCK_NB bounded by min(original remaining,1second); timeout unavailable.
Trusted wall clock default time.time_ns gives plain int1..2**63-1 once per prepare;
invalid wall invalid_request. Bad monotonic/expiry/clock exceptions unavailable.
After any trusted clock callback revalidate active base and anchors before effects.
No arbitrary callback between final fences and publication.

## Namespace and leaves

Anchor absolute directory chain with no-follow directory FDs; owners current uid
or root, no group/other write except root-owned sticky ancestors such as /tmp.
Namespace exact owner0700; before/final pathname-vs-heldFD dev+ino/mode/owner checks.
Absent namespace lookup returns None; no parent creation or guessing. Leaf regular
owner0600/nlink1/no-follow,<=4096bytes, strictUTF8 duplicate-aware exact-key JSON,
no nonfinite/bool-for-int/surrogates. Final heldFD/currentname bytes+dev/ino/ctime
commitments freshly rechecked. No overwrite/unlink/cleanup recovery; orphan/temp
leaves retained/count. Errors after possible publication unavailable/unknown, not
permission to retry any native effect.

Namespace directory flock serializes trusted readers/writers/cap/temp/NOREPLACE/
fsync. Count ALL physical entries including malformed/temp/orphans. Maximum10000
retained leaves,10002 incl transients; reserve capacity for BOTH new leaves before
writing. Recheck cap/anchors through operation; no payloads filtered out of count.
First slice refuses namespaces containing recognized future C/I/A/stop-stage leaves
(any BC-*.C/A.json, BI-*.json, BS-*.json); no partial acceptance/downgrade. This
availability restriction is intentional until corresponding fullstore stages exist.

R exact parent record schema from pure codec and K SHA256 canonical
{context_ref,project,root,operation_id}; name BC-K.R.json. G exact
{schema:1,kind:bound_session_reservation,context_ref,project,root,session_ref,
operation_id,r_parent}, name BG-S-session_ref.json. Both fullref/project/root/
session/op identities match; r_parent exact fresh R commitment, role filename
checked by codec. G permanent global UUID reservation, no delete/reassign.

Under same lock initial publication checks R and global G absence. Write R then G
via owner0600 O_EXCL/no-follow temp, file fsync, Linux RENAME_NOREPLACE, directory
fsync; capture commitments AFTER rename. If R becomes visible without durable G,
operation permanently unavailable: no reconstruction even with matching R. If both
present exact matching, readonly replay yields unknown data, never dispatch.
Global foreign G fails before creating R for the conflicting session UUID.

## Acceptance

Independent DESIGN then frozen blind RED, implementation unchanged tests, distinct
SOURCE and exact complete Ubuntu CI. Synthetic positive Linux tests must use actual
NOREPLACE/FD/flock; Mac unsupported is reported honestly, not Linux success. Test
fullref-first, no constructor/prepare IO, opaque/thread/lifetime, cap/orphans/temp,
R/G corruption/conflict/globalUUID across accounts, actual no-replace, R-only
crash unrecoverable, inode/path replacement/finalfences, replay no clock/no writes,
shared deadline/busy and strict leaf schemas. No real credentials/project files or
server account/runtime operations. Full C/I/A/stop/native/auth gates remain separate.
