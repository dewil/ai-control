"""Single-worker task UI. Authentication secrets never cross the broker."""
import base64
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import threading
import time
from urllib.parse import urlsplit
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1)
    return 'scrypt$16384$8$1$' + salt.hex() + '$' + digest.hex()


def verify_password(password, encoded):
    try:
        method, n, r, p, salt, digest = encoded.split('$')
        if method != 'scrypt' or (n, r, p) != ('16384', '8', '1'):
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual, bytes.fromhex(digest))
    except (ValueError, TypeError, AttributeError):
        return False


def totp_code(secret, at):
    key = base64.b32decode(secret.upper() + '=' * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack('>Q', int(at) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7fffffff
    return '%06d' % (number % 1000000)



def _load_totp_step(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > 1024:
            raise ValueError('invalid replay state')
        try:
            with os.fdopen(fd, closefd=False) as stream:
                state = json.load(stream)
            if type(state) is not dict or set(state) != {'last_step'} or type(state['last_step']) is not int or state['last_step'] < -1:
                raise ValueError('invalid replay state')
            return state['last_step']
        except (ValueError, TypeError, KeyError):
            raise ValueError('invalid replay state') from None
    finally:
        os.close(fd)

def create_app(config, backend, clock=None):
    clock = clock or time.time
    origin = config['origin']
    parsed = urlsplit(origin)
    secure = config.get('secure_cookie', True)
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError('exact origin required')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost') and config.get('secure_cookie') is False):
        raise ValueError('HTTPS required except explicit loopback development')
    if parsed.scheme == 'https' and not secure:
        raise ValueError('HTTPS requires secure cookie')
    ttl = config.get('session_ttl', 3600)
    if type(ttl) is not int or not 1 <= ttl <= 86400:
        raise ValueError('invalid session lifetime')
    # Fail startup on invalid secret without exposing its value.
    try:
        totp_code(config['totp_secret'], clock())
    except Exception:
        raise ValueError('invalid authentication configuration') from None
    sessions, attempts = {}, []
    used_step = -1
    replay_path = config.get('totp_state_path')
    if replay_path is not None:
        replay_path = Path(replay_path).absolute()
        parent = replay_path.parent.stat()
        if Path('/data') in replay_path.resolve().parents or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ValueError('private replay directory required')
        used_step = _load_totp_step(replay_path)
    lock = threading.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    def error(code, status):
        return JSONResponse({'error': code}, status_code=status)

    def session(request, mutation=False):
        now = clock()
        token = request.cookies.get('control_session', '')
        with lock:
            for key in list(sessions):
                if sessions[key]['expires'] <= now:
                    del sessions[key]
            current = sessions.get(token)
        if current is None:
            return None, error('unauthorized', 401)
        supplied_csrf = request.headers.get('x-csrf-token', '')
        if mutation and (request.headers.get('origin') != origin or not supplied_csrf.isascii() or not hmac.compare_digest(supplied_csrf, current['csrf'])):
            return None, error('forbidden', 403)
        return current, None

    def consume_totp(value):
        nonlocal used_step
        if type(value) is not str or not re.fullmatch(r'[0-9]{6}', value):
            return False
        lock_fd = None
        try:
            if replay_path is not None:
                # Lock a stable adjacent inode, never the atomically replaced state.
                lock_path = replay_path.with_name(replay_path.name + '.lock')
                lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
                info = os.fstat(lock_fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                    raise ValueError('invalid replay lock')
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                used_step = _load_totp_step(replay_path)
            now = clock()
            for step in (int(now) // 30, int(now) // 30 - 1, int(now) // 30 + 1):
                if step <= used_step or not hmac.compare_digest(value, totp_code(config['totp_secret'], step * 30)):
                    continue
                if replay_path is not None:
                    temporary = replay_path.with_name('.replay-' + secrets.token_hex(8))
                    try:
                        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                        with os.fdopen(fd, 'w') as stream:
                            json.dump({'last_step': step}, stream)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, replay_path)
                        directory = os.open(replay_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(directory)
                        finally:
                            os.close(directory)
                    finally:
                        temporary.unlink(missing_ok=True)
                used_step = step
                return True
            return False
        finally:
            if lock_fd is not None:
                os.close(lock_fd)

    async def body(request):
        def unique_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError('duplicate field')
                value[key] = item
            return value
        try:
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > 128 * 1024:
                    return None
                data.extend(chunk)
            value = json.loads(data, object_pairs_hook=unique_object)
            return value if type(value) is dict else None
        except (ValueError, UnicodeError):
            return None

    def outcome(call):
        try:
            result = call()
            if type(result) is not dict:
                return error('unavailable', 503)
            if result.get('status') in ('applied', 'already'):
                return JSONResponse({'status': result['status']})
            code = result.get('error')
            if code not in ('stale', 'invalid_or_stale', 'saved_pending', 'unavailable'):
                code = 'unavailable'
            return error(code, 409 if code in ('stale', 'invalid_or_stale') else 503)
        except Exception:
            return error('unavailable', 503)

    @app.middleware('http')
    async def security_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    @app.get('/')
    def index():
        return HTMLResponse(Path(__file__).with_name('_control_web.html').read_text())

    @app.get('/favicon.svg')
    def favicon_svg():
        from fastapi.responses import Response
        return Response(Path(__file__).with_name('_control_web.svg').read_bytes(), media_type='image/svg+xml')

    @app.get('/favicon.ico')
    def favicon_ico():
        from fastapi.responses import RedirectResponse
        return RedirectResponse('/favicon.svg', status_code=307)

    @app.get('/web.js')
    def javascript():
        from fastapi.responses import Response
        return Response(Path(__file__).with_name('_control_web.js').read_text(), media_type='application/javascript')

    @app.get('/web.css')
    def stylesheet():
        from fastapi.responses import Response
        return Response(Path(__file__).with_name('_control_web.css').read_text(), media_type='text/css')

    @app.post('/api/login')
    async def login(request: Request):
        if request.headers.get('origin') != origin:
            return error('forbidden', 403)
        data = await body(request)
        if data is None or set(data) != {'password', 'totp'} or type(data['password']) is not str or len(data['password']) > 1024:
            return error('invalid_request', 422)
        now = clock()
        with lock:
            attempts[:] = [at for at in attempts if at > now - 60]
            if len(attempts) >= 10:
                return error('rate_limited', 429)
            attempts.append(now)
            try:
                valid = verify_password(data['password'], config['password_hash']) and consume_totp(data['totp'])
            except (OSError, ValueError):
                return error('unavailable', 503)
            if not valid:
                return error('unauthorized', 401)
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            # SIMPLIFIED: one operator, one worker, bounded in-memory sessions;
            # restart requires login. Use an external store before multi-worker.
            if len(sessions) >= 100:
                sessions.clear()
            sessions[token] = {'expires': now + ttl, 'csrf': csrf}
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('control_session', token, max_age=ttl, httponly=True, secure=secure, samesite='strict', path='/')
        return response

    @app.get('/api/session')
    def current_session(request: Request):
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            return error('forbidden', 403)
        current, failure = session(request)
        if failure:
            return failure
        return JSONResponse({'csrf': current['csrf']})

    @app.get('/api/tasks')
    def tasks(request: Request):
        _, failure = session(request)
        if failure:
            return failure
        try:
            result = backend.snapshot()
            if type(result) is not dict or type(result.get('tasks')) is not list or result.get('error'):
                return error('unavailable', 503)
            return JSONResponse({'tasks': result['tasks']})
        except Exception:
            return error('unavailable', 503)

    def valid_name(value):
        return type(value) is str and bool(re.fullmatch(r'[a-z][a-z0-9-]{0,30}[a-z0-9]', value))

    def valid_uuid(value):
        try:
            return type(value) is str and str(uuid.UUID(value)) == value
        except ValueError:
            return False

    def text(value, required=False):
        return type(value) is str and len(value) <= 16000 and (not required or bool(value.strip()))

    def chat_project(value):
        return type(value) is str and bool(re.fullmatch(r'[a-zA-Z0-9_-]{1,32}', value))

    def chat_cursor(value):
        return value is None or (type(value) is str and 0 < len(value) <= 4096)

    def chat_result(call, sending=False):
        try:
            result = call()
            if type(result) is not dict:
                return error('unavailable', 503)
            code = result.get('error')
            if code is not None:
                return error(code if code in ('invalid_request', 'stale') else 'unavailable',
                             {'invalid_request': 422, 'stale': 409}.get(code, 503))
            if 'status' in result:
                if result['status'] not in ('accepted', 'delivery_unknown', 'rejected'):
                    return error('unavailable', 503)
                if not valid_uuid(result.get('message_id')) or result.get('turn_id') is not None and (type(result['turn_id']) is not str or not 0 < len(result['turn_id']) <= 500):
                    return error('unavailable', 503)
                result = {key: result.get(key) for key in ('status', 'message_id', 'turn_id')}
                status = {'delivery_unknown': 503, 'rejected': 409}.get(result['status'], 200) if sending else 200
                return JSONResponse(result, status_code=status)
            if sending:
                return error('unavailable', 503)
            return JSONResponse(result)
        except Exception:
            return error('unavailable', 503)

    def chat_query(request, required, optional=()):
        pairs = list(request.query_params.multi_items())
        data = dict(pairs)
        if len(pairs) != len(data) or not set(required).issubset(data) or set(data) - set(required) - set(optional):
            return None
        if 'project' in data and not chat_project(data['project']):
            return None
        if any(not valid_uuid(data[key]) for key in ('sid', 'message_id') if key in data):
            return None
        if 'cursor' in data and not chat_cursor(data['cursor']):
            return None
        if 'page' in data:
            if not re.fullmatch(r'[0-9]{1,32}', data['page']):
                return None
            data['page'] = int(data['page'])
        return data

    async def chat_read(request, required, optional, call):
        _, failure = session(request)
        if failure:
            return failure
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            return error('forbidden', 403)
        data = chat_query(request, required, optional)
        if data is None:
            return error('invalid_request', 422)
        return await run_in_threadpool(chat_result, lambda: call(data))

    @app.get('/api/session-projects')
    async def session_projects(request: Request):
        return await chat_read(request, (), (), lambda data: backend.session_projects())

    @app.get('/api/sessions')
    async def session_list(request: Request):
        return await chat_read(request, ('project',), ('page',), lambda data: backend.session_list(data['project'], data.get('page', 0)))

    @app.get('/api/session-history')
    async def session_history(request: Request):
        return await chat_read(request, ('project', 'sid'), ('cursor',), lambda data: backend.session_history(data['project'], data['sid'], data.get('cursor')))

    @app.get('/api/session-send-status')
    async def session_send_status(request: Request):
        return await chat_read(request, ('project', 'sid', 'message_id'), (), lambda data: backend.session_send_status(data['project'], data['sid'], data['message_id']))

    @app.post('/api/session-send')
    async def session_send(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request)
        if data is None or set(data) != {'project', 'sid', 'message_id', 'text'} or not chat_project(data['project']) or not valid_uuid(data['sid']) or not valid_uuid(data['message_id']) or not text(data['text'], True):
            return error('invalid_request', 422)
        try:
            data['text'].encode('utf-8')
        except UnicodeError:
            return error('invalid_request', 422)
        return await run_in_threadpool(chat_result, lambda: backend.session_send(data['project'], data['sid'], data['message_id'], data['text']), True)

    @app.post('/api/answer')
    async def answer(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request)
        if data is None or set(data) != {'agent', 'qid', 'decision', 'text'} or not valid_name(data['agent']) or not valid_uuid(data['qid']) or data['decision'] not in ('text', 'approve', 'reject', 'recover') or not text(data['text'], data['decision'] == 'text') or (data['decision'] == 'recover' and data['text'] != ''):
            return error('invalid_request', 422)
        return await run_in_threadpool(outcome, lambda: backend.answer(data['agent'], data['qid'], data['decision'], data['text']))

    @app.post('/api/verdict')
    async def verdict(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request)
        fields = {'agent', 'generation', 'decision', 'comment', 'confirmed'}
        if data is None or not fields.issubset(data) or set(data) - fields - {'totp'} or not valid_name(data['agent']) or type(data['generation']) is not str or not re.fullmatch(r'[0-9a-f]{8}', data['generation']) or data['decision'] not in ('accept', 'reject') or data['confirmed'] is not True or not text(data['comment']):
            return error('invalid_request', 422)
        if data['decision'] == 'reject':
            with lock:
                now = clock()
                attempts[:] = [at for at in attempts if at > now - 60]
                if len(attempts) >= 10:
                    return error('rate_limited', 429)
                attempts.append(now)
                try:
                    valid = consume_totp(data.get('totp'))
                except (OSError, ValueError):
                    return error('unavailable', 503)
                if not valid:
                    return error('invalid_code', 403)
        return await run_in_threadpool(outcome, lambda: backend.verdict(data['agent'], data['generation'], data['decision'], data['comment']))

    @app.post('/api/logout')
    def logout(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        with lock:
            sessions.pop(request.cookies.get('control_session'), None)
        response = JSONResponse({'status': 'applied'})
        response.delete_cookie('control_session', httponly=True, secure=secure, samesite='strict')
        return response

    return app
