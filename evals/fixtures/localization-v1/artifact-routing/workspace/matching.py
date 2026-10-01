from fnmatch import fnmatchcase

from paths import canonical_path


def matches_rule(path, rule):
    return fnmatchcase(path, canonical_path(rule.pattern))
