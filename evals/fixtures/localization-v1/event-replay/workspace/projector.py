from event_keys import event_identity


def apply_batch(state, seen, records):
    for event in records:
        identity = event_identity(event)
        if identity in seen:
            return state
        tenant = event["tenant"]
        state[tenant] = state.get(tenant, 0) + event["delta"]
        seen.add(identity)
    return state
