# Совместимость Codex native transport

INV-COMPAT-03: ordinary mutation admission допускает exact0.160.0/0.161.0/
0.162.1 после сверки официальных wire schemas; frontend и ownerbroker
показывают тот же статус reviewed. Unknown versions остаются read-compatible
только по фиксированным read contracts; write запрещён до wire/receipt.
Owner/socket/peer/account-context/generation fences обязательны независимо
от версии. Этот инцидент не реализует универсальный capability discovery.

INV-COMPAT-04: очередь/steer допускают exact0.161.0/0.162.1 отдельно от
ordinary admission;0.160.0 queue не поддерживает. Доставка неизвестного
результата не повторяется автоматически, queue snapshot transfer предупреждает
о concurrent edits. Callback/participation/approval lifecycle guards не
расширяются этой правкой. Схема не доказывает атомарность runtime.

11.10: свежие official CLI schemas0.161.0/0.162.1, совместимые optional
additions; отдельная native0.162.1 fixture queue start/replay/finalnonce/
archive/context equality PASS. Рабочие чаты и vendor auth не изменялись.
Трассировка: test_control_web_codex_0162_mutations_blind.py и
 test_control_web_codex_0162_browser_blind.py. Публичный feature contract
 docs/dev/done/2026-10-11-spec-codex-0162-mutations.md.
