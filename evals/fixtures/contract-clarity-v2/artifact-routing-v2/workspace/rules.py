from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    pattern: str
    destination: str
    priority: int = 0
