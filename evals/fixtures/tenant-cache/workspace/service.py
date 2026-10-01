from store import SessionStore


def save_session(store, tenant, user, token):
    store.put(tenant, user, token)
    return store.get(tenant, user)
