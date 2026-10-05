from routing import choose_destination


def archive_plan(paths, rules):
    return {path: choose_destination(path, rules) for path in paths}
