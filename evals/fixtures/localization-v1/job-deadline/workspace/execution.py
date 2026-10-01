from budget import request_timeout
from retry import pause_before_retry


def execute(call, clock, total_timeout, attempt_timeout, max_attempts, backoff):
    started = clock.now()
    deadline = started + total_timeout
    attempts = 0
    while attempts < max_attempts:
        remaining = deadline - clock.now()
        if remaining <= 0:
            break
        attempts += 1
        status = call(request_timeout(attempt_timeout, remaining))
        if status < 400:
            return {"status": "done", "attempts": attempts, "elapsed": clock.now() - started}
        if status != 429 and status < 500:
            return {"status": "stopped", "attempts": attempts, "elapsed": clock.now() - started}
        if attempts >= max_attempts:
            break
        if not pause_before_retry(clock, deadline, backoff):
            break
    state = "deadline" if clock.now() >= deadline else "attempt_limit"
    return {"status": state, "attempts": attempts, "elapsed": clock.now() - started}
