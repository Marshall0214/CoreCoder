from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    timeout_seconds: float = 5.0


def parse_settings(raw):
    return Settings(timeout_seconds=float(raw.get("timeout_seconds", 5.0)))
