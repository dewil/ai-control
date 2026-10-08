"""Public immutable APK feed, with descriptor-based no-symlink file access."""
import errno
import html
import json
import os
import re
import stat

PREFIX = '/download/android/'
ORIGIN = 'https://llm-web.dewil.ru:18443'


class FeedMissing(Exception):
    pass


class FeedUnavailable(Exception):
    pass


class FeedOperational(FeedUnavailable):
    pass


def open_file(directory, name):
    """Walk every directory component without following links; return owned fd."""
    fd = None
    try:
        if not isinstance(directory, str) or not directory.startswith('/') or '\x00' in directory:
            raise FeedUnavailable()
        parts = directory.split('/')[1:]
        if any(part in ('.', '..') for part in parts):
            raise FeedUnavailable()
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in filter(None, parts):
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        result = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        if not stat.S_ISREG(os.fstat(result).st_mode):
            os.close(result)
            raise FeedMissing()
        return os.fdopen(result, 'rb')
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            raise FeedMissing() from None
        raise FeedOperational() from None
    finally:
        if fd is not None:
            os.close(fd)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Invalid manifest')
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('Invalid manifest')


def manifest(directory):
    try:
        with open_file(directory, 'version.json') as stream:
            raw = stream.read(16385)
    except OSError:
        raise FeedOperational() from None
    try:
        if len(raw) > 16384:
            raise ValueError()
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_object, parse_constant=reject_constant)
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        if not isinstance(value, dict):
            raise ValueError()
        code = value.get('versionCode')
        name = value.get('versionName')
        digest = value.get('sha256')
        if type(code) is not int or not 1 <= code <= 2147483647:
            raise ValueError()
        if type(name) is not str or not name.strip() or len(name) > 64:
            raise ValueError()
        if type(digest) is not str or not re.fullmatch('[0-9a-f]{64}', digest):
            raise ValueError()
        filename = f'ai-control-{code}.apk'
        if value.get('apkUrl') != ORIGIN + PREFIX + filename:
            raise ValueError()
        with open_file(directory, filename):
            pass
        return value
    except (ValueError, UnicodeError, RecursionError, FeedMissing, OSError):
        raise FeedUnavailable() from None


def landing(value=None, broken=False):
    body = '<p>Версия еще не опубликована</p>'
    if broken:
        body = '<p>Не удалось проверить опубликованную версию. Повторите подключение позже.</p>'
    if value is not None:
        path = PREFIX + f'ai-control-{value["versionCode"]}.apk'
        body = f'<p>Версия {html.escape(value["versionName"])}</p><p><a href="{path}" download>Скачать APK</a></p><p>SHA-256: <code>{value["sha256"]}</code></p>'
    return '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="dark"><title>ai-control для Android</title><link rel="stylesheet" href="/web.css"></head><body><main class="android-download"><header><h1>ai-control для Android</h1><a href="/">В главное меню</a></header><section>' + body + '</section></main></body></html>'
