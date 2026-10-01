def is_retryable(status_code):
    return status_code == 429 or 500 <= status_code < 600
