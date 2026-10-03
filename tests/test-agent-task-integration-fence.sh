#!/usr/bin/env bash
# Independent public CLI integration contract suite: INV-TASK-39/41/42/51.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/test-agent-task-integration-fence.py"
