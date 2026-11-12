"""Read back real feedback usage and publish a post-termination evidence summary."""
import argparse
import hashlib
import time
from pathlib import Path

import httpx

from deploy.langfuse.swebench_agent import inference_receipt
from integrations.harness2 import read, sha, write
from integrations.harness2_runtime import ROOT, workspace
from repairflow.telemetry import configuration


def public_summary(report, feedback):
    if report['status'] != 'completed' or feedback['independent_grading_used'] is not False:
        raise ValueError('Require a completed rollout with independent grading kept outside feedback')
    return {'fresh_model_calls': report['usage']['fresh_model_calls'],
            'actual_tokens': report['usage']['actual_tokens'],
            'feedback_rounds': feedback['feedback_rounds_attempted'],
            'public_accepted': feedback['accepted'], 'initial_candidate_reused': report['execution']['initial_candidate_reused']}


def publish(output):
    from langfuse import Langfuse

    report = read(output / 'report.json')
    protocol = read(output / 'protocol.json')
    if any(sha(ROOT / name) != value for name, value in protocol['source_files'].items()):
        raise ValueError('Execution implementation changed before publication')
    folder = Path(report['rollout'])
    feedback = read(folder / 'feedback/report.json')
    data = public_summary(report, feedback)
    settings = configuration()
    if settings is None:
        raise ValueError('Configure the existing local Langfuse')
    client = Langfuse(**settings, timeout=10, flush_at=1, environment='harness2-feedback-validation')
    trace_id = hashlib.sha256(('harness2-feedback:' + str(output)).encode()).hexdigest()[:32]
    try:
        with httpx.Client(base_url=settings['base_url'], auth=(settings['public_key'], settings['secret_key']),
                          trust_env=False, timeout=15) as reader:
            response = reader.get('/api/public/v2/observations', params={
                'traceId': feedback['observability']['trace_id'], 'limit': 1000, 'fields': 'basic,usage'})
            response.raise_for_status()
            observations = response.json()['data']
            receipt = inference_receipt(observations, {**feedback, 'inference_trace_id': feedback['observability']['trace_id']})
            if receipt is None:
                raise ValueError('Feedback generation usage not confirmed by the server')
            roots = [row for row in observations if row['name'] == 'issue-repair']
            generations = [row for row in observations if row['type'] == 'GENERATION']
            rounds = feedback['rounds']
            if len(roots) != 1 or len(generations) != len(rounds):
                raise ValueError('Unexpected inference/round mapping')
            measured = sorted((row['usageDetails']['input'], row['usageDetails']['output']) for row in generations)
            expected = sorted((row['usage']['prompt_tokens'], row['usage']['completion_tokens']) for row in rounds)
            if measured != expected:
                raise ValueError('Per-round Token usage differs from the server')
            root = client.start_observation(name='harness2-public-feedback-validation', as_type='span',
                trace_context={'trace_id': trace_id}, metadata={'experiment_id': output.name,
                    'task_id': 'toolz-join-unmatched', 'harness_variant': 'frozen-agg1', 'strategy_search': False,
                    'post_termination_publication': True, 'grading_returned_to_agent': False})
            phases = report['usage']['phases']
            for phase in phases:
                root.start_observation(name=phase['phase'], as_type='span', metadata=phase).end()
            grades = report['grading']['agg1']
            root.start_observation(name='independent-grading', as_type='span',
                metadata={'after_agent_termination': True, 'returned_to_agent': False},
                output={'passed': grades['passed'], 'groups': {name: {key: row[key] for key in ('tests_run', 'passed')}
                        for name, row in grades['groups'].items()}}).end()
            root.update(output=data)
            root.end()
            client.flush()
            for _ in range(20):
                response = reader.get('/api/public/v2/observations', params={'traceId': trace_id, 'limit': 1000})
                response.raise_for_status()
                rows = response.json()['data']
                if len(rows) == 4:
                    break
                time.sleep(0.5)
            if len(rows) != 4 or any(row['type'] == 'GENERATION' for row in rows):
                raise ValueError('Controller publication receipt mismatch')
        write(output / 'langfuse.json', {'status': 'passed', 'trace_id': trace_id,
            'trace_url': client.get_trace_url(trace_id=trace_id), 'controller_observations': 4,
            'controller_generations': 0, 'publication_model_calls': 0, 'inference_receipt': receipt,
            'inference_observations': len(observations), 'per_round_usage_verified': True,
            'publisher_sha256': sha(ROOT / 'deploy/langfuse/harness2_feedback.py')})
    finally:
        client.shutdown()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    publish(workspace(parser.parse_args().output))
