"""Shared done writer. Locked API requires caller to hold done.lock and fencing."""
import html
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from _agent_question_io import durable_json, strict_json, remaining, validate_done
from _agent_worktree import BASE_SHA_RE, worktree_facts, git_run, GitGuardError

class DoneError(Exception): pass

def raise_done(message):
    raise DoneError(message)

def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# кап карточки готовности (bin/claude-agent-tgbot _done_card) учитывал
# только поля кандидатов урока (LESSON_CANDIDATE_MAX_BYTES в claude-agent-
# run), summary заявки не был ограничен вовсе (контрольный аудит серьезная
# 6): summary ~3000 символов + три допустимых кандидата режут карточку
# готовности на несколько сообщений Telegram (_chunk_for_html, лимит 3800
# HTML-escaped символов), клавиатура (принять/отклонить) прикрепляется
# ТОЛЬКО к последнему чанку - обрыв доставки после первого оставляет
# карточку без кнопок, а повтор дублирует уже доставленный текст. Обрезка
# ЗДЕСЬ, на источнике (единственный писатель done.json.summary) - карточка
# по построению никогда не увидит необрезанное значение; та же обрезка
# продублирована в claude-agent-tgbot как защита в глубину (значение могло
# попасть в done.json иначе - старый файл до фикса, ручная правка).
DONE_SUMMARY_MAX_BYTES = 1500


def cap_summary(text):
    """Обрезает summary по HTML-ESCAPED длине (не по сырым символам - см.
    LESSON_CANDIDATE_MAX_BYTES в claude-agent-run: escape-длина - то, что
    реально уходит в отправку, а не сырая)."""
    s = str(text or "")
    esc_len, kept = 0, []
    for ch in s:
        e = len(html.escape(ch))
        if esc_len + e > DONE_SUMMARY_MAX_BYTES:
            return "".join(kept) + " [обрезано]"
        kept.append(ch)
        esc_len += e
    return s


class SpecReadError(Exception):
    """spec.yaml нечитаем/невалиден (yq вернул ненулевой код) - вызывающий
    обязан отказать (аудит V2.7a, major 3), а не тихо подставить default:
    подмененная/битая спека иначе молча вырождалась в workspace:'none' и
    весь фенсинг worktree (чистое дерево/база/ветка) пропускался целиком."""


def spec_get(agent_dir, expr, default="", *, deadline=None, clock=time.monotonic):
    try:
        r = subprocess.run(
            ["yq", "-r", '%s // ""' % expr,
             os.path.join(agent_dir, "spec.yaml")],
            capture_output=True, text=True, timeout=remaining(deadline, clock, 10))
    except Exception as e:
        raise SpecReadError(str(e))
    if r.returncode != 0:
        raise SpecReadError(r.stderr.strip() or "yq exit %d" % r.returncode)
    remaining(deadline, clock)
    v = r.stdout.strip()
    return v if v else default


DONE_SCHEMA_NULLS = {
    "branch": None, "base": None, "commit_sha": None, "empty": None,
    "changes": None, "pushed_at": None, "accepted_at": None,
    "integrated_at": None, "cleaned_at": None, "archived_at": None}


