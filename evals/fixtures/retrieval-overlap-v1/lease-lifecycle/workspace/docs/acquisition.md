# Acquisition interface

acquire(store, tenant, job, owner, now, ttl_ms) returns a boolean.
Success creates a lease using the shared lease contract in leases.md.
A rejected acquisition retains the original owner and expiration.
The input TTL is supplied by external configuration; do not change its public unit.
