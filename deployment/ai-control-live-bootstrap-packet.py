#!/usr/bin/python3
"""Immutable fixed-path packet transport; unbound production values fail closed."""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import types

MAX_FILE = 2 * 1024 * 1024
MAX_MANIFEST = 64 * 1024
MAX_EXECUTABLE = 32 * 1024 * 1024
WHEEL_SHA256 = '132a8e4b646ad058c7b242b7161621832ee8737ca6f6cbd47dcb6d3ad09490ed'
WHEEL_SIZE = 82408
WHEEL_INVENTORY_SHA256 = '40b35159d50cf2bf0f645f5ab1564f5a3fd0efcee266405fffeb6a496dc7bb43'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')

def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Invalid JSON number')))
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid JSON') from exc

def keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError('Unexpected schema keys')

def pin(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('Reviewed pin missing')
    return value

def strict_blob(value, maximum):
    if type(value) is not str or len(value) > 4 * ((maximum + 2) // 3):
        raise ValueError('Invalid embedded blob')
    try:
        data = base64.b64decode(value.encode('ascii'), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise ValueError('Invalid embedded blob') from exc
    if not data or len(data) > maximum or base64.b64encode(data).decode('ascii') != value:
        raise ValueError('Noncanonical embedded blob')
    return data

def manifest_value(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_MANIFEST:
        raise ValueError('Invalid manifest snapshot')
    value = decode(raw)
    keys(value, ('schema', 'bootstrap', 'helper', 'wheel', 'unit_before', 'unit_after'))
    if type(value['schema']) is not int or value['schema'] != 1 or encode(value) != raw:
        raise ValueError('Noncanonical manifest')
    for name, maximum in (('bootstrap', 4194304), ('helper', 1048576), ('wheel', 82408),
                          ('unit_before', 65536), ('unit_after', 65536)):
        keys(value[name], ('sha256', 'size'))
        pin(value[name]['sha256'])
        if type(value[name]['size']) is not int or not 0 < value[name]['size'] <= maximum:
            raise ValueError('Invalid manifest size')
    if value['wheel'] != {'sha256': WHEEL_SHA256, 'size': WHEEL_SIZE}:
        raise ValueError('Manifest wheel mismatch')
    return value

SYSTEM_PYTHON = '/usr/bin/python3'
VENV_PYTHON = '/opt/ai-control-web/venv/bin/python'
OWNER_IMPORT_LAUNCHER = '/usr/bin/setpriv'
SYSTEMCTL = '/usr/bin/systemctl'
CONTROL_DEVBUS_CONFIG = '/home/dwl/.config/ai-control/devbus-observer.json'
CONFIG_LINE = b'Environment=CONTROL_DEVBUS_CONFIG=/home/dwl/.config/ai-control/devbus-observer.json\n'
LEGACY_MODES = {'bin/ai-control-web': 493, 'bin/_control_web.py': 420, 'bin/_control_web_broker.py': 420, 'bin/_control_web_sessions.py': 420, 'bin/_codex_rc.py': 420, 'bin/_rc_projects.sh': 493, 'bin/_control_web.html': 420, 'bin/_control_web.css': 420, 'bin/_control_web.js': 420, 'requirements-web.lock': 420, 'systemd/ai-control-web.service.tmpl': 420, 'systemd/ai-control-web-broker.service.tmpl': 420, 'bin/_control_web.svg': 420}
NEW_LEAF = 'bin/_control_web_configured_create.py'
CURRENT_MODES = {**LEGACY_MODES, NEW_LEAF: 0o644}
APP_LEAVES = ('bin/_control_web_android_auth.py', 'bin/_control_web_android_download.py')
APP_MODES = {**CURRENT_MODES, **dict.fromkeys(APP_LEAVES, 0o644)}

def canonical_inventory(rows):
    if type(rows) not in (list, tuple):
        raise ValueError('Invalid inventory')
    seen = set()
    for row in rows:
        if type(row) is not dict or set(row) != {'path', 'sha256', 'size', 'archive_mode', 'install_mode'}:
            raise ValueError('Invalid inventory row')
        path = row['path']
        if (type(path) is not str or not path or path.startswith('/') or
                any(part in ('', '.', '..') for part in path.split('/')) or
                any(c in path for c in '\\:\x00') or len(path.split('/')) > 8 or path in seen):
            raise ValueError('Invalid inventory path')
        seen.add(path)
        if type(row['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None:
            raise ValueError('Invalid inventory digest')
        if type(row['size']) is not int or not 0 <= row['size'] <= MAX_FILE:
            raise ValueError('Invalid inventory size')
        for field in ('archive_mode', 'install_mode'):
            if type(row[field]) is not int or not 0 <= row[field] <= 0o7777:
                raise ValueError('Invalid inventory mode')
    return json.dumps(sorted(rows, key=lambda row: row['path']), sort_keys=True,
                      separators=(',', ':'), ensure_ascii=True).encode('utf-8')

def identity_row(row, *, extra=()):
    keys(row, ('dev', 'ino', 'uid', 'gid', 'mode', *extra))
    for name in ('dev', 'ino', 'uid', 'gid', 'mode'):
        if type(row[name]) is not int:
            raise ValueError('Invalid stat pin')
    if row['dev'] < 0 or row['ino'] <= 0 or row['uid'] != 0 or row['gid'] != 0 or not 0 <= row['mode'] <= 0o7777:
        raise ValueError('Unsafe stat pin')

def runtime_shape(value):
    names = ('LOCK', 'SITE_PACKAGES', 'VENV_ROOT', 'BROKER_UNIT_MODE', 'SYSTEM_PYTHON',
             'VENV_PYTHON', 'OWNER_IMPORT_LAUNCHER', 'SYSTEMCTL')
    keys(value, names)
    for name in ('LOCK', 'SITE_PACKAGES', 'VENV_ROOT'):
        identity_row(value[name])
        required = {'LOCK': 0o600, 'SITE_PACKAGES': 0o755}.get(name)
        if ((required is not None and value[name]['mode'] != required) or
                (name == 'VENV_ROOT' and value[name]['mode'] & 0o022)):
            raise ValueError('Unsafe directory pin')
    if type(value['BROKER_UNIT_MODE']) is not int or value['BROKER_UNIT_MODE'] not in (0o644, 0o600):
        raise ValueError('Invalid unit mode pin')
    for name in ('SYSTEM_PYTHON', 'VENV_PYTHON', 'OWNER_IMPORT_LAUNCHER', 'SYSTEMCTL'):
        row = value[name]
        keys(row, ('links', 'resolved'))
        if type(row['links']) is not list or len(row['links']) > 8:
            raise ValueError('Invalid executable chain')
        current, seen = globals()[name], set()
        for link in row['links']:
            identity_row(link, extra=('path', 'target'))
            if (link['path'] != current or current in seen or type(link['target']) is not str or
                    not link['target'] or '\x00' in link['target']):
                raise ValueError('Invalid executable link')
            seen.add(current)
            current = os.path.normpath(os.path.join(os.path.dirname(current), link['target']))
            if not current.startswith('/'):
                raise ValueError('Invalid executable path')
        resolved = row['resolved']
        identity_row(resolved, extra=('path', 'size', 'sha256'))
        if (resolved['path'] != current or current in seen or resolved['mode'] & 0o022 or
                not resolved['mode'] & 0o111 or type(resolved['size']) is not int or
                not 0 < resolved['size'] <= MAX_EXECUTABLE):
            raise ValueError('Unsafe executable terminal')
        pin(resolved['sha256'])

def validate_unit(raw):
    """Closed renderer shape; independent secret-free attestation remains external."""
    if type(raw) is not bytes or not 0 < len(raw) <= 65536:
        raise ValueError('Invalid unit size')
    text = raw.decode('utf-8')
    if any(c in text for c in ('\x00', '\r', '\\', '$', '%', '{{', '}}')):
        raise ValueError('Unsafe unit syntax')
    if re.search(r'(?:token|password|secret|credential)\s*[:=]|://[^/\s]+@', text, re.IGNORECASE):
        raise ValueError('Unsafe inline unit data')
    sections = {'Unit': {'Description', 'After'},
                'Service': {'Type', 'User', 'Group', 'Environment', 'ExecStart', 'RuntimeDirectory',
                            'RuntimeDirectoryMode', 'Restart', 'RestartSec', 'UMask', 'NoNewPrivileges',
                            'PrivateTmp', 'BindReadOnlyPaths', 'ProtectSystem', 'ProtectHome',
                            'ProtectKernelTunables', 'ProtectKernelModules', 'RestrictSUIDSGID',
                            'RestrictAddressFamilies', 'CapabilityBoundingSet', 'LockPersonality'},
                'Install': {'WantedBy'}}
    current, seen_sections, seen, envs = None, set(), {}, {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        if line.startswith('['):
            current = line[1:-1]
            if line != '[' + current + ']' or current not in sections or current in seen_sections:
                raise ValueError('Invalid unit section')
            seen_sections.add(current)
            continue
        if '=' not in line or current is None:
            raise ValueError('Invalid unit directive')
        name, value = line.split('=', 1)
        if name not in sections[current] or (name in seen and name != 'Environment'):
            raise ValueError('Unknown or duplicate unit directive')
        if name == 'Environment':
            if '=' not in value:
                raise ValueError('Invalid unit environment')
            key, argument = value.split('=', 1)
            fixed = {'HOME': '/home/dwl', 'XDG_RUNTIME_DIR': '/run/user/1000',
                     'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/1000/bus',
                     'CONTROL_DEVBUS_CONFIG': CONTROL_DEVBUS_CONFIG}
            if key in envs or key not in {*fixed, 'PATH'}:
                raise ValueError('Unsafe unit environment')
            if key == 'PATH':
                if re.fullmatch('/home/dwl/[A-Za-z0-9_./-]+:/usr/local/bin:/usr/bin:/bin', argument) is None:
                    raise ValueError('Unsafe unit path')
            elif argument != fixed[key]:
                raise ValueError('Unit environment mismatch')
            envs[key] = argument
        else:
            seen[name] = value
    if seen_sections != set(sections) or not {'HOME', 'PATH', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS'} <= envs.keys():
        raise ValueError('Incomplete unit shape')
    fixed = {'User': 'dwl', 'Group': 'ai-panel', 'Type': 'simple', 'ProtectSystem': 'full',
             'NoNewPrivileges': 'yes', 'PrivateTmp': 'yes', 'RuntimeDirectory': 'ai-control-web',
             'RuntimeDirectoryMode': '0750', 'Restart': 'on-failure', 'RestartSec': '3', 'UMask': '0077',
             'ProtectKernelTunables': 'yes', 'ProtectKernelModules': 'yes', 'RestrictSUIDSGID': 'yes',
             'RestrictAddressFamilies': 'AF_UNIX AF_INET AF_INET6', 'CapabilityBoundingSet': '',
             'LockPersonality': 'yes', 'After': 'network.target', 'WantedBy': 'multi-user.target'}
    if any(seen.get(key) != value for key, value in fixed.items()):
        raise ValueError('Unit role mismatch')
    if 'ProtectHome' in seen and seen['ProtectHome'] != 'no':
        raise ValueError('Broker sandbox mismatch')
    if 'BindReadOnlyPaths' in seen and seen['BindReadOnlyPaths'] != '-/tmp/codex-daemon-1000':
        raise ValueError('Unknown broker binding')
    args = seen.get('ExecStart', '').split(' ')
    if (len(args) != 11 or args[:3] != [VENV_PYTHON, '/opt/ai-control-web/bin/ai-control-web', 'broker'] or
            args[3] != '--registry' or args[5] != '--bin-dir' or args[7:] !=
            ['--socket', '/run/ai-control-web/broker.sock', '--allowed-uid', '993']):
        raise ValueError('Unsafe broker command')
    if (re.fullmatch('/home/dwl/[A-Za-z0-9_./-]+', args[4]) is None or
            re.fullmatch('/home/dwl/[A-Za-z0-9_./-]+', args[6]) is None or
            envs['PATH'] != args[6] + ':/usr/local/bin:/usr/bin:/bin' or
            any('/../' in value or '/./' in value for value in (args[4], args[6]))):
        raise ValueError('Unknown renderer parameters')

def unit_pair(before, after):
    for raw in (before, after):
        validate_unit(raw)
    if (before.count(b'[Service]\n') != 1 or CONFIG_LINE in before or
            after != before.replace(b'[Service]\n', b'[Service]\n' + CONFIG_LINE, 1)):
        raise ValueError('Unit change outside fixed pointer')

def literal_assignments(raw, names):
    if type(raw) is not bytes:
        raise ValueError('Source snapshot required')
    try:
        tree = ast.parse(raw.decode('utf-8'))
    except (SyntaxError, UnicodeError, RecursionError) as exc:
        raise ValueError('Invalid source syntax') from exc
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            touched = {part.id for target in targets for part in ast.walk(target) if isinstance(part, ast.Name)} & set(names)
            if touched:
                if (node not in tree.body or not isinstance(node, ast.Assign) or len(node.targets) != 1 or
                        not isinstance(node.targets[0], ast.Name) or len(touched) != 1):
                    raise ValueError('Nonplain producer assignment')
                name = node.targets[0].id
                if name in found:
                    raise ValueError('Duplicate producer assignment')
                try:
                    ast.literal_eval(node.value)
                except (ValueError, TypeError) as exc:
                    raise ValueError('Nonliteral producer assignment') from exc
                found[name] = node.value
    if set(found) != set(names):
        raise ValueError('Missing producer assignment')
    return tree, found


def verified_packet(manifest_snapshot, bootstrap_snapshot):
    manifest = manifest_value(manifest_snapshot)
    if type(bootstrap_snapshot) is not bytes or not 0 < len(bootstrap_snapshot) <= 4194304:
        raise ValueError('Invalid bootstrap snapshot')
    if manifest['bootstrap'] != {'sha256': digest(bootstrap_snapshot), 'size': len(bootstrap_snapshot)}:
        raise ValueError('Bootstrap hash mismatch')
    names = ('NEW_HELPER_BLOB_B64', 'WHEEL_BLOB_B64', 'BEFORE_BROKER_UNIT_BLOB_B64', 'AFTER_BROKER_UNIT_BLOB_B64',
             'NEW_HELPER_SHA256', 'BEFORE_BROKER_UNIT_SHA256', 'AFTER_BROKER_UNIT_SHA256',
             'WHEEL_SHA256', 'WHEEL_SIZE', 'WHEEL_INVENTORY_SHA256', 'WHEEL_MEMBERS',
             'PACKET_SHA256', 'PACKET_MANIFEST_SNAPSHOT', 'OWNER_IMPORT_CODE')
    _, nodes = literal_assignments(bootstrap_snapshot, names)
    values = {name: ast.literal_eval(node) for name, node in nodes.items()}
    if (values['PACKET_SHA256'] is not None or values['PACKET_MANIFEST_SNAPSHOT'] is not None or
            values['WHEEL_SHA256'] != WHEEL_SHA256 or type(values['WHEEL_SIZE']) is not int or values['WHEEL_SIZE'] != WHEEL_SIZE or
            values['WHEEL_INVENTORY_SHA256'] != WHEEL_INVENTORY_SHA256 or type(values['WHEEL_MEMBERS']) is not tuple or
            len(values['WHEEL_MEMBERS']) != 29 or digest(canonical_inventory(values['WHEEL_MEMBERS'])) != WHEEL_INVENTORY_SHA256 or
            type(values['OWNER_IMPORT_CODE']) is not str or digest(values['OWNER_IMPORT_CODE'].encode()) !=
            '70b31a6b98b049a0a3a6eba2af77f0732a2fcd856d232c5f86928b9b642a2189'):
        raise ValueError('Source-final bootstrap pin drift')
    decoded = {}
    for name, blob, hashname, maximum in (
            ('helper', 'NEW_HELPER_BLOB_B64', 'NEW_HELPER_SHA256', 1048576),
            ('wheel', 'WHEEL_BLOB_B64', 'WHEEL_SHA256', 82408),
            ('unit_before', 'BEFORE_BROKER_UNIT_BLOB_B64', 'BEFORE_BROKER_UNIT_SHA256', 65536),
            ('unit_after', 'AFTER_BROKER_UNIT_BLOB_B64', 'AFTER_BROKER_UNIT_SHA256', 65536)):
        raw = strict_blob(values[blob], maximum)
        if digest(raw) != pin(values[hashname]) or manifest[name] != {'sha256': digest(raw), 'size': len(raw)}:
            raise ValueError('Embedded artifact crossbinding mismatch')
        decoded[name] = raw
    if len(decoded['wheel']) != WHEEL_SIZE:
        raise ValueError('Wheel size mismatch')
    return manifest, decoded


BOOT_BINDINGS = ('EXPECTED_ACCEPTED_SHA256', 'EXPECTED_BEFORE_FILES', 'NEW_HELPER_SHA256', 'NEW_HELPER_BLOB_B64',
                 'BEFORE_BROKER_UNIT_SHA256', 'AFTER_BROKER_UNIT_SHA256', 'BEFORE_BROKER_UNIT_BLOB_B64',
                 'AFTER_BROKER_UNIT_BLOB_B64', 'EXPECTED_RUNTIME_STAT_PINS', 'WHEEL_BLOB_B64')
STAGE_BINDINGS = tuple(prefix + suffix for prefix in ('WRAPPER', 'MANIFEST', 'BOOTSTRAP')
                       for suffix in ('_B64', '_SHA256', '_SIZE'))


def spans(raw, nodes):
    offsets = [0]
    for line in raw.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return {name: (offsets[node.lineno - 1] + node.col_offset,
                   offsets[node.end_lineno - 1] + node.end_col_offset) for name, node in nodes.items()}


def masked(raw, nodes):
    for start, end in sorted(spans(raw, nodes).values(), reverse=True):
        raw = raw[:start] + b'<literal>' + raw[end:]
    return raw


def fill_literals(template, values):
    tree, nodes = literal_assignments(template, values)
    if any(ast.literal_eval(node) is not None for node in nodes.values()):
        raise ValueError('Template bindings must start unbound')
    filled = template
    for name, (start, end) in sorted(spans(template, nodes).items(), key=lambda pair: pair[1][0], reverse=True):
        replacement = repr(values[name]).encode('utf-8')
        if ast.literal_eval(replacement.decode('utf-8')) != values[name]:
            raise ValueError('Nonliteral binding value')
        filled = filled[:start] + replacement + filled[end:]
    after_tree, after_nodes = literal_assignments(filled, values)
    if masked(template, nodes) != masked(filled, after_nodes):
        raise ValueError('Code bytes changed outside binding spans')
    for before_node, after_node in zip((nodes[name] for name in values), (after_nodes[name] for name in values)):
        # Rewrite just the allowed value nodes for structural comparison.
        before_node.__class__ = ast.Constant
        before_node.value = None
        after_node.__class__ = ast.Constant
        after_node.value = None
    if ast.dump(tree, include_attributes=False) != ast.dump(after_tree, include_attributes=False):
        raise ValueError('Executable AST changed')
    return filled


def inventory_literals(raw):
    names = ('WHEEL_SHA256', 'WHEEL_SIZE', 'WHEEL_INVENTORY_SHA256', 'WHEEL_MEMBERS')
    _, nodes = literal_assignments(raw, names)
    values = {name: ast.literal_eval(node) for name, node in nodes.items()}
    if (values['WHEEL_SHA256'] != WHEEL_SHA256 or type(values['WHEEL_SIZE']) is not int or values['WHEEL_SIZE'] != WHEEL_SIZE or
            values['WHEEL_INVENTORY_SHA256'] != WHEEL_INVENTORY_SHA256 or type(values['WHEEL_MEMBERS']) is not tuple or
            len(values['WHEEL_MEMBERS']) != 29 or digest(canonical_inventory(values['WHEEL_MEMBERS'])) != WHEEL_INVENTORY_SHA256):
        raise ValueError('Compiled inventory mismatch')
    return values


def build_packet(inputs, bindings):
    keys(inputs, ('bootstrap_template', 'wrapper_template', 'helper', 'wheel', 'unit_before', 'unit_after'))
    nonblob = ('EXPECTED_ACCEPTED_SHA256', 'EXPECTED_BEFORE_FILES', 'NEW_HELPER_SHA256',
               'BEFORE_BROKER_UNIT_SHA256', 'AFTER_BROKER_UNIT_SHA256', 'EXPECTED_RUNTIME_STAT_PINS')
    keys(bindings, nonblob)
    caps = {'bootstrap_template': 4194304, 'wrapper_template': 2097152, 'helper': 1048576,
            'wheel': 82408, 'unit_before': 65536, 'unit_after': 65536}
    for name, raw in inputs.items():
        if type(raw) is not bytes or not 0 < len(raw) <= caps[name]:
            raise ValueError('Invalid packet input')
    for name in ('EXPECTED_ACCEPTED_SHA256', 'NEW_HELPER_SHA256', 'BEFORE_BROKER_UNIT_SHA256', 'AFTER_BROKER_UNIT_SHA256'):
        pin(bindings[name])
    keys(bindings['EXPECTED_BEFORE_FILES'], APP_MODES)
    for value in bindings['EXPECTED_BEFORE_FILES'].values():
        pin(value)
    runtime_shape(bindings['EXPECTED_RUNTIME_STAT_PINS'])
    for name, binding in (('helper', 'NEW_HELPER_SHA256'), ('unit_before', 'BEFORE_BROKER_UNIT_SHA256'),
                          ('unit_after', 'AFTER_BROKER_UNIT_SHA256')):
        if digest(inputs[name]) != bindings[binding]:
            raise ValueError('Artifact pin mismatch')
    if digest(inputs['wheel']) != WHEEL_SHA256 or len(inputs['wheel']) != WHEEL_SIZE:
        raise ValueError('Wheel pin mismatch')
    unit_pair(inputs['unit_before'], inputs['unit_after'])
    if inventory_literals(inputs['helper']) != inventory_literals(inputs['bootstrap_template']):
        raise ValueError('Helper and bootstrap inventory differ')
    _, immutable = literal_assignments(inputs['bootstrap_template'], ('PACKET_SHA256', 'PACKET_MANIFEST_SNAPSHOT', 'OWNER_IMPORT_CODE'))
    if (ast.literal_eval(immutable['PACKET_SHA256']) is not None or ast.literal_eval(immutable['PACKET_MANIFEST_SNAPSHOT']) is not None or
            digest(ast.literal_eval(immutable['OWNER_IMPORT_CODE']).encode()) != '70b31a6b98b049a0a3a6eba2af77f0732a2fcd856d232c5f86928b9b642a2189'):
        raise ValueError('Immutable bootstrap literal changed')
    values = dict(bindings)
    for name, input_name in (('NEW_HELPER_BLOB_B64', 'helper'), ('WHEEL_BLOB_B64', 'wheel'),
                             ('BEFORE_BROKER_UNIT_BLOB_B64', 'unit_before'), ('AFTER_BROKER_UNIT_BLOB_B64', 'unit_after')):
        values[name] = base64.b64encode(inputs[input_name]).decode('ascii')
    bootstrap = fill_literals(inputs['bootstrap_template'], values)
    if len(bootstrap) > 4194304:
        raise ValueError('Filled bootstrap oversized')
    artifacts = {'bootstrap': bootstrap, 'helper': inputs['helper'], 'wheel': inputs['wheel'],
                 'unit_before': inputs['unit_before'], 'unit_after': inputs['unit_after']}
    manifest = encode({'schema': 1, **{name: {'sha256': digest(raw), 'size': len(raw)} for name, raw in artifacts.items()}})
    verified_packet(manifest, bootstrap)
    wrapper = fill_literals(inputs['wrapper_template'], {'MANIFEST_SHA256': digest(manifest)})
    if len(wrapper) > 2097152:
        raise ValueError('Filled wrapper oversized')
    proof = encode({'schema': 1, 'bootstrap_template_sha256': digest(inputs['bootstrap_template']),
                    'bootstrap_sha256': digest(bootstrap), 'wrapper_template_sha256': digest(inputs['wrapper_template']),
                    'wrapper_sha256': digest(wrapper), 'bootstrap_bindings': sorted(BOOT_BINDINGS),
                    'wrapper_bindings': ['MANIFEST_SHA256']})
    return {'bootstrap.py': bootstrap, 'wrapper.py': wrapper, 'manifest.json': manifest, 'bindings-proof.json': proof}


def fill_stage(stage_template, packet):
    keys(packet, ('bootstrap.py', 'wrapper.py', 'manifest.json', 'bindings-proof.json'))
    if type(stage_template) is not bytes or not 0 < len(stage_template) <= 10485760:
        raise ValueError('Invalid stage template')
    if any(type(raw) is not bytes for raw in packet.values()):
        raise ValueError('Invalid packet snapshots')
    verified_packet(packet['manifest.json'], packet['bootstrap.py'])
    _, nodes = literal_assignments(packet['wrapper.py'], ('MANIFEST_SHA256',))
    if ast.literal_eval(nodes['MANIFEST_SHA256']) != digest(packet['manifest.json']):
        raise ValueError('Wrapper manifest crossbinding mismatch')
    proof = decode(packet['bindings-proof.json'])
    if (type(proof) is not dict or type(proof.get('schema')) is not int or proof.get('schema') != 1 or
            proof.get('bootstrap_sha256') != digest(packet['bootstrap.py']) or proof.get('wrapper_sha256') != digest(packet['wrapper.py'])):
        raise ValueError('Packet binding proof drift')
    values = {}
    for prefix, name, maximum in (('WRAPPER', 'wrapper.py', 2097152), ('MANIFEST', 'manifest.json', 65536),
                                  ('BOOTSTRAP', 'bootstrap.py', 4194304)):
        raw = packet[name]
        if not 0 < len(raw) <= maximum:
            raise ValueError('Stage artifact oversized')
        values[prefix + '_B64'] = base64.b64encode(raw).decode('ascii')
        values[prefix + '_SHA256'] = digest(raw)
        values[prefix + '_SIZE'] = len(raw)
    if sum(len(packet[name]) for name in ('wrapper.py', 'manifest.json', 'bootstrap.py')) > 6356992:
        raise ValueError('Stage aggregate oversized')
    filled = fill_literals(stage_template, values)
    if len(filled) > 10485760:
        raise ValueError('Filled stage source oversized')
    return filled
