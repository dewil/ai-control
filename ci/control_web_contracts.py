#!/usr/bin/env python3
"""Partition the original web discovery by defining module, preserving cases."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import json
from pathlib import Path
import sys
import unittest


SHARD_COUNT = 4


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def inventory_hash(test_ids):
    serialized = json.dumps(sorted(test_ids), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def collect():
    # Match `python -m unittest` imports from the cwd repository.
    sys.path.insert(0, str(Path.cwd()))
    loader = unittest.TestLoader()
    # Import chatter belongs in diagnostics, never in the JSON inventory.
    with redirect_stdout(sys.stderr):
        original = list(cases(loader.discover("tests", pattern="test_control_web*.py")))
        original.extend(cases(loader.discover("tests", pattern="test_ai_control_names.py")))
    if loader.errors:
        raise RuntimeError("Test collection failed:\n" + "\n".join(loader.errors))
    return original


def partition(original):
    module_counts = Counter(case.__class__.__module__ for case in original)
    loads = [0] * SHARD_COUNT
    assignment = {}
    for module in sorted(module_counts, key=lambda name: (-module_counts[name], name)):
        index = min(range(SHARD_COUNT), key=lambda index: (loads[index], index))
        assignment[module] = index
        loads[index] += module_counts[module]
    selected = [[] for _ in range(SHARD_COUNT)]
    for case in original:
        selected[assignment[case.__class__.__module__]].append(case)

    original_ids = [case.id() for case in original]
    selected_ids = [[case.id() for case in shard] for shard in selected]
    if Counter(original_ids) != Counter(case_id for shard in selected_ids for case_id in shard):
        raise RuntimeError("Shard inventory does not preserve the original test multiset")
    module_sets = [{case.__class__.__module__ for case in shard} for shard in selected]
    if sum(map(len, module_sets)) != len(set().union(*module_sets)):
        raise RuntimeError("Defining modules overlap between shards")

    plan = {
        "total_test_count": len(original_ids),
        "inventory_hash": inventory_hash(original_ids),
        "shards": [
            {"index": index, "test_count": len(test_ids), "test_ids": test_ids,
             "modules": sorted(module_sets[index]), "inventory_hash": inventory_hash(test_ids)}
            for index, test_ids in enumerate(selected_ids)
        ],
    }
    return plan, selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="print the full JSON inventory")
    mode.add_argument("--shard", type=int, choices=range(SHARD_COUNT))
    mode.add_argument("--aggregate", metavar="STATUS")
    args = parser.parse_args()
    if args.aggregate is not None:
        if args.aggregate != "success":
            print(f"Required contract groups did not succeed: {args.aggregate!r}", file=sys.stderr)
            return 1
        return 0

    try:
        plan, selected = partition(collect())
    except (ImportError, RuntimeError) as error:
        print(error, file=sys.stderr)
        return 1
    if args.list:
        print(json.dumps(plan, ensure_ascii=False))
        return 0
    for shard in plan["shards"]:
        print(f"Shard {shard['index']}: {shard['test_count']} tests, "
              f"inventory SHA256 {shard['inventory_hash']}", file=sys.stderr)
    if not selected[args.shard]:
        print(f"Selected shard {args.shard} is empty", file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(selected[args.shard]))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
