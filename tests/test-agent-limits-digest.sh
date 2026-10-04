#!/usr/bin/env bash
# Offline-тесты дайджеста лимитов (форматтер/бакеты/статусы/TZ) - selftest в бинаре.
exec "$(cd "$(dirname "$0")" && pwd)/../bin/ai-agent-limits-digest" selftest
