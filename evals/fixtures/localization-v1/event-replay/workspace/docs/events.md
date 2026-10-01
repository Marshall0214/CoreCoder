# Event projection contract

Process records in input order and sum delta per tenant.
event_id is unique within a tenant, not globally. Identifiers can include punctuation.
An already-applied event does not change counts; it does not invalidate later records.
The caller supplies persistent state and seen sets and can replay across multiple batches.
Offline export IDs remain the original event_id because export files contain one tenant only.
