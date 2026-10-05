# Переход страницы вверх и вниз

Владелец CONTROL-WEB-SESSIONS. Пользователь05.10 просит стрелки вверху и
внизу страницы, чтобы не прокручивать переписку руками.

INV-WSESS-14: в разделе Сессии сверху и снизу содержимого есть по две
настоящие кнопки «↑ В начало» и «↓ В конец», с понятным accessible name и
клавиатурным управлением. Они прокручивают document viewport до самого
начала или естественного конца страницы, а не внутренний контейнер истории.
Работают на360/768/1280px, не создают horizontal page overflow; targets40px
наdesktop/44pxmobile. Existing «К последним сообщениям» сохраняется.

INV-WSESS-15: ↑ сбрасывает pending initial autoscroll и временный scrollslack,
переводит пользователя к началу; обычные новые данные после этого сохраняют
режим чтения, а не возвращают вниз. ↓ сбрасывает pending initial autoscroll
и scrollslack, возобновляет follow новейших сообщений. Пользовательский send
сохраняет существующий explicit-to-bottom контракт. Кнопки локальные:
не отправляют RPC/POST, не подгружают историю, не меняют draft/выбранную
сессию/receipt/auth; не создают фоновые viewport movements.

Критерии: независимые synthetic browser проверки desktop/mobile обеихпар,
keyboard activation, actual document scrollY/maxscroll, draft/session
сохранены, zero click-caused requests, ↑+new-update readeranchor±8px и
↓+new-update follow≤80px. Existing compact/width/Markdown/scroll regressions,
distinct model review и exactCI передmerge/deploy.

Не входит: SSE, ограничение100DOM сообщений, fileupload/nativeattachments,
новыеdependencies, auth/nativeprotocol/backend/units. Это следующие срезы.

## Уточнение после независимой сверки05.10

INV-WSESS-15 сохраняет прежний естественный follow: если после ↑ пользователь
сам прокрутил длинную страницу обратно вниз (колесо/scrollbar/End), очередные
новые сообщения сноваfollow≤80px безобязательногонажатия↓. Программная
прокрутка↑/перерисовка/кламп короткой страницы не считается ручнымвозвратом
вниз; pendinginitial отменяется и typingdraft не возобновляетfollow.
Выбранные taskstab/hiddenbackground не меняютviewport отстарогоhistoryGET;
readerintent применяется толькок соответствующемуproject/sid/generation.
Независимый browsercase: ↑→ручнойEnd/колесо доbottom→реальныйupdatefollow.

Validation: frozen0c46618 independent9browserPASS; prior width/Markdown/anchor26PASS plusauthorcompact5PASS. Distinct-model gpt6solmedium sameSID01a10ccd re-reviewPASS closesmanualreturn andeditablewheel findings. ExacthostedCI remainsrequired beforemerge; installedacceptance separately.
