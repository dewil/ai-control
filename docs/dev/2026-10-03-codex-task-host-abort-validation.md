# Проверка scoped host abort

Reviewed implementation203a148, independentRED236c9a4. 21 новых и полный316Codex/Telegram tests GREEN подumask077; install72/72, ShellCheck0.11.0CI-набор/diff-check GREEN. Старый stop quiescent gate сохранён. Abort только owned host drain под injected trusted revoked guard; production TASK fence integration следует отдельно. Native acceptance временногопрофиля/owned cells выполняется отдельным экспериментом, не заявляется этими unit tests.
