# Visible project activity

Owner CONTROL-WEB-SESSIONS. User reports sorting/count/activity unavailable. This amendment adds visible authoritative activity only; cold context-generation recovery is a distinct incident.

## INV-WSESS-19 visible activity amendment

Each project tile displays the existing authoritative session count and a separate visible last-activity label. For a known fresh or stale summary with non-null last_activity, display elapsed relative time using existing message-age formatting, derived solely from native max Thread.updatedAt. Exact local date, hour and minute appear on hover and through the time element title. Relative time is computed against current clock, never substituted for the authoritative timestamp. Stale activity remains explicitly marked stale. A confirmed null activity displays no activity; an unknown/unavailable summary displays activity unknown/unavailable, never a fabricated time or zero.

The time is ordinary text within the existing accessible project button, not a separate action. Existing count/activity ordering, alias ties, bounded tile sizes, aria-pressed, keyboard selection, project/auth generation fences and no sensitive browser storage remain unchanged. Rendering must preserve focus on the same project and viewport. Updating relative labels adds no network requests, native history reads or mutation. Reuse the existing local relative-time formatter; do not add a dependency.

Acceptance: visible time on known fresh/stale tiles; precise hover time; distinct null/unknown/unavailable; authoritative fixture changes reorder count/activity correctly and keep focused tile/scroll/selection; no extra network for relative-time rendering.
