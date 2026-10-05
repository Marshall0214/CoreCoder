"""Small Decimal expression interpreter; no eval, imports, variables or powers."""

import ast
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext


def calculate(expression):
    if not isinstance(expression, str) or not 1 <= len(expression) <= 300:
        raise ValueError("Arithmetic expression exceeds bounds")
    if "=" in expression:
        if expression.count("=") != 1:
            raise ValueError("Only a single arithmetic equality is supported")
        left, right = expression.split("=")
        value = calculate(left.strip())
        if value != calculate(right.strip()):
            raise ValueError("Arithmetic equality is inconsistent")
        return value
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 80:
        raise ValueError("Arithmetic expression is too complex")

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            value = Decimal(ast.get_source_segment(expression, node))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                value = left + right
            elif isinstance(node.op, ast.Sub):
                value = left - right
            elif isinstance(node.op, ast.Mult):
                value = left * right
            else:
                value = left / right
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id == "round_half_up" and len(node.args) == 1 and not node.keywords):
            value = visit(node.args[0]).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in {"min", "max"} and 2 <= len(node.args) <= 8 and not node.keywords):
            values = [visit(arg) for arg in node.args]
            value = min(values) if node.func.id == "min" else max(values)
        else:
            raise ValueError("Unsupported arithmetic syntax")
        if not value.is_finite() or abs(value) > Decimal("1e12"):
            raise ValueError("Arithmetic value exceeds bounds")
        return value

    try:
        with localcontext() as context:
            context.prec = 50
            return visit(tree.body)
    except (DecimalException, OverflowError) as exc:
        raise ValueError("Invalid arithmetic operation") from exc


def numeric_assertions(code):
    result = {}
    for cls in ast.parse(code).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef) or not method.name.startswith("test_"):
                continue
            calls = sorted((n for n in ast.walk(method) if isinstance(n, ast.Call)
                            and isinstance(n.func, ast.Attribute) and n.func.attr == "assertEqual"),
                           key=lambda n: (n.lineno, n.col_offset))
            result[f"{cls.name}.{method.name}"] = [
                {"assertion": index, "expected": node.args[1].value}
                for index, node in enumerate(calls) if len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant) and type(node.args[1].value) in {int, float}]
    return result


def validate_numeric_proofs(proofs, assertions):
    if not isinstance(proofs, list) or len(proofs) != len(assertions):
        raise ValueError("Every numeric literal assertEqual needs a derivation")
    expected = {item["assertion"]: item["expected"] for item in assertions}
    seen, calculations = set(), []
    for proof in proofs:
        if not isinstance(proof, dict) or set(proof) != {"assertion", "expression"}:
            raise ValueError("Invalid numeric proof fields")
        index = proof["assertion"]
        if type(index) is not int or index not in expected or index in seen:
            raise ValueError("Unknown or duplicate numeric assertion")
        seen.add(index)
        value = calculate(proof["expression"])
        if value != Decimal(str(expected[index])):
            raise ValueError(f"Assertion {index}: derived {value} differs from expected {expected[index]}")
        calculations.append({**proof, "computed": str(value), "expected": expected[index]})
    return calculations
