# Удаление версионной раскатки Toolkit из Control

Владелец CANON-RETIRE-VERSION-ROLLOUT-20261003. Dwl явно поручил убрать механизм раскатки через версии.

Toolkit больше не содержит canon-vN release engine. Control не должен предлагать, устанавливать, запускать по таймеру или сигналу harvest старый canon-maintainer. Удалить оператор, принадлежащие только ему systemd templates/tests/активные инструкции и запись scripts.manifest. Install на существующей машине должен отключать/убирать только ранее установленный старый оператор/его service и timer, не трогая клиентские repositories/worktrees/PR/архивы, other service/config/env. Не создавать замену, не рестартовать unrelated services ради этого изменения. Uninstall/CI не должны зависеть от удаленных template/binary/test paths.

Harvest должен продолжать доставлять и подтверждать upstream-брифы; убрать только сигнал/маркер/вызов удаленного reconciler. Остальная семантика доставки/receipt/локальных данных не меняется. Перед удалением sharedhelpers проверить потребителей. Старые version tests удаляются вместе с их exclusively-owned implementation; общие install/manifest/harvest тесты сохраняются и актуализируются без ослабления оставшегося поведения.

SHA pinning bootstrap/sync/migrate — безопасность операций, не версионная раскатка; сохранить. Git старые теги/releases, данные проектного парка и старые client archives не удалять. Текущий установленный Linux timer отключен до исходников, service был inactive/dead; окончательно удалить остатки установленного оператора после проверенного результата. Машинные действия с backup, без значения env/секретов в артефактах.

Приемка: независимые сценарии/RED до реализации; no live routes to canon-vN operator in install/CLI/harvest/docs/manifest/workflows; корректное повторное удаление старой установки; modernotherCLI/install/manifest/harvest CI GREEN; actualothermodelreview; публикация и ограниченная локальная установка согласованного результата. Control foreignwork не перезаписывать — isolatedworktree от актуального origin/main.


## Уточнение Control и трассируемость

Generic read-only `pending` JSON CLI и T25 сохраняются. Удаляется только `_emit_canon_trigger`, его вызов, owned marker/env wake coupling и T17. Legacy cleanup не запускает оператор и не зависит от удалённых templates; сбой остановки не скрывается успешным удалением активного оператора. Повторная очистка отсутствующих остатков безопасна. Unrelated services не рестартуются ради retirement; обычная установка сохраняет свой прежний контракт.

- INV-CANONRET-01: чистая установка и manifest не поставляют удалённый оператор.
- INV-CANONRET-02: обновление удаляет только legacy operator binary/units, повтор безопасен; остановка и reload проверяются.
- INV-CANONRET-03: uninstall не зависит от удалённых исходников и сохраняет пользовательские данные.
- INV-CANONRET-04: harvest сохраняет delivery/receipt/pending/manual lifecycle без wake.
- INV-CANONRET-05: остальные Control компоненты, SHA pinning, история и клиентские данные сохраняются.
- INV-CANONRET-06: активные CLI/docs/workflows не предлагают старую раскатку, архивные сведения явно исторические.
