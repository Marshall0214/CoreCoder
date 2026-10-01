from matching import matches_rule


def choose_destination(path, rules):
    matches = [rule for rule in rules if matches_rule(path, rule)]
    if not matches:
        return "unassigned"
    return matches[0].destination
