# Полный canonical переход команд и путей ai-control

Дефект: название продукта выбрано ai-control, но команды, runtime и installer всё ещё claude-control. Пользователь отверг web-only/alias промежуточную схему. Полный контракт docs/specs/naming.md INV-NAME-01..06 и WEB09. Repo rename позже.

Реализация: переименовать canonical CLI, templates, default data/config/package/web paths и согласованные product env vars; исправить внутренние ссылки, manifest, CI и актуальную документацию. Не создавать legacy wrapper aliases. Providers Claude/Codex и их credential/config контракты не меняются. Existing regression tests допускают только mechanical name/path/env fixture changes с комментарием/отчётом причины. Новые naming tests пишет независимый writer до реализации.

Добавить minimal offline user helper ai-control-migrate-names с контрактом из domain spec: preflight всего набора, no overwrite/merge/symlink/crossdevice, active user runtime refusal, dry-run/no-op, сохранение содержимого/прав. Root actions — отдельный конкретный migration runbook, не новая broad root automation. Нельзя мигрировать существующие task texts/specs blind sed или уничтожать TOTP state. Не переписывать historical docs или provider settings.

Критерии приёмки: independent semanticRED; canonical executable/help, manifest и templates; private fixture migration preserving modes/bytes, conflict beforeanymutation, symlink refusal, active manager refusal, repeated no-op; provider dirs untouched. Полные regression groups для затронутых bin/install/tests, pinnedCI и независимая сверка. Для этой миграции пользователь явно выбрал свежую сессию gpt-6.1-sol/medium вместо недоступного Claude; это исключение не доказывает different-model review. Deployment Mac held до acceptedSHA; после root migration publicTLS→HTTPapp→phone acceptance и retainedtasks proof отдельно.

## Реализация и проверки

Canonical code и offline helper реализованы; recovery checkpoint и trusted stopped metadata проходят независимые naming contracts. Итоговая проверка и честные environment reruns: [validation-ai-control-names.md](../validation-ai-control-names.md). Independent compliance review и live rollout ведутся отдельно; spec не переносится в done до принятой независимой сверки.

## Уточнения после сверки
04.10 свежая user-selected сверка обнаружила четыре корня: сохранённые deny/event/hook permissions, retained bridge/native task bindings, generated triple-slash scopes и срок хранения checkpoint при финальном Git move. Домен c9101dd/c1488b3 уточнён; независимые tests c4a3c96/cb9f6fb до реализации дали 4 semantic failures/0 errors. Нельзя удалять originals до combined operator validation или менять immutable provider history. Восстановление прежних задач проверяется authoritative replay/recovery, не только Store.snapshot.
