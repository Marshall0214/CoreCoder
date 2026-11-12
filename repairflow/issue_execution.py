"""Administrator-owned execution profiles; HTTP callers cannot supply overrides."""
from dataclasses import asdict, dataclass

LEGACY = 'symbol-recovery-v1'
FEEDBACK = 'feedback-actions-v2'
DEFAULT_PROFILE = {'exploration_requests': 20, 'feedback_requests': 20, 'exploration_seconds': 1200,
                   'feedback_seconds': 1200, 'context_target_tokens': 12000}


def profile(value=None):
    if value is not None and not isinstance(value, dict):
        raise ValueError('Require an execution profile object')
    result = dict(DEFAULT_PROFILE if value is None else value)
    if set(result) != set(DEFAULT_PROFILE) or any(type(v) is not int or v < 1 for v in result.values()):
        raise ValueError('Require the five positive integer execution profile fields')
    return result


@dataclass(frozen=True)
class ApprovalConfig:
    mode: str
    model: str
    max_rounds: int
    wall_timeout: int
    token_budget: None = None
    max_output_tokens: None = None
    context_tokens: int = 65536
    reasoning_effort: str = 'none'
    output_policy: str = 'account_only'

    def to_dict(self):
        return asdict(self)


def limits(value=None, service_timeout=None):
    requested = profile(value)
    total = requested['exploration_seconds'] + requested['feedback_seconds']
    if service_timeout is not None:
        if service_timeout <= 0:
            raise ValueError('Require a positive trusted service timeout')
        total = min(total, max(1, int(service_timeout) - 5))
    return {'requested': requested, 'total_seconds': total, 'service_timeout_seconds': service_timeout,
            'exploration_requests': requested['exploration_requests'], 'feedback_requests': requested['feedback_requests'],
            'token_budget': None, 'max_output_tokens': None, 'model_call_seconds': 480,
            'time_policy': 'Shared total deadline; each phase also has its declared maximum'}
