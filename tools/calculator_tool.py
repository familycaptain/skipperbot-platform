"""
Calculator Tool - Evaluate mathematical expressions.

Uses a restricted AST evaluator (never eval()) so a chat-supplied expression
can't run arbitrary code or mount an unbounded-compute DoS via huge powers
(e.g. 9**9**9 or (2**900)**900). (Security audit #26/#27.)
"""

import ast
import math
import operator

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY_OPS = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_MAX_POW_EXP = 1000      # cap exponent magnitude
_MAX_RESULT_BITS = 4096  # cap result size regardless of base/exponent


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric literals are allowed")
        return node.value
    if isinstance(node, ast.UnaryOp):
        op = _UNARY_OPS.get(type(node.op))
        if op is None:
            raise ValueError("unsupported unary operator")
        return op(_eval_node(node.operand))
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > _MAX_POW_EXP:
                raise ValueError("exponent too large")
            base = abs(left)
            if base not in (0, 1) and abs(right) * math.log2(max(base, 2)) > _MAX_RESULT_BITS:
                raise ValueError("result too large")
            return left ** right
        op = _BIN_OPS.get(type(node.op))
        if op is None:
            raise ValueError("unsupported operator")
        return op(left, right)
    raise ValueError("unsupported expression")


def calculate(expression: str) -> str:
    """
    Evaluate a mathematical expression.

    Args:
        expression: A mathematical expression to evaluate (e.g., "2 + 2", "10 * 5").
                    Supports + - * / // % ** and parentheses on numbers only.
    """
    if not expression or not expression.strip():
        return "Error: expression is required"
    try:
        tree = ast.parse(expression, mode="eval")
        return str(_eval_node(tree))
    except ZeroDivisionError:
        return "Error: division by zero"
    except SyntaxError:
        return "Error: invalid expression"
    except Exception as e:
        return f"Error: {str(e)}"
