# CONTROL-WEB-FIRST-USABLE — вопросы и результаты в браузере

Сейчас веб существует только в плане, пользователь зависит от Telegram и хочет управлять задачами через браузер. Первая версия показывает ожидающие ответа вопросы и готовые результаты, позволяет ответить, разрешить допустимую операцию и принять либо отклонить результат. Все действия делегируются существующим trusted writers Control. Изоляция web process от OAuth реализуется узким owner broker, а не правами на owner home. Это один корень: отсутствующий task web workflow.

Обязательный контракт и инварианты: docs/specs/web.md, INV-WEB-01..08. Данные агента недоверенны; auth/CSRF/peer UID обязательны. Существующие TASK и Codex гарантии не ослабляются. Новый web стек FastAPI/uvicorn в изолированном venv, одна worker; HTML/CSS/JS без frontend framework. Не добавлять DB, tunnel, внешнюю авторизацию и broad CLI gateway.

Приёмка: independent RED до реализации; offline auth/CSRF/replay/expiry/XSS/errors, broker traversal/symlink/argv/no secret leaks/peer refusal и stale verdict; phone-width browser login→questions→answer→result→confirm accept/reject; actual trusted writer integration на private /var/tmp fixtures; production install только после review с безопасным enrollment и HTTPS. Отказ инфраструктуры виден, не превращается в пустой парк или success. Самопроверка автора не заменяет distinct-model compliance.

Сценарии риска для review: неавторизованный доступ к задачам; CSRF/replayed TOTP; web-RCE запрос arbitrary owner command/path; symlink из registry к OAuth; stale generation принимает другую задачу; transient выдаётся за success; native permission расширяется; вывод credentials в log/artifact. Доступ: authenticated единственный оператор, web UID только narrow broker, owner только existing writer semantics. Accepted deployment design от14.07 сохраняется.

Код принят 04.10.2026: 46 тестов GREEN, мобильный browser QA PASS, distinct-model static review PASS на 5e9871f. Доказательства: ../2026-10-04-web-validation.md. Файл закрывает реализацию; клиентская задача CONTROL-WEB-FIRST-USABLE остаётся открытой до HTTPS/enrollment и установленной публичной приёмки.
