"""Dispatch only the explicitly scoped flag contract; keep other checks unchanged."""
from docs.experiments import caller_fallback_feedback_v1 as standard
from docs.experiments import public_contract_feedback_v1 as contract

previous = standard.previous
restore = standard.restore


def valid(outcomes):
    return contract.valid(outcomes) if 'contract' in outcomes else standard.valid(outcomes)


def run_candidate(llm, job, events):
    if job.get('task_id') == 'click-flag-envvar':
        if 'contract_harness' not in job:
            raise ValueError('Flag task requires versioned public contract')
        return contract.run_candidate(llm, job, events)
    if 'contract_harness' in job:
        raise ValueError('Public flag contract cannot run on unrelated tasks')
    return standard.run_candidate(llm, job, events)
