#!/usr/bin/env python3
"""Freeze local source-build identity into the web HTML before review/CI."""
import argparse
import datetime as dt
import html
import os
from pathlib import Path
import stat
import subprocess
import sys
import uuid

START = '<!-- BUILD-INFO:START -->'
END = '<!-- BUILD-INFO:END -->'


def render_build_info(release_id, built_at, branch):
    if type(release_id) is not int or release_id <= 0:
        raise ValueError('release id must be a positive integer')
    if not isinstance(built_at, dt.datetime) or built_at.utcoffset() is None:
        raise ValueError('build time must be an aware datetime')
    if (not isinstance(branch, str) or not branch.strip()
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in branch)):
        raise ValueError('branch must be nonempty text without control characters')
    instant = built_at.astimezone(dt.timezone.utc)
    moscow = instant.astimezone(dt.timezone(dt.timedelta(hours=3)))
    datetime = instant.isoformat().replace('+00:00', 'Z')
    label = moscow.strftime('%d.%m.%Y %H:%M МСК')
    source = '' if branch in ('main', 'origin', 'origin/main') else ' · Ветка: ' + html.escape(branch)
    return (f'<footer id="build-info" class="build-info" data-release-id="{release_id}">'
            f'ai-control · r{release_id} · Собрано: '
            f'<time datetime="{datetime}">{label}</time>{source}</footer>')


def source_branch(root):
    # Ambient Git selectors must not substitute another checkout's identity.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], env=env,
                              capture_output=True, text=True, timeout=5)

    top = git('rev-parse', '--show-toplevel')
    if top.returncode or Path(top.stdout.strip()).resolve() != root:
        raise ValueError('source checkout Git context unavailable')
    branch = git('symbolic-ref', '--quiet', '--short', 'HEAD')
    if branch.returncode == 0:
        return branch.stdout.strip()
    if branch.returncode != 1:
        raise ValueError('source branch unavailable')
    revision = git('rev-parse', '--short', 'HEAD')
    if revision.returncode or not revision.stdout.strip():
        raise ValueError('source revision unavailable')
    return 'detached@' + revision.stdout.strip()


def stamp(root, release_id):
    directory = os.open(root / 'bin', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        source = os.open('_control_web.html', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory)
        with os.fdopen(source, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError('build-info target must be a regular source file')
            value = stream.read().decode('utf-8')
        if value.count(START) != 1 or value.count(END) != 1:
            raise ValueError('expected exactly one build-info marker pair')
        start, end = value.index(START) + len(START), value.index(END)
        if end < start:
            raise ValueError('build-info markers are reversed')
        footer = render_build_info(release_id, dt.datetime.now(dt.timezone.utc), source_branch(root))
        replacement = (value[:start] + '\n' + footer + '\n' + value[end:]).encode('utf-8')
        name = '.build-info-' + uuid.uuid4().hex + '.tmp'
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        temporary = name
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(replacement)
            stream.flush()
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            os.fsync(stream.fileno())
        os.replace(temporary, '_control_web.html', src_dir_fd=directory, dst_dir_fd=directory)
        temporary = None
    finally:
        try:
            if temporary is not None:
                os.unlink(temporary, dir_fd=directory)
        finally:
            os.close(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-id', type=int, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    try:
        stamp(root, args.release_id)
    except (ValueError, OSError, subprocess.SubprocessError):
        print('Build-info preparation failed; check release id, markers and local Git context.', file=sys.stderr)
        return 1
    print(f'Prepared web build info r{args.release_id}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
