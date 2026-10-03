def expired(lease, now):
    return lease.expires_at < now
