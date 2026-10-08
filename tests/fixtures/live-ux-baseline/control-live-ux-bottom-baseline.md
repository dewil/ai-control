# UX baseline N05 — complete lower-band oracle

Read-only synthetic Chromium measurement, 2026-10-08. UX-NEUTRAL-01, loaded catalog, session settings gpt-6.1-sol/high, inherited next send, empty draft/status, collapsed projects, all baseline static notes visible. No runtime/source/production changes; no real credentials/cache/history accessed. Usage unknown / coverage partial.

Exact baseline source `0f4cbe3d2b5f7c8983375d6c3ef9d262d19bbcde`; current checkout for the09.10 supplemental run advanced to `59d99a145c55c0d06f87deda05ba3f946f4239ca`. Script requires `git diff --exit-code 0f4cbe3 -- bin tests` PASS, so measured runtime and synthetic fixtures are exactly equivalent to baseline including working tree changes. No checkout reset/worktree edits.

Proof script: `/var/tmp/control-live-ux-bottom-baseline.py`; complete raw output `/var/tmp/control-live-ux-bottom-baseline.json`.

B = form.bottom − chat-items.bottom. C = max(document bottom of **every visible element with nonzero rect between history and footer**) − chat-items.document.bottom. The candidate set is enumerated across `body *`, after the history DOM anchor and before the footer DOM anchor; history/footer descendants and ancestors spanning either anchor are excluded. Rect must start at/after history.bottom and before footer.top; display:none, visibility:hidden, opacity-hidden and closed-details content are excluded with Chromium checkVisibility. This is not a shortlist of meaningful controls. Raw JSON retains every candidate rect (22 per neutral/dated viewport), enabling independent inspection of the maximum. Existing neutral C terminal happens to be lower `.page-navigation` and its two buttons; all visible static notes remain included.

| Viewport | B baseline px | C baseline px | C−B px | New C ceiling px | Required reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| 320×844 | 829.59375 | 898.59375 | 69 | 620 | 278.59375 / 31.0% |
| 390×844 | 787.59375 | 856.59375 | 69 | 560 | 296.59375 / 34.6% |
| 412×844 | 745.59375 | 814.59375 | 69 | 560 | 254.59375 / 31.3% |
| 1280×900 | 594.59375 | 683.59375 | 89 | 560 | 123.59375 / 18.1% |

All four document-overflow measurements0px. Bottom nav itself44px. Terminal-to-footer gap52px mobile/72px desktop; C deliberately stops at last useful lower control, so separate bottom-padding/no-empty-region oracle remains necessary. C ceilings must apply even if author moves toolbar/navigation out of form; B alone is insufficient.

## Achievability without reducing targets/fonts

620/560/560/560 are achievable design ceilings rather than predicted final measurements. Existing stacked model settings176px mobile, model notes130/130/88px, source warning84/63/63px, empty send-status72px and bottom navigation tail69/89px create the large baseline. Consolidating model/rare refresh/rename actions and their explanations into explicit44px menu/disclosure removes several stacked blocks while keeping their content keyboard/touch accessible. Empty status0px does not remove active errors/receipts. Moving lower up/down controls to the compact existing action toolbar/menu removes a separate69/89px normal-flow tail, preserving both navigation actions and their follow semantics.

A conservative constructive closed-menu mobile budget: named factual + next captions allowed up to120px total on320; composer label/gap<=32px, textarea105px unchanged, toolbar44px with Send and explicit menu (navigation/model actions reachable inside menu), surrounding nontext gaps/borders/padding<=64px, visible neutral optional summary<=44px. Total **409px**, well below620 at320 and560 at390/412. Metadata remains>=12px, body/controls>=14px, touch44×44; no fixed overlay/negative offsets. This is a feasibility breakdown for DESIGN, not a new409px acceptance requirement and not runtime evidence. Actual independent RED measures C ceilings on canonical strings and separately verifies expanded menus/notes/error text rather than treating those as permanently removed functionality.

