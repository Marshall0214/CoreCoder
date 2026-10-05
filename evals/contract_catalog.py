"""Public contract lines and implementation-free API metadata for check review."""

import ast

PROTOCOL = "public-contract-feedback-v3-contract-only"


def contract_catalog(description, evidence):
    sources = [("description", description)] + sorted(
        (item["path"], item["content"]) for item in evidence if item["path"].endswith(".md"))
    result = []
    for path, text in sources:
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            if len(line) > 2000 or len(result) >= 160:
                raise ValueError("Contract catalog exceeds bounds; no silent truncation")
            result.append({"id": f"c{len(result) + 1:04d}", "source": path,
                           "line": line_number, "text": line})
    return result


def public_interfaces(evidence):
    result = []

    def signature(node, prefix=""):
        args = node.args
        positional = args.posonlyargs + args.args
        default_start = len(positional) - len(args.defaults)
        parameters = [{"name": arg.arg, "kind": "positional_only" if i < len(args.posonlyargs) else "positional",
                       "has_default": i >= default_start} for i, arg in enumerate(positional)]
        if args.vararg:
            parameters.append({"name": args.vararg.arg, "kind": "varargs", "has_default": False})
        parameters.extend({"name": arg.arg, "kind": "keyword_only", "has_default": default is not None}
                          for arg, default in zip(args.kwonlyargs, args.kw_defaults))
        if args.kwarg:
            parameters.append({"name": args.kwarg.arg, "kind": "kwargs", "has_default": False})
        return {"name": prefix + node.name, "async": isinstance(node, ast.AsyncFunctionDef), "parameters": parameters}

    for item in evidence:
        if not item["path"].endswith(".py"):
            continue
        symbols = []
        try:
            tree = ast.parse(item["content"])
        except SyntaxError:
            result.append({"path": item["path"], "symbols": [], "parse_error": True})
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(signature(node))
            elif isinstance(node, ast.ClassDef):
                symbols.extend(signature(method, node.name + ".") for method in node.body
                               if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)))
        result.append({"path": item["path"], "symbols": symbols})
    return result
