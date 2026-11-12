"""Audit the full PPC result, exact review packets, and the worker delivery boundary."""
import argparse
import hashlib
import json
from pathlib import Path

import check_harness2_ppc_20261106 as previous

from integrations import harness2 as bridge
from integrations.harness2_reader import Store


def check(output):
    audit = previous.audit(output)
    root = output / 'experiment'
    job = bridge.read(root / 'public-selection/job.json')
    assert set(job) == {'kind', 'rollouts', 'official_label', 'public_hash', 'source_hash', 'config'}
    assert bridge.read(root / 'public-selection/result.json') == audit['delivery']
    assert audit['delivery']['model_calls'] == 0 and not audit['delivery']['independent_grading_used']
    checked = []
    for folder in sorted((root / 'editors').glob('call-*')):
        job = bridge.read(folder / 'job.json')
        store = Store(Path(job['evidence_manifest']), job['evidence_manifest_sha256'])
        assert store.manifest['schema'] == 'public-editor-evidence-v2'
        packet = store.index['review_packet']
        contents = {}
        for row in packet['short_files']:
            if 'content' in row:
                content = row['content']
            elif 'content_alias_of' in row:
                content = contents[row['content_alias_of']]
            else:
                assert row['read_required'] and row['characters'] > 4000
                continue
            raw = (store.path.parent / store.manifest['files'][row['id']]['storage']).read_bytes()
            assert content.encode('utf-8') == raw
            assert hashlib.sha256(raw).hexdigest() == row['sha256']
            contents[row['id']] = content
        for step in sorted((folder / 'steps').glob('*')):
            request = bridge.read(step / 'messages.json')
            payload = json.loads(request[1]['content'])
            assert payload['evidence_index']['review_packet'] == packet
            state = payload['decision_state']
            assert state['remaining_model_requests'] == 21 - int(step.name)
            assert (state['phase'] == 'finalize') == (state['remaining_model_requests'] <= 2)
        checked.append({'editor': job['label'], 'exact_short_files': len(contents),
                        'public_candidates': len(packet['candidates']), 'decision_state_verified': True})
    audit['review_packet_checks'] = checked
    audit['public_selection_worker_verified'] = True
    bridge.write(output / 'audit.json', audit)
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--receipts', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    audit = check(output)
    if args.receipts:
        previous.receipts(output)
    print(json.dumps({key: audit[key] for key in ('complete_fresh_ppc', 'independent_resolved',
                                                'public_selection_worker_verified')}))
