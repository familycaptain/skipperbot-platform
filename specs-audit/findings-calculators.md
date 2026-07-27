# Findings — calculators

Survey only; nothing fixed. Corpus 8 → 47 records. The app is scientific + compound interest + loan
amortization — there is **no unit conversion and no tip calculator**, contrary to how it is often
described.

## A. VERIFIED — no `eval`, but an unbounded expression wedges the server

The good news first: both evaluators are genuine whitelists. `tools.py::_safe_eval` walks the AST allowing
only `Constant`/`BinOp`/`UnaryOp`/`Call`/`Name` against a fixed `funcs`/`consts` map, and the browser uses
a hand-written tokenizer plus shunting-yard. `__import__("os").system("id")` and
`open("/etc/passwd").read()` are both refused. **There is no code-execution hole.**

What is not bounded is the *cost* of a permitted operation. `ast.Pow` is allowed with no magnitude check,
so `calculate(expression="9^9^9")` never returns — confirmed directly: computing `9**9**9` still had not
finished after a 3-second timeout, on Python ints, so memory is unbounded too. `50000000!` is the same
shape.

`calculate` is a registered MCP tool reached from an ordinary chat message and run **synchronously in the
server process**, so one chat turn can hang or OOM Skipper. Expected: bound exponent and operand magnitude
and the factorial argument before computing, or run under a wall-clock bound.

The browser has the same shape — `sciFactorial` loops to `n` with no bound (`r` is `Infinity` after ~170
iterations but the loop continues), so `1000000000!` freezes the tab. Partial accident worth knowing:
Python 3.11's int→str digit cap makes `200000!` *return* an error after 0.44s because formatting the
result raises — the computation still ran, and it does not save `9^9^9`.

## B. Non-numeric input to either finance tool raises instead of answering

`tools.py::compound_interest` (131) and `::loan_amortization` (182) call `_num()` **outside** the `try`.
`_num` is `float(...)`, so `compound_interest(principal="ten thousand")` and
`loan_amortization(loan_amount="250k")` raise an uncaught `ValueError`. Every other bad input returns a
sentence; these become a tool error. Arguments arrive from a model paraphrasing a person ("250k",
"$1,200/mo"), so **this is the likeliest failure in practice.**

## C. `OverflowError` is not caught

`compound_interest` catches only `(ValueError, ZeroDivisionError)`, so
`compound_interest(principal="10000", annual_rate="6", years="1e6")` raises an uncaught `OverflowError`
from `P * (1 + r/n) ** (n*t)`.

## D. Solving a loan's rate can return a fabricated rate as fact

The `annual_rate` branch of `loan_amortization` bisects on `lo=1e-9, hi=1.0` with **no bracket check**,
unlike the UI (`solveLoan` guards `if (M <= P/N)`).
`loan_amortization(loan_amount="250000", years="30", monthly_payment="100")` returns
`"Annual rate: 0.000%. … ($-214,000.00 interest on a $250,000.00 loan)"` — that payment cannot repay the
loan at any rate, and a negative interest figure is printed as a result. `monthly_payment="9999999"`
returns `"Annual rate: 1200.000%"`, which is just the upper bracket (100%/month), not a solved rate. The
UI shares the upper-bracket problem.

## E. Same question, two different totals

Solving for the term, chat reports `total = M * N` with `N = ceil(...)`, but the UI's `finishLoan` clamps
the final payment to the remaining balance. For $250,000 at 6.5% with a $2,000 payment the app shows
total paid $418,494.40 / interest $168,494.40 while chat says $420,000.00 / $170,000.00 — **a $1,505.60
gap on one question.** Both files' header comments assert the two surfaces are kept identical. Precision
diverges too: the UI rounds a solved compound rate to 2 dp, chat prints 3 dp.

## F. Negative inputs produce nonsense with no refusal

`compound_interest`: `principal="-10000"` → "Future value: $-18,193.97"; `years="-10"` → "…for -10.0
years"; `annual_rate="-5"` accepted silently. `loan_amortization` and `solveLoan`: `annual_rate="-6.5"` →
"Monthly payment: $223.24 … ($-169,634.57 interest on a $250,000.00 loan)", and the app renders "Total
interest −$169,634.57" as a stat tile. Only the compound solver's years/rate branches guard positivity,
and only in the UI.

## G. Compound edge cases disagree between surfaces, contradicting the spec that governed them

The old `goal-already-met` spec required "Behavior and wording must match across both surfaces". With
`annual_rate="0"` and a goal below the balance, `compound_interest` returns the "already reached it"
sentence while `solveCompound` returns "Need positive Principal, Future value, and Rate to solve for
Years." — the UI checks `c <= 0` first, the tool checks `A < P` first. That spec also called the A<P case
an `{error}`-style message in the UI; it is actually `{info}`. And `tools.py` has no equivalent of the
UI's positivity guards at all — `P<=0` falls through to `math.log` and yields the generic "Could not
compute".

