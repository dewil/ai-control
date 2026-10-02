# Проверка scoped file tools

Финальная реализация a9cf330 на base4b1ab3f. 29 независимых тестов новых инструментов и полный295Codex/Telegram GREEN под umask077. install-completeness72/72, ShellCheck0.11.0 по CI-набору и git diff --check GREEN.

Independent RED4c8b986 предшествует реализации. Дополнительный RED63afac6 воспроизводит реальные200файлов при RLIMIT_NOFILE128 и подмену между stat/open; исправлен original author a9cf330. Helper использует actual guard, bounded stdlib reads и O(depth) дескрипторы; native permissions/runtime здесь не заявлены.
