"""Exclusive, fenced Codex event TASK controller. Native content is data."""
from contextlib import contextmanager, ExitStack
import copy
from datetime import datetime, timezone, timedelta
import fcntl
import hashlib
import json
import importlib.machinery
import importlib.util
import math
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import time
from uuid import UUID, uuid4
from _codex_task_store import CodexTaskOperationStore
from _codex_task_profile import sealed_overrides, sealed_host_argv, sealed_thread_params, validate_sealed_policy, _HASHES, _plain, _equal
from _codex_task_host import CodexTaskHost, SystemdTaskManager
from _codex_task_transport import CodexTaskRuntimeTransport
from _codex_task_backend import CodexTaskBackend, BackendBusyError
from _codex_task_bridge import TaskBinding, CodexTaskBridge, dynamic_tools
from _codex_task_files import CodexTaskFiles
from _codex_task_lifecycle import CodexTaskLifecycle, TaskThread
from _agent_question_io import strict_json, durable_json, create_question_locked, fsync_dir
from _agent_done_io import request_done_locked
from _agent_worktree import git_run


class RuntimeError(Exception):
    pass


def require(value):
    if not value:
        raise RuntimeError('Codex TASK runtime refused')


def digest(value):
    _plain(value)
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _stamp(value):
    return (value.st_dev,value.st_ino,value.st_uid,value.st_gid,value.st_mode,value.st_nlink,
            value.st_size,value.st_mtime_ns,value.st_ctime_ns)


def file_info(path, *, private=True, executable=False):
    require(type(path) is str and os.path.isabs(path) and os.path.normpath(path) == path and os.path.realpath(path) == path)
    parent=os.path.dirname(path)
    while True:
        directory=os.lstat(parent)
        require(stat.S_ISDIR(directory.st_mode) and directory.st_uid in (0,os.getuid()))
        require(not directory.st_mode & 0o022 or directory.st_uid==0 and directory.st_mode & stat.S_ISVTX)
        if parent=='/': break
        parent=os.path.dirname(parent)
    info = os.lstat(path)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid in ((os.getuid(),) if private else (0, os.getuid())))
    require(stat.S_IMODE(info.st_mode) == 0o600 if private else not info.st_mode & 0o022)
    if executable:
        require(bool(info.st_mode & 0o111))
    return info


def read_json(path):
    before=file_info(path)
    require(before.st_size<=1024*1024)
    result = strict_json(path)
    require(_stamp(os.lstat(path))==_stamp(before))
    _plain(result)
    return result


def hash_file(path, deadline):
    before = file_info(path, private=False, executable=True)
    require(before.st_size <= 512 * 1024 * 1024)
    sha = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        require(_stamp(os.fstat(fd)) == _stamp(before))
        while True:
            require(time.monotonic() < deadline)
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
        require(_stamp(os.fstat(fd)) == _stamp(before) and _stamp(os.lstat(path)) == _stamp(before))
    finally:
        os.close(fd)
    return sha.hexdigest()


def verify_release(executable, companion_paths, *, deadline):
    require(platform.system() == 'Linux' and platform.machine() == 'x86_64')
    paths = dict(companion_paths, codex=executable)
    hashes = {key: hash_file(path, deadline) for key, path in paths.items()}
    require(hashes == _HASHES)
    result = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=max(.01, deadline-time.monotonic()))
    require(result.returncode == 0 and result.stdout.strip() == 'codex-cli 0.160.0')
    return {'version': '0.160.0', 'hashes': hashes}


def host_factory(state_dir, task_incarnation, cwd, *, executable, argv_factory, budget, clock):
    return CodexTaskHost(state_dir, task_incarnation, cwd, executable=executable,
                         argv_factory=argv_factory, manager=SystemdTaskManager(clock=clock, host_budget=budget), clock=clock)


def transport_factory(socket, *, deadline, clock):
    require(type(socket) is str and os.path.isabs(socket) and os.path.normpath(socket)==socket and clock()<deadline)
    alias=os.lstat(socket)
    require(alias.st_uid==os.getuid() and (stat.S_ISSOCK(alias.st_mode) or stat.S_ISLNK(alias.st_mode)))
    target=os.path.realpath(socket)
    require(len(os.fsencode(target))<108 and os.path.realpath(os.path.dirname(socket))==os.path.dirname(socket))
    info=os.lstat(target)
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and stat.S_IMODE(info.st_mode)==0o600)
    parent=os.path.dirname(target)
    while True:
        directory=os.lstat(parent)
        require(stat.S_ISDIR(directory.st_mode) and directory.st_uid in (0,os.getuid())
            and (not directory.st_mode & 0o022 or directory.st_uid==0 and directory.st_mode & stat.S_ISVTX))
        if parent=='/':break
        parent=os.path.dirname(parent)
    transport=CodexTaskRuntimeTransport(target,deadline=deadline,clock=clock)
    try:
        require(_stamp(os.lstat(socket))==_stamp(alias) and os.path.realpath(socket)==target
            and _stamp(os.lstat(target))==_stamp(info))
    except Exception:
        transport.close();raise
    return transport


def verify_child(host_snapshot, companion_paths, *, deadline):
    require(host_snapshot.control_group is not None and host_snapshot.main_pid is not None)
    manager = SystemdTaskManager()
    status = manager.inspect(host_snapshot.unit, deadline=deadline)
    require(status['invocation_id'] == host_snapshot.invocation_id and status['main_pid'] == host_snapshot.main_pid
            and status['control_group'] == host_snapshot.control_group)
    handle = manager._open_process(host_snapshot.main_pid, host_snapshot.control_group, deadline=deadline)
    try:
        matches = []
        for entry in os.scandir('/proc'):
            require(time.monotonic() < deadline)
            if not entry.name.isdigit():
                continue
            try:
                pid = int(entry.name)
                directory = '/proc/' + entry.name
                info = os.stat(directory)
                if info.st_uid != os.getuid() or os.readlink(directory + '/exe') != companion_paths['code_mode_host']:
                    continue
                group = Path(directory + '/cgroup').read_text().strip()
                if group != '0::' + host_snapshot.control_group:
                    continue
                raw = Path(directory + '/stat').read_text()
                ticks = int(raw[raw.rindex(')')+2:].split()[19])
                sha = hash_file(companion_paths['code_mode_host'], deadline)
                require(sha == _HASHES['code_mode_host'])
                after=Path(directory + '/stat').read_text()
                require(int(after[after.rindex(')')+2:].split()[19])==ticks and os.stat(directory).st_uid==info.st_uid
                    and os.readlink(directory+'/exe')==companion_paths['code_mode_host'] and Path(directory + '/cgroup').read_text().strip() == group)
                matches.append(dict(pid=pid, start_ticks=ticks, uid=info.st_uid, executable=companion_paths['code_mode_host'],
                    sha256=sha, control_group=host_snapshot.control_group, invocation_id=host_snapshot.invocation_id))
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
        require(len(matches) == 1 and not handle.exited())
        current = manager.inspect(host_snapshot.unit, deadline=deadline)
        require(current['invocation_id'] == status['invocation_id'] and current['control_group'] == status['control_group'] and current['main_pid'] == status['main_pid'])
        return matches[0]
    finally:
        handle.close()


def read_thread_metadata(thread_path, thread_id, cwd, *, deadline):
    root = os.path.join(os.environ.get('CODEX_HOME', os.path.expanduser('~/.codex')), 'sessions')
    require(os.path.realpath(root) == root and os.path.commonpath((root, thread_path)) == root)
    before = file_info(thread_path)
    parent = os.path.dirname(thread_path)
    while True:
        info = os.lstat(parent)
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022)
        if parent == root:
            break
        parent = os.path.dirname(parent)
    with open(thread_path, 'rb') as stream:
        raw = stream.readline(1024*1024+1)
    require(len(raw) <= 1024*1024 and _stamp(os.lstat(thread_path)) == _stamp(before) and time.monotonic() < deadline)
    def pairs(rows):
        result = {}
        for key, val in rows:
            require(key not in result)
            result[key] = val
        return result
    record = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: require(False))
    _plain(record)
    require(record.get('type') == 'session_meta')
    meta = record['payload']
    tools = copy.deepcopy(meta['dynamic_tools'])
    for tool in tools:
        tool.setdefault('deferLoading', False)
    require(meta['id'] == thread_id and meta['cwd'] == cwd and meta['cli_version'] == '0.160.0')
    require(meta.get('history_mode', 'legacy') in ('legacy', 'paginated'))
    return dict(id=meta['id'], cwd=meta['cwd'], cli_version=meta['cli_version'], history_mode=meta.get('history_mode', 'legacy'),
        roots=meta.get('roots', [cwd]), dynamic_tools=tools, dynamic_tools_digest=digest(tools))


def _registry_input(value):
    return type(value) is str and re.fullmatch(r'\s*text\s*\(\s*ALL_TOOLS\s*\.\s*map\s*\(\s*t\s*=>\s*t\s*\.\s*name\s*\)\s*\.\s*sort\s*\(\s*\)\s*\)\s*;?\s*',value) is not None

def _registry(events, thread, turn):
    inputs={}; names=None
    for event in events:
        method=event.get('method'); params=event.get('params',{})
        if method in ('rawResponseItem/completed','item/rawResponseItem/completed'):
            require(params.get('threadId')==thread and params.get('turnId')==turn)
            item=params.get('item',{})
            if item.get('type')=='custom_tool_call':
                require(item.get('name') in ('exec','functions.exec') and _registry_input(item.get('input'))
                    and type(item.get('call_id')) is str and item['call_id'])
                require(not inputs or item['call_id'] in inputs)
                inputs[item['call_id']]=True
            elif item.get('type')=='custom_tool_call_output':
                require(item.get('call_id') in inputs)
                output=item['output']
                if type(output) is list:
                    require(1<=len(output)<=100)
                    require(all(type(block) is dict and set(block)=={'type','text'} and block['type'] in ('input_text','text') and type(block['text']) is str for block in output))
                    output='\n'.join(block['text'] for block in output)
                require(type(output) is str and len(output.encode())<=65536 and names is None)
                offset=output.find('[')
                require(offset>=0)
                names=json.loads(output[offset:]); _plain(names)
    require(type(names) is list and len(names)==7 and set(names)=={'apply_patch','clock__curr_time','task_read','task_search','task_list','task_ask','task_done'})
    return names


