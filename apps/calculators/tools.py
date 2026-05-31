"""Calculators — agent tools.

Mirrors the Calculators app UI so everything it does also works through chat:
a scientific expression evaluator, a compound-interest calculator, and a loan
amortization calculator (both solve for whichever value is left blank).

Only the public functions below are registered as MCP tools; helpers are
underscore-prefixed so the loader skips them.
"""

from __future__ import annotations

import ast
import math
import re


def _num(v):
    """Parse a tool string arg into a float, or None when blank."""
    v = (v or "").strip().replace(",", "")
    return None if v == "" else float(v)


def _payment(P, c, N):
    return P / N if c == 0 else P * c / (1 - (1 + c) ** (-N))


def _safe_eval(expr: str, deg: bool) -> float:
    """Safely evaluate a math expression via a whitelisted AST walk (no eval())."""
    expr = (expr.replace("^", "**").replace("×", "*").replace("÷", "/")
            .replace("−", "-").replace("π", "pi").replace("√", "sqrt"))
    expr = re.sub(r"(\d+(?:\.\d+)?)!", r"factorial(\1)", expr)  # n! -> factorial(n)

    def _trig(fn):
        return lambda x: fn(math.radians(x) if deg else x)

    def _itrig(fn):
        return lambda x: (math.degrees(fn(x)) if deg else fn(x))

    funcs = {
        "sin": _trig(math.sin), "cos": _trig(math.cos), "tan": _trig(math.tan),
        "asin": _itrig(math.asin), "acos": _itrig(math.acos), "atan": _itrig(math.atan),
        "ln": math.log, "log": math.log10, "sqrt": math.sqrt, "abs": abs,
        "exp": math.exp, "factorial": lambda n: math.factorial(int(n)),
    }
    consts = {"pi": math.pi, "e": math.e}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float)):
                return n.value
            raise ValueError("only numbers allowed")
        if isinstance(n, ast.BinOp):
            a, b = ev(n.left), ev(n.right)
            op = n.op
            if isinstance(op, ast.Add): return a + b
            if isinstance(op, ast.Sub): return a - b
            if isinstance(op, ast.Mult): return a * b
            if isinstance(op, ast.Div): return a / b
            if isinstance(op, ast.Pow): return a ** b
            if isinstance(op, ast.Mod): return a % b
            raise ValueError("unsupported operator")
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            if isinstance(n.op, ast.USub): return -v
            if isinstance(n.op, ast.UAdd): return v
            raise ValueError("unsupported unary")
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.func.id not in funcs:
                raise ValueError("unknown function")
            return funcs[n.func.id](*[ev(a) for a in n.args])
        if isinstance(n, ast.Name):
            if n.id in consts:
                return consts[n.id]
            raise ValueError(f"unknown name: {n.id}")
        raise ValueError("unsupported expression")

    return ev(ast.parse(expr, mode="eval"))


def calculate(expression: str = "", angle_mode: str = "deg") -> str:
    """Scientific calculator — evaluate a math expression.

    Supports + - * / and ^ (power), parentheses, sqrt(), sin/cos/tan and
    asin/acos/atan, ln, log (base 10), exp, abs, factorial (n! or factorial(n)),
    and the constants pi and e.

    Args:
        expression: The expression to evaluate, e.g. "sin(90) + sqrt(16) * 2".
        angle_mode: "deg" (default) or "rad" — how trig functions read angles.

    Returns:
        The numeric result, or an error describing what went wrong.
    """
    if not expression.strip():
        return "Provide an expression to evaluate, e.g. '2*(3+4)^2'."
    try:
        v = _safe_eval(expression, deg=angle_mode.strip().lower() != "rad")
        if not math.isfinite(v):
            return "Result is not a finite number — check the expression."
        return f"{expression} = {round(v, 10)}"
    except Exception:  # noqa: BLE001
        return "Could not evaluate that expression — check the syntax and supported functions."


