"""Single-worker task UI. Authentication secrets never cross the broker."""
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import asyncio
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
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool


class DevbusFrontend:
    """One actual owner read and one short-lived, exact-filter cache."""

    def __init__(self, backend, *, clock=time.monotonic):
        self.backend, self.clock = backend, clock
        self.executor = None
        self.flight = None
        self.key = None
        self.started = 0
        self.cache = None
        self.generation = 0
        self.closed = False

    def invalidate(self):
        self.generation += 1
        self.cache = None

    async def overview(self, task=None, agent=None):
        from _control_web_broker import devbus_result
        key = (task, agent)
        if self.closed:
            return {'error': 'unavailable'}
        if self.cache is not None and self.cache[0] == key and self.clock() < self.cache[1]:
            return devbus_result(self.cache[2])
        if self.flight is not None and not self.flight.done():
            if self.key != key:
                self.invalidate()
                return {'error': 'busy'}
        else:
            self.invalidate()
            self.key, self.started = key, self.clock()
            if self.executor is None:
                self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='control-devbus-read')
            def call():
                self.started = self.clock()
                return self.backend.devbus_overview(task=task, agent=agent)
            async def read():
                try:
                    value = await asyncio.get_running_loop().run_in_executor(
                        self.executor, call)
                    return devbus_result(value)
                except Exception:
                    return {'error': 'unavailable'}
            self.flight = asyncio.create_task(read())
        flight, generation = self.flight, self.generation
        try:
            result = await asyncio.wait_for(asyncio.shield(flight), 6)
        except asyncio.TimeoutError:
            return {'error': 'unavailable'}
        if not self.closed and generation == self.generation and self.clock() < self.started + 1 and 'error' not in result:
            self.cache = (key, self.started + 1, result)
        return devbus_result(result)

    async def close(self):
        self.closed = True
        self.invalidate()
        try:
            if self.flight is not None:
                await asyncio.wait_for(asyncio.shield(self.flight), 7)
        except asyncio.TimeoutError:
            if self.executor is not None:
                self.executor.shutdown(wait=False, cancel_futures=True)
            raise RuntimeError('devbus owner did not stop') from None
        if self.executor is not None:
            self.executor.shutdown(wait=True)