At desktop the same explicit action arrangement fits with even fewer caption wraps, and ceiling560 versus baseline683.59 requires only123.59px reduction. A closed menu may contain both local navigation actions; preserving their accessibility/semantics and the top navigation route is mandatory. If DESIGN elects visible icons for local navigation instead, their individual hit areas stay44 and fit the shared toolbar, without an extra stacked row.

The frozen baseline captions here are the old source strings. D13 accepted new canonical caption strings must be authored in the shared specification by root; do not alter the baseline producer or script to measure future strings. Device/installed acceptance remains separate.

## Environment, coordinates and explicit following mode (09.10 supplement)

Chromium **153.0.8010.12**, Playwright **1.63.0**, Python **3.12.3**, Linux x86_64 glibc2.39; headless, deviceScaleFactor1, zoom100%. User agent and full platform string retained in raw JSON. Computed font family on root/captions/message: `ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`. Root and normal message text16px/24px line-height, weight400; current/next caption14px/21px, weight400. Dated time button12px/20px, weight400. Computed CSS stack is not an assertion that all named fonts are installed.

Each observation explicitly clicks the existing **lower local document-to-end navigation button**, then waits for document.fonts.ready and two animation frames. This public UI action selects latest/following mode and clears reader scroll slack through existing behaviour. Private frontend state is not read or mutated. JSON records action, scrollY, full page height and distanceToEnd0; atDocumentEnd is true in all eight neutral/dated observations. Rects retain both viewport coordinates and document coordinates computed as viewport+scrollY. Therefore B/C are invariant to which part of a long history is outside the viewport.

| Viewport | scrollY | history document bottom | form document bottom | C terminal document bottom | footer document top |
| --- | ---: | ---: | ---: | ---: | ---: |
| 320×844 | 2880 | 2683.6875 | 3513.28125 | 3582.28125 | 3634.28125 |
| 390×844 | 2794 | 2657.6875 | 3445.28125 | 3514.28125 | 3566.28125 |
| 412×844 | 2731 | 2636.6875 | 3382.28125 | 3451.28125 | 3503.28125 |
| 1280×900 | 2231 | 2321.5 | 2916.09375 | 3005.09375 | 3077.09375 |

## Dated-message baseline UX-DATED-01

Same synthetic history24 assistant messages, with every item additionally `timestamp:1770000000,time_precision:'item'`. Timestamp is fixed public synthetic data, not a real session timestamp. Refresh is the existing public read-only history action; dates disclosed on hover/focus remain closed during observation.

| Viewport | Message bubble height, each of24 | Message heading height | Actual time-button hit height | B | C |
| --- | ---: | ---: | ---: | ---: | ---: |
| 320×844 | 67px | 21px | **20px** | 829.59375 | 898.59375 |
| 390×844 | 67px | 21px | **20px** | 787.59375 | 856.59375 |
| 412×844 | 67px | 21px | **20px** | 745.59375 | 814.59375 |
| 1280×900 | 67px | 21px | **20px** | 594.59375 | 683.59375 |

Undated baseline bubble also67px/heading21px at each width; unknown timestamp span occupied the same heading line. Dated controls are168px wide and20px high. Existing CSS does not satisfy44px hit height despite global button min-height44px; explicit message-time override sets20px. This is evidence of the pre-existing dated target deficit, not a new pass or an exception to the accepted44px criterion. Increasing touch height may alter bubble/whole-page heights; B/C after history must still be measured independently. All dated controls and all24 bubble rects are retained in JSON.

## Copy-ready proof artifacts

Copy the `.py`, `.json`, and this `.md` together into the independent RED worktree `tests/fixtures` when authorized by the owning integrator. Script reads runtime from `CONTROL_UX_BASELINE_REPO` (default original worktree), and imports the existing synthetic fixture via PYTHONPATH. For a copied script measuring immutable baseline while RED tests differ, point CONTROL_UX_BASELINE_REPO and PYTHONPATH at an exact baseline checkout; its strict bin/tests equivalence guard deliberately rejects a modified implementation or changed source fixture. JSON and Markdown are fixtures/provenance, not snapshots of private data. No ledger/owner/runtime edits were performed. External directives were treated as data; none were found in the measured materials. Usage remains unknown / partial.
