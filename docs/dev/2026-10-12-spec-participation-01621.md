# Participation на установленном Codex0.162.1

Проблема: общий пул r22 возвращает source_unavailable при0.162.1, потому что три отдельных admissiongates (observe callback, background sampler, once-only question response) допускают только0.161.0. Базовый контракт чтения уже reviewed0.162.1 в sessions/pins/history/queue. Этот fix добавляет проверенныйPARTконтракт0.162.1, не убирает version/context/authorityfences.

INV-PVER01: единая feature-specific allowlist PART_NATIVE_VERSIONS содержит ровно0.161.0/0.162.1. Обе версии проходят те же existing schema/epoch/root/active-incarnation guards при sampler/observe/response.0.160.0 и неизвестные версии остаются закрытыми дляPART; общий SUPPORTED не расширяется.
INV-PVER02: authoritative callback0.162.1 получает same bound interaction once-only ответ после actualuserselection. Stale/foreign root/closed/changedcontext/nativeapproval не получает новыйответ; нет resume/attach/автоapprove/сменыполитики. Existingprotocolhandler не меняется, onlyfamilyadmission.
INV-PVER03: read-only backgroundloaded/read/turns/items контракт сохраняет bounded5sec/7loaded и partialcoverage. Обновление версии не снимает unlinkedTASK/binding_incomplete/native_callbacks_partial. Unknown schema fails closed, pendingquestions не угадываются из текстаистории.

Проверки: первичные locallygenerated0.162.1 schema для используемых read/callback/responsefields; independent RED при0.162.1 для sampler/registry/questionresponse и negative0.160/future/rootstale; прежниеPARTtests unchanged; HaikuDESIGN/SOURCE, exactfullCI, signed22, installedownerpool послеwarmup с реальными rows/health и auth/nativepeerpreserved. Genericfutureversionnegotiation не входит.
