# APK publish automation: source candidate

Owner: CONTROL-ANDROID-PUBLISH-AUTONOMY. Контракт:
[permanent publisher](2026-10-08-spec-android-publish-automation.md).

Новый helper использует fixed paths/accounts/certificate, isolated noargs runtime,
root-owned bounded nofollow publisher snapshot и permanent privilege drop перед
compile и stage I/O. Существующий deployment/publish-android-release.py остается
byte-identical SHA256 `47d2705d87fad44e5263e30259dad5cd86fc80e5ca7de590a0219b1a962771ec`.

Owner-side generator создает standalone checksum-pinned root packet с embedded
helper/publisher snapshots. Он проверяет exact existing collisions и trusted
root-owned ancestors, проверяет sudoers до writes, устанавливает только три
fixed leaves, sudoers последним. Изменения web/auth/state/service или
account membership изменения отсутствуют. Root выполняет trusted bootstrap
stdlib и visudo; APK publisher и owner tooling исполняются только после drop.

Локальные проверки: `python3 -m unittest discover -s tests -p
 'test_control_android_publish_*blind.py'` - 17 tests, 16 PASS, один intentional
architecture-baseline skip (RUN_FIXED_WRAPPER_BASELINE не задан). Frozen tests
не изменены; synthetic successive code8/9 используют одни helper bytes.
Existing PublisherContracts/PublisherProbes/toolchain tests - 15 PASS:

```sh
PYTHONPATH=tests python3 -m unittest \
  test_control_web_app_deploy16_operations_blind_red.PublisherContracts \
  test_control_web_app_deploy16_author.PublisherProbes \
  test_control_web_app_deploy16_publisher_toolchain_blind_red
```

Compile helper/generator/generated packet PASS; git diff --check PASS.
Runbook: [staging/bootstrap](../android-publish-automation.md).
Concrete packet создается генератором из exact reviewed tree; digest относится к
целому generated packet, а не только embedded source. Existing code7 может дать
production exact-repeat proof без новой подписи/пересборки после принятой установки.

Это local synthetic proof. Independent SOURCE/full CI, physical root install,
real noargs sudo publication и anonymous HTTPS proof еще не выполнены этим автором.
Device acceptance не следует из publisher tests. Receipt unknown.

Same-author atime follow-up: snapshot/existing-file guards compare dev/ino/mode/
nlink/uid/gid/size/mtime_ns/ctime_ns and exclude only access time, which can advance
on a valid read. Byte equality and nofollow path-to-fd binding remain enforced.
Independent old-atime regressions precede this fix; generated packet must be
regenerated with its own new checksum before review/install.

Root-adjudicated supplementary groups are exactly {1000,987}; real/effective/
saved uid/gid are dwl1000, not a panel-only group987 policy.
