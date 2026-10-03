def list_tenant(store, tenant):
    return sorted((row.job, row.owner, row.expires_at)
                  for row in store.all() if row.tenant == tenant)
