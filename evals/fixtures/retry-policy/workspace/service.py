from worker import handle_response


def next_action(response):
    return handle_response(response["status"])
