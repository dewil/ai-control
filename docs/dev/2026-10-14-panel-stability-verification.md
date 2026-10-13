# Проверка пакета стабильности панели

Реализация: контрастная граница×2/×3, автоматическое read-only восстановление explicit модели/effort с deadline10s, coalescing и безPOSTretry, native indexed session-list безscan/repair, confirmed read-generation drift→stale. Ограничение полноты списков — текущий индекс; summaryscope не изменён.

Независимые RED: marker2FAIL→2PASS; recovery12FAIL/1PASS→13PASS, deadline1FAIL→14PASS; indexmissingflag/pagination/error/race и exceptiondriftFAIL→backendfocused71PASS. Testfixturegenerationseam исправлен под actualprepare_context, это не runtimeослабление. Rendered pixel/positionmobile360/desktop1280/forcedcolors PASS. Legacy10controls и послеCIguard25mixed PASS. Haiku SOURCE/delta PASS.

Actual source native0.162.1: defaultlist6.5068s и14.3952s, indexed0.0026s; rowproof4total0.0121s. Первый freshclientproof unavailable0.0753s FAIL сохранён; independent exceptiondriftRED выявил classification gap. Послеfix: firstreadstale0.0763s +одинwhole-readretry0.0542s=0.1305s/4rows; next0.0317s. Ниauthниnativeпроцессы не менялись. Это source-only, не полный page cold-start и не installedacceptance.

ПервыйCI38486536145: web1 нашёл unexpectedinheritforegroundGET и прежний exactparamsoracle. Исправлены guard и index-onlyожидание; callcounts/proofs сохранены. ПовторныйfullCI и signed33installation фиксируются владельцем пакета после получения фактических результатов. APKcode10 не пересобирается. PhysicalAndroidNOTRUN; синтетический браузерныйlifecycle не заменяетdeviceприёмку.
