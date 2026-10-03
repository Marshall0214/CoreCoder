def old_batch_expired(expires_at, now):
    # Historic reports use a strict cutoff; this is not lease authorization.
    return expires_at < now


def configured_ttl_ms(config):
    return config.get("ttl_ms", 1000)
