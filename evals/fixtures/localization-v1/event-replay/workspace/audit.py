def audit_label(record):
    return f'{record["tenant"]}:{record["event_id"]}'
