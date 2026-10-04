#!/usr/bin/env bash
set -euo pipefail
umask 077
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/test-bot-answer-recovery.py" "$@"
