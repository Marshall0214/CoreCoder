# Cleanup interface

sweep(store, now) returns sorted identity tuples.
Use the same live/expired boundary as renewal and acquisition, defined in leases.md.
monitor.list_tenant is a read-only view. legacy.old_batch_expired keeps its historic
strict reporting boundary; it does not participate in lease authorization.
