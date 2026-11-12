"""One experiment overview linking native traces; no duplicate generations or model calls."""
import argparse
import hashlib
import time
from pathlib import Path

import httpx
from langfuse import Langfuse

from integrations import harness2 as bridge
from repairflow.telemetry import configuration


def publish(output):
    audit = bridge.read(output / 'audit.json')
    receipt = bridge.read(output / 'langfuse-receipts.json')
    report = bridge.read(output / 'report.json')
    recovery = bridge.read(output / 'recovery/report.json') if (output / 'recovery/report.json').exists() else {}
    assert audit['checks_passed'] and receipt['all_confirmed']
    assert report['status'] == 'completed' or recovery.get('status') == 'completed'
    assert not (output / 'langfuse-overview.json').exists(), 'Do not duplicate publication'
    result = report['result']
    config = configuration()
    trace_id = hashlib.sha256(('indexed-ppc:' + str(output)).encode()).hexdigest()[:32]
    client = Langfuse(**config, timeout=10, flush_at=1, environment='harness2-indexed-ppc-acceptance')
    try:
        root = client.start_observation(name='harness2-indexed-ppc-acceptance', as_type='span',
            trace_context={'trace_id': trace_id}, input={'task_id': report['task_id'], 'model': 'qwen3.5:27b'},
            metadata={'experiment_id': output.name, 'post_termination_publication': True,
                      'generation_data': 'linked native traces only', 'model_calls_in_publication': 0})
        for phase in result['usage']['phases']:
            root.start_observation(name=phase['phase'], as_type='span', metadata={
                **phase, 'native_trace_url': client.get_trace_url(trace_id=phase['trace_id']) if phase['trace_id'] else None}).end()
        root.start_observation(name='independent-grading', as_type='span',
            metadata={'after_optimization_termination': True, 'returned_to_agent': False},
            output=report.get('grading', recovery.get('grading'))).end()
        root.update(output={
            'complete_fresh_ppc': audit['complete_fresh_ppc'], 'independent_resolved': audit['independent_resolved'],
            'rollouts': audit['rollouts'], 'editors': audit['editors'],
            'fresh_model_calls': result['usage']['fresh_model_calls'], 'actual_tokens': result['usage']['tokens'],
            'original_ppc_status': report['status'], 'recovered_delivery_only': bool(recovery),
            'not_repair_accuracy_experiment': True})
        root.end()
        client.flush()
        expected = len(result['usage']['phases']) + 2
        rows = []
        with httpx.Client(base_url=config['base_url'], auth=(config['public_key'], config['secret_key']),
                          trust_env=False, timeout=10) as reader:
            for _ in range(10):
                response = reader.get('/api/public/v2/observations', params={'traceId': trace_id, 'limit': 1000})
                response.raise_for_status()
                rows = response.json()['data']
                if len(rows) == expected and all(row.get('endTime') for row in rows):
                    break
                time.sleep(0.5)
        assert len(rows) == expected and all(row.get('endTime') for row in rows)
        assert not any(row['type'] == 'GENERATION' for row in rows)
        bridge.write(output / 'langfuse-overview.json', {
            'trace_id': trace_id, 'trace_url': client.get_trace_url(trace_id=trace_id),
            'observations_confirmed': expected, 'generations': 0, 'model_calls': 0,
            'native_usage_verified_separately': True})
    finally:
        client.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    publish(parser.parse_args().output.resolve())
