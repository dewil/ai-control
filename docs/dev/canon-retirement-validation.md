# Проверка удаления версионной раскатки Toolkit

Оператор canon-maintainer, его binary/templates/exclusive suite/mock и manifest/install routes удалены. Общий source-only helper убирает прежнюю установку после подтверждённой остановки; повторная очистка, masks, dangling links, manager-loaded units без файлов, stop/query/reload failures и dry-run проверены. Harvest delivery, JSON pending/T25, ручной lifecycle и receipts сохранены; удалён только wake. SHA pinning, данные клиентов, история, env, бэкапы и прочие runtime компоненты не изменены. Исторические operator docs явно архивированы.

Независимые тесты созданы до реализации. Baseline: 8 сценариев (6 semantic RED), 7 edges (6 RED), 3 manager cases (3 RED). По замечаниям review пять дополнительных semantic RED закоммичены до исправления. Final: 23 retirement tests GREEN. Изменения test fixtures исправили только моделирование публичного systemctl show/state; исходные assertions сохранены.

Root regression: все 697 Python tests GREEN, включая 23 retirement cases. Сохранённые 10 component suites GREEN: installer completeness78, idempotence11, macOS legacy15, harvest62, CLI90, schedule256, sessions porcelain34, up/down46, no-systemd28 и review. IO33 дополнительно GREEN у автора. Exact ShellCheck CI set плюс новый helper и diff check GREEN. Сетевой harvest corpus не запускался: это отдельный opt-in suite.

Secure Codex fixtures требуют private parents и kernel FLOCK в /proc/locks. Первоначальный TMPDIR не давал этого доказательства; затронутые suites повторены на private /var/tmp с umask077 без ослабления runtime checks.

Независимый read-only compliance: отдельная сессия actual gpt-6-sol/medium, автор actual gpt-6.1-sol. Первый review по0e86272 выявил failed-state gate, stale pending help и gap перед destructive effects. Пять новых RED воспроизвели замечания. Та же сессия повторно проверила fec4cf4 и дала PASS; обе фактические модели/effort подтверждены CLI header и rollout. Проверки перед отдельными systemd/filesystem effects не являются атомарной защитой от same-UID ручного запуска.

Побочные существующие расхождения INV-CANON-13/15 и общий installer dry-run template записаны отдельно; retirement не меняет их поведение.

Локальная приёмка после merge: только обновление установленного harvest и shared retirement helper, без полного install/restart других служб. Проверяются отсутствие legacy binary/units/enable-links, повторная очистка, installed harvest delivery/pending/no-wake, прежние PID/runtime states и 48 побайтно неизменённых соседних scripts.
