def canonical_path(path):
    return "/".join(part for part in path.replace("\\", "/").split("/") if part not in {"", "."})
