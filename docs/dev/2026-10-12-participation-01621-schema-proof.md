# Первичная wire-сверка PART0.162.1

Cached official generated JSONschemas: /var/tmp/control-limits-native-schema-01621/v2 иtop-level ToolRequestUserInput*.json. Readonlyreview gpt-6-luna/low, никакихnativecalls/auth/historyreads.

ThreadLoadedListParams limit/cursor иResponse data:string[]/nextCursor совместимы. ThreadReadParams includeTurns:boolean; Thread id/cwd/status обязательны. ThreadTurnsListParams itemsView=notLoaded,sortDirection=desc,limit; TurnStatus exactly inProgress/completed/failed/interrupted. ThreadItemsListResponse data:{turnId,item}[], agentMessage.phase допускает final_answer/null/absence; отсутствиеphaseостаётсябезfinalwitness. Callback item/tool/requestUserInput содержитthreadId/turnId/itemId/isBlocking/questions; response {answers:{id:{answers:string[]}}}. Currentparserстроже schema приomitteddefault isOther/isSecret/options: safe native_only/unknown сохраняется, не расширяетсяэтимfix. Schema не доказывает live callbackcoverage.

Hashes: loadedparams42c2d124ab2b2998d84f0126daae2d32b0bf9c5a7ea7266e3a0814e5e37cf00d; loadedresponse1ea02c4710083e552b2a3a89b931b9049d5bf05b7db46278b8352cf9fd80cd52; turnsparams2a8b93d7d4437cc25e16a1dde16d8db3c338d39e16c5eece2a56e943a21577d7; itemsresponse0ecf37ff62571c8411aab271ea65d22be4da1108cc2fd2dffb15a7034bfedb28; questionparamsfda15b62e7446105b59c8ed85c908abed2a47db70653e57c92c47a2f204fa77a; response5073b245f741fa8ce62ec52e4dd1809b7831f9c4284c279a78abc9b171f8e3f2.

Добавлять только reviewedPARTallowlist0.161.0/0.162.1; future/0.160.0 остаютсязакрыты. Opportunistic history-part_publish exact0.161 fastpath остаётся прежним; backgroundsampler отвечает за0.162.1. Genericcapabilitynegotiation остаётсяотдельнымbacklog. Liveownerwarmrowsиauth/nativepeerpreservation требуютсяприустановке.
