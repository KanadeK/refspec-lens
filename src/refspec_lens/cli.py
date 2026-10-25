import argparse
import json
from pathlib import Path

from . import __version__
from .core import InputError, explain, snapshot


def read_snapshot(path: str, max_bytes: int, max_refs: int):
    with Path(path).open('rb') as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise InputError('Snapshot exceeds --max-bytes')
    return snapshot(raw.decode('utf-8-sig'), max_refs)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Explain fetch rules using offline ref snapshots.')
    parser.add_argument('--remote', required=True, help='UTF-8 git ls-remote --refs snapshot')
    parser.add_argument('--local', help='UTF-8 direct local refs snapshot; symbolic refs excluded')
    parser.add_argument('--refspec', action='append', required=True)
    parser.add_argument('--prune', action='store_true', help='Also fail on pruning exposure')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--max-bytes', type=int, default=16 * 1024 * 1024)
    parser.add_argument('--max-refs', type=int, default=100_000)
    parser.add_argument('--version', action='version', version=__version__)
    args = parser.parse_args(argv)
    try:
        if args.max_bytes < 1 or args.max_refs < 1:
            raise InputError('Limits must be positive')
        if args.prune and not args.local:
            raise InputError('--prune requires a complete --local snapshot')
        remote = read_snapshot(args.remote, args.max_bytes, args.max_refs)
        local = read_snapshot(args.local, args.max_bytes, args.max_refs) if args.local else {}
        report = explain(remote, local, args.refspec)
        report['local_snapshot_supplied'] = bool(args.local)
        code = int(bool(report['conflicts'] or report['missing_exact_rules'] or
                        (args.prune and report['prune_candidates'])))
    except (InputError, OSError, UnicodeError) as exc:
        report = {'schema_version': 1, 'error': str(exc)}
        code = 2
    if args.json:
        print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    elif 'error' in report:
        print('Error: ' + report['error'])
    else:
        for source in report['sources']:
            print(f"{source['state']}: {json.dumps(source['source'])} "
                  f"-> {json.dumps(source['destinations'])}")
        for conflict in report['conflicts']:
            print('Conflict: ' + json.dumps(conflict))
        for ref in report['prune_candidates']:
            print('Pruning exposure: ' + json.dumps(ref))
        if report['missing_exact_rules']:
            print('Missing exact sources for rules: ' + str(report['missing_exact_rules']))
        print('Offline mapping only. Check ancestry, symbolic refs and live state with Git.')
    return code
