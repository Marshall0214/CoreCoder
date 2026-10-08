"""One optional third request after a rejected correction, within the original token cap."""
import argparse
import copy
import json
import shutil
from pathlib import Path

from docs.experiments import frozen_feedback_v1 as guarded
from evals.runner import digest, snapshot
from evals.runtime import Events

previous = guarded.previous


def inherit_budget(llm, metrics):
    if metrics['llm_calls'] != 2 or metrics['missing_usage_calls'] or metrics['budget_accounted_tokens'] >= llm.config.token_budget:
        raise ValueError('Require two known-usage calls with remaining budget')
    llm.calls = metrics['llm_calls']
    llm.spent = metrics['budget_accounted_tokens']
    llm.prompt_known = metrics['known_prompt_tokens']
    llm.completion_known = metrics['known_completion_tokens']


def correction(llm, job, outcomes, observation, events, starting_source):
    root, workspace = events.path.parent, Path(job['workspace'])
    guarded.validate(job, root)
    starting_hash = digest(snapshot(starting_source))
    if starting_hash != job['starting_source_hash']:
        raise ValueError('Rollback source changed')
    result = {'status': 'failed_public_validation', 'published': False, 'max_total_calls': 3}
    try:
        if llm.calls != 2 or guarded.valid(outcomes) or not guarded.executable(outcomes):
            raise ValueError('Third call requires failed executable correction checks')
        attempt = previous.request(llm, workspace, job, job['evidence'], root, 'feedback', observation)
        result['correction'] = attempt
        if attempt['status'] == 'completed':
            final = guarded.checked(workspace, job, root, 'corrected')
            result['checks'] = final
            result['published'] = guarded.valid(final)
        result['status'] = 'completed' if result['published'] else attempt['status'] if attempt['status'] != 'completed' else 'failed_public_validation'
    except Exception as exc:  # noqa: BLE001 - never retain unvalidated source
        result.update(status='agent_error', error_type=type(exc).__name__, published=False)
    finally:
        if not result['published']:
            guarded.restore(workspace, starting_source, root)
        result['metrics'] = llm.metrics()
        result['final_source_hash'] = digest(snapshot(workspace))
        result['starting_version_restored'] = result['final_source_hash'] == starting_hash
    return result


def run(prior, output):
    load = lambda p: json.loads(p.read_text(encoding='utf-8'))
    old = load(prior / 'repair.json')
    result = old['worker']
    if (not old['complete'] or old['accepted'] or result['published'] or not result['original_restored']
            or result.get('correction', {}).get('status') != 'completed'):
        raise ValueError('Require completed rejected correction with rollback')
    old_job = load(prior / 'live' / 'job.json')
    candidate = prior / 'live' / 'feedback-staging'
    certificate = load(prior / 'certificate.json')
    admitted_path = next(Path(p) for p in certificate['input_hashes'] if Path(p).name == 'admission.json')
    case = next(c for c in load(admitted_path)['cases'] if c['task_id'] == old['task_id'])
    private_path = prior / 'grading-checks-v2'
    hashes = dict(certificate['input_hashes'])
    for p in (prior / 'repair.json', prior / 'certificate.json', prior / 'live' / 'job.json', Path(__file__)):
        hashes[str(p.resolve())] = previous.admission.history.sha(p)
    protected = [prior.resolve(), *(Path(case[k]).resolve() for k in ('before', 'after', 'checks'))]
    output = output.resolve()
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError('Fresh output outside frozen inputs required')
    candidate_hash = digest(snapshot(candidate))

    def unchanged():
        if any(previous.admission.history.sha(Path(p)) != h for p, h in hashes.items()):
            raise ValueError('Frozen input changed')
        for key in ('before', 'after', 'checks'):
            if digest(snapshot(Path(case[key]))) != case[key + '_hash']:
                raise ValueError('Frozen source/checks changed')
        if digest(snapshot(candidate)) != candidate_hash or digest(snapshot(private_path)) != certificate['private_hash']:
            raise ValueError('Candidate or grading checks changed')
        for name in ('harness', 'frozen_harness'):
            if digest(snapshot(Path(old_job[name]))) != old_job[name + '_hash']:
                raise ValueError('Certified public checks changed')

    unchanged()
    previous.repair.check_identity(previous.repair.config())
    output.mkdir(parents=True)
    workspace = output / 'workspace'
    shutil.copytree(candidate, workspace)
    outcomes = guarded.checked(workspace, old_job, output, 'rejected')
    observation = copy.deepcopy({'provenance': 'actual public failure of rejected correction; no private grading',
        'test_code': (Path(old_job['harness']) / 'test_admission.py').read_text(encoding='utf-8'),
        'observations': '\n'.join(label + ':\n' + previous.diagnostic(outcomes[label], output / ('rejected-' + label),
                                    workspace, Path(old_job[name]))
                                 for label, name in [('public', 'harness'), ('frozen', 'frozen_harness')])[:4400]})
    evidence = previous.refresh_seeds(workspace, old_job['allowed_files'], old_job['evidence'])['evidence']
    job = dict(old_job, workspace=str(workspace), evidence=evidence, original_hash=candidate_hash,
               starting_source_hash=case['before_hash'])
    previous.write_json(output / 'job.json', job)
    events = Events(output / 'trace.jsonl', 'verified-correction-retry-v1')
    provider = previous.Provider('qwen', events)
    llm = previous.CheckedBudgetLLM(provider, previous.repair.config(), events)
    try:
        inherit_budget(llm, result['metrics'])
        fixed = correction(llm, job, outcomes, observation, events, Path(case['before']))
        try:
            previous.repair.check_identity(previous.repair.config())
        except Exception:
            guarded.restore(workspace, Path(case['before']), output)
            fixed.update(status='agent_error', published=False, starting_version_restored=True,
                         final_source_hash=digest(snapshot(workspace)))
            raise
    finally:
        provider.client.close()
    unchanged()
    grade = output / 'verification'
    grade.mkdir()
    verified = previous.baseline.verify(dict(case, checks=str(private_path)), workspace, grade)
    accepted = fixed['status'] == 'completed' and fixed['published'] and verified['passed']
    unchanged()
    data = {'complete': True, 'task_id': case['task_id'], 'accepted': accepted, 'worker': fixed,
            'verification': verified, 'new_provider_calls': provider.calls, 'input_hashes': hashes,
            'protocol': {'config': previous.repair.config().to_dict(), 'model_digest': previous.repair.MODEL_DIGEST,
                         'max_total_calls': 3, 'token_budget': 15000, 'inherited_usage': result['metrics'],
                         'extra_feedback': 'actual failure of rejected second patch under certified public v2 checks',
                         'limits': 'Known development case; an extra call, not same-call-count gain; no default integration'}}
    previous.write_json(output / 'repair.json', data)
    print(json.dumps({'accepted': accepted, 'metrics': fixed['metrics'], 'target': verified['groups']['Target']['passed'],
                      'controls': verified['groups']['Controls']['passed']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prior', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.prior.resolve(), args.output)
