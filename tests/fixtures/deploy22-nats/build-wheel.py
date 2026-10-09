import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tarfile
import tomllib
import venv
import zipfile

assert os.getuid() == 1000 and os.geteuid() == 1000
assert not Path('/home/dwl').exists() and not Path('/data').exists()
assert list(Path(os.environ['HOME']).iterdir()) == []
assert os.environ['SOURCE_DATE_EPOCH'] == '1700000000'
assert socket.if_nameindex() == [(1, 'lo')]
os.umask(0o022)
inputs, work = Path('/inputs'), Path('/work')
env = work / 'venv'
venv.EnvBuilder(with_pip=False).create(env)
site = env / 'lib' / ('python' + '.'.join(map(str, sys.version_info[:2]))) / 'site-packages'
pins = {
    'pip-25.0.1-py3-none-any.whl': 'c46efd13b6aa8279f33f2864459c8ce587ea6a1a59ee20de055868d8f7688f7f',
    'setuptools-75.8.0-py3-none-any.whl': 'e3982f444617239225d675215d51f6ba05f845d4eec313da4418fdbb56fb27e3',
    'wheel-0.45.1-py3-none-any.whl': '708e7481cc80179af0e556bbf0cc00b8444c7321e2700b8d8580231d13017248',
}
for filename, expected in pins.items():
    path = inputs / filename
    assert hashlib.sha256(path.read_bytes()).hexdigest() == expected
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            member = Path(info.filename)
            assert not member.is_absolute() and '..' not in member.parts
        archive.extractall(site)
source_archive = inputs / 'nats_py-2.9.0.tar.gz'
assert hashlib.sha256(source_archive.read_bytes()).hexdigest() == '01886eb9e0a87f0ec630652cf1fae65d2a8556378a609bc6cc07d2ea60c8d0dd'
source_root = work / 'source'
source_root.mkdir()
with tarfile.open(source_archive, 'r:gz') as archive:
    archive.extractall(source_root, filter='data')
source = source_root / 'nats_py-2.9.0'
assert tomllib.loads((source / 'pyproject.toml').read_text())['build-system'] == {
    'requires': ['setuptools>=68.0'], 'build-backend': 'setuptools.build_meta'}
python = str(env / 'bin/python')
probe = subprocess.run([python, '-I', '-c', 'import importlib.metadata,json; print(json.dumps({x:importlib.metadata.version(x) for x in ["pip","setuptools","wheel"]}))'], check=True, capture_output=True, text=True)
builder_versions = json.loads(probe.stdout)
assert builder_versions == {'pip': '25.0.1', 'setuptools': '75.8.0', 'wheel': '0.45.1'}
output = work / 'wheelhouse'
output.mkdir()
command = [python, '-I', '-m', 'pip', '--isolated', 'wheel', '--no-index', '--no-deps', '--no-build-isolation', '--no-cache-dir', '--wheel-dir', str(output), str(source)]
build = subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
(work / 'build.stdout').write_text(build.stdout)
(work / 'build.stderr').write_text(build.stderr)
wheels = list(output.glob('*.whl'))
assert len(wheels) == 1 and wheels[0].name == 'nats_py-2.9.0-py3-none-any.whl'
wheel = wheels[0]
subprocess.run([python, '-I', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-cache-dir', str(wheel)], check=True, capture_output=True, text=True, timeout=30)
smoke_code = '''import importlib.metadata,inspect,json,socket
class NoNetworkSocket(socket.socket):
    def __new__(cls,*args,**kwargs):
        raise RuntimeError("network forbidden in import-only smoke")
socket.socket=NoNetworkSocket
import nats
from nats.aio.client import Client
from nats.js.client import JetStreamContext
from nats.js.api import ConsumerConfig,AckPolicy,DeliverPolicy,RetentionPolicy,StorageType
assert importlib.metadata.version("nats-py")=="2.9.0"
assert callable(nats.connect)
assert all(callable(getattr(JetStreamContext,name)) for name in ("stream_info","add_consumer","delete_consumer","pull_subscribe_bind"))
params=inspect.signature(Client.connect).parameters
assert all(name in params for name in ("servers","connect_timeout","max_reconnect_attempts","allow_reconnect","disconnected_cb","error_cb","token","user_credentials"))
cfg=ConsumerConfig(name="synthetic",ack_policy=AckPolicy.EXPLICIT,deliver_policy=DeliverPolicy.ALL,filter_subject="devbus.events.*",max_ack_pending=64,inactive_threshold=30)
assert cfg.filter_subject=="devbus.events.*"
assert RetentionPolicy.LIMITS and StorageType.FILE
print(json.dumps({"version":importlib.metadata.version("nats-py"),"observer_apis":True,"consumer_config":True,"network_calls":0}))
'''
smoke = subprocess.run([python, '-I', '-B', '-c', smoke_code], check=True, capture_output=True, text=True, timeout=10)
proof = {'uid': os.getuid(), 'python': platform.python_version(), 'python_detail': sys.version, 'source_date_epoch': 1700000000,
         'builder_versions': builder_versions, 'wheel': wheel.name, 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(), 'wheel_size': wheel.stat().st_size,
         'isolated_network_namespace': True, 'home_empty_at_start': True, 'user_home_absent': True, 'data_absent': True,
         'smoke': json.loads(smoke.stdout), 'runtime_owner_import_certified': False}
(work / 'build-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps(proof, indent=2))
