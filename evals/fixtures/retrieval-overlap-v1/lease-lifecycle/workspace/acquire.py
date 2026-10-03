from models import Lease


def acquire(store, tenant, job, owner, now, ttl_ms):
    existing = store.get(tenant, job)
    if existing is not None and existing.expires_at > now:
        return False
    store.put(Lease(tenant, job, owner, now + ttl_ms))
    return True
