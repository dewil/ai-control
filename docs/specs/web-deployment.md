# Подписанная поставка web

## Граница домена

Root helper устанавливает только фиксированный signed web package и управляет
двумя разрешенными службами. Private app config/storage и публичный APK catalog
имеют отдельные транзакции; native/provider auth не относится к deployment.
Принятая база R5 `0ea544756765c68ee3fea262a8a77ab4d4b8fe41` остается исходным
exact14. Расширение exact16 - DESIGN, не установленное состояние.

## Инварианты

- INV-DEPLOY-01: Target paths, mode и службы образуют фиксированный allowlist. Payload никогда не исполняется root helper; hooks и self-update отсутствуют.
- INV-DEPLOY-02: Прежний root-owned Ed25519 trust key авторизует exact bounded strict manifest и проверенные snapshot bytes. Issuer secret не публикуется.
- INV-DEPLOY-03: Root-private accepted baseline/release identity защищает от drift/replay и не поступает из owner stage. State/trust не обнуляются ради миграции.
- INV-DEPLOY-04: Journal/checkpoint/fsync/rollback/recovery сохраняют last accepted tree. Неизвестное состояние сохраняет evidence и не считается успехом.
- INV-DEPLOY-05: Healthy exact same release идемпотентен; следующие релизы внутри принятого состава не требуют изменения helper.
- INV-DEPLOY-06: Legacy13 и current14 - закрытые точные составы;14 добавляет только configured-create0644.13 recovery сохраняется после расширения.
- INV-DEPLOY-07: Schema1/exact13 и schema2/exact14 сохраняют version/provenance и state-zero compiled13 семантику. Bootstrap не пересоздает существующий accepted state.
- INV-DEPLOY-08: Переход13->14 авторизуется full14 signed schema2 с точным accepted base и возрастающим ID; downgrade/subsets не допускаются.
- INV-DEPLOY-09: Journal2 before13/14 -> after14 и checkpoint durable до mutations; accepted durable до journal clear.
- INV-DEPLOY-10: Rollback13 восстанавливает raw state и отсутствие configured-create, удаляя только доказанный after leaf через безопасный descriptor.
- INV-DEPLOY-11: Recovery legacy journal1/2 проверяет exact before/after/checkpoint и допустимое interrupted tree; unknown не удаляется и не чинится по догадке.
- INV-DEPLOY-12: App16 расширяет current14 ровно android-auth0644 и android-download0644. Noargs sudo, root target, authority, службы, accounts, порты и dependencies сохраняются.
- INV-DEPLOY-13: Schema3/exact16 сохраняет release provenance; новые manifests только3/full16 с accepted base14 либо16. Прямой13->16, install старых manifests и downgrade запрещены.
- INV-DEPLOY-14: До journal14->16 доказано отсутствие обоих app leaves. Durable checkpoint/raw before state и journal3 предшествуют full16 install/health/accepted/clear.
- INV-DEPLOY-15: Rollback14 проверяет весь interrupted tree, удаляет только доказанные after app leaves и восстанавливает exact14/raw state/две absence proofs. Unknown сохраняет pending; rollback16 восстанавливает before16.
- INV-DEPLOY-16: Recovery различает закрытые journal1/2/3 pairs и независимое присутствие двух app leaves. Kill/повтор/частичный rollback не ослабляют validation или ordering.
- INV-DEPLOY-17: Замена helper - отдельно reviewed checksum-pinned root bootstrap на accepted14/no pending. State/trust/package/config не меняются; old helper после accepted16 не восстанавливается.
- INV-DEPLOY-18: Отдельная reviewed config migration добавляет только fixed DB/catalog paths и сохраняет exact dwl, password/TOTP/replay, TTL10800 и неизвестные поля. Private proof не содержит secrets; rollback не стирает DB/grants и не ослабляет private parent mode.
- INV-DEPLOY-19: Отдельный reviewed publisher фиксирует проверенный immutable APK до atomic feed. Catalog dwl:ai-panel0750/files0640 не входит в signed package; stale/concurrent publication не overwrites APK и не откатывает новый feed.

## Контракты, решения и известные дыры

Подробные схемы, maps, limits, failure semantics и критерии INV-DEPLOY-01..05:
[universal deploy](../dev/done/2026-10-05-spec-web-universal-deploy.md).
INV-DEPLOY-06..11:
[13->14](../dev/2026-10-06-spec-web-create-deploy-scope-transition.md).
INV-DEPLOY-12..19:
[app deploy16](../dev/2026-10-07-spec-app-deploy16.md).

06.10: signed fixed14/noargs helper принят; расширение требует отдельного
root bootstrap. 07.10: app DESIGN сохраняет accepted14 и задает schema3,
exact16 и отдельные config/publisher artifacts. Signing доказывает authority,
а качество source устанавливают independent review и exact CI.

Известная дыра: installed helper4ead не принимает exact16. Новый helper,
bootstrap/config migration/publisher, их blind RED, privileged review/CI и
операторский пакет еще не созданы. DESIGN не является installation proof.
Открытых продуктовых вопросов в bounded deployment нет; app grant lifetime
и device acceptance принадлежат CONTROL-APP-AUTH-RELEASE.

## Трассируемость

INV-DEPLOY-01..11 - существующие deployment synthetic suites; поиск тега
проверяет фактическую связь, документация не заменяет выполненный тест.
INV-DEPLOY-12..19 - будущие blind RED группы в feature specification, coverage
пока не заявляется. Helper/bootstrap/config migration/publisher должны получить
meaningful committed RED до автора реализации. Root production и device
проверки учитываются отдельно от synthetic tests и CI.
