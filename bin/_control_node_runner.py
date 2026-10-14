"""Canonical patch capture for the trusted, disposable ALP fixture workspace.

The caller must first stop and drain the editing process. Staging uses private
metadata and objects; the source repository's index, objects and refs are never
written. This is a capture seam, not a process sandbox or task executor.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile


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
