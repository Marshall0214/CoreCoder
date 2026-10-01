from defaults import DEFAULTS
from options import supplied_values


def effective_options(raw):
    return {**DEFAULTS, **supplied_values(raw)}
