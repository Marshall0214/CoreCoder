from fnmatch import fnmatchcase


def preview_first(path, rules):
    for rule in rules:
        if fnmatchcase(path, rule.pattern):
            return rule.destination
    return "unassigned"
