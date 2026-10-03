from expiry import expired


def sweep(store, now):
    removed = []
    for lease in store.all():
        if expired(lease, now):
            store.remove(lease.tenant, lease.job)
            removed.append((lease.tenant, lease.job))
    return sorted(removed)
