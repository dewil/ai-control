#!/usr/bin/env bash
# Legacy runner fixtures still need authoritative control admission. Initialize
# through the real writer; absence of provider_binding remains legacy-unbound.
init_legacy_control() {
  local dir="$1" io="$HERE/../bin/ai-agent-io"
  [[ ! -e "$dir/control.json" ]] || return 0
  "$io" control-init "$dir" '{"schema":1,"seq":0,"desired":"running","generation":1,"lease":{"state":"active","start_attempt_id":"test-attempt"},"acceptance":{"status":"pending"},"hold":null,"attention":null,"handoff":null}' >/dev/null
}
