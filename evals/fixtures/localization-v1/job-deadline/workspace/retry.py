def pause_before_retry(clock, deadline, delay):
    clock.advance(delay)
    return clock.now() < deadline
