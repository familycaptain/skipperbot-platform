# Calculators Tools Guide

Math and financial calculators. Prefer these over guessing arithmetic.

## calculate
Scientific calculator — evaluate a math expression. Supports `+ - * /`, `^`
(power), parentheses, `sqrt()`, `sin`/`cos`/`tan` (and `asin`/`acos`/`atan`),
`ln`, `log` (base 10), `exp`, `abs`, factorial (`n!` or `factorial(n)`), and
`pi`/`e`. Pass `angle_mode="rad"` for radians (default is degrees).
- "what's sin(90) + sqrt(16)*2" → `calculate(expression="sin(90) + sqrt(16)*2")`

## compound_interest
Savings/investment growth. Provide principal, annual_rate (%), compounds_per_year
(12 = monthly), years, future_value — leave exactly one of principal/rate/years/
future_value blank to solve for it.
- "how much is $10k at 6% for 10 years" → leave future_value blank.

## loan_amortization
Loan payment / payoff. Provide loan_amount, annual_rate (%), years,
monthly_payment — leave exactly one blank to solve for it; returns payoff totals.
- "payment on a $250k 30-year loan at 6.5%" → leave monthly_payment blank.
