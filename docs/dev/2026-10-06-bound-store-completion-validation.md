# Complete bound-session store: source and Linux validation

This extends the accepted R/G reservation store through C/I/A/S/T. It is an
isolated filesystem component; receipts do not authorize native launch, refresh,
drain, account activation, or server installation.

Frozen DESIGN `3386848cb8359e8c79447419ab7b663ea53bca9e`, spec SHA256
`0f5f46211b06d9dff798874d95926d1c4a8f671b947dace0d5d7be511822063e`, received two
independent reviews. Blind test-only RED `69b8c6d6aeea0c5c1431b3d076250291be9c2643`
received independent QA. Actual Linux observed 94 tests, 105 missing-API assertion
failures, zero errors/skips; the accepted 25 R/G tests passed.

Initial source `04dec68` failed positive Linux paths because receipt-derived
immutable context mappings reached JSON hashing without primitive capture.
Correction `e105d0596d3c3e7717a155f5ca287602ce9dbe8f` preserves all frozen tests
and DTOs. Source SHA256:
`d2b647063e3aa6331adb15a9867ea1e87a7a0c88cc50949fb8265f9cc3cb23c9`.

Actual Linux: 94 completion tests and 25 accepted reservation/fault tests passed,
zero failures/errors/skips. This includes real renameat2 NOREPLACE, flock, fsync,
inode/ancestor fences, capacity bounds, crash recovery and terminal refusal.
Strict noncanonical one-I recovery passed both orders with byte identity.
Evidence: private synthetic `/tmp/mac-bound-author-green.EqlZbQ` on the Linux
test host. Tests mounted public source and synthetic tmpfs only; operator homes,
current auth/grants, provider network and runtimes were inaccessible.

Separate configured gpt-6-sol/high SOURCE review passed that exact source against
the frozen contract. Independent private probes checked complete progression,
equal native IDs across contexts, foreign-locator rejection and no recreation of
a removed accepted stop. Mac probes used a synthetic NOREPLACE shim; they do not
replace the actual Linux evidence above.

The configured-create browser fixture also includes the independently reviewed
response-completion barrier from `8eee3d0`, preserving its original assertions.
Full hosted CI for the final integration head is pending and must pass every stage
before this integration is called CI-ready. Whole account preparation remains
incomplete; host/TLS, durable quarantine, owned transport/launcher, packaging and
later operational admission are separate gates. The existing store manifest leaf
is reused. No installed package, credentials or runtime was changed.