def read_registry_evidence(thread_path, thread_id, turn_id, cwd, operation_id, *, deadline):
    """Read only an immutable prefix of the admitted, owned native rollout."""
    root=os.path.join(os.environ.get('CODEX_HOME',os.path.expanduser('~/.codex')),'sessions')
    require(os.path.isabs(root) and os.path.realpath(root)==root and os.path.commonpath((root,thread_path))==root)
    for value in (thread_id,turn_id,operation_id):
        require(type(value) is str and str(UUID(value))==value)
    before=file_info(thread_path)
    require(before.st_size<=32*1024*1024)
    identity=lambda info:(info.st_dev,info.st_ino,info.st_uid,info.st_gid,info.st_mode,info.st_nlink)
    ancestors={};parent=os.path.dirname(thread_path)
    while True:
        info=os.lstat(parent)
        require(stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid() and not info.st_mode & 0o022)
        ancestors[parent]=identity(info)
        if parent==root:break
        parent=os.path.dirname(parent)
    fd=os.open(thread_path,os.O_RDONLY|os.O_NOFOLLOW)
    def prefix():
        data=bytearray()
        while len(data)<before.st_size:
            require(time.monotonic()<deadline)
            chunk=os.read(fd,min(1024*1024,before.st_size-len(data)))
            require(bool(chunk));data.extend(chunk)
        return bytes(data)
    try:
        require(identity(os.fstat(fd))==identity(before))
        raw=prefix();os.lseek(fd,0,os.SEEK_SET)
        require(hashlib.sha256(prefix()).digest()==hashlib.sha256(raw).digest())
        require(identity(os.fstat(fd))==identity(before) and os.fstat(fd).st_size>=before.st_size
            and identity(os.lstat(thread_path))==identity(before) and os.lstat(thread_path).st_size>=before.st_size
            and os.path.realpath(thread_path)==thread_path)
        require(all(identity(os.lstat(path))==pin for path,pin in ancestors.items()))
    finally:os.close(fd)
    lines=raw.split(b'\n')
    require(len(lines)-1<=100000 and all(len(line)<=1024*1024 for line in lines))
    def pairs(entries):
        result={}
        for key,value in entries:
            require(key not in result);result[key]=value
        return result
    stage=0;current=None;found=False;evidence=[];proven=False
    for index,line in enumerate(lines[:-1]):
        require(time.monotonic()<deadline)
        row=json.loads(line,object_pairs_hook=pairs,parse_constant=lambda _:require(False));_plain(row)
        require(type(row) is dict and type(row.get('payload')) is dict)
        kind=row.get('type');item=row['payload']
        if index==0:
            require(kind=='session_meta' and item.get('id')==thread_id and item.get('cwd')==cwd
                and item.get('cli_version')=='0.160.0' and item.get('history_mode')=='legacy')
            continue
        require(kind!='session_meta')
        if kind=='event_msg' and item.get('type')=='task_started':
            current=item.get('turn_id')
            if current==turn_id:
                require(not found);found=True;stage=1
            continue
        if kind=='turn_context' and item.get('turn_id')==turn_id:
            require(current==turn_id and stage==1 and item.get('cwd')==cwd);stage=2
            continue
        if kind=='event_msg' and item.get('type')=='user_message' and current==turn_id:
            require(stage==2 and item.get('client_id')==operation_id);stage=3
            continue
        if kind!='response_item':continue
        effect=item.get('type') not in ('message','reasoning','compaction')
        if not effect:continue
        require(current is not None)
        if current!=turn_id:continue
        require(stage==3)
        if item.get('type') not in ('custom_tool_call','custom_tool_call_output'):
            require(proven)
            continue
        call=item['type']=='custom_tool_call'
        if proven and call and not _registry_input(item.get('input')):continue
        if proven and not call and item.get('call_id')!=evidence[0]['params']['item']['call_id']:continue
        keys=('type','name','call_id','input') if call else ('type','call_id','output')
        normalized={key:copy.deepcopy(item[key]) for key in keys}
        frame=dict(method='rawResponseItem/completed',params=dict(threadId=thread_id,turnId=turn_id,item=normalized))
        if proven:
            if call:require(_equal(frame,evidence[0]))
            else:_registry([evidence[0],frame],thread_id,turn_id)
            continue
        evidence.append(frame)
        require(len(evidence)<=256 and len(json.dumps(evidence).encode())<=1024*1024)
        if call:
            require(normalized['name'] in ('exec','functions.exec') and _registry_input(normalized['input']))
        else:
            _registry(evidence,thread_id,turn_id);proven=True
    require(found or not any(line for line in lines[1:-1]))
    if not proven:return None
    return dict(schema=1,thread_id=thread_id,turn_id=turn_id,operation_id=operation_id,events=evidence)


def heartbeat(agent_dir, generation, attempt_id, phase, iteration_started_at, *, deadline):
    control = read_json(agent_dir + '/control.json')
    require(control['generation'] == generation and control['lease']['start_attempt_id'] == attempt_id)
    now = datetime.now(timezone.utc)
    stamp = lambda value: value.strftime('%Y-%m-%dT%H:%M:%SZ')
    started = now - timedelta(seconds=max(0, time.monotonic() - iteration_started_at))
    durable_json(agent_dir + '/state.%s.json' % generation, dict(schema=1, generation=generation,
        attempt_id=attempt_id, phase='working' if phase=='running' else phase, status_line='Codex: '+phase, agent_claim='running',
        claim_artifact=None, session_id=None, iteration_started_at=stamp(started),
        last_progress_at=stamp(now), next_wakeup_at=stamp(now+timedelta(seconds=30)),
        iterations=0, cost_usd=None), deadline=deadline)


_DEFAULTS = dict(host_factory=host_factory, transport_factory=transport_factory, verify_release=verify_release,
    verify_child=verify_child, read_thread_metadata=read_thread_metadata, read_registry_evidence=read_registry_evidence, heartbeat=heartbeat)