class _APKResponse(StreamingResponse):
    """Own the open descriptor for the entire ASGI response, even before iteration."""

    def __init__(self, stream, content, **kwargs):
        self._stream = stream
        super().__init__(content, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            stream, self._stream = self._stream, None
            if stream is not None:
                stream.close()


def valid_username(value):
    return type(value) is str and re.fullmatch(r'[a-z][a-z0-9_-]{1,31}', value) is not None


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

def create_app(config, backend, clock=None, *, owner_only=True, session_store=None):
    clock = clock or time.time
    username = config.get('username', 'owner')
    if not valid_username(username):
        raise ValueError('invalid authentication configuration')
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
    if session_store is not None and type(session_store) is not dict:
        raise ValueError("invalid session store")
    sessions, attempts = session_store if session_store is not None else {}, []
    used_step = -1
    replay_path = config.get('totp_state_path')
    if replay_path is not None:
        replay_path = Path(replay_path).absolute()
        parent = replay_path.parent.stat()
        if Path('/data') in replay_path.resolve().parents or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ValueError('private replay directory required')
        used_step = _load_totp_step(replay_path)
    lock = threading.Lock()
    device_store = None

    def android_store():
        nonlocal device_store
        path = config.get('android_auth_db')
        if not path:
            raise RuntimeError('device store unavailable')
        if device_store is None:
            import importlib.util
            spec = importlib.util.spec_from_file_location('_control_web_android_auth',
                         Path(__file__).with_name('_control_web_android_auth.py'))
            helper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(helper)
            device_store = helper.DeviceGrantStore(path, clock)
        return device_store

    manager = None
    devbus = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal manager, devbus
        from _control_web_live import Manager
        devbus = DevbusFrontend(backend)
        if replay_path is not None:
            manager = Manager(backend, replay_path)
            await manager.start()
        try:
            yield
        finally:
            try:
                if manager is not None:
                    await manager.stop()
            finally:
                manager = None
                try:
                    await devbus.close()
                finally:
                    devbus = None

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

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
        if current.get('device_id'):
            try:
                if not android_store().valid(current['device_id']):
                    return None, error('unauthorized', 401)
            except (ValueError, RuntimeError):
                return None, error('unavailable', 503)
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

    async def body(request, limit=128 * 1024, strict=False):
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
                if len(data) + len(chunk) > limit:
                    return None
                data.extend(chunk)
            value = (json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                     if strict else json.loads(data, object_pairs_hook=unique_object))
            return value if type(value) is dict else None
        except (ValueError, UnicodeError, RecursionError):
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

    class SecurityHeaders:
        def __init__(self, application):
            self.application = application

        async def __call__(self, scope, receive, send):
            if scope['type'] != 'http':
                return await self.application(scope, receive, send)
            path = scope['path']
            app_namespace = path == '/api/app' or path.startswith('/api/app/')
            download_namespace = path == '/download/android' or path.startswith('/download/android/')
            canonical_app = path in ('/api/app/login', '/api/app/session', '/api/app/logout')
            canonical_download = (path in ('/download/android/', '/download/android/version.json') or
                                  re.fullmatch(r'/download/android/ai-control-[1-9][0-9]{0,9}\.apk', path))
            async def secured(message):
                if message['type'] == 'http.response.start':
                    headers = list(message.get('headers', []))
                    content_type = dict(headers).get(b'content-type', b'').decode('latin1')
                    immutable = (message['status'] == 200 and re.fullmatch(r'/download/android/ai-control-[1-9][0-9]{0,9}\.apk', path)
                                 and content_type == 'application/vnd.android.package-archive')
                    values = {'x-content-type-options':'nosniff', 'referrer-policy':'no-referrer',
                              'content-security-policy':"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}
                    if not immutable:
                        values['cache-control'] = 'no-store'
                    headers = [(key,value) for key,value in headers if key.decode('latin1').lower() not in values]
                    headers.extend((key.encode(), value.encode()) for key,value in values.items())
                    message = dict(message, headers=headers)
                await send(message)
            if (app_namespace and not canonical_app) or (download_namespace and not canonical_download):
                return await error('not_found', 404)(scope, receive, secured)
            await self.application(scope, receive, secured)

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

    @app.get('/devbus.js')
    def devbus_javascript():
        from fastapi.responses import Response
        return Response(Path(__file__).with_name('_control_web_devbus.js').read_bytes(), media_type='application/javascript')

    @app.get('/devbus.css')
    def devbus_stylesheet():
        from fastapi.responses import Response
        return Response(Path(__file__).with_name('_control_web_devbus.css').read_bytes(), media_type='text/css')

    def authenticate(data, now):
        attempts[:] = [at for at in attempts if at > now - 60]
        if len(attempts) >= 10:
            return error('rate_limited', 429)
        attempts.append(now)
        try:
            # Unknown valid names still pay the hash cost; only the owner may consume TOTP.
            password_valid = verify_password(data['password'], config['password_hash'])
            valid = data['username'] == username and password_valid and consume_totp(data['totp'])
        except (OSError, ValueError):
            return error('unavailable', 503)
        if not valid:
            return error('unauthorized', 401)
        return None

    @app.post('/api/login')
    async def login(request: Request):
        if request.headers.get('origin') != origin:
            return error('forbidden', 403)
        data = await body(request)
        if (data is None or set(data) != {'username', 'password', 'totp'}
                or not valid_username(data['username'])
                or type(data['password']) is not str or len(data['password']) > 1024):
            return error('invalid_request', 422)
        now = clock()
        with lock:
            failure = authenticate(data, now)
            if failure is not None:
                return failure
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            # SIMPLIFIED: one operator, one worker, bounded in-memory sessions;
            # restart requires login. Use an external store before multi-worker.
            if len(sessions) >= 100:
                sessions.clear()
            sessions[token] = {'expires': now + ttl, 'csrf': csrf, 'principal': 'owner'}
        response = JSONResponse({'csrf': csrf})
        response.set_cookie('control_session', token, max_age=ttl, httponly=True, secure=secure, samesite='strict', path='/')
        return response

    def android_error(code, status):
        response = error(code, status)
        response.headers['Cache-Control'] = 'no-store'
        return response

    def android_gate(request):
        if owner_only is not True or request.headers.getlist('origin') != [origin]:
            return android_error('forbidden', 403)
        return None

    def bearer(request):
        values = request.headers.getlist('authorization')
        if len(values) != 1 or re.fullmatch(r'Bearer [A-Za-z0-9_-]{43}', values[0]) is None:
            return ''
        return values[0][7:]

    def android_cookie(response, token):
        response.set_cookie('control_session', token, max_age=10800,
                            httponly=True, secure=secure, samesite='strict', path='/')
        response.headers['Cache-Control'] = 'no-store'
        return response

    def download_helper():
        import importlib.util
        spec = importlib.util.spec_from_file_location('_control_android_download',
                    Path(__file__).with_name('_control_web_android_download.py'))
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper

    @app.get('/download/android/')
    def android_landing():
        directory = config.get('android_download_dir')
        if not directory:
            return android_error('not_found', 404)
        helper = download_helper()
        try:
            value = helper.manifest(directory)
            return HTMLResponse(helper.landing(value), headers={'Cache-Control': 'no-store'})
        except helper.FeedMissing:
            return HTMLResponse(helper.landing(), headers={'Cache-Control': 'no-store'})
        except helper.FeedOperational:
            return android_error('unavailable', 503)
        except helper.FeedUnavailable:
            return HTMLResponse(helper.landing(broken=True), headers={'Cache-Control': 'no-store'})

    @app.get('/download/android/version.json')
    def android_manifest():
        directory = config.get('android_download_dir')
        if not directory:
            return android_error('not_found', 404)
        helper = download_helper()
        try:
            return JSONResponse(helper.manifest(directory), headers={'Cache-Control': 'no-store'})
        except helper.FeedMissing:
            return android_error('not_found', 404)
        except helper.FeedUnavailable:
            return android_error('unavailable', 503)

    @app.get('/download/android/{filename}')
    def android_apk(filename: str):
        directory = config.get('android_download_dir')
        match = re.fullmatch(r'ai-control-([1-9][0-9]{0,9})\.apk', filename)
        if not directory or not match or int(match[1]) > 2147483647:
            return android_error('not_found', 404)
        helper = download_helper()
        stream = None
        try:
            stream = helper.open_file(directory, filename)
            size = os.fstat(stream.fileno()).st_size
        except helper.FeedMissing:
            return android_error('not_found', 404)
        except (helper.FeedUnavailable, OSError):
            if stream is not None:
                stream.close()
            return android_error('unavailable', 503)
        async def chunks():
            while True:
                chunk = await run_in_threadpool(stream.read, 65536)
                if not chunk:
                    break
                yield chunk
        return _APKResponse(stream, chunks(), media_type='application/vnd.android.package-archive',
            headers={'Content-Length': str(size), 'Content-Disposition': f'attachment; filename="{filename}"',
                     'Cache-Control': 'public, max-age=31536000, immutable'})

    async def app_preflight(request, endpoint):
        failure = android_gate(request)
        if failure is not None:
            return None, None, failure
        data = await body(request, strict=True)
        valid = data is not None
        if endpoint == 'login':
            valid = (valid and set(data) == {'username', 'password', 'totp'}
                     and valid_username(data['username'])
                     and type(data['password']) is str and 0 < len(data['password']) <= 1024
                     and type(data['totp']) is str and len(data['totp']) <= 1024)
        elif endpoint == 'session':
            valid = valid and set(data) == {'foreground_open'} and type(data['foreground_open']) is bool
        else:
            valid = valid and not data
        if not valid:
            return None, None, android_error('invalid_request', 422)
        try:
            grant = android_store()
            grant.check_available()
        except (ValueError, RuntimeError):
            return None, None, android_error('unavailable', 503)
        return data, grant, None

    @app.post('/api/app/login')
    async def app_login(request: Request):
        data, grant, failure = await app_preflight(request, 'login')
        if failure is not None:
            return failure
        now = clock()
        with lock:
            failure = authenticate(data, now)
            if failure is not None:
                return failure
            try:
                token, identity = grant.issue_grant()
            except (ValueError, RuntimeError):
                return android_error('unavailable', 503)
            cookie = secrets.token_urlsafe(32)
            if len(sessions) >= 100:
                sessions.clear()
            sessions[cookie] = {'expires': now + 10800, 'csrf': secrets.token_urlsafe(32),
                                'device_id': identity, 'principal': 'owner'}
        return android_cookie(JSONResponse({'device_token': token}), cookie)

    @app.post('/api/app/session')
    async def android_session(request: Request):
        data, grant, failure = await app_preflight(request, 'session')
        if failure is not None:
            return failure
        try:
            identity = grant.admit(bearer(request), foreground_open=data['foreground_open'])
        except (ValueError, RuntimeError):
            return android_error('unavailable', 503)
        if identity is None:
            return android_error('device_unauthorized', 401)
        now = clock()
        old = request.cookies.get('control_session', '')
        with lock:
            current = sessions.get(old)
            replaced = not (current and current.get('device_id') == identity and current['expires'] > now and current.get('principal') == 'owner')
            if replaced:
                old = secrets.token_urlsafe(32)
                current = {'expires': now + 10800, 'csrf': secrets.token_urlsafe(32),
                           'principal': 'owner', 'device_id': identity}
                if len(sessions) >= 100:
                    sessions.clear()
                sessions[old] = current
            else:
                current['expires'] = now + 10800
        return android_cookie(JSONResponse({'status': 'ok', 'session_replaced': replaced}), old)

    @app.post('/api/app/logout')
    async def android_logout(request: Request):
        data, grant, failure = await app_preflight(request, 'logout')
        if failure is not None:
            return failure
        try:
            if not grant.revoke_token(bearer(request)):
                return android_error('device_unauthorized', 401)
        except (ValueError, RuntimeError):
            return android_error('unavailable', 503)
        response = JSONResponse({'status': 'ok'}, headers={'Cache-Control': 'no-store'})
        response.delete_cookie('control_session', httponly=True, secure=secure, samesite='strict')
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

    def chat_result(call, sending=False, preserve_forbidden=False):
        try:
            result = call()
            if type(result) is not dict:
                return error('unavailable', 503)
            code = result.get('error')
            if code is not None:
                if preserve_forbidden and code == 'forbidden':
                    return error('forbidden', 403)
                return error(code if code in ('invalid_request', 'stale') else 'unavailable',
                             {'invalid_request': 422, 'stale': 409}.get(code, 503))
            if result.get('status') in ('queued', 'cancelled', 'changed') or 'queued_submission_id' in result:
                from _control_web_broker import queue_mutation_result
                result = queue_mutation_result(result, result.get('message_id'))
                if 'error' in result:
                    return error('unavailable', 503)
                return JSONResponse(result, status_code=503 if sending and result['status'] == 'delivery_unknown' else 200)
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
        if any(not valid_uuid(data[key]) for key in ('sid', 'message_id', 'operation_id') if key in data):
            return None
        if 'cursor' in data and not chat_cursor(data['cursor']):
            return None
        if 'page' in data:
            if not re.fullmatch(r'[0-9]{1,32}', data['page']):
                return None
            data['page'] = int(data['page'])
        return data

    async def chat_read(request, required, optional, call, preserve_forbidden=False):
        _, failure = session(request)
        if failure:
            return failure
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            return error('forbidden', 403)
        data = chat_query(request, required, optional)
        if data is None:
            return error('invalid_request', 422)
        return await run_in_threadpool(chat_result, lambda: call(data), preserve_forbidden=preserve_forbidden)

    @app.get('/api/session-projects')
    async def session_projects(request: Request):
        return await chat_read(request, (), (), lambda data: backend.session_projects())

    @app.get('/api/session-project-summary')
    async def session_project_summary(request: Request):
        return await chat_read(request, (), (), lambda data: backend.session_project_summary())

    @app.get('/api/sessions')
    async def session_list(request: Request):
        return await chat_read(request, ('project',), ('page',), lambda data: backend.session_list(data['project'], data.get('page', 0)))

    @app.get('/api/session-history')
    async def session_history(request: Request):
        from _control_web_broker import history_result
        return await chat_read(request, ('project', 'sid'), ('cursor',), lambda data: history_result(backend.session_history(data['project'], data['sid'], data.get('cursor'))))

    def live_auth(request):
        current, failure = session(request)
        if failure is not None:
            return None, failure
        if owner_only is not True or type(current.get('principal')) is not str or current['principal'] != 'owner':
            return None, error('forbidden', 403)
        return current, None

    @app.get('/api/devbus/overview')
    async def devbus_overview(request: Request):
        from fastapi.responses import Response
        pairs = list(request.query_params.multi_items())
        if (len(pairs) > 2 or len({key for key, _ in pairs}) != len(pairs)
                or any(key not in ('task', 'agent') or re.fullmatch(r'[A-Za-z0-9_-]{1,80}', value) is None
                       for key, value in pairs)):
            return error('invalid_request', 400)
        origins, sites = request.headers.getlist('origin'), request.headers.getlist('sec-fetch-site')
        if origins and origins != [origin] or sites and sites != ['same-origin']:
            return error('forbidden', 403)
        current, failure = live_auth(request)
        if failure is not None:
            return failure
        if manager is None or devbus is None:
            return error('unavailable', 503)
        identity = ('device', current['device_id']) if current.get('device_id') else ('cookie', request.cookies.get('control_session', ''))
        if not manager.reserve(identity):
            return error('unavailable', 429)
        try:
            result = await devbus.overview(**dict(pairs))
            _, failure = live_auth(request)
            if failure is not None:
                devbus.invalidate()
                return failure
            if 'error' in result:
                return error('unavailable', 503)
            return Response(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8'),
                            media_type='application/json')
        finally:
            manager.release(identity)

    async def live_read(request, stream=False):
        from _control_web_live import SSEResponse, encoded
        from fastapi.responses import Response
        data = chat_query(request, ('project', 'sid'))
        identifiers = request.headers.getlist('last-event-id')
        if (data is None or len(identifiers) > 1 or identifiers and
                (len(identifiers[0]) > 128 or not re.fullmatch(r'[0-9a-f]{32}:[1-9][0-9]{0,15}', identifiers[0])
                 or int(identifiers[0].split(':')[1]) > 2**53-1)
                or stream and not any(part.split(';', 1)[0].strip().lower() == 'text/event-stream'
                                     for part in request.headers.get('accept', '').split(','))):
            return error('invalid_request', 422)
        origins = request.headers.getlist('origin')
        sites = request.headers.getlist('sec-fetch-site')
        if origins and origins != [origin] or sites and sites != ['same-origin']:
            return error('forbidden', 403)
        current, failure = live_auth(request)
        if failure is not None:
            return failure
        if manager is None:
            return error('unavailable', 503)
        key = (data['project'], data['sid'])
        identity = ('device', current['device_id']) if current.get('device_id') else ('cookie', request.cookies.get('control_session', ''))
        if not manager.reserve(identity, key):
            return error('unavailable', 429)
        handed_off = False
        result = None
        def check():
            _, failure = live_auth(request)
            return failure
        try:
            result = await manager.admit(key, check, stream=stream)
            if isinstance(result, Response):
                return result
            _, failure = live_auth(request)
            if failure is not None:
                return failure
            if isinstance(result, dict) and 'error' in result:
                code = 'unsupported' if result['error'] == 'unsupported' else 'unavailable'
                return error(code, 429 if result['error'] == 'capacity' else 503)
            if stream:
                response = SSEResponse(manager, result, identity, check, identifiers[0] if identifiers else None)
                handed_off = True
                return response
            return Response(encoded(result), media_type='application/json', headers={'Cache-Control':'no-store'})
        finally:
            if not handed_off:
                if stream and result is not None and not isinstance(result, (dict, Response)):
                    manager.detach(result)
                manager.release(identity)

    @app.get('/api/session-events')
    async def session_events(request: Request):
        return await live_read(request, stream=True)

    @app.get('/api/session-live-snapshot')
    async def session_live_snapshot(request: Request):
        return await live_read(request)

    @app.get('/api/session-models')
    async def session_models(request: Request):
        return await chat_read(request, ('project', 'sid'), (), lambda data: backend.session_models(data['project'], data['sid']), preserve_forbidden=True)

    @app.get('/api/session-send-status')
    async def session_send_status(request: Request):
        return await chat_read(request, ('project', 'sid', 'message_id'), (), lambda data: backend.session_send_status(data['project'], data['sid'], data['message_id']))

    def create_response(call, project, operation_id=None, sending=False):
        from _control_web_broker import configured_create_result
        try:
            result = configured_create_result(call(), project, operation_id)
        except Exception:
            return error('unavailable', 503)
        if 'error' in result:
            code = result['error']
            return error(code, {'invalid_request': 422, 'forbidden': 403, 'stale': 409}.get(code, 503))
        return JSONResponse(result, status_code=503 if sending and
                            result.get('status') == 'delivery_unknown' else 200)

    async def create_read(request, status=False):
        _, failure = session(request)
        if failure:
            return failure
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            return error('forbidden', 403)
        if len(request.scope.get('query_string', b'')) > 4096:
            return error('invalid_request', 422)
        fields = ('project', 'operation_id', 'context_mode', 'provider_id') if status else ('project',)
        data = chat_query(request, fields)
        if data is None or status and (data['context_mode'] != 'configured' or data['provider_id'] != 'codex'):
            return error('invalid_request', 422)
        call = (lambda: backend.session_create_status(data['project'], data['operation_id'],
                data['context_mode'], data['provider_id'])) if status else (
                lambda: backend.session_create_options(data['project']))
        return await run_in_threadpool(create_response, call, data['project'], data.get('operation_id'))

    @app.get('/api/session-create-options')
    async def session_create_options(request: Request):
        return await create_read(request)

    @app.get('/api/session-create-status')
    async def session_create_status(request: Request):
        return await create_read(request, True)

    @app.post('/api/session-create')
    async def session_create(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request, limit=4096, strict=True)
        from _control_web_broker import _valid_session
        if data is None or not _valid_session(dict(data, op='session_create')) or 'op' in data:
            return error('invalid_request', 422)
        return await run_in_threadpool(create_response,
            lambda: backend.session_create(data['project'], data['operation_id'],
                data['context_mode'], data['provider_id']), data['project'], data['operation_id'], True)

    def rename_response(call, operation_id, sending=False):
        from _control_web_broker import rename_result
        try:
            result = rename_result(call(), operation_id)
        except Exception:
            return error('unavailable', 503)
        if 'error' in result:
            code = result['error']
            return error(code, {'invalid_request': 422, 'forbidden': 403, 'stale': 409}.get(code, 503))
        status = 503 if sending and result['status'] == 'delivery_unknown' else 200
        return JSONResponse(result, status_code=status)

    @app.get('/api/session-rename-status')
    async def session_rename_status(request: Request):
        _, failure = session(request)
        if failure:
            return failure
        supplied_origin = request.headers.get('origin')
        if supplied_origin is not None and supplied_origin != origin:
            return error('forbidden', 403)
        data = chat_query(request, ('project', 'sid', 'operation_id'))
        if data is None:
            return error('invalid_request', 422)
        return await run_in_threadpool(rename_response,
            lambda: backend.session_rename_status(data['project'], data['sid'], data['operation_id']), data['operation_id'])

    @app.post('/api/session-rename')
    async def session_rename(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request)
        if (data is None or set(data) != {'project', 'sid', 'operation_id', 'title'}
                or not chat_project(data['project']) or not valid_uuid(data['sid'])
                or not valid_uuid(data['operation_id'])):
            return error('invalid_request', 422)
        from _control_web_broker import valid_rename_title
        if not valid_rename_title(data['title']):
            return error('invalid_request', 422)
        return await run_in_threadpool(rename_response,
            lambda: backend.session_rename(data['project'], data['sid'], data['operation_id'], data['title']),
            data['operation_id'], True)

    @app.get('/api/session-queue')
    async def session_queue(request: Request):
        from _control_web_broker import queue_result
        return await chat_read(request, ('project', 'sid'), (),
            lambda data: queue_result(backend.session_queue(data['project'], data['sid'])))

    async def queue_write(request, cancel=False):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request)
        fields = {'project', 'sid', 'queued_submission_id', 'action_id'} if cancel else {'project', 'sid', 'message_id', 'text'}
        from _control_web_broker import queue_mutation_result, valid_queue_id
        if (data is None or set(data) not in ((fields,) if cancel else (fields, fields | {'selection'}))
                or not chat_project(data['project']) or not valid_uuid(data['sid'])
                or not valid_uuid(data['action_id'] if cancel else data['message_id'])
                or cancel and not valid_queue_id(data['queued_submission_id'])
                or not cancel and not text(data['text'], True)):
            return error('invalid_request', 422)
        if not cancel:
            from _control_web_sessions import _valid_selection
            if 'selection' in data and not _valid_selection(data['selection']):
                return error('invalid_request', 422)
            try:data['text'].encode('utf-8')
            except UnicodeError:return error('invalid_request', 422)
        def call():
            if cancel:
                result = backend.session_queue_cancel(data['project'], data['sid'], data['queued_submission_id'], data['action_id'])
            else:
                result = backend.session_enqueue(data['project'], data['sid'], data['message_id'], data['text'], **({'selection':data['selection']} if 'selection' in data else {}))
            return queue_mutation_result(result, data['action_id'] if cancel else data['message_id'], data.get('queued_submission_id'))
        try:
            result = await run_in_threadpool(call)
        except Exception:
            return error('unavailable', 503)
        if 'error' in result:
            code = result['error']
            return error(code, {'invalid_request':422, 'queue_unsupported_selection':422, 'stale':409}.get(code,503))
        return JSONResponse(result, status_code=503 if result['status'] == 'delivery_unknown' else 200)

    @app.post('/api/session-queue')
    async def session_enqueue(request: Request):
        return await queue_write(request)

    @app.post('/api/session-queue-cancel')
    async def session_queue_cancel(request: Request):
        return await queue_write(request, True)

    @app.post('/api/session-send')
    async def session_send(request: Request):
        _, failure = session(request, True)
        if failure:
            return failure
        data = await body(request)
        fields = {'project', 'sid', 'message_id', 'text'}
        if (data is None or set(data) not in (fields, fields | {'selection'})
                or not chat_project(data['project']) or not valid_uuid(data['sid'])
                or not valid_uuid(data['message_id']) or not text(data['text'], True)):
            return error('invalid_request', 422)
        if 'selection' in data:
            from _control_web_sessions import _valid_selection
            if not _valid_selection(data['selection']):
                return error('invalid_request', 422)
        try:
            data['text'].encode('utf-8')
        except UnicodeError:
            return error('invalid_request', 422)
        args = (data['project'], data['sid'], data['message_id'], data['text'])
        def send():
            if 'selection' in data:
                return backend.session_send(*args, selection=data['selection'])
            return backend.session_send(*args)
        return await run_in_threadpool(chat_result, send, True)

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
        cookie = request.cookies.get('control_session')
        with lock:
            current = sessions.get(cookie)
        if current and current.get('device_id'):
            try:
                android_store().revoke(current['device_id'])
            except (ValueError, RuntimeError):
                return error('unavailable', 503)
        with lock:
            sessions.pop(cookie, None)
        response = JSONResponse({'status': 'applied'})
        response.delete_cookie('control_session', httponly=True, secure=secure, samesite='strict')
        return response

    from _control_web_live import SSEWriteDeadline
    app.add_middleware(SecurityHeaders)
    app.add_middleware(SSEWriteDeadline)
    return app
