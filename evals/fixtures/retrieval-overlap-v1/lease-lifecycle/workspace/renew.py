from dataclasses import replace

from lookup import renewal_target


def renew(store, tenant, job, owner, now, ttl_ms):
    current = renewal_target(store, tenant, job)
    if current is None or current.owner != owner or current.expires_at <= now:
        return False
    store.put(replace(current, expires_at=now + ttl_ms / 1000.0))
    return True