class CodexTaskRuntime:
    def __init__(self, agent_dir, *, state_root, executable, companion_paths, host_budget, adapters=None, clock=time.monotonic):
        try:
            require(adapters is None or type(adapters) is dict)
            overrides = {} if adapters is None else dict(adapters)
            require(set(overrides) <= set(_DEFAULTS) | {'checkpoint'} and all(callable(v) for v in overrides.values()))
            self.agent_dir, self.state_root, self.executable = agent_dir, state_root, executable
            self.companion_paths, self.host_budget = copy.deepcopy(companion_paths), copy.deepcopy(host_budget)
            self.clock, self.adapters = clock, dict(_DEFAULTS, **overrides)
            self.adapters.setdefault('checkpoint', self._checkpoint)
            if 'heartbeat' not in overrides: self.adapters['heartbeat'] = self._heartbeat
            self.store = CodexTaskOperationStore(agent_dir, state_root=state_root, clock=clock)
            self.cwd = agent_dir + '/work'
            self.hosts = {}
        except Exception:
            raise RuntimeError('Codex TASK runtime refused') from None

    def _deadline(self, deadline):
        require(type(deadline) in (float, int) and math.isfinite(deadline) and deadline > self.clock())

    def _heartbeat(self, agent_dir, generation, attempt_id, phase, iteration_started_at, *, deadline):
        require(agent_dir == self.agent_dir)
        with self._guard(self.heartbeat_binding,self.heartbeat_operation,generation,attempt_id,deadline=deadline):
            control=read_json(agent_dir+'/control.json')
            require(type(generation) is int and control['generation']==generation
                and control['lease']['start_attempt_id']==attempt_id and control['lease']['state']=='active'
                and control['desired']=='running' and control.get('hold') is None
                and control['incarnation']==self.active_incarnation)
            heartbeat(agent_dir,generation,attempt_id,phase,iteration_started_at,deadline=deadline)

    def _spec(self, deadline):
        self._deadline(deadline)
        path = self.agent_dir + '/spec.yaml'
        before = file_info(path)
        result = subprocess.run(['yq', '-o=json', '-I=0', '.', path], capture_output=True, timeout=min(10, deadline-self.clock()))
        require(result.returncode == 0 and len(result.stdout) <= 1024*1024 and _stamp(os.lstat(path)) == _stamp(before))
        def pairs(items):
            out = {}
            for key, value in items:
                require(key not in out)
                out[key] = value
            return out
        value = json.loads(result.stdout, object_pairs_hook=pairs, parse_constant=lambda _: require(False))
        _plain(value)
        require(type(value) is dict and all(value.get(k) == v for k, v in dict(engine='codex',type='event',runtime='drain',workspace='worktree').items()))
        return value

    def static_preflight(self, *, deadline):
        try:
            spec = self._spec(deadline)
            sealed_overrides(self.cwd, [])
            require(type(self.companion_paths) is dict and set(self.companion_paths) == {'code_mode_host','bwrap','rg'})
            for path in [self.executable] + list(self.companion_paths.values()):
                file_info(path, private=False, executable=True)
            require(type(self.host_budget) is dict and set(self.host_budget) == {'memory_max_mb','tasks_max','cpu_quota_percent'})
            for key, low, high in (('memory_max_mb',256,8192),('tasks_max',16,256),('cpu_quota_percent',1,400)):
                require(type(self.host_budget[key]) is int and low <= self.host_budget[key] <= high)
            require(not any(key in spec.get('limits', {}) for key in ('cost_usd','cost_per_day_usd','usd_cap','max_cost_usd','week_usd_cap')))
            evidence = self.adapters['verify_release'](self.executable, self.companion_paths, deadline=deadline)
            _plain(evidence)
            require(_equal(evidence, {'version':'0.160.0','hashes':_HASHES}))
            self._deadline(deadline)
            return dict(ready=True, version='0.160.0',permission_profile='control_task',release_hashes=copy.deepcopy(_HASHES))
        except Exception:
            raise RuntimeError('Codex TASK runtime refused') from None

    def require_drained(self, *, deadline):
        try:
            self._deadline(deadline)
            return self.store.require_drained(deadline=deadline)
        except Exception:
            raise RuntimeError('Codex TASK runtime refused') from None

    def _host(self, op, names):
        key = op['operation_id']
        if key not in self.hosts:
            self.hosts[key] = self.adapters['host_factory'](op['host_state_dir'], str(UUID(hex=op['task_incarnation'])), self.cwd,
                executable=self.executable, argv_factory=lambda socket, *, executable: sealed_host_argv(socket,self.cwd,names,executable=executable),
                budget=copy.deepcopy(self.host_budget), clock=self.clock)
        return self.hosts[key]

    def revoke_and_drain(self, reason, *, deadline):
        try:
            self._deadline(deadline)
            require(reason in ('cancel','pause','recovery','ask','done','terminal','timeout','policy','shutdown'))
            records = self.store.revoke(deadline=deadline)
            for op in records:
                if not op['launch_reserved']:
                    continue
                require(os.path.isfile(op['host_state_dir'] + '/journal.json'))
                parent=str(Path(op['host_state_dir']).parent)
                completion_path=parent+'/completion.json'
                if os.path.lexists(completion_path):
                    with self.store.revoked_guard(op['operation_id'],str(UUID(hex=op['task_incarnation'])),deadline=deadline):
                        with self._completion_lock(parent,deadline):
                            completion=read_json(completion_path)
                            require(all(_equal(completion.get(key),op[key]) for key in ('operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id')))
                            if completion['phase']=='requested':
                                completion['phase']='revoked';durable_json(completion_path,completion,deadline=deadline,clock=self.clock)
                host = self._host(op, [])
                snapshot = host.abort(deadline=deadline, guard=lambda incarnation, *, deadline, key=op['operation_id']:
                    self.store.revoked_guard(key, incarnation, deadline=deadline))
                require(snapshot.phase == 'stopped')
                journal = read_json(op['host_state_dir'] + '/journal.json')
                evidence = dict(operation_id=op['operation_id'], task_incarnation=op['task_incarnation'], host_state_dir=op['host_state_dir'],
                    phase='stopped', unit=journal['unit'], token=journal['token'], invocation_id=journal['invocation_id'], drained=True)
                self.store.record_drained(op['operation_id'], evidence, deadline=deadline)
            self.require_drained(deadline=deadline)
            if reason in ('pause','cancel','shutdown'):
                for op in self.store.snapshot(deadline=deadline)['operations'].values():self._expire_questions(op,deadline)
            return dict(drained=True, operations=[op['operation_id'] for op in records])
        except Exception:
            raise RuntimeError('Codex TASK runtime refused') from None

    @contextmanager
    def _locks(self, *, deadline, all_locks=False):
        paths = []
        if all_locks:
            paths = [self.agent_dir+'/questions/.lock', self.agent_dir+'/done.lock',
                os.path.dirname(self.agent_dir)+'/.locks/new-task-'+os.path.basename(self.agent_dir)+'.lock']
        paths += [self.agent_dir+'/.lock',self.agent_dir+'/inbox/.inbox.lock']
        descriptors = []
        try:
            for path in paths:
                self._deadline(deadline)
                before = file_info(path)
                fd = os.open(path,os.O_RDWR|os.O_NOFOLLOW)
                descriptors.append((path,fd,before))
                require(_stamp(os.fstat(fd))==_stamp(before))
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
            for path, fd, before in descriptors:
                require(_stamp(os.lstat(path))==_stamp(before) and _stamp(os.fstat(fd))==_stamp(before))
        finally:
            for _,fd,_ in reversed(descriptors):
                os.close(fd)

    def _synthetic(self, owner, purpose, generation, attempt, deadline):
        key = ('codex-config-discovery-' if purpose=='config_discovery' else 'codex-bootstrap-') + str(uuid4())
        with self._locks(deadline=deadline):
            control = read_json(self.agent_dir+'/control.json')
            require(control['generation']==generation and control['lease']['start_attempt_id']==attempt and control['desired']=='running' and control['hold'] is None)
            require(os.path.isfile(self.agent_dir+'/inbox/inflight/'+owner+'.json'))
            env = dict(key=key,meta=dict(internal='codex_config_discovery' if purpose=='config_discovery' else 'codex_bootstrap',owner_event_key=owner))
            if purpose=='config_discovery':
                env['meta']['purpose']=purpose
            path=self.agent_dir+'/inbox/inflight/'+key+'.json'
            fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            os.close(fd)
            durable_json(path,env,deadline=deadline,clock=self.clock)
        return key

    def _archive_internal(self, key, outcome, deadline):
        with self._locks(deadline=deadline):
            path=self.agent_dir+'/inbox/inflight/'+key+'.json'
            env=read_json(path)
            env['meta'].setdefault('history',[]).append(dict(outcome=outcome,internal=env['meta']['internal']))
            durable_json(path,env,deadline=deadline,clock=self.clock)
            destination=self.agent_dir+'/inbox/done/'+key+'.json'
            self._dedup_locked(key)
            require(not os.path.lexists(destination))
            os.rename(path,destination)
            fsync_dir(os.path.dirname(path)); fsync_dir(os.path.dirname(destination))

    def _launch(self, key, generation, attempt, names, deadline):
        op=self.store.prepare(key,generation,attempt,deadline=deadline)
        self.current_op=op
        host=self._host(op,names)
        with self.store.launch_guard(op['operation_id'],deadline=deadline):
            snapshot=host.start(deadline=deadline)
            require(snapshot.phase=='running' and type(snapshot.socket_ready) is bool and snapshot.control_group)
            identity=[snapshot.unit,snapshot.invocation_id,snapshot.main_pid,snapshot.socket,snapshot.control_group]
            require(type(snapshot.main_pid) is int and snapshot.main_pid>0
                and all(type(value) is str and value for value in (snapshot.unit,snapshot.invocation_id,snapshot.socket,snapshot.control_group)))
            token=read_json(op['host_state_dir']+'/journal.json')['token']
            ready_deadline=min(deadline,self.clock()+10)
            while not snapshot.socket_ready:
                self._deadline(ready_deadline)
                snapshot=host.inspect(deadline=ready_deadline)
                require(snapshot.phase=='running' and type(snapshot.socket_ready) is bool
                    and _equal([snapshot.unit,snapshot.invocation_id,snapshot.main_pid,snapshot.socket,snapshot.control_group],identity)
                    and read_json(op['host_state_dir']+'/journal.json')['token']==token)
                if not snapshot.socket_ready: time.sleep(min(.05,max(0,ready_deadline-self.clock())))
            self._deadline(deadline)
        transport=self.adapters['transport_factory'](snapshot.socket,deadline=deadline,clock=self.clock)
        return op,host,snapshot,transport

    def _config(self, transport, names, deadline):
        result=transport.call('config/read',dict(cwd=self.cwd,includeLayers=False),deadline=deadline)
        _plain(result)
        config=result['config']; servers=config.get('mcp_servers',{})
        require(type(servers) is dict and len(servers)<=1000)
        require(all(type(name) is str and re.fullmatch('[A-Za-z0-9_-]+',name) for name in servers))
        if names is not None:
            require(set(servers)==set(names) and all(row.get('enabled') is False for row in servers.values()))
        return config,list(servers)

    def _catalog(self, transport, thread_id, deadline):
        pages=[]; cursor=None
        for _ in range(100):
            params=dict(threadId=thread_id)
            if cursor is not None: params['cursor']=cursor
            page=transport.call('mcpServerStatus/list',params,deadline=deadline); pages.append(page)
            cursor=page.get('nextCursor')
            if cursor is None: return pages
        require(False)

    def _child(self,snapshot,deadline):
        proof=self.adapters['verify_child'](snapshot,self.companion_paths,deadline=deadline); _plain(proof)
        require(set(proof)=={'pid','start_ticks','uid','executable','sha256','control_group','invocation_id'})
        require(type(proof['pid']) is int and proof['pid']>0 and type(proof['start_ticks']) is int and proof['start_ticks']>0)
        require(type(proof['uid']) is int and proof['uid']==os.getuid() and proof['executable']==self.companion_paths['code_mode_host']
            and proof['sha256']==_HASHES['code_mode_host'] and proof['control_group']==snapshot.control_group and proof['invocation_id']==snapshot.invocation_id)

    def _metadata(self,thread,tools,deadline):
        result=self.adapters['read_thread_metadata'](thread['path'],thread['id'],self.cwd,deadline=deadline); _plain(result)
        require(set(result)=={'id','cwd','cli_version','history_mode','roots','dynamic_tools','dynamic_tools_digest'})
        require(result['id']==thread['id'] and result['cwd']==self.cwd and result['cli_version']=='0.160.0'
            and result['history_mode'] in ('legacy','paginated') and result['roots']==[self.cwd])
        normalized=copy.deepcopy(result['dynamic_tools'])
        for tool in normalized: tool.setdefault('deferLoading',False)
        require(_equal(normalized,tools) and result['dynamic_tools_digest']==digest(result['dynamic_tools']))

    @contextmanager
    def _guard(self, binding, op, generation, attempt, *, deadline):
        backend=CodexTaskBackend(binding,generation,attempt,op['operation_id'],clock=self.clock)
        with ExitStack() as stack:
            while True:
                self._deadline(deadline)
                try:
                    permitted=stack.enter_context(backend.guard(binding,deadline=deadline))
                    break
                except BackendBusyError:
                    time.sleep(min(.01,max(0,deadline-self.clock())))
            require(permitted is True)
            with self.store.guard_locked(binding,op['operation_id'],deadline=deadline) as permitted:
                require(permitted is True)
                yield backend

    def _registry_input(self,value):
        return _registry_input(value)

    def _registry(self,events,thread,turn):
        return _registry(events,thread,turn)

    def _bootstrap_events(self,transport,evidence,thread,turn):
        batch=list(transport.events);transport.events.clear()
        _plain(batch)
        require(len(batch)<=256 and len(json.dumps(batch).encode())<=1024*1024)
        for event in batch:
            require(type(event) is dict and 'id' not in event)
            params=event.get('params',{});item=params.get('item',{})
            require(item.get('type')!='fileChange' and event.get('method')!='item/fileChange/patchUpdated')
            if event.get('method') in ('rawResponseItem/completed','item/rawResponseItem/completed'):
                require(params.get('threadId')==thread and params.get('turnId')==turn)
                if item.get('type') in ('custom_tool_call','custom_tool_call_output'):
                    evidence.append(event)
        require(len(evidence)<=256 and len(json.dumps(evidence).encode())<=1024*1024)

    def _terminal(self,transport,thread,turn,operation_id,deadline):
        result=transport.call('thread/read',dict(threadId=thread,includeTurns=True),deadline=deadline)['thread']
        require(result['id']==thread and result['cwd']==self.cwd)
        turns=[entry for entry in result['turns'] if entry['id']==turn]
        require(len(turns)==1 and turns[0]['status'] in ('completed','failed','interrupted'))
        clients=[item for item in turns[0]['items'] if item.get('type')=='userMessage' and item.get('clientId')==operation_id]
        require(len(clients)==1)
        self.last_native_thread=result
        return turns[0]['status']

    def _finish(self,op,terminal,deadline):
        self.store.finish(op['operation_id'],dict(operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],thread_id=op['thread_id'],
            turn_id=op['turn_id'],terminal=terminal,terminal_proven=True,quiescent=True),deadline=deadline)

    def _state_dir(self,deadline):
        snap=self.store.snapshot(deadline=deadline)
        return self.state_root+'/'+snap['state_id']

    def _executor_owner(self):
        path=self.agent_dir+'/inbox/.executor.lock';before=file_info(path)
        with open('/proc/locks','rb') as stream:raw=stream.read(1024*1024+1)
        require(len(raw)<=1024*1024)
        owners=[]
        for line in raw.decode('ascii').splitlines():
            fields=line.split()
            if len(fields)<8 or fields[1:4]!=['FLOCK','ADVISORY','WRITE']:continue
            device=fields[5].split(':')
            if len(device)!=3:continue
            if (int(device[0],16),int(device[1],16),int(device[2]))==(os.major(before.st_dev),os.minor(before.st_dev),before.st_ino):
                owners.append(int(fields[4]))
        require(owners==[os.getpid()] and _stamp(os.lstat(path))==_stamp(before))

    def execute(self,event_key,generation,attempt_id,*,deadline):
        self._deadline(deadline)
        self.current_op=None
        op=None; transport=None; thread_id=None; turn_id=None
        try:
            self._deadline(deadline)
            self._executor_owner()
            self.static_preflight(deadline=deadline)
            self.require_drained(deadline=deadline)
            spec=self._spec(deadline)
            require(type(event_key) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,256}',event_key) and event_key not in ('.','..'))
            require(type(generation) is int and generation>=1 and type(attempt_id) is str)
            control=read_json(self.agent_dir+'/control.json')
            self.active_incarnation=control['incarnation']
            require(control['generation']==generation and control['lease']['state']=='active' and control['lease']['start_attempt_id']==attempt_id
                and control['desired']=='running' and control['hold'] is None)
            read_json(self.agent_dir+'/inbox/inflight/'+event_key+'.json')
            root=self._state_dir(deadline); admission_path=root+'/admission.json'
            tools=CodexTaskFiles.dynamic_tools()+dynamic_tools()
            if os.path.lexists(admission_path):
                admission=read_json(admission_path)
                require(admission['incarnation']==control['incarnation'] and admission['release']==_HASHES and admission['tools']==tools)
                names=admission['mcp_names']; thread_id=admission['thread_id']
            else:
                require(not self.store.snapshot(deadline=deadline)['operations'])
                key=self._synthetic(event_key,'config_discovery',generation,attempt_id,deadline)
                op,host,snapshot,transport=self._launch(key,generation,attempt_id,[],deadline)
                config,names=self._config(transport,None,deadline)
                transport.close(); transport=None
                self.revoke_and_drain('terminal',deadline=deadline)
                self._archive_internal(key,'cancelled',deadline)
                key=self._synthetic(event_key,'bootstrap',generation,attempt_id,deadline)
                op,host,snapshot,transport=self._launch(key,generation,attempt_id,names,deadline)
                config,_=self._config(transport,names,deadline)
                start_params=sealed_thread_params(self.cwd,names,tools)
                start_params['experimentalRawEvents']=True
                start_params['historyMode']='legacy'
                response=transport.call('thread/start',start_params,deadline=deadline)
                thread_id=response['thread']['id']; self.store.record_thread(op['operation_id'],thread_id,deadline=deadline)
                text='text(ALL_TOOLS.map(t=>t.name).sort())'
                with self.store.reserve_start(op['operation_id'],deadline=deadline) as reservation:
                    result=transport.call('turn/start',dict(threadId=thread_id,clientUserMessageId=op['operation_id'],input=[dict(type='text',text=text)]),deadline=deadline)
                    turn_id=result['turn']['id']; op=reservation.activate(thread_id,turn_id)
                transport.bind_operation(thread_id,turn_id)
                events=[]; registry=None
                while True:
                    self._deadline(deadline)
                    self._bootstrap_events(transport,events,thread_id,turn_id)
                    outputs=[event for event in events if event.get('method') in ('rawResponseItem/completed','item/rawResponseItem/completed') and event.get('params',{}).get('item',{}).get('type')=='custom_tool_call_output']
                    if outputs: registry=self._registry(events,thread_id,turn_id)
                    history=transport.call('thread/read',dict(threadId=thread_id,includeTurns=True),deadline=deadline)['thread']
                    require(history['id']==thread_id and history['cwd']==self.cwd)
                    turns=[row for row in history['turns'] if row['id']==turn_id]
                    require(len(turns)==1)
                    if turns[0]['status'] in ('completed','failed','interrupted'):
                        self._bootstrap_events(transport,events,thread_id,turn_id)
                        registry=self._registry(events,thread_id,turn_id)
                        self._child(snapshot,deadline)
                        break
                    time.sleep(min(.05,max(0,deadline-self.clock())))
                pages=self._catalog(transport,thread_id,deadline)
                validate_sealed_policy(response,self.cwd,config,pages,registry,dict(version='0.160.0',hashes=_HASHES))
                terminal=self._terminal(transport,thread_id,turn_id,op['operation_id'],deadline); require(terminal=='completed')
                self._bootstrap_events(transport,events,thread_id,turn_id)
                require(_equal(self._registry(events,thread_id,turn_id),registry))
                self._metadata(self.last_native_thread,tools,deadline)
                transport.close(); transport=None
                self.revoke_and_drain('terminal',deadline=deadline)
                require(not git_run(['status','--porcelain'],self.cwd,spec['project'],deadline=deadline).stdout.strip())
                admission=dict(incarnation=control['incarnation'],release=copy.deepcopy(_HASHES),tools=tools,mcp_names=names,thread_id=thread_id,
                    thread_path=self.last_native_thread['path'],model=response['model'],reasoning_effort=response['reasoningEffort'],
                    permission_profile='control_task',config_digest=digest(sealed_overrides(self.cwd,names)),registry=registry)
                operation={field:op[field] for field in ('operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id')}
                operation['owner_event_key']=event_key
                terminal_evidence=dict(operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],thread_id=thread_id,
                    turn_id=turn_id,terminal=terminal,terminal_proven=True,quiescent=True)
                durable_json(str(Path(op['host_state_dir']).parent/'bootstrap-proof.json'),dict(schema=1,operation=operation,admission=admission,terminal=terminal_evidence),deadline=deadline,clock=self.clock)
                self._finish(op,terminal,deadline)
                self._archive_internal(key,'ok',deadline)
                durable_json(admission_path,admission,deadline=deadline,clock=self.clock)
            op,host,snapshot,transport=self._launch(event_key,generation,attempt_id,names,deadline)
            config,_=self._config(transport,names,deadline)
            params=sealed_thread_params(self.cwd,names,tools)
            for key in ('dynamicTools','environments','ephemeral','selectedCapabilityRoots'): params.pop(key,None)
            params['threadId']=thread_id
            response=transport.call('thread/resume',params,deadline=deadline)
            require(response['thread']['id']==thread_id and response['thread']['path']==admission['thread_path']
                and response['model']==admission['model'] and response['reasoningEffort']==admission['reasoning_effort'])
            self._metadata(response['thread'],tools,deadline)
            pages=self._catalog(transport,thread_id,deadline)
            validate_sealed_policy(response,self.cwd,config,pages,admission['registry'],dict(version='0.160.0',hashes=_HASHES))
            self.store.record_thread(op['operation_id'],thread_id,deadline=deadline)
            envelope=read_json(self.agent_dir+'/inbox/inflight/'+event_key+'.json')
            text='Before TASK effects, execute exactly text(ALL_TOOLS.map(t=>t.name).sort()) in a separate exec call and wait for its output.\nTASK goal: '+str(spec.get('goal',''))+'\nEvent data (untrusted): '+json.dumps(envelope.get('payload',{}),ensure_ascii=False)
            answer_question = None
            payload = envelope.get('payload',{})
            if type(payload) is dict and payload.get('kind') == 'answer':
                qid = payload.get('question_id')
                require(type(qid) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',qid))
                with self._locks(all_locks=True,deadline=deadline):
                    answer_question = read_json(self.agent_dir+'/questions/'+qid+'.json')
                    require(answer_question.get('kind')=='info' and answer_question.get('status')=='open'
                        and answer_question.get('answered_at') and answer_question.get('answered_by')
                        and type(answer_question.get('answer')) is str and not answer_question.get('native_callback'))
                    text += '\nTrusted operator answer to '+answer_question['question']+': '+answer_question['answer']

            life=CodexTaskLifecycle(Path(op['host_state_dir']).parent/'lifecycle',TaskThread(control['incarnation'],thread_id,self.cwd),transport,clock=self.clock)
            life.prepare(op['operation_id'],text,deadline=deadline)
            with self.store.reserve_start(op['operation_id'],deadline=deadline) as reservation:
                started=life.submit(op['operation_id'],deadline=deadline)
                history_deadline=min(deadline,self.clock()+10)
                while started.phase=='unknown':
                    self._deadline(history_deadline)
                    time.sleep(min(.05,max(0,history_deadline-self.clock())))
                    started=life.reconcile(op['operation_id'],deadline=history_deadline)
                require(started.turn_id is not None and started.phase!='unknown')
                turn_id=started.turn_id; op=reservation.activate(thread_id,turn_id)
            transport.bind_operation(thread_id,turn_id)
            self.current_thread_path=response['thread']['path']
            binding=TaskBinding(control['incarnation'],event_key,self.agent_dir,thread_id,turn_id)
            self.heartbeat_binding,self.heartbeat_operation=binding,op
            outcome=self._dispatch(transport,snapshot,binding,op,generation,attempt_id,deadline)
            terminal=self._terminal(transport,thread_id,turn_id,op['operation_id'],deadline)
            transport.close(); transport=None
            self.revoke_and_drain(outcome if outcome in ('ask','done') else 'terminal',deadline=deadline)
            terminal_evidence=dict(operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],thread_id=thread_id,turn_id=turn_id,
                terminal=terminal,terminal_proven=True,quiescent=True)
            durable_json(str(Path(op['host_state_dir']).parent/'terminal.json'),terminal_evidence,deadline=deadline,clock=self.clock)
            completion_path=Path(op['host_state_dir']).parent/'completion.json'
            if completion_path.exists():
                self._complete(op,deadline)
            else:
                self._checkpoint_twice(op,event_key,'TASK checkpoint',deadline)
            if answer_question is not None:
                with self._locks(all_locks=True,deadline=deadline):
                    current = read_json(self.agent_dir+'/questions/'+answer_question['qid']+'.json')
                    require(current == answer_question)
                    current['status']='closed';current['closed_by_envelope']=event_key
                    durable_json(self.agent_dir+'/questions/'+current['qid']+'.json',current,deadline=deadline,clock=self.clock)
            self._finish(op,terminal,deadline)
            return dict(outcome={'ask':'asked','done':'done_requested'}.get(outcome,'ran'),event_key=event_key,operation_id=op['operation_id'],thread_id=thread_id,turn_id=turn_id,reason=None)
        except Exception:
            if op is None: op=self.current_op
            if transport is not None:
                transport.close()
            if op is not None:
                try: self.revoke_and_drain('policy',deadline=max(deadline,self.clock()+30))
                except Exception: pass
            return dict(outcome='unknown' if op is not None else 'blocked',event_key=event_key,operation_id=op['operation_id'] if op else None,thread_id=thread_id,turn_id=turn_id,reason='native_evidence_unconfirmed')

    @contextmanager
    def _already_guarded(self, binding, *, deadline):
        self._deadline(deadline)
        yield True
        self._deadline(deadline)

    def _owned_registry(self,binding,op,snapshot,captured_events,deadline):
        self._deadline(deadline)
        proof=self.adapters['read_registry_evidence'](self.current_thread_path,binding.thread_id,binding.turn_id,self.cwd,op['operation_id'],deadline=deadline)
        if proof is None:return None
        _plain(proof)
        require(type(proof) is dict and set(proof)=={'schema','thread_id','turn_id','operation_id','events'}
            and type(proof['schema']) is int and proof['schema']==1 and proof['thread_id']==binding.thread_id
            and proof['turn_id']==binding.turn_id and proof['operation_id']==op['operation_id']
            and type(proof['events']) is list and len(proof['events'])<=256 and len(json.dumps(proof['events']).encode())<=1024*1024)
        require(all(type(frame) is dict and set(frame)=={'method','params'} and frame['method'] in ('rawResponseItem/completed','item/rawResponseItem/completed')
            and type(frame['params']) is dict and set(frame['params'])=={'threadId','turnId','item'}
            and type(frame['params']['item']) is dict and frame['params']['item'].get('type') in ('custom_tool_call','custom_tool_call_output')
            for frame in proof['events']))
        self._registry(proof['events'],binding.thread_id,binding.turn_id)
        for captured in captured_events:
            item=captured.get('params',{}).get('item',{})
            if item.get('type')=='custom_tool_call':
                require(any(all(_equal(item.get(key),candidate['params']['item'].get(key)) for key in ('type','name','call_id','input'))
                    for candidate in proof['events'] if candidate.get('params',{}).get('item',{}).get('type')=='custom_tool_call'))
            elif item.get('type')=='custom_tool_call_output':
                self._registry([proof['events'][0],captured],binding.thread_id,binding.turn_id)
        self._child(snapshot,deadline)
        return copy.deepcopy(proof['events'])

    def _dispatch(self,transport,snapshot,binding,op,generation,attempt,deadline):
        waiting=[]; changes={}; seen={}; resolved=set(); iteration=self.clock();registry_events=[];registry_proven=False
        pending=[];proof_deadline=min(deadline,self.clock()+10)
        while True:
            self._deadline(deadline)
            self.adapters['heartbeat'](self.agent_dir,generation,attempt,'running',iteration,deadline=deadline)
            events=list(transport.events); transport.events.clear()
            _plain(events)
            require(len(events)<=256 and len(json.dumps(events).encode())<=1024*1024)
            sampled=False;proof=None
            wire=any(event.get('method') in ('rawResponseItem/completed','item/rawResponseItem/completed')
                and event.get('params',{}).get('item',{}).get('type') in ('custom_tool_call','custom_tool_call_output') for event in events)
            file_events=any(event.get('method')=='item/fileChange/patchUpdated' or event.get('method') in ('item/started','item/completed')
                and event.get('params',{}).get('item',{}).get('type')=='fileChange' for event in events)
            if not registry_proven and not wire and (file_events or pending or any('id' in event for event in events)):
                proof=self._owned_registry(binding,op,snapshot,registry_events,proof_deadline);sampled=True
                if proof is not None:registry_events=proof;registry_proven=True
            for event in events:
                if event.get('method') in ('rawResponseItem/completed','item/rawResponseItem/completed'):
                    item=event.get('params',{}).get('item',{})
                    if not registry_proven:
                        registry_events.append(event)
                        require(len(registry_events)<=256 and len(json.dumps(registry_events).encode())<=1024*1024)
                        if item.get('type')=='custom_tool_call':
                            require(item.get('name') in ('exec','functions.exec') and self._registry_input(item.get('input')))
                        if item.get('type')=='custom_tool_call_output':
                            self._registry(registry_events,binding.thread_id,binding.turn_id);self._child(snapshot,deadline);registry_proven=True
                    elif item.get('type')=='custom_tool_call' and self._registry_input(item.get('input')):
                        originals=[row for row in registry_events if row.get('params',{}).get('item',{}).get('type')=='custom_tool_call']
                        require(any(_equal(event,row) for row in originals))
                    elif item.get('type')=='custom_tool_call_output':
                        originals=[row for row in registry_events if row.get('params',{}).get('item',{}).get('type')=='custom_tool_call' and row['params']['item']['call_id']==item.get('call_id')]
                        if originals:self._registry([originals[0],event],binding.thread_id,binding.turn_id)
                if not registry_proven:
                    require(event.get('method')!='item/fileChange/patchUpdated'
                        and not (event.get('method') in ('item/started','item/completed') and event.get('params',{}).get('item',{}).get('type') in ('fileChange','commandExecution')))
                    if 'id' in event:
                        params=event.get('params',{})
                        require(event.get('method')=='item/tool/call' and params.get('tool') in ('task_read','task_search','task_list','task_ask','task_done')
                            and params.get('threadId')==binding.thread_id and params.get('turnId')==binding.turn_id)
            if not registry_proven:
                self._deadline(proof_deadline)
                if not sampled:
                    proof=None
                    if pending or any('id' in event for event in events):
                        proof=self._owned_registry(binding,op,snapshot,registry_events,proof_deadline)
                if proof is not None:
                    registry_events=proof;registry_proven=True
                else:
                    pending.extend(event for event in events if 'id' in event)
                    require(len(pending)<=256 and len(json.dumps(pending).encode())<=1024*1024)
                    observed=transport.call('thread/read',dict(threadId=binding.thread_id,includeTurns=True),deadline=proof_deadline)['thread']
                    require(observed['id']==binding.thread_id and observed['cwd']==self.cwd)
                    terminal=any(turn.get('id')==binding.turn_id and turn.get('status') in ('completed','failed','interrupted') for turn in observed['turns'])
                    if terminal and not sampled:
                        proof=self._owned_registry(binding,op,snapshot,registry_events,proof_deadline)
                        if proof is not None:
                            registry_events=proof;registry_proven=True
                    if not registry_proven:
                        time.sleep(min(.05,max(0,proof_deadline-self.clock())))
                        continue
            if pending:
                events=pending+events;pending=[]
                require(len(events)<=256 and len(json.dumps(events).encode())<=1024*1024)
            for event in events:
                _plain(event)
                method=event.get('method'); params=event.get('params',{})
                if method=='serverRequest/resolved':
                    resolved.add((type(params['requestId']),params['requestId']))
                if method=='item/fileChange/patchUpdated':
                    require(not waiting)
                if method=='item/started' and params.get('item',{}).get('type')=='fileChange':
                    require(params.get('threadId')==binding.thread_id and params.get('turnId')==binding.turn_id)
                    changes[params['item']['id']]=params['item']['changes']
                if 'id' not in event:
                    continue
                require(registry_proven)
                key=(type(event['id']),event['id']); fingerprint=digest(event)
                if key in seen:
                    require(seen[key]==fingerprint)
                    continue
                seen[key]=fingerprint
                require(params.get('threadId')==binding.thread_id and params.get('turnId')==binding.turn_id)
                self._child(snapshot,deadline)
                if method=='item/tool/call':
                    tool=params['tool']; args=params['arguments']
                    with self._guard(binding,op,generation,attempt,deadline=deadline) as backend:
                        if tool in ('task_read','task_search','task_list'):
                            value=CodexTaskFiles(binding,guard=self._already_guarded,clock=self.clock).handle(tool,args,deadline=deadline)
                            result=dict(success=True,contentItems=[dict(type='inputText',text=json.dumps(value,ensure_ascii=False))])
                        else:
                            validator=object.__new__(CodexTaskBridge); validator.binding=binding
                            validator._request(event)
                            parent=str(Path(op['host_state_dir']).parent)
                            def writer(owned, name, arguments, *, deadline):
                                if name=='task_ask':
                                    return backend.write(owned,name,arguments,deadline=deadline)
                                summary=arguments.get('summary') or 'TASK completion'
                                completion=dict(schema=1,operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],generation=generation,attempt_id=attempt,
                                    event_key=binding.event_key,thread_id=binding.thread_id,turn_id=binding.turn_id,request_id=event['id'],call_id=params['callId'],
                                    request_digest=digest(event),summary=summary,phase='requested',checkpoint=None,done_receipt=None)
                                with self._completion_lock(parent,deadline):
                                    path=parent+'/completion.json'; require(not os.path.lexists(path))
                                    durable_json(path,completion,deadline=deadline,clock=self.clock)
                                return dict(requested=True)
                            value=CodexTaskBridge(parent+'/bridge',binding,guard=self._already_guarded,writer=writer,clock=self.clock).handle(event,deadline=deadline)
                            result=value['result']
                        transport.reply_dynamic(event['id'],result,thread_id=binding.thread_id,turn_id=binding.turn_id,call_id=params['callId'],deadline=deadline)
                    if tool in ('task_ask','task_done'):
                        transport.call('turn/interrupt',dict(threadId=binding.thread_id,turnId=binding.turn_id),deadline=deadline)
                        return 'ask' if tool=='task_ask' else 'done'
                elif method=='item/fileChange/requestApproval':
                    waiting.append(event)
                else:
                    require(False)
            if waiting:
                event=waiting[0]; params=event['params']; key=(type(event['id']),event['id'])
                require(key not in resolved)
                patch=changes.get(params['itemId'])
                if patch is not None:
                    self._capture_patch(patch)
                    allowed_decisions=['reject']
                    try:
                        self._validate_patch(patch)
                        if params.get('grantRoot') is None: allowed_decisions=['approve','reject']
                    except RuntimeError: pass
                    with self._guard(binding,op,generation,attempt,deadline=deadline):
                        extra=dict(native_callback=dict(operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],generation=generation,attempt_id=attempt,
                            thread_id=binding.thread_id,turn_id=binding.turn_id,request_id=event['id'],method=event['method'],item_id=params['itemId'],
                            payload_fingerprint=digest(event),changes_digest=digest(patch),allowed_decisions=allowed_decisions,status='pending'),engine='codex')
                        qid=create_question_locked(self.agent_dir,binding.event_key,'permission','Codex file changes: '+json.dumps(patch,ensure_ascii=False),extra=extra,
                            strict=True,deadline=deadline,clock=self.clock)
                    while True:
                        self._deadline(deadline)
                        self.adapters['heartbeat'](self.agent_dir,generation,attempt,'waiting_input',iteration,deadline=deadline)
                        queued=list(transport.events); transport.events.clear()
                        for update in queued:
                            if update.get('method')=='serverRequest/resolved':
                                rpc=update.get('params',{}).get('requestId'); require((type(rpc),rpc)!=key)
                            require(update.get('method')!='item/fileChange/patchUpdated')
                            if update.get('method')=='item/started' and update.get('params',{}).get('item',{}).get('id')==params['itemId']:
                                updated=update['params'];require(updated.get('threadId')==binding.thread_id and updated.get('turnId')==binding.turn_id
                                    and updated['item'].get('type')=='fileChange' and _equal(updated['item'].get('changes'),patch))
                            if 'id' in update and (type(update['id']),update['id'])==key: require(digest(update)==seen[key])
                        with self._guard(binding,op,generation,attempt,deadline=deadline):
                            question=read_json(self.agent_dir+'/questions/'+qid+'.json')
                        if question.get('answered_at') is not None:
                            require(question.get('answered_by') and question.get('decision') in ('approve','reject') and question.get('answer') is None)
                            with self._guard(binding,op,generation,attempt,deadline=deadline):
                                question=read_json(self.agent_dir+'/questions/'+qid+'.json')
                                require(question.get('qid')==qid and question.get('engine')=='codex'
                                    and question.get('kind')=='permission' and question.get('status')=='open'
                                    and _equal(question.get('native_callback'),extra['native_callback'])
                                    and question.get('decision') in allowed_decisions
                                    and question.get('answered_at') and question.get('answered_by') and question.get('answer') is None)
                                self._child(snapshot,deadline)
                                require(question['decision'] in allowed_decisions)
                                self._capture_patch(patch)
                                if question['decision']=='approve': self._validate_patch(patch)
                                future_callback=copy.deepcopy(question['native_callback']);future_callback['status']='answered'
                                receipt=dict(question_id=qid,operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],
                                    callback_digest=digest(future_callback),decision=question['decision'],answered_at=question['answered_at'],answered_by=question['answered_by'])
                                parent=str(Path(op['host_state_dir']).parent);confirmed=parent+'/approval-'+qid+'.json';intent=parent+'/approval-'+qid+'-intent.json'
                                require(not os.path.lexists(intent))
                                require(not os.path.lexists(confirmed))
                                durable_json(intent,dict(schema=1,phase='send_intent',**receipt),deadline=deadline,clock=self.clock)
                                transport.reply_approval(event['id'],dict(decision='accept' if question['decision']=='approve' else 'decline'),method=event['method'],
                                    thread_id=binding.thread_id,turn_id=binding.turn_id,item_id=params['itemId'],deadline=deadline)
                            self._approval_resolution(transport,event,binding,patch,generation,attempt,iteration,deadline)
                            with self._guard(binding,op,generation,attempt,deadline=deadline):
                                require(_equal(read_json(self.agent_dir+'/questions/'+qid+'.json'),question))
                                self._child(snapshot,deadline)
                                self._capture_patch(patch)
                                if question['decision']=='approve':self._validate_patch(patch)
                                require(_equal(read_json(intent),dict(schema=1,phase='send_intent',**receipt)) and not os.path.lexists(confirmed))
                                durable_json(confirmed,receipt,deadline=deadline,clock=self.clock)
                                question['status']='closed'
                                question['native_callback']=future_callback
                                durable_json(self.agent_dir+'/questions/'+qid+'.json',question,deadline=deadline,clock=self.clock)
                            waiting.clear(); break
                        transport.call('thread/read',dict(threadId=binding.thread_id,includeTurns=True),deadline=deadline)
                        time.sleep(min(.05,max(0,deadline-self.clock())))
                    continue
            thread=transport.call('thread/read',dict(threadId=binding.thread_id,includeTurns=True),deadline=deadline)['thread']
            turn=[t for t in thread['turns'] if t['id']==binding.turn_id]
            if turn and turn[0]['status'] in ('completed','failed','interrupted'):
                require(not waiting)
                require(registry_proven and turn[0]['status']=='completed')
                return 'terminal'
            time.sleep(min(.05,max(0,deadline-self.clock())))

    def _approval_resolution(self,transport,event,binding,patch,generation,attempt,iteration,deadline):
        deferred=[];resolved=False
        while not resolved:
            self._deadline(deadline)
            self.adapters['heartbeat'](self.agent_dir,generation,attempt,'waiting_input',iteration,deadline=deadline)
            require(len(transport.events)<=256)
            while transport.events:
                notification=transport.receive(deadline=deadline);_plain(notification)
                require(len(json.dumps(notification).encode())<=1024*1024)
                params=notification.get('params',{});item=params.get('item',{})
                if notification.get('method')=='serverRequest/resolved':
                    require(not resolved and type(params.get('requestId')) is type(event['id'])
                        and params['requestId']==event['id'] and params.get('threadId')==binding.thread_id)
                    resolved=True
                else:
                    require(notification.get('method')!='item/fileChange/patchUpdated')
                    if item.get('type')=='fileChange':
                        require(params.get('threadId')==binding.thread_id and params.get('turnId')==binding.turn_id
                            and item.get('id')==event['params']['itemId'] and _equal(item.get('changes'),patch))
                    deferred.append(notification)
                    require(len(deferred)<=256 and len(json.dumps(deferred).encode())<=1024*1024)
            if not resolved:
                transport.call('thread/read',dict(threadId=binding.thread_id,includeTurns=True),deadline=deadline)
                time.sleep(min(.05,max(0,deadline-self.clock())))
        transport.events.extend(deferred)

    def _capture_patch(self,patch):
        _plain(patch)
        require(type(patch) is list and 1<=len(patch)<=100 and len(json.dumps(patch).encode())<=256*1024)
        for row in patch:
            require(type(row) is dict and set(row)=={'path','kind','diff'} and type(row['diff']) is str)
            kind=row['kind'];require(type(kind) is dict and kind.get('type') in ('add','delete','update'))
            require(set(kind)<= {'type','move_path'})
            for path in [row['path']]+([kind['move_path']] if kind.get('move_path') is not None else []):
                require(type(path) is str and len(path.encode())<=4096 and os.path.isabs(path)
                    and os.path.normpath(path)==path and '\x00' not in path)

    def _validate_patch(self,patch):
        _plain(patch); require(type(patch) is list and 1<=len(patch)<=100 and len(json.dumps(patch).encode())<=256*1024)
        for row in patch:
            require(type(row) is dict and set(row)=={'path','kind','diff'} and type(row['diff']) is str)
            kind=row['kind']; require(type(kind) is dict and kind.get('type') in ('add','delete','update'))
            paths=[row['path']]
            if kind.get('move_path') is not None: paths.append(kind['move_path'])
            for path in paths:
                require(type(path) is str and os.path.isabs(path) and os.path.normpath(path)==path and os.path.realpath(path)==path
                    and os.path.commonpath((self.cwd,path))==self.cwd and path!=self.cwd)
                relative=os.path.relpath(path,self.cwd)
                for component in relative.split('/'):
                    name=component.lower()
                    require(name not in ('.git','.ssh','.aws','.azure','.kube','browser-sessions','.env','.netrc','.npmrc','.pypirc','auth.json','credentials.json','cookies.json','id_rsa','id_ed25519','id_dsa','id_ecdsa')
                        and not name.startswith('.env.') and not name.endswith(('.pem','.key','.p12','.pfx')))

    def _checkpoint_twice(self,op,event,summary,deadline,completion=None):
        self.require_drained(deadline=deadline)
        path=str(Path(op['host_state_dir']).parent/'checkpoint.json') if completion is None else str(Path(op['host_state_dir']).parent/'completion.json')
        prepared=completion.get('checkpoint') if completion else None
        if prepared is None:
            prepared=self.adapters['checkpoint'](self.agent_dir,op['operation_id'],event,summary,None,deadline=deadline)
            self._receipt(prepared,op)
            if completion is not None:
                completion['checkpoint']=prepared; durable_json(path,completion,deadline=deadline,clock=self.clock)
            else: durable_json(path,prepared,deadline=deadline,clock=self.clock)
        receipt=self.adapters['checkpoint'](self.agent_dir,op['operation_id'],event,summary,prepared,deadline=deadline)
        self._receipt(receipt,op); require(receipt['commit_sha'] is not None)
        if completion is not None:
            completion['checkpoint']=receipt; completion['phase']='checkpointed'; durable_json(path,completion,deadline=deadline,clock=self.clock)
        else: durable_json(path,receipt,deadline=deadline,clock=self.clock)
        return receipt

    def _receipt(self,value,op):
        _plain(value); require(type(value) is dict and set(value)=={'branch','parent_sha','tree_sha','commit_sha','trailer','intent_trailer','no_commit'})
        require(value['trailer']=='Codex-Task-Operation: '+op['operation_id'] and type(value['no_commit']) is bool)
        for key in ('parent_sha','tree_sha'):
            require(type(value[key]) is str and re.fullmatch('[0-9a-f]{40}',value[key]))
        require(value['commit_sha'] is None or type(value['commit_sha']) is str and re.fullmatch('[0-9a-f]{40}',value['commit_sha']))

    def _checkpoint(self,agent_dir,operation_id,event_key,summary,prepared_receipt,*,deadline):
        self.require_drained(deadline=deadline)
        snapshot=self.store.snapshot(deadline=deadline); op=snapshot['operations'][operation_id]
        require(op['event_key']==event_key and agent_dir==self.agent_dir)
        require(type(summary) is str and not any(re.match(r'^\s*Codex-Task-(Operation|Intent):',line) for line in summary.splitlines()))
        spec=self._spec(deadline); project=spec['project']; parent=str(Path(op['host_state_dir']).parent)
        def git(args,index=None):
            result=git_run(args,self.cwd,project,index_file=index,deadline=deadline,clock=self.clock)
            require(result.returncode==0); return result.stdout.strip()
        head=git(['rev-parse','HEAD']); branch=git(['symbolic-ref','--short','HEAD'])
        require(branch=='task/'+os.path.basename(self.agent_dir)+'-'+snapshot['task_incarnation'][:8])
        completion=parent+'/completion.json'
        request_digest=read_json(completion)['request_digest'] if os.path.isfile(completion) else hashlib.sha256(summary.encode()).hexdigest()
        trailer='Codex-Task-Operation: '+operation_id; intent_trailer='Codex-Task-Intent: '+request_digest
        index=parent+'/checkpoint.index'
        if prepared_receipt is None:
            require(not os.path.lexists(index))
            source=git(['rev-parse','--git-path','index'])
            if not os.path.isabs(source): source=os.path.join(self.cwd,source)
            source=os.path.realpath(source)
            with open(source,'rb') as src:
                fd=os.open(index,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'wb') as dst: shutil.copyfileobj(src,dst); dst.flush(); os.fsync(dst.fileno())
            git(['read-tree','HEAD'],index); git(['add','--all'],index); tree=git(['write-tree'],index)
            return dict(branch=branch,parent_sha=head,tree_sha=tree,commit_sha=None,trailer=trailer,intent_trailer=intent_trailer,no_commit=False)
        receipt=copy.deepcopy(prepared_receipt); self._receipt(receipt,op)
        require(receipt['branch']==branch and receipt['intent_trailer']==intent_trailer)
        if head!=receipt['parent_sha']:
            require(git(['rev-parse',head+'^'])==receipt['parent_sha'] and git(['rev-parse',head+'^{tree}'])==receipt['tree_sha'])
            message=git(['show','-s','--format=%B',head])
            require(message.splitlines().count(trailer)==1 and message.splitlines().count(intent_trailer)==1)
            receipt.update(commit_sha=head,no_commit=False)
        elif git(['rev-parse','HEAD^{tree}'])==receipt['tree_sha']:
            receipt.update(commit_sha=head,no_commit=True)
        else:
            require(git(['write-tree'],index)==receipt['tree_sha'])
            git(['-c','user.name=claude-control','-c','user.email=claude-control@localhost','commit','--no-verify','--no-gpg-sign','-m',summary,'-m',trailer,'-m',intent_trailer],index)
            new_head=git(['rev-parse','HEAD'])
            require(git(['rev-parse',new_head+'^'])==receipt['parent_sha'] and git(['rev-parse',new_head+'^{tree}'])==receipt['tree_sha'])
            receipt.update(commit_sha=new_head,no_commit=False)
        if not receipt['no_commit']:
            message=git(['show','-s','--format=%B',receipt['commit_sha']])
            for label,expected in (('Codex-Task-Operation:',trailer),('Codex-Task-Intent:',intent_trailer)):
                rows=[line for line in message.splitlines() if line.startswith(label)]
                require(rows==[expected])
        git(['read-tree','HEAD'])
        require(git(['status','--porcelain','--untracked-files=all'])=='')
        return receipt

    @contextmanager
    def _completion_lock(self,parent,deadline):
        self._deadline(deadline)
        path=parent+'/completion.lock'
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            before=file_info(path);require(_stamp(os.fstat(fd))==_stamp(before))
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            yield
            require(_stamp(os.lstat(path))==_stamp(before) and _stamp(os.fstat(fd))==_stamp(before))
        finally: os.close(fd)

    def _complete(self,op,deadline):
        self.require_drained(deadline=deadline)
        path=str(Path(op['host_state_dir']).parent/'completion.json'); require(file_info(path).st_size<=64*1024); value=read_json(path)
        require(set(value)=={'schema','operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id','request_id','call_id','request_digest','summary','phase','checkpoint','done_receipt'})
        require(type(value['schema']) is int and value['schema']==1 and all(_equal(value[key],op[key]) for key in ('operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id')))
        require(type(value['request_id']) in (str,int) and type(value['call_id']) is str and 0<len(value['call_id'].encode())<=256
            and type(value['request_digest']) is str and re.fullmatch(r'[0-9a-f]{64}',value['request_digest'])
            and type(value['summary']) is str and 0<len(value['summary'].encode())<=16384)
        require(value['phase'] in ('requested','revoked','drained','checkpointed','done_written','finalized'))
        if value['phase'] in ('done_written','finalized'): return
        if value['phase'] in ('requested','revoked'):
            value['phase']='drained'; durable_json(path,value,deadline=deadline,clock=self.clock)
        if value['phase']=='drained': self._checkpoint_twice(op,op['event_key'],value['summary'],deadline,value)
        with self._locks(deadline=deadline,all_locks=True):
            with self.store._context(deadline,locked=True) as context:
                control=context['control']; require(control['generation']==op['generation'] and control['lease']['start_attempt_id']==op['attempt_id']
                    and control['desired']=='running' and control['hold'] is None and control['acceptance']['status'] in ('pending','revise'))
                for known in context['index']['operations'].values(): self.store._drain_gate(context,known,deadline)
                with self._completion_lock(str(Path(op['host_state_dir']).parent),deadline):
                    self._write_done(op,value,path,deadline)

    def _write_done(self,op,value,path,deadline):
        done=self.agent_dir+'/done.json'
        if os.path.lexists(done):
            prior=read_json(done); require(prior['envelope_key']==op['event_key'] and prior['summary']==value['summary'])
        else: request_done_locked(self.agent_dir,op['event_key'],value['summary'],strict=True,deadline=deadline,clock=self.clock)
        value['done_receipt']=dict(envelope_key=op['event_key'],summary_digest=digest(value['summary']))
        value['phase']='done_written'; durable_json(path,value,deadline=deadline,clock=self.clock)

    def _ask_proof(self,op):
        parent=str(Path(op['host_state_dir']).parent)
        journal=read_json(parent+'/bridge/journal.json')
        expected=dict(task_incarnation=op['task_incarnation'],event_key=op['event_key'],agent_dir=self.agent_dir,
                      thread_id=op['thread_id'],turn_id=op['turn_id'])
        require(type(journal['schema']) is int and journal['schema']==1 and _equal(journal['binding'],expected))
        candidates=[row for row in journal['calls'].values() if row.get('tool')=='task_ask' and row.get('result') is not None]
        require(len(candidates)==1)
        row=candidates[0];qid=row['result']['qid'];require(type(qid) is str and str(UUID(qid))==qid)
        question=read_json(self.agent_dir+'/questions/'+qid+'.json')
        require(question.get('qid')==qid and question.get('kind')=='info' and question.get('envelope_key')==op['event_key']
            and question.get('status')=='open' and not question.get('native_callback'))
        arguments=dict(question=question['question'])
        for key in ('options','context'):
            if question.get(key) is not None:arguments[key]=question[key]
        require(row['fingerprint']==digest(arguments))

    def _shared_runner(self):
        loader=importlib.machinery.SourceFileLoader('_codex_runtime_shared_runner',os.path.join(os.path.dirname(__file__),'claude-agent-run'))
        spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def _dedup_locked(self,key):
        self._shared_runner().dedup_add(self.agent_dir+'/inbox',key)

    def _finalize_completion(self,op,deadline):
        parent=str(Path(op['host_state_dir']).parent);path=parent+'/completion.json'
        value=read_json(path);receipt=value['checkpoint'];self._receipt(receipt,op)
        require(value['phase'] in ('done_written','finalized') and receipt['commit_sha'] is not None)
        spec=self._spec(deadline)
        with self._locks(all_locks=True,deadline=deadline),self.store._context(deadline,locked=True) as context:
            current=context['index']['operations'][op['operation_id']];control=context['control']
            require(all(_equal(current[key],op[key]) for key in ('operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id')))
            require(current['status'] in ('revoked','finished') and control['generation']==op['generation']
                and control['lease']['start_attempt_id']==op['attempt_id'] and control['desired']=='running'
                and control['hold'] is None and control['acceptance']['status'] in ('pending','revise'))
            for known in context['index']['operations'].values():self.store._drain_gate(context,known,deadline)
            with self._completion_lock(parent,deadline):
                require(_equal(read_json(path),value))
                done_path=self.agent_dir+'/done.json';done=read_json(done_path)
                require(done['state']=='requested' and done['envelope_key']==op['event_key'] and done['summary']==value['summary'])
                result=git_run(['rev-parse','HEAD'],self.cwd,spec['project'],deadline=deadline,clock=self.clock)
                require(result.returncode==0 and result.stdout.strip()==receipt['commit_sha'])
                expected=dict(commit_sha=receipt['commit_sha'],branch=receipt['branch'],base=control['mission_base'])
                if done.get('finalized') is True:
                    require(all(_equal(done.get(key),expected[key]) for key in expected))
                else:
                    self._shared_runner().finalize_worktree_done_locked(self.agent_dir,op['event_key'],os.path.basename(self.agent_dir),spec['project'])
                finalized=read_json(done_path)
                require(finalized['state']=='requested' and finalized['finalized'] is True
                    and finalized['envelope_key']==op['event_key'] and finalized['summary']==value['summary']
                    and all(_equal(finalized.get(key),expected[key]) for key in expected))
                self._deadline(deadline)
                value['phase']='finalized';durable_json(path,value,deadline=deadline,clock=self.clock)

    def _archive_ordinary(self,op,deadline):
        with self._locks(all_locks=True,deadline=deadline):
            with self.store._context(deadline,locked=True) as context:
                current=context['index']['operations'][op['operation_id']]
                require(current['status']=='finished')
                for known in context['index']['operations'].values():self.store._drain_gate(context,known,deadline)
                source=self.agent_dir+'/inbox/inflight/'+op['event_key']+'.json'
                destination=self.agent_dir+'/inbox/done/'+op['event_key']+'.json'
                if not os.path.lexists(source):
                    env=read_json(destination);require(_equal(env['meta']['codex_operation'],current))
                    return
                env=read_json(source);require(_equal(env['meta']['codex_operation'],current))
                outcome='ok'
                if current['terminal_evidence']['terminal']=='interrupted' and not os.path.lexists(str(Path(op['host_state_dir']).parent/'completion.json')):
                    self._ask_proof(op);outcome='asked'
                env['meta'].setdefault('history',[]).append(dict(outcome=outcome))
                durable_json(source,env,deadline=deadline,clock=self.clock)
                self._dedup_locked(op['event_key'])
                require(not os.path.lexists(destination));os.rename(source,destination)
                fsync_dir(os.path.dirname(source));fsync_dir(os.path.dirname(destination))

    def _recover_questions(self,op,deadline):
        parent=Path(op['host_state_dir']).parent
        for path in parent.glob('approval-*-intent.json'):
            intent=read_json(str(path))
            require(set(intent)=={'schema','phase','question_id','operation_id','task_incarnation','callback_digest','decision','answered_at','answered_by'}
                and type(intent['schema']) is int and intent['schema']==1 and intent['phase']=='send_intent')
            receipt={key:value for key,value in intent.items() if key not in ('schema','phase')}
            qid=receipt['question_id'];require(type(qid) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',qid))
            require(path.name=='approval-'+qid+'-intent.json' and receipt['operation_id']==op['operation_id'] and receipt['task_incarnation']==op['task_incarnation'])
            require(_equal(read_json(str(parent/('approval-'+qid+'.json'))),receipt))
            with self._locks(all_locks=True,deadline=deadline), self.store._context(deadline,locked=True) as context:
                current=context['index']['operations'][op['operation_id']]
                require(current['task_incarnation']==op['task_incarnation'] and current['status'] in ('revoked','finished'))
                for known in context['index']['operations'].values():self.store._drain_gate(context,known,deadline)
                question_path=self.agent_dir+'/questions/'+qid+'.json';question=read_json(question_path)
                callback=copy.deepcopy(question['native_callback'])
                require(question['qid']==qid and question['engine']=='codex' and question['kind']=='permission'
                    and question['status'] in ('open','closed') and callback['status'] in ('pending','answered')
                    and callback['operation_id']==op['operation_id'] and callback['task_incarnation']==op['task_incarnation']
                    and callback['thread_id']==op['thread_id'] and callback['turn_id']==op['turn_id']
                    and callback['generation']==op['generation'] and callback['attempt_id']==op['attempt_id']
                    and question['decision'] in callback['allowed_decisions'] and question['answer'] is None)
                callback['status']='answered'
                expected=dict(question_id=qid,operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],
                    callback_digest=digest(callback),decision=question['decision'],answered_at=question['answered_at'],answered_by=question['answered_by'])
                require(_equal(receipt,expected) and question['answered_at'] and question['answered_by'])
                if question['status']=='open':
                    question['status']='closed';question['native_callback']=callback
                    durable_json(question_path,question,deadline=deadline,clock=self.clock)

    def _expire_questions(self,op,deadline):
        parent=Path(op['host_state_dir']).parent
        pending=False
        for path in Path(self.agent_dir+'/questions').glob('*.json'):
            self._deadline(deadline)
            question=read_json(str(path));callback=question.get('native_callback')
            if callback is None:continue
            require(type(callback) is dict)
            if callback.get('operation_id')!=op['operation_id']:continue
            require(question.get('engine')=='codex' and question.get('kind')=='permission'
                and question.get('qid')==path.stem and all(_equal(callback.get(key),op[key]) for key in
                    ('operation_id','task_incarnation','generation','attempt_id','thread_id','turn_id')))
            if question.get('status')=='open' and callback.get('status')=='pending':pending=True
        if not pending:
            self.require_drained(deadline=deadline)
            return
        with self._locks(all_locks=True,deadline=deadline), self.store._context(deadline,locked=True) as context:
            current=context['index']['operations'][op['operation_id']]
            require(current['status'] in ('revoked','finished'))
            for known in context['index']['operations'].values():self.store._drain_gate(context,known,deadline)
            for path in Path(self.agent_dir+'/questions').glob('*.json'):
                question=read_json(str(path));callback=question.get('native_callback')
                if callback is None:continue
                require(type(callback) is dict)
                if callback.get('operation_id')!=op['operation_id']:continue
                require(question.get('engine')=='codex' and question.get('kind')=='permission'
                    and question.get('qid')==path.stem and all(_equal(callback.get(key),op[key]) for key in
                        ('operation_id','task_incarnation','generation','attempt_id','thread_id','turn_id')))
                if question.get('status')=='open' and callback.get('status')=='pending':
                    require(not os.path.lexists(str(parent/('approval-'+question['qid']+'.json')))
                        and not os.path.lexists(str(parent/('approval-'+question['qid']+'-intent.json'))))
                    question['status']='expired';callback['status']='expired'
                    durable_json(str(path),question,deadline=deadline,clock=self.clock)

    def _recover_bootstrap(self,op,deadline):
        parent=Path(op['host_state_dir']).parent
        source=self.agent_dir+'/inbox/inflight/'+op['event_key']+'.json'
        done=self.agent_dir+'/inbox/done/'+op['event_key']+'.json'
        envelope=read_json(source if os.path.lexists(source) else done)
        if envelope.get('meta',{}).get('internal')!='codex_bootstrap':return False
        proof=read_json(str(parent/'bootstrap-proof.json'))
        require(set(proof)=={'schema','operation','admission','terminal'} and type(proof['schema']) is int and proof['schema']==1)
        operation=proof['operation'];require(set(operation)=={'operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id','owner_event_key'})
        require(all(_equal(operation[key],op[key]) for key in operation if key!='owner_event_key')
            and operation['owner_event_key']==envelope['meta']['owner_event_key'])
        terminal=proof['terminal'];require(_equal(terminal,dict(operation_id=op['operation_id'],task_incarnation=op['task_incarnation'],
            thread_id=op['thread_id'],turn_id=op['turn_id'],terminal='completed',terminal_proven=True,quiescent=True)))
        admission=proof['admission'];tools=CodexTaskFiles.dynamic_tools()+dynamic_tools()
        require(set(admission)=={'incarnation','release','tools','mcp_names','thread_id','thread_path','model','reasoning_effort','permission_profile','config_digest','registry'})
        require(admission['incarnation']==op['task_incarnation'] and admission['thread_id']==op['thread_id']
            and _equal(admission['release'],_HASHES) and _equal(admission['tools'],tools) and admission['permission_profile']=='control_task'
            and admission['config_digest']==digest(sealed_overrides(self.cwd,admission['mcp_names']))
            and type(admission['registry']) is list and len(admission['registry'])==7
            and set(admission['registry'])=={'apply_patch','clock__curr_time','task_read','task_search','task_list','task_ask','task_done'})
        self.static_preflight(deadline=deadline)
        require(type(admission['model']) is str and admission['model'] and (admission['reasoning_effort'] is None or type(admission['reasoning_effort']) is str))
        self._metadata(dict(id=admission['thread_id'],path=admission['thread_path']),tools,deadline)
        if os.path.lexists(source):
            self.store.finish(op['operation_id'],terminal,deadline=deadline)
            self._archive_internal(op['event_key'],'ok',deadline)
        else:
            require(op['status']=='finished' and _equal(op['terminal_evidence'],terminal)
                and envelope['meta']['history'][-1]['outcome']=='ok')
        admission_path=self._state_dir(deadline)+'/admission.json'
        if os.path.lexists(admission_path):require(_equal(read_json(admission_path),admission))
        else:durable_json(admission_path,admission,deadline=deadline,clock=self.clock)
        return True

    def _historical_checkpoint(self,op,parent,deadline):
        checkpoint=parent+'/checkpoint.json';completion=parent+'/completion.json'
        if os.path.lexists(completion):
            value=read_json(completion)
            require(value['phase'] in ('done_written','finalized') and all(_equal(value[key],op[key]) for key in
                ('operation_id','task_incarnation','generation','attempt_id','event_key','thread_id','turn_id')))
            receipt=value['checkpoint']
        else:receipt=read_json(checkpoint)
        self._receipt(receipt,op);require(receipt['commit_sha'] is not None)
        spec=self._spec(deadline)
        def git(args):
            result=git_run(args,self.cwd,spec['project'],deadline=deadline,clock=self.clock)
            require(result.returncode==0);return result.stdout.strip()
        require(receipt['branch']=='task/'+os.path.basename(self.agent_dir)+'-'+op['task_incarnation'][:8]
            and git(['symbolic-ref','--short','HEAD'])==receipt['branch'])
        commit=receipt['commit_sha'];require(git(['rev-parse',commit+'^{tree}'])==receipt['tree_sha'])
        git(['merge-base','--is-ancestor',commit,'HEAD'])
        if receipt['no_commit']:require(commit==receipt['parent_sha'])
        else:
            require(git(['rev-parse',commit+'^'])==receipt['parent_sha'])
            message=git(['show','-s','--format=%B',commit])
            for label,expected in (('Codex-Task-Operation:',receipt['trailer']),('Codex-Task-Intent:',receipt['intent_trailer'])):
                require([line for line in message.splitlines() if line.startswith(label)]==[expected])

    def reconcile(self,*,deadline):
        try:
            self._deadline(deadline); self._executor_owner(); snapshot=self.store.snapshot(deadline=deadline)
            if not snapshot['operations']: return dict(outcome='idle',operations=[],reason=None)
            self.revoke_and_drain('recovery',deadline=deadline)
            recovered=False
            for op in snapshot['operations'].values():
                self._recover_questions(op,deadline)
                self._expire_questions(op,deadline)
                if self._recover_bootstrap(op,deadline): recovered=True;continue
                source=self.agent_dir+'/inbox/inflight/'+op['event_key']+'.json'
                envelope=read_json(source if os.path.lexists(source) else self.agent_dir+'/inbox/done/'+op['event_key']+'.json')
                if envelope.get('meta',{}).get('internal')=='codex_config_discovery':continue
                parent=str(Path(op['host_state_dir']).parent)
                terminal=read_json(parent+'/terminal.json')
                require(set(terminal)=={'operation_id','task_incarnation','thread_id','turn_id','terminal','terminal_proven','quiescent'}
                    and all(_equal(terminal[key],op[key]) for key in ('operation_id','task_incarnation','thread_id','turn_id'))
                    and terminal['terminal'] in ('completed','interrupted') and terminal['terminal_proven'] is True and terminal['quiescent'] is True)
                if op['status']=='finished':
                    require(_equal(op['terminal_evidence'],terminal))
                    self._historical_checkpoint(op,parent,deadline)
                    if os.path.lexists(source) and os.path.lexists(parent+'/completion.json'):
                        self._finalize_completion(op,deadline)
                    self._archive_ordinary(op,deadline)
                    continue
                path=parent+'/completion.json'
                if os.path.lexists(path):
                    self._complete(op,deadline)
                    self._finalize_completion(op,deadline)
                else:
                    checkpoint=parent+'/checkpoint.json'
                    if os.path.lexists(checkpoint):
                        prepared=read_json(checkpoint);self._receipt(prepared,op)
                        receipt=self.adapters['checkpoint'](self.agent_dir,op['operation_id'],op['event_key'],'TASK checkpoint',prepared,deadline=deadline)
                        self._receipt(receipt,op);require(receipt['commit_sha'] is not None)
                        if not _equal(prepared,receipt):durable_json(checkpoint,receipt,deadline=deadline,clock=self.clock)
                    else:self._checkpoint_twice(op,op['event_key'],'TASK checkpoint',deadline)
                self.store.finish(op['operation_id'],terminal,deadline=deadline)
                self._archive_ordinary(op,deadline)
                recovered=True
            return dict(outcome='recovered' if recovered else 'idle',operations=list(snapshot['operations']),reason=None)
        except Exception:
            return dict(outcome='blocked',operations=[],reason='native_evidence_unconfirmed')


