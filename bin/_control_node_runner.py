"""Patch capture and native stream evidence for the disposable ALP fixture.

The caller must first stop and drain the editing process. Staging uses private
metadata and objects; the source repository's index, objects and refs are never
written. These are evidence seams, not a process sandbox or task executor.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import uuid


_CONFIG = (
    'core.hooksPath=/dev/null', 'core.quotePath=true', 'core.fileMode=true',
    'core.autocrlf=false', 'core.safecrlf=false', 'core.symlinks=true',
    'core.fsmonitor=false', 'core.excludesFile=/dev/null',
    'core.attributesFile=/dev/null', 'diff.noprefix=false',
    'diff.mnemonicPrefix=false', 'diff.relative=false',
    'advice.addEmbeddedRepo=false',
)
_DIFF = (
    'diff', '--cached', '--no-ext-diff', '--no-textconv', '--no-color',
    '--no-renames', '--full-index', '--diff-algorithm=myers',
    '--indent-heuristic', '--ignore-submodules=none',
    '--src-prefix=a/', '--dst-prefix=b/',
)


class _CaptureError(Exception):
    pass


def _environment():
    # Do not inherit GIT_*, executable search paths, loader settings or secrets.
    return dict(PATH='/usr/bin:/bin', HOME='/nonexistent', LC_ALL='C', TZ='UTC',
                GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')


def _git(cwd, args, env, *, gitdir=None, base=None):
    argv = ['/usr/bin/git']
    if base is not None:
        argv.append('--attr-source=' + base)
    for setting in _CONFIG:
        argv.extend(('-c', setting))
    if gitdir is not None:
        argv.extend(('--git-dir=' + str(gitdir), '--work-tree=' + str(cwd),
                     '-c', 'core.bare=false'))
    argv.extend(args)
    result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=30, close_fds=True, check=False)
    if result.returncode:
        # Git stderr can contain private paths or configuration. Never export it.
        raise _CaptureError('git_error')
    return result.stdout


def _source(cwd, env):
    entries = _git(cwd, ('config', '--local', '--no-includes', '--null', '--list'), env)
    for entry in entries.split(b'\0'):
        key = entry.split(b'\n', 1)[0].lower()
        if (key.startswith((b'include.', b'includeif.', b'filter.'))
                or key == b'core.attributesfile'
                or key == b'extensions.worktreeconfig'):
            raise _CaptureError('unsafe_git_config')
    common = Path(os.fsdecode(_git(cwd, ('rev-parse', '--git-common-dir'), env).rstrip(b'\n')))
    if not common.is_absolute():
        common = cwd / common
    common = common.resolve(strict=True)
    attributes = common / 'info' / 'attributes'
    if attributes.is_symlink() or (attributes.exists() and attributes.read_bytes()):
        raise _CaptureError('unsafe_attributes')
    objects = (common / 'objects').resolve(strict=True)
    if not objects.is_dir() or '\n' in str(objects) or '\r' in str(objects):
        raise _CaptureError('invalid_repository')
    head = _git(cwd, ('rev-parse', '--verify', 'HEAD'), env).decode('ascii').strip()
    return objects, head


def canonical_patch(worktree, base_sha):
    """Return the frozen six-field canonical-patch-v1 DTO, with full metrics.

    Errors yield unavailable without exception text or a fabricated artifact.
    Only trusted SHA-1 fixture repositories are supported by this profile.
    """
    result = dict(base_sha=base_sha, patch_status='unavailable', patch=None,
                  patch_bytes=None, patch_sha256=None, reasons=[])
    try:
        if type(base_sha) is not str or re.fullmatch(r'[0-9a-f]{40}', base_sha) is None:
            raise _CaptureError('invalid_base')
        cwd = Path(worktree).resolve(strict=True)
        env = _environment()
        objects, head = _source(cwd, env)
        reasons = [] if head == base_sha else ['head_moved']
        # Scratch lives outside the editable tree; no project files are excluded.
        with tempfile.TemporaryDirectory(prefix='control-canonical-', dir='/var/tmp') as scratch:
            gitdir = Path(scratch) / 'git'
            _git(cwd, ('init', '--bare', '--template=', str(gitdir)), env)
            (gitdir / 'objects' / 'info' / 'alternates').write_bytes(os.fsencode(objects) + b'\n')
            env['GIT_INDEX_FILE'] = str(Path(scratch) / 'index')
            _git(cwd, ('read-tree', base_sha), env, gitdir=gitdir, base=base_sha)
            _git(cwd, ('add', '--all', '--force', '--', '.'), env, gitdir=gitdir, base=base_sha)
            raw = _git(cwd, (*_DIFF, '--raw', '-z', base_sha, '--'), env,
                       gitdir=gitdir, base=base_sha)
            numstat = _git(cwd, (*_DIFF, '--numstat', '-z', base_sha, '--'), env,
                           gitdir=gitdir, base=base_sha)
            patch = _git(cwd, (*_DIFF, '--patch', '-U3', base_sha, '--'), env,
                         gitdir=gitdir, base=base_sha)
        records = raw.split(b'\0')
        for index in range(0, len(records) - 1, 2):
            metadata = records[index].split()
            for mode in (metadata[0][1:], metadata[1]):
                if mode not in (b'000000', b'100644', b'100755'):
                    kind = {b'120000': 'symlink', b'160000': 'submodule'}.get(
                        mode, 'mode_' + mode.decode('ascii'))
                    reasons.append('unsupported_' + kind)
        if any(record.startswith(b'-\t-\t') for record in numstat.split(b'\0')):
            reasons.append('unsupported_binary')
        try:
            text = patch.decode('utf-8')
        except UnicodeDecodeError:
            text = None
            reasons.append('unsupported_non_utf8')
        if b'\r' in patch:
            reasons.append('unsupported_cr')
        status = ('unsupported' if reasons else 'oversize' if len(patch) > 32768
                  else 'ok' if raw else 'empty')
        result.update(patch_status=status,
                      patch=text if status in ('ok', 'empty') else None,
                      patch_bytes=len(patch), patch_sha256=hashlib.sha256(patch).hexdigest(),
                      reasons=sorted(set(reasons)))
    except _CaptureError as error:
        result['reasons'] = [str(error)]
    except (OSError, ValueError, TypeError, UnicodeError, IndexError,
            subprocess.SubprocessError):
        result['reasons'] = ['capture_error']
    return result


def _native_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate native field')
        result[key] = value
    return result


def _native_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite native number')
    return number


def _native_constant(value):
    raise ValueError('invalid native constant')


def decode_native_stream(lines, expected_session_uuid, expected_model):
    """Project bounded native JSON lines into session/model/turn evidence.

    This does not prove process exit, account identity or execution isolation.
    Limits count original bytes, including any supplied line separators; no
    bytes are stripped or silently truncated before accounting.
    """
    evidence = dict(binding='unknown', model=None, successful_turn=False,
                    effort_state='requested_unverified')
    try:
        if (type(expected_session_uuid) is not str
                or str(uuid.UUID(expected_session_uuid)) != expected_session_uuid
                or type(expected_model) is not str or not expected_model):
            return evidence
        total = 0
        init = result = None
        conflict = False
        for raw in lines:
            if type(raw) is not bytes:
                return evidence
            total += len(raw)
            if len(raw) > 1048576 or total > 4194304:
                return evidence
            record = json.loads(raw.decode('utf-8'), object_pairs_hook=_native_object,
                                parse_float=_native_float, parse_constant=_native_constant)
            # Escaped lone surrogates are invalid UTF-8 evidence too.
            json.dumps(record, ensure_ascii=False).encode('utf-8')
            if type(record) is not dict or type(record.get('type')) is not str:
                return evidence
            if record['type'] == 'system' and record.get('subtype') == 'init':
                projection = (record.get('session_id'), record.get('model'))
                if any(type(value) is not str for value in projection):
                    return evidence
                if result is not None:
                    conflict = True
                if init is None:
                    init = projection
                elif init != projection:
                    conflict = True
            elif record['type'] == 'result':
                projection = (record.get('session_id'), record.get('subtype'),
                              record.get('is_error'))
                if (type(projection[0]) is not str or type(projection[1]) is not str
                        or type(projection[2]) is not bool):
                    return evidence
                if init is None:
                    conflict = True
                if result is None:
                    result = projection
                elif result != projection:
                    conflict = True
            # Irrelevant valid records and extra envelope fields have no
            # session/model/turn authority, including rate_limit_event.
        if init is not None and type(init[1]) is str:
            evidence['model'] = init[1]
        if (not conflict and init is not None and result is not None
                and init[0] == result[0] == expected_session_uuid):
            evidence['binding'] = 'verified'
            evidence['successful_turn'] = (init[1] == expected_model
                                           and result[1] == 'success'
                                           and result[2] is False)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        # Never publish raw native lines, parser exception strings or tokens.
        pass
    return evidence
