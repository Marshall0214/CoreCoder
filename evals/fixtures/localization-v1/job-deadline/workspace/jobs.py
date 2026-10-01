from execution import execute


def run_job(call, clock, total_timeout=5, attempt_timeout=3, max_attempts=3, backoff=2):
    return execute(call, clock, total_timeout, attempt_timeout, max_attempts, backoff)
