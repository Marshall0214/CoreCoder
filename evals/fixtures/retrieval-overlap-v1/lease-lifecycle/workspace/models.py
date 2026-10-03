from dataclasses import dataclass


@dataclass(frozen=True)
class Lease:
    tenant: str
    job: str
    owner: str
    expires_at: float
