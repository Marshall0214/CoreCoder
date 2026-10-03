def renewal_target(store, tenant, job):
    return next((row for row in store.all() if row.job == job), None)
