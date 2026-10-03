"""Concrete TASK authority fence and shared evidence writers; no runner effects."""
import fcntl
import json
import math
import os
import re
import stat
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager

from _agent_question_io import (create_question_locked, strict_json, remaining,
                                validate_done)
from _agent_done_io import request_done_locked
from _codex_task_bridge import CodexTaskBridge, TaskBinding


class BackendError(Exception):
    pass


class BackendBusyError(BackendError):
    """Canonical lock acquisition refused before any authority/effect."""
    pass


def require(condition):
    if not condition:
        raise BackendError('TASK backend refused')


class CodexTaskBackend:
    def __init__(self, binding, generation, attempt_id, operation_id, *,
                 clock=time.monotonic, spec_reader=None):
        try:
            require(isinstance(binding, TaskBinding))
            require(type(generation) is int and generation >= 1)
            require(isinstance(attempt_id, str) and attempt_id == attempt_id.strip()
                    and 0 < len(attempt_id.encode()) <= 256
                    and not any(ord(c) < 32 or ord(c) == 127 or c in '/\\' for c in attempt_id))
            require(isinstance(operation_id, str) and str(uuid.UUID(operation_id)) == operation_id)
            require(re.fullmatch('[0-9a-f]{32}', binding.task_incarnation) is not None)
            require(isinstance(binding.event_key, str) and binding.event_key
                    and binding.event_key not in ('.', '..')
                    and not any(ord(c) < 32 or ord(c) == 127 or c in '/\\' for c in binding.event_key))
            require(all(isinstance(v, str) and v for v in (binding.thread_id, binding.turn_id)))
            require(isinstance(binding.agent_dir, str) and os.path.isabs(binding.agent_dir))
        except Exception:
            raise BackendError('Invalid TASK backend configuration') from None
        self.binding, self.generation = binding, generation
        self.attempt_id, self.operation_id = attempt_id, operation_id
        self.clock, self.spec_reader = clock, spec_reader
        self._active = None
        self._mutex = threading.Lock()

    def _budget(self, deadline):
        require(type(deadline) in (int, float) and math.isfinite(deadline))
        return remaining(deadline, self.clock)

    def _info(self, path, *, directory=False, private=True, spec=False):
        require(os.path.realpath(path) == path)
        info = os.lstat(path)
        mode = stat.S_IMODE(info.st_mode)
        require(info.st_uid == os.getuid())
        if directory:
            require(stat.S_ISDIR(info.st_mode) and (mode == 0o700 if private else not mode & 0o022))
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and (not mode & 0o022 if spec else mode == 0o600))
            require(info.st_size <= 1024 * 1024)
        return info

    def _pins(self, deadline, pins):
        agent = self.binding.agent_dir
        parent, name = os.path.dirname(agent), os.path.basename(agent)
        require(os.path.basename(parent) == 'agents')
        require(re.fullmatch('[a-z][a-z0-9-]{0,30}[a-z0-9]', name) is not None)
        dirs = [(parent, False), (os.path.join(parent, '.locks'), False)]
        dirs += [(agent, True), (agent + '/questions', True), (agent + '/inbox', True),
                 (agent + '/inbox/inflight', True)]
        locks = [agent + '/questions/.lock', agent + '/done.lock',
                 parent + '/.locks/new-task-' + name + '.lock', agent + '/.lock',
                 agent + '/inbox/.inbox.lock']
        for path, private in dirs:
            self._budget(deadline)
            info = self._info(path, directory=True, private=private)
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                require((os.fstat(fd).st_dev, os.fstat(fd).st_ino) == (info.st_dev, info.st_ino))
            except Exception:
                os.close(fd)
                raise
            pins.append((path, fd, True, private))
        return locks

    def _check_pins(self, pins, deadline):
        for path, fd, directory, private in pins:
            self._budget(deadline)
            info = self._info(path, directory=directory, private=private)
            opened = os.fstat(fd)
            require((info.st_dev, info.st_ino) == (opened.st_dev, opened.st_ino))

    def _spec(self, deadline):
        self._budget(deadline)
        path = self.binding.agent_dir + '/spec.yaml'
        before = self._info(path, spec=True)
        if self.spec_reader is not None:
            value = self.spec_reader(self.binding.agent_dir, deadline=deadline)
        else:
            result = subprocess.run(['yq', '-o=json', '-I=0', '.', path], capture_output=True,
                                    timeout=self._budget(deadline))
            require(result.returncode == 0 and len(result.stdout) <= 1024 * 1024)
            def pairs(items):
                out = {}
                for key, val in items:
                    require(key not in out)
                    out[key] = val
                return out
            value = json.loads(result.stdout, object_pairs_hook=pairs)
        after = self._info(path, spec=True)
        require((before.st_dev, before.st_ino) == (after.st_dev, after.st_ino))
        self._budget(deadline)
        require(type(value) is dict)
        require(all(value.get(k) == v for k, v in dict(engine='codex', type='event',
                    runtime='drain', workspace='worktree').items()))
        project = value.get('project')
        require(isinstance(project, str) and os.path.isabs(project)
                and os.path.realpath(project) == project and os.path.isdir(project))

    def _authority(self, deadline):
        self._spec(deadline)
        agent = self.binding.agent_dir
        control = strict_json(agent + '/control.json', deadline=deadline, clock=self.clock)
        require(type(control.get('schema')) is int and control['schema'] == 1)
        require(control.get('incarnation') == self.binding.task_incarnation)
        require(type(control.get('generation')) is int and control['generation'] == self.generation)
        require(control.get('desired') == 'running' and 'hold' in control and control['hold'] is None)
        require(isinstance(control.get('mission_base'), str)
                and re.fullmatch('[0-9a-fA-F]{40}', control['mission_base']) is not None)
        lease, acceptance = control.get('lease'), control.get('acceptance')
        require(type(lease) is dict and lease.get('state') == 'active'
                and lease.get('start_attempt_id') == self.attempt_id)
        require(type(acceptance) is dict and acceptance.get('status') in ('pending', 'revise'))
        inflight = strict_json(agent + '/inbox/inflight/' + self.binding.event_key + '.json',
                               deadline=deadline, clock=self.clock)
        require(inflight.get('key') == self.binding.event_key and type(inflight.get('meta')) is dict)
        op = inflight['meta'].get('codex_operation')
        expected = dict(schema=1, operation_id=self.operation_id,
                        task_incarnation=self.binding.task_incarnation, generation=self.generation,
                        attempt_id=self.attempt_id, thread_id=self.binding.thread_id,
                        turn_id=self.binding.turn_id, status='active')
        require(type(op) is dict and all(type(op.get(k)) is type(v) and op[k] == v for k, v in expected.items()))
        if os.path.lexists(agent + '/done.json'):
            validate_done(strict_json(agent + '/done.json', deadline=deadline, clock=self.clock))
        self._budget(deadline)

    @contextmanager
    def guard(self, binding, *, deadline):
        pins = []
        acquired = False
        try:
            require(binding == self.binding)
            self._budget(deadline)
            require(self._mutex.acquire(blocking=False))
            acquired = True
            locks = self._pins(deadline, pins)
            for path in locks:
                self._budget(deadline)
                before = self._info(path)
                fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
                pins.append((path, fd, False, True))
                require((before.st_dev, before.st_ino) == (os.fstat(fd).st_dev, os.fstat(fd).st_ino))
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise BackendBusyError('TASK backend busy') from None
                self._check_pins(pins, deadline)
            self._authority(deadline)
            self._check_pins(pins, deadline)
            self._active = (threading.get_ident(), deadline, pins)
            yield True
        except BackendBusyError:
            raise
        except Exception:
            raise BackendError('TASK backend refused') from None
        finally:
            if acquired:
                self._active = None
                for _, fd, _, _ in reversed(pins):
                    os.close(fd)
                self._mutex.release()

    def write(self, binding, tool, arguments, *, deadline):
        try:
            require(binding == self.binding and self._active is not None
                    and self._active[0] == threading.get_ident())
            effective = min(deadline, self._active[1])
            self._budget(deadline)
            self._budget(effective)
            # Use exactly the bridge text contract without opening bridge state.
            validator = object.__new__(CodexTaskBridge)
            validator.binding = binding
            validator._request(dict(id=1, method='item/tool/call', params=dict(
                threadId=binding.thread_id, turnId=binding.turn_id, callId='backend',
                tool=tool, arguments=arguments)))
            self._check_pins(self._active[2], effective)
            self._authority(effective)
            self._check_pins(self._active[2], effective)
            if tool == 'task_ask':
                qid = create_question_locked(binding.agent_dir, binding.event_key, 'info',
                    arguments['question'], options=arguments.get('options'), context=arguments.get('context'),
                    strict=True, deadline=effective, clock=self.clock)
                result = {'qid': qid}
            else:
                request_done_locked(binding.agent_dir, binding.event_key, arguments.get('summary'),
                                    strict=True, deadline=effective, clock=self.clock)
                result = {'requested': True}
            self._budget(effective)
            return result
        except Exception:
            raise BackendError('TASK backend refused') from None