def request_done_locked(agent_dir, envelope_key, summary=None, *, strict=False, deadline=None, clock=time.monotonic):
    """Trusted caller only: caller owns evidence locks and operation fencing."""
    remaining(deadline, clock)
    summary = cap_summary(summary) if summary is not None else None
    ws = spec_get(agent_dir, ".workspace", "none", deadline=deadline, clock=clock) or "none"
    if ws not in ("worktree", "direct", "none"):
        raise_done("invalid workspace")
    dp = os.path.join(agent_dir, "done.json")
    def write_json(path, doc):
        remaining(deadline, clock)
        durable_json(path, doc, deadline=deadline, clock=clock)
        remaining(deadline, clock)
    existing = None
    if strict and os.path.lexists(dp):
        existing = strict_json(dp, deadline=deadline, clock=clock)
        validate_done(existing)
    elif os.path.isfile(dp):
        try:
            with open(dp) as f:
                existing = json.load(f)
        except (OSError, ValueError):
            existing = None
    if not isinstance(existing, dict):
        existing = None

    if existing and existing.get("state") not in (None, "requested"):
        raise_done("заявка уже в состоянии %r - переоткрыть нельзя"
             % existing.get("state"))

    commit_sha = base = branch = empty = None
    if ws == "worktree":
        work = os.path.join(agent_dir, "work")
        agent_name = os.path.basename(os.path.normpath(agent_dir))
        # project_path - для fail-closed guard'а ЕДИНОГО git-хелпера
        # (V2.10 §3d.2): worktree_facts/git_run отказывают без него.
        try:
            project_path = spec_get(agent_dir, ".project", deadline=deadline, clock=clock)
        except SpecReadError as e:
            raise_done("spec.yaml нечитаем/невалиден - проект worktree не "
                 "определить (%s)" % e)
        if not project_path:
            raise_done("spec.project пуст - заявку о готовности не на что "
                 "опереть")
        # базовый коммит ветки задачи - из control.json (mission_base:
        # имя историческое, смысл общий - точка форка, зафиксированная
        # при create). Вывести ее из HEAD нельзя, см. worktree_facts.
        try:
            if strict:
                control = strict_json(os.path.join(agent_dir, "control.json"), deadline=deadline, clock=clock)
            else:
                with open(os.path.join(agent_dir, "control.json")) as stream:
                    control = json.load(stream)
            base_recorded = (control or {}).get("mission_base")
        except (OSError, ValueError):
            base_recorded = None
        if not base_recorded:
            raise_done("в control.json нет базового коммита ветки задачи - "
                 "заявку о готовности не на что опереть")
        # база обязана быть полным 40-hex sha (аудит V2.7a, major 4):
        # подмененный control.json с mission_base:"HEAD" делал бы
        # проверку "--is-ancestor HEAD HEAD" тавтологией, истинной
        # при любой истории.
        if not BASE_SHA_RE.match(base_recorded):
            raise_done("mission_base в control.json обязан быть полным "
                 "40-hex sha, получено %r" % base_recorded)
        facts = worktree_facts(work, base_recorded, agent_name,
                               project_path, deadline=deadline, clock=clock)
        if facts is None:
            try:
                st = git_run(["status", "--porcelain"], work,
                             project_path, deadline=deadline, clock=clock)
            except GitGuardError as e:
                raise_done("worktree заблокирован защитой git (%s)" % e)
            if st.returncode != 0 or st.stdout.strip():
                raise_done("грязное дерево worktree - у тебя нет git (V2.10 "
                     "§3d.1), эту команду нужно звать РАНЬШЕ, пока "
                     "дерево еще чисто; рантайм закоммитит правки "
                     "позже сам")
            raise_done("HEAD ветки задачи не потомок зафиксированной базы, "
                 "detached HEAD, чужая ветка либо симлинк вместо work")
        commit_sha, base, branch, empty = facts

    if existing and existing.get("state") == "requested":
        same_content = True
        if ws == "worktree":
            same_content = existing.get("commit_sha") == commit_sha
        same_owner = existing.get("envelope_key") == envelope_key
        if same_content and same_owner:
            if summary is not None:
                existing["summary"] = summary
                write_json(dp, existing)
            return  # идемпотентный no-op (§3): тот же прогон, тот же коммит
        if same_content and not same_owner:
            # V2.10 §3c, аудит серьезная 5: явный вызов done из НОВОГО
            # конверта (envelope_key прогона отличается от владельца
            # заявки) переносит владение, даже если содержимое пока не
            # изменилось (agent позвал done рано, до правок). Без этого
            # прогон B делает работу и коммитит, но не может заявить о
            # готовности заново (idempotent no-op молча сохранял бы
            # владение прогона A) - карточка осталась бы на старом
            # коммите, а Y нельзя было бы принять. pushed_at обнуляется -
            # свежая карточка должна суметь уйти; finalized сбрасывается
            # для worktree/direct - запись не считается финализированной,
            # пока терминальная ветка ЭТОГО (B) прогона не подтвердит ее
            # заново (fill_direct_changes/finalize_worktree_done).
            # Прогон, который done не звал, чужую заявку по-прежнему не
            # трогает - перенос владения делает только сам вызов done.
            existing["envelope_key"] = envelope_key
            existing["pushed_at"] = None
            existing["finalized"] = (ws == "none")
            # ЗАКРЫВАЕМ legacy-режим сверки тапа (аудит V2.10 r4,
            # блокер 3). Заявка, чья карточка ушла ДО перехода на
            # поколение, не имеет ключа pushed_gen8, и вердикт
            # разрешает ей фолбэк на прежний идентификатор ("-" у
            # direct/none). Без этой строки перенос владения такой
            # фолбэк УНАСЛЕДОВАЛ БЫ: тап по старой карточке приняли бы
            # уже против работы нового прогона, ничего не предъявив.
            # Явный None - не то же самое, что отсутствие ключа.
            existing["pushed_gen8"] = None
            if summary is not None:
                existing["summary"] = summary
            write_json(dp, existing)
            return

    doc = dict(DONE_SCHEMA_NULLS)
    doc.update({"state": "requested", "requested_at": now_iso(),
               "envelope_key": envelope_key, "workspace": ws,
               "summary": summary or "",
               # V2.10 §3c, аудит блокер 2: durable-признак готовности
               # заявки к отправке карточки. workspace:none ничего не
               # ждет от терминальной ветки runner'а (только summary,
               # уже записан) - финализирован сразу. worktree/direct
               # ждут fill_direct_changes/finalize_worktree_done -
               # done-notify молчит, пока finalized не станет true.
               "finalized": (ws == "none")})
    if ws == "worktree":
        doc.update({"branch": branch, "base": base,
                   "commit_sha": commit_sha, "empty": empty})
    write_json(dp, doc)
