# Полный canonical переход команд и путей ai-control

Дефект: название продукта выбрано ai-control, но команды, runtime и installer всё ещё claude-control. Пользователь отверг web-only/alias промежуточную схему. Полный контракт docs/specs/naming.md INV-NAME-01..06 и WEB09. Repo rename позже.

Реализация: переименовать canonical CLI, templates, default data/config/package/web paths и согласованные product env vars; исправить внутренние ссылки, manifest, CI и актуальную документацию. Не создавать legacy wrapper aliases. Providers Claude/Codex и их credential/config контракты не меняются. Existing regression tests допускают только mechanical name/path/env fixture changes с комментарием/отчётом причины. Новые naming tests пишет независимый writer до реализации.

Добавить minimal offline user helper ai-control-migrate-names с контрактом из domain spec: preflight всего набора, no overwrite/merge/symlink/crossdevice, active user runtime refusal, dry-run/no-op, сохранение содержимого/прав. Root actions — отдельный конкретный migration runbook, не новая broad root automation. Нельзя мигрировать существующие task texts/specs blind sed или уничтожать TOTP state. Не переписывать historical docs или provider settings.

Критерии приёмки: independent semanticRED; canonical executable/help, manifest и templates; private fixture migration preserving modes/bytes, conflict beforeanymutation, symlink refusal, active manager refusal, repeated no-op; provider dirs untouched. Полные regression groups для затронутых bin/install/tests, pinnedCI и distinct-modelreview. Deployment Mac held до acceptedSHA; после root migration publicTLS→HTTPapp→phone acceptance и retainedtasks proof отдельно.