def compound_interest(principal: str = "", annual_rate: str = "", compounds_per_year: str = "12",
                      years: str = "", future_value: str = "") -> str:
    """Compound-interest calculator. Provide the values you know and leave exactly
    one of principal / annual_rate / years / future_value blank; it solves for it.

    Args:
        principal: Starting amount, e.g. "10000".
        annual_rate: Annual interest rate in percent, e.g. "6".
        compounds_per_year: Times per year interest compounds (default "12" = monthly).
        years: Number of years.
        future_value: Ending amount.

    Returns:
        The solved value described in words.
    """
    P, rate, n, t, A = _num(principal), _num(annual_rate), _num(compounds_per_year), _num(years), _num(future_value)
    if n is None or n <= 0:
        return "compounds_per_year is required and must be > 0 (e.g. 12 for monthly)."
    blanks = [k for k, v in [("principal", P), ("annual_rate", rate), ("years", t), ("future_value", A)] if v is None]
    if len(blanks) != 1:
        return "Leave exactly one of principal / annual_rate / years / future_value blank."
    field = blanks[0]
    r = None if rate is None else rate / 100
    try:
        if field == "future_value":
            out = P * (1 + r / n) ** (n * t)
            return f"Future value: ${out:,.2f} — ${P:,.2f} at {rate}% compounded {int(n)}×/yr for {t} years."
        if field == "principal":
            out = A / (1 + r / n) ** (n * t)
            return f"Required principal: ${out:,.2f} to reach ${A:,.2f} at {rate}% over {t} years."
        if field == "years":
            out = math.log(A / P) / (n * math.log(1 + r / n))
            return f"Years needed: {out:.2f} to grow ${P:,.2f} to ${A:,.2f} at {rate}%."
        if field == "annual_rate":
            cc = (A / P) ** (1 / (n * t)) - 1
            return f"Required annual rate: {cc * n * 100:.3f}% to grow ${P:,.2f} to ${A:,.2f} in {t} years."
    except (ValueError, ZeroDivisionError):
        return "Could not compute — check the inputs (positive principal/future value/years/rate where needed)."
    return "Nothing to solve."


def loan_amortization(loan_amount: str = "", annual_rate: str = "", years: str = "",
                      monthly_payment: str = "") -> str:
    """Loan/amortization calculator. Provide the values you know and leave exactly
    one of loan_amount / annual_rate / years / monthly_payment blank; it solves for
    it and reports total interest and total paid.

    Args:
        loan_amount: Principal borrowed, e.g. "250000".
        annual_rate: Annual interest rate in percent, e.g. "6.5".
        years: Loan term in years, e.g. "30".
        monthly_payment: Monthly payment amount.

    Returns:
        The solved value plus payoff totals.
    """
    P, rate, yrs, M = _num(loan_amount), _num(annual_rate), _num(years), _num(monthly_payment)
    blanks = [k for k, v in [("loan_amount", P), ("annual_rate", rate), ("years", yrs), ("monthly_payment", M)] if v is None]
    if len(blanks) != 1:
        return "Leave exactly one of loan_amount / annual_rate / years / monthly_payment blank."
    field = blanks[0]
    c = None if rate is None else rate / 100 / 12
    N = None if yrs is None else round(yrs * 12)
    solved = ""
    try:
        if field == "monthly_payment":
            M = _payment(P, c, N)
            solved = f"Monthly payment: ${M:,.2f}"
        elif field == "loan_amount":
            P = M * N if c == 0 else M * (1 - (1 + c) ** (-N)) / c
            solved = f"Loan amount: ${P:,.2f}"
        elif field == "years":
            if c is None or c <= 0:
                return "Enter a rate above 0 to solve for the term."
            if M <= P * c:
                return "Monthly payment is too low to ever pay off this loan (must exceed the first month's interest)."
            N = math.ceil(-math.log(1 - (P * c) / M) / math.log(1 + c))
            solved = f"Term: {N / 12:.2f} years ({N} payments)"
        elif field == "annual_rate":
            lo, hi = 1e-9, 1.0
            for _ in range(200):
                mid = (lo + hi) / 2
                if _payment(P, mid, N) > M:
                    hi = mid
                else:
                    lo = mid
            c = (lo + hi) / 2
            solved = f"Annual rate: {c * 12 * 100:.3f}%"
        total = M * N
        interest = total - P
        return (f"{solved}. Monthly payment ${M:,.2f} × {N} = ${total:,.2f} total paid "
                f"(${interest:,.2f} interest on a ${P:,.2f} loan).")
    except (ValueError, ZeroDivisionError):
        return "Could not compute — check the inputs."