## H. `compounds_per_year` accepts a fraction and then mislabels it

`compound_interest` validates only `n > 0`, then prints `{int(n)}×/yr`. `compounds_per_year="0.5"`
computes with 0.5 and reports "compounded 0×/yr" — **an answer labelled with a frequency it did not
use.** `"1e9"` is accepted.

## I. Angle mode falls back to degrees silently

`calculate` computes `deg = angle_mode.strip().lower() != "rad"`, so only the exact string `"rad"`
selects radians. `calculate("sin(90)", angle_mode="radians")` returns `1.0` — degrees — with no warning,
and "radians" is the obvious paraphrase for a model to emit.

## J. Factorial silently truncates a fraction in chat

`_safe_eval` binds `"factorial": lambda n: math.factorial(int(n))`, and the pre-pass regex
`(\d+(?:\.\d+)?)!` matches decimals. `calculate("3.7!")` returns `3.7! = 6` — the factorial of 3,
presented as the answer. The browser's `sciFactorial` correctly returns NaN → "Error".

## K. The two scientific evaluators are not the same calculator

Chat only: `%` (via `ast.Mod`), `factorial(n)` as a named call, `pi` spelled out, comma-stripped numbers.
App only: factorial on a bracketed sub-expression — `(2+3)!` gives 120 in the app but "Could not evaluate
that expression" in chat, because the Python pre-pass regex only rewrites `<digits>!`. And
`asin`/`acos`/`atan`/`exp`/`abs` are defined in `CalculatorsApp.jsx::SCI_FUNCS` but **unreachable in the
app** — the display is a `<div>`, not an input, and no keys exist for them (they work in chat).
`help.md` omits them; `guide.md` lists them. Also `2e5` cannot be entered in the app: the tokenizer reads
`2` then the constant `e`, leaving two values on the stack → "Error".

## L. The app's amortization schedule silently truncates at 1200 payments

`finishLoan` loops `i <= N && balance > 0.005 && i <= 1200`. A term over 100 years stops at row 1200 with
a balance still owed, and `summary.payments`/`totalPaid` are computed from the truncated rows — for a
150-year loan the app reports roughly $1.63M total paid where chat reports $2,437,645.89. No warning that
anything was cut off.

## M. Overflow in the app becomes an unexplained dash

`money()` returns `"—"` for any non-finite value and `round2(Infinity)` is `Infinity`, so a compound
calculation that overflows shows the label "Future value" over a dash with no error — unlike the
scientific tab, which refuses non-finite results.

## N. Currency is hard-coded to US dollars

`CalculatorsApp.jsx::money` uses `{ style: "currency", currency: "USD" }` and every `tools.py` string
prefixes `$`. `manifest.yaml` has `config: []`, so there is no setting. **For an open-source project with
installs outside the US, every money figure is mislabelled with no way to change it.**

## O. `tan(90)` in degrees answers `1.633123935319537e+16`

Both surfaces. The value is finite, so the "not a finite number" guard never fires and a 17-digit number
is presented as the tangent of a right angle. Low severity, but it is precisely the confidently-wrong
output the app exists to prevent.

## P. Documentation overclaims

`manifest.yaml`: "The finance calculators solve for whichever value you leave blank **and show a full
payoff schedule**" — the compound calculator has no schedule and neither chat tool returns one.
`manifest.yaml` and `help.md` both say calculation "runs entirely in your browser"; the three chat tools
run server-side in the Skipper process. The privacy claim still holds (nothing is written), but the
framing is wrong for the chat path — **and it is what makes finding A a server problem rather than a tab
problem.**

## Q. No statement of assumptions, and no "not advice" framing

Nothing in `tools.py`, `CalculatorsApp.jsx`, `help.md` or `guide.md` says the figures are nominal: no tax,
inflation, fees, or mortgage escrow/insurance; level payments; interest compounded exactly monthly.
`help.md` calls the loan tab "A loan or mortgage" and `manifest.yaml` lists `mortgage` as a keyword, yet a
reported "$1,580.17" payment carries no note that a real mortgage payment includes tax and insurance.
Output is arithmetic and never phrased as a recommendation, so it is **not** advice — but a household
comparing against a lender's quote cannot tell what was excluded.

## R. Sub-monthly loan terms round to zero payments

`N = round(yrs * 12)` in both surfaces; `years="0.04"` → `N = 0` → `ZeroDivisionError` → "Could not
compute — check the inputs.", which does not say the term was too short.

## S. Test bindings are real but thin

Both files named by the old spec exist and were carried forward; nothing else in the app has a test.
`test_tools_compound.py` asserts `assertNotIn("-", out)` and the strings it checks use an em dash
(U+2014), so it passes — but it would also pass on a genuine minus rendered as an en/em dash. The
Playwright spec's `openCompoundTab` clicks the "Compound interest" tab without first opening the
Calculators window, which may be why it is marked box-2-only; not run.
