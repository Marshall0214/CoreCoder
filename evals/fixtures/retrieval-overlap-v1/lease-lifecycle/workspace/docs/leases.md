# Shared lease contract

A lease is identified by (tenant, job); tenants may use the same job and owner names.
The clock now and persisted expires_at are seconds. Public TTL arguments are milliseconds.
A lease is live exactly when expires_at > now. At equality it is expired.
acquire may replace an expired lease but cannot steal a live one.
renew requires the exact tenant/job and matching owner of a live lease.
sweep removes all expired leases and returns sorted (tenant, job) keys.
Read operations and rejected updates do not mutate stored leases.
