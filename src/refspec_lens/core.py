"""Offline explanation of a deliberately explicit subset of fetch refspecs."""

import re
from dataclasses import dataclass


class InputError(ValueError):
    pass


def valid_ref(value: str, pattern: bool = False) -> bool:
    if pattern and value.count('*') == 1:
        value = value.replace('*', 'WILDCARD')
    if not value.startswith('refs/') or value.endswith(('/', '.')):
        return False
    if any(ord(c) < 33 or ord(c) == 127 or c in '~^:?*[\\' for c in value):
        return False
    if '..' in value or '@{' in value or '//' in value:
        return False
    return all(part and not part.startswith('.') and not part.endswith('.lock')
               for part in value.split('/'))


def snapshot(text: str, max_refs: int = 100_000) -> dict[str, str]:
    refs = {}
    widths = set()
    for number, line in enumerate(text.removeprefix('\ufeff').split('\n'), 1):
        line = line.removesuffix('\r')
        if not line:
            continue
        fields = re.fullmatch(r'([0-9a-fA-F]+)[ \t]+(.*)', line)
        if fields is None:
            raise InputError(f'Line {number}: expected OBJECT_ID REF')
        oid, name = fields.groups()
        if not re.fullmatch(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})', oid):
            raise InputError(f'Line {number}: expected a full SHA-1 or SHA-256 object ID')
        if set(oid) == {'0'} or not valid_ref(name):
            raise InputError(f'Line {number}: invalid full ref or zero object ID; use --refs')
        if name in refs:
            raise InputError(f'Line {number}: duplicate ref')
        refs[name] = oid.lower()
        widths.add(len(oid))
        if len(refs) > max_refs:
            raise InputError('Snapshot exceeds the ref limit')
    if len(widths) > 1:
        raise InputError('A snapshot cannot mix SHA-1 and SHA-256 IDs')
    return refs


def match(pattern: str, ref: str) -> str | None:
    if '*' not in pattern:
        return '' if pattern == ref else None
    before, after = pattern.split('*')
    if ref.startswith(before) and ref.endswith(after) and len(ref) >= len(before) + len(after):
        return ref[len(before):len(ref) - len(after) if after else None]
    return None


@dataclass(frozen=True)
class Rule:
    number: int
    original: str
    source: str
    destination: str | None
    negative: bool
    force: bool

    @classmethod
    def parse(cls, text: str, number: int):
        negative = text.startswith('^')
        force = text.startswith('+')
        body = text[1:] if negative or force else text
        if negative:
            source, destination = body, None
            if ':' in body:
                raise InputError(f'Rule {number}: negative rules have no destination')
        else:
            if body.count(':') != 1:
                raise InputError(f'Rule {number}: require full SOURCE:DESTINATION')
            source, destination = body.split(':')
            if source.count('*') != destination.count('*') or not valid_ref(destination, True):
                raise InputError(f'Rule {number}: destination must have the matching wildcard')
        if source.count('*') > 1 or not valid_ref(source, True):
            raise InputError(f'Rule {number}: invalid fully qualified source pattern')
        return cls(number, text, source, destination, negative, force)


def explain(remote: dict[str, str], local: dict[str, str], refspecs: list[str]) -> dict:
    if not 1 <= len(refspecs) <= 128:
        raise InputError('Supply between 1 and 128 refspecs')
    widths = {len(oid) for oid in [*remote.values(), *local.values()]}
    if len(widths) > 1:
        raise InputError('Remote and local snapshots must use the same object format')
    rules = [Rule.parse(text, i) for i, text in enumerate(refspecs, 1)]
    positives = [r for r in rules if not r.negative]
    negatives = [r for r in rules if r.negative]
    if not positives:
        raise InputError('At least one positive refspec is required')

    def excluded(ref):
        return [r.number for r in negatives if match(r.source, ref) is not None]

    sources = []
    mappings = {}
    expansions = 0
    for source, oid in sorted(remote.items()):
        matched = [(r, match(r.source, source)) for r in positives]
        matched = [(r, capture) for r, capture in matched if capture is not None]
        expansions += len(matched)
        if expansions > 200_000:
            raise InputError('Rule expansion limit exceeded (200000)')
        excluded_by = excluded(source)
        destinations = []
        if matched and not excluded_by:
            for rule, capture in matched:
                destination = rule.destination.replace('*', capture)
                if not valid_ref(destination):
                    raise InputError(f'Rule {rule.number} generates an invalid destination')
                key = source, destination
                if key not in mappings:
                    mappings[key] = {'source': source, 'destination': destination, 'oid': oid,
                                     'rules': [], 'force_rules': [],
                                     'local_oid': local.get(destination),
                                     'state': ('new' if destination not in local else
                                               'same' if local[destination] == oid else 'different')}
                mappings[key]['rules'].append(rule.number)
                if rule.force:
                    mappings[key]['force_rules'].append(rule.number)
                destinations.append(destination)
        sources.append({'source': source, 'oid': oid,
                        'matched_rules': [r.number for r, _ in matched],
                        'excluded_by': excluded_by,
                        'state': 'unmatched' if not matched else 'excluded' if excluded_by else 'mapped',
                        'destinations': sorted(set(destinations))})
    by_destination = {}
    for item in mappings.values():
        by_destination.setdefault(item['destination'], []).append(item['source'])
    conflicts = []
    for destination, refs in sorted(by_destination.items()):
        if len(refs) > 1:
            conflicts.append({'kind': 'multiple-sources', 'destination': destination,
                              'sources': sorted(refs)})
        components = destination.split('/')
        for i in range(1, len(components)):
            prefix = '/'.join(components[:i])
            if prefix in by_destination:
                conflicts.append({'kind': 'file-directory', 'destinations': [prefix, destination]})
    local_scope = []
    for ref, oid in sorted(local.items()):
        implied = set()
        for rule in positives:
            capture = match(rule.destination, ref)
            if capture is not None:
                expansions += 1
                if expansions > 200_000:
                    raise InputError('Rule expansion limit exceeded (200000)')
                implied.add(rule.source.replace('*', capture))
        eligible = sorted(source for source in implied if not excluded(source))
        if not implied:
            state = 'outside-scope'
        elif not eligible:
            state = 'excluded'
        elif any(source in remote for source in eligible):
            state = 'advertised'
        else:
            state = 'unadvertised'
        local_scope.append({'ref': ref, 'oid': oid, 'state': state,
                            'possible_sources': sorted(implied), 'eligible_sources': eligible})
    candidates = [item['ref'] for item in local_scope if item['state'] == 'unadvertised']
    missing_exact = [r.number for r in positives if '*' not in r.source
                     and r.source not in remote and not excluded(r.source)]
    return {'schema_version': 1, 'rules': refspecs, 'sources': sources,
            'mappings': list(mappings.values()), 'conflicts': conflicts,
            'local_scope': local_scope, 'prune_candidates': candidates,
            'missing_exact_rules': missing_exact,
            'counts': {'advertised': len(remote), 'local': len(local),
                       'mappings': len(mappings), 'conflicts': len(conflicts),
                       'prune_candidates': len(candidates)},
            'assumptions': ['Complete, contemporaneous snapshots',
                            'Explicit refspecs only; no automatic tags or symbolic refs',
                            'No ancestry, object-type or update-permission prediction']}
