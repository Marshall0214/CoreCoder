from policy import is_retryable


def handle_response(status_code):
    if status_code < 400:
        return "done"
    if status_code >= 400:
        return "retry"
    return "stop"
