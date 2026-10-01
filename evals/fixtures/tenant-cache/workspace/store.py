from keys import session_key


class SessionStore:
    def __init__(self):
        self.values = {}

    def put(self, tenant_id, user_id, value):
        self.values[session_key(tenant_id, user_id)] = value

    def get(self, tenant_id, user_id):
        return self.values.get(session_key(tenant_id, user_id))
