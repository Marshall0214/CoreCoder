"""Standalone isolated runner for bounded, model-selected iterator probes; no arbitrary code."""
import collections
import collections.abc
import importlib
import itertools
import json
import sys
from pathlib import Path


def safe(value, marker):
    if value is marker:
        return {'type': 'internal_marker'}
    if type(value) in (int, bool, str, type(None)):
        return value
    if type(value) in (list, tuple):
        return [safe(v, marker) for v in value[:12]]
    return {'type': type(value).__name__}


def run(job):
    source = (Path(job['workspace']) / job['source_root']).resolve()
    for name in ('Mapping', 'MutableMapping', 'Sequence', 'MutableSequence', 'Set', 'MutableSet',
                 'Iterable', 'Iterator', 'Callable', 'Container', 'Hashable', 'ItemsView', 'KeysView', 'ValuesView'):
        if not hasattr(collections, name):
            setattr(collections, name, getattr(collections.abc, name))
    sys.path.insert(0, str(source))
    module = importlib.import_module('more_itertools.more')
    if not Path(module.__file__).resolve().is_relative_to(source):
        raise ValueError('Probe imports shadowed source')
    marker = module._marker
    original_windowed = module.windowed
    records = []
    for case in job['cases']:
        record = {'parameters': case, 'iterator_reads': [], 'windows': [], 'predicate_calls': [], 'truncated': False}

        def items(record=record, case=case):
            for item in case['items']:
                record['iterator_reads'].append(item)
                yield item

        def windows(*args, record=record, **kwargs):
            for window in original_windowed(*args, **kwargs):
                if len(record['windows']) < 24:
                    record['windows'].append(safe(window, marker))
                else:
                    record['truncated'] = True
                yield window

        def predicate(*args, record=record, case=case):
            if len(record['predicate_calls']) < 24:
                record['predicate_calls'].append(safe(args, marker))
            else:
                record['truncated'] = True
            return sum(args) == case.get('target', 7) if case.get('pred', 'sum_equals') == 'sum_equals' else all(args)

        module.windowed = windows
        try:
            method = case['method']
            if method == 'locate':
                iterator = module.locate(items(), predicate, window_size=case.get('window_size', 2))
            elif method == 'replace':
                iterator = module.replace(items(), predicate, case.get('substitutes', [9]),
                                          window_size=case.get('window_size', 2), count=case.get('count'))
            elif method == 'windowed':
                iterator = module.windowed(items(), case.get('n', 2),
                                           fillvalue=case.get('fillvalue'), step=case.get('step', 1))
            elif method == 'ichunked':
                iterator = module.ichunked(items(), case.get('n', 2))
            else:
                raise ValueError('Unknown probe method')
            output = []
            for value in itertools.islice(iterator, 13):
                output.append(list(itertools.islice(value, 13)) if method == 'ichunked' else value)
            record['truncated'] |= len(output) > 12
            record['result'] = safe(output[:12], marker)
        except Exception as exc:  # noqa: BLE001 - behavior exceptions are observations
            record.update(error_type=type(exc).__name__, error=str(exc)[:300])
        finally:
            module.windowed = original_windowed
        records.append(record)
    return {'status': 'observed', 'cases': records,
            'provenance': 'Model-selected bounded inputs on buggy source; no reference patch or grading tests'}


if __name__ == '__main__':
    job = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    Path(job['destination']).write_text(json.dumps(run(job)), encoding='utf-8')