def task_engine(agent_dir):
    result=subprocess.run(['yq','-o=json','-I=0','.engine',os.path.join(agent_dir,'spec.yaml')],capture_output=True,timeout=10)
    require(result.returncode==0 and len(result.stdout)<=4096)
    value=json.loads(result.stdout)
    require(value is None or type(value) is str and value in ('claude','codex'))
    engine=value or 'claude'
    control_path=agent_dir+'/control.json'
    if os.path.lexists(control_path):
        control=read_json(control_path)
        require('codex_state_id' not in control or engine=='codex')
    return engine


def ensure_native_python():
    target=os.path.abspath(os.environ.get('CODEX_RC_PYTHON',os.path.expanduser('~/.local/share/claude-control/codex-venv/bin/python')))
    require(os.path.isfile(target) and os.access(target,os.X_OK))
    if target!=os.path.abspath(os.sys.executable):
        os.execv(target,[target]+os.sys.argv)
    import websockets
    require(websockets.__version__=='15.0.1')


def runtime_for(agent_dir):
    executable=shutil.which('codex')
    require(executable is not None)
    executable=os.path.realpath(executable)
    if executable.endswith('/bin/codex.js'):
        package=os.path.dirname(os.path.dirname(executable))
        candidate=package+'/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex'
        require(os.path.isfile(candidate)); executable=candidate
    vendor=os.path.dirname(os.path.dirname(executable))
    companions=dict(code_mode_host=vendor+'/bin/codex-code-mode-host',bwrap=vendor+'/codex-resources/bwrap',rg=vendor+'/codex-path/rg')
    spec_result=subprocess.run(['yq','-o=json','-I=0','.',agent_dir+'/spec.yaml'],capture_output=True,timeout=10)
    require(spec_result.returncode==0)
    spec=json.loads(spec_result.stdout)
    return CodexTaskRuntime(agent_dir,state_root=os.path.dirname(os.path.dirname(agent_dir))+'/codex-task-state',executable=executable,
        companion_paths=companions,host_budget=spec.get('host_budget',dict(memory_max_mb=1024,tasks_max=64,cpu_quota_percent=100)))


