from identity import lease_key


class Store:
    def __init__(self):
        self.rows = {}

    def put(self, lease):
        self.rows[lease_key(lease.tenant, lease.job)] = lease

    def get(self, tenant, job):
        return self.rows.get(lease_key(tenant, job))

    def remove(self, tenant, job):
        return self.rows.pop(lease_key(tenant, job), None)

    def all(self):
        return list(self.rows.values())
