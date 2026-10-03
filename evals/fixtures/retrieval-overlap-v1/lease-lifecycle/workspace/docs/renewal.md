# Renewal interface

renew(store, tenant, job, owner, now, ttl_ms) returns a boolean.
Apply the shared lease identity and lifetime rules in leases.md.
Renewal replaces the expiration of the selected row, retaining its identity and owner.
Two tenants with the same job name must be independently renewable.
