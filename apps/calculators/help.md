# Calculators

Three calculators in one app: a **scientific calculator**, a **compound-interest**
calculator, and a **loan / amortization** calculator.

## Overview

Open Calculators for quick math or to model money questions — how savings grow,
or what a loan costs. The two finance calculators are "solve for the blank": fill
in what you know, leave the one value you want blank, and it solves for it.
Everything runs in your browser.

You can also ask Skipper to do any of this in chat — handy when you don't want to
open the app.

## Screens

Tabs across the top switch between the three calculators:

### Scientific (default)
A standard scientific calculator, like your phone's or Windows in scientific
mode. Digits and `+ − × ÷`, parentheses, powers (`^`), square root, `ln`/`log`,
trig (`sin`/`cos`/`tan`), factorial (`x!`), and the constants `π` and `e`.
- **DEG/RAD** toggle controls how trig interprets angles.
- `C` clears, `⌫` deletes the last entry, `=` evaluates.

### Compound
Savings / investment growth. Fields: **Principal**, **Annual rate** (%),
**Compounds per year** (12 = monthly), **Years**, and **Future value**. Leave
**exactly one** of Principal / Rate / Years / Future value blank and it solves
for that one.

### Loan
A loan or mortgage. Fields: **Loan amount**, **Annual rate** (%), **Term
(years)**, and **Monthly payment** — leave one blank to solve for it. It also
shows the **monthly payment, total interest, total paid, and a full
month-by-month amortization schedule** (how each payment splits between interest
and principal).

## Example workflows

**Crunch a quick number**
- *In the app:* Scientific tab → type `1234 * 0.0825`, press `=`.
- *Through chat:* "what's 1234 times 8.25 percent?" or "calculate sqrt(2)\*10".

**How much will savings grow?**
- *In the app:* Compound tab → Principal `10000`, Annual rate `6`, Compounds per
  year `12`, Years `10`, leave **Future value** blank.
- *Through chat:* "if I invest $10,000 at 6% compounded monthly for 10 years,
  what's it worth?"

**What rate do I need?**
- *In the app:* Compound tab → fill Principal, Years, and Future value, leave
  **Annual rate** blank.
- *Through chat:* "what rate doubles my money in 8 years?"

**Monthly payment on a loan**
- *In the app:* Loan tab → Loan amount `250000`, Annual rate `6.5`, Term `30`,
  leave **Monthly payment** blank → solves the payment and shows the payoff
  schedule.
- *Through chat:* "payment on a $250k 30-year loan at 6.5%?"

**How long to pay it off?**
- *In the app:* Loan tab → fill amount, rate, and the payment you can afford,
  leave **Term** blank.
- *Through chat:* "how long to pay off $250k at $2,000/month at 6.5%?"

## Tips

- Trig results look off? Check the **DEG/RAD** toggle.
- The finance calculators solve for the single blank field — fill in everything
  else.
- The Loan amortization schedule shows how much of early payments goes to
  interest vs. principal.

## Your data

This app **stores nothing** — every calculation runs in your browser and isn't
saved, so there's nothing here in Skipper's memory to recall later.