def native_barrier(agent_dir,reason='shutdown'):
    if task_engine(agent_dir)!='codex': return True
    controller=runtime_for(agent_dir)
    controller.revoke_and_drain(reason,deadline=time.monotonic()+30)
    return controller.require_drained(deadline=time.monotonic()+30)


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('preflight','reconcile','barrier','execute'):
        child=sub.add_parser(name); child.add_argument('agent')
        if name=='barrier':child.add_argument('--reason',required=True,choices=('cancel','pause','recovery','ask','done','terminal','timeout','policy','shutdown'))
        if name=='execute':
            child.add_argument('--event',required=True);child.add_argument('--generation',required=True,type=int);child.add_argument('--attempt',required=True)
    raw=list(os.sys.argv[1:] if argv is None else argv)
    require(all(raw.count(flag)<=1 for flag in ('--reason','--event','--generation','--attempt')))
    args=parser.parse_args(raw)
    try:
        ensure_native_python()
        controller=runtime_for(args.agent); deadline=time.monotonic()+30
        if args.command=='preflight':result=controller.static_preflight(deadline=deadline)
        elif args.command=='reconcile':
            path=args.agent+'/inbox/.executor.lock';file_info(path)
            fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=controller.reconcile(deadline=deadline)
            finally:os.close(fd)
        elif args.command=='barrier':result=controller.revoke_and_drain(args.reason,deadline=deadline)
        else:
            spec=controller._spec(deadline); timeout=spec.get('limits',{}).get('run_timeout_s',300)
            require(type(timeout) in (int,float) and not isinstance(timeout,bool) and math.isfinite(timeout) and 1<=timeout<=86400)
            path=args.agent+'/inbox/.executor.lock';file_info(path)
            fd=os.open(path,os.O_RDWR|os.O_NOFOLLOW)
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=controller.execute(args.event,args.generation,args.attempt,deadline=time.monotonic()+timeout)
            finally:os.close(fd)
        print(json.dumps(result,ensure_ascii=False))
        return 2 if result.get('outcome') in ('blocked','unknown') else 0
    except Exception:
        print(json.dumps(dict(outcome='blocked',reason='native_dependencies_or_evidence_unconfirmed')))
        return 2
