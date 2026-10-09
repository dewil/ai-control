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


MANIFEST_SHA256 = None


def run_packet(manifest_snapshot, bootstrap_snapshot):
    try:
        if (len(sys.argv) != 1 or sys.argv[0] != '-' or
                any(call() != 0 for call in (os.getuid, os.geteuid, os.getgid, os.getegid)) or
                any(name.startswith(('PYTHON', 'LD_')) for name in os.environ)):
            raise ValueError('Isolated root execution required')
        pin(MANIFEST_SHA256)
        if type(manifest_snapshot) is not bytes or digest(manifest_snapshot) != MANIFEST_SHA256:
            raise ValueError('Manifest external pin mismatch')
        verified_packet(manifest_snapshot, bootstrap_snapshot)
        loaded_bootstrap = types.ModuleType('verified_live_bootstrap')
        loaded_bootstrap.__file__ = '<verified-live-bootstrap>'
        exec(compile(bootstrap_snapshot, loaded_bootstrap.__file__, 'exec'), loaded_bootstrap.__dict__)
        loaded_bootstrap.PACKET_SHA256 = digest(manifest_snapshot)
        loaded_bootstrap.PACKET_MANIFEST_SNAPSHOT = manifest_snapshot
        loaded_bootstrap.bootstrap()
        return 0
    except Exception:
        return 1
