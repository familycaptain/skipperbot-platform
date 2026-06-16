import { useState } from "react";
import { Calculator, TrendingUp, Landmark, AlertCircle, Info, FlaskConical } from "lucide-react";

// Shared edge-case messages for the compound-interest solver. Kept IDENTICAL to
// the strings in apps/calculators/tools.py (compound_interest) so the in-app UI,
// chat, and voice all read the same when the goal is already met.
const GOAL_MET_YEARS = "Your goal is below your current balance — you've already reached it, so no saving time is needed.";
const BELOW_PRINCIPAL_RATE = "Your future value is below your principal, so no positive rate would reach it.";
const ALREADY_AT_GOAL_NOTE = "Already at your goal.";

// ---------------------------------------------------------------------------
// Math helpers — pure functions, no UI.
// ---------------------------------------------------------------------------

const num = (v) => (v === "" || v == null ? null : Number(v));
const isNum = (v) => v != null && Number.isFinite(v);
const money = (v) =>
  isNum(v) ? v.toLocaleString(undefined, { style: "currency", currency: "USD" }) : "—";
const round2 = (v) => Math.round(v * 100) / 100;

// Compound interest: A = P(1 + r/n)^(n·t). Solve for the one blank of P/r/t/A
// (n = compounds per year is always required).
function solveCompound({ P, rate, n, t, A }) {
  const r = rate == null ? null : rate / 100;
  const blanks = [["P", P], ["rate", rate], ["t", t], ["A", A]].filter(([, v]) => v == null);
  if (n == null || n <= 0) return { error: "Compounds per year (n) is required and must be > 0." };
  if (blanks.length !== 1) return { error: "Leave exactly one of Principal / Rate / Years / Future value blank." };
  const field = blanks[0][0];
  const c = r == null ? null : r / n;

  try {
    if (field === "A") {
      const out = P * Math.pow(1 + c, n * t);
      return { field, value: round2(out), label: "Future value" };
    }
    if (field === "P") {
      const out = A / Math.pow(1 + c, n * t);
      return { field, value: round2(out), label: "Principal" };
    }
    if (field === "t") {
      if (A <= 0 || P <= 0 || c <= 0) return { error: "Need positive Principal, Future value, and Rate to solve for Years." };
      if (A < P) return { info: GOAL_MET_YEARS };
      if (A === P) return { field, value: 0, label: "Years", unit: "yr", note: ALREADY_AT_GOAL_NOTE };
      const out = Math.log(A / P) / (n * Math.log(1 + c));
      return { field, value: round2(out), label: "Years", unit: "yr" };
    }
    if (field === "rate") {
      if (P <= 0 || A <= 0 || t <= 0) return { error: "Need positive Principal, Future value, and Years to solve for Rate." };
      if (A < P) return { info: BELOW_PRINCIPAL_RATE };
      if (A === P) return { field, value: 0, label: "Annual rate", unit: "%", note: ALREADY_AT_GOAL_NOTE };
      const cc = Math.pow(A / P, 1 / (n * t)) - 1;
      return { field, value: round2(cc * n * 100), label: "Annual rate", unit: "%" };
    }
  } catch (e) {
    return { error: "Could not compute — check your inputs." };
  }
  return { error: "Nothing to solve." };
}

function payment(P, c, N) {
  if (c === 0) return P / N;
  return (P * c) / (1 - Math.pow(1 + c, -N));
}

// Amortized loan: solve for the one blank of Loan / Rate / Years / Monthly payment.
function solveLoan({ P, rate, years, M }) {
  const blanks = [["P", P], ["rate", rate], ["years", years], ["M", M]].filter(([, v]) => v == null);
  if (blanks.length !== 1) return { error: "Leave exactly one of Loan amount / Rate / Years / Monthly payment blank." };
  const field = blanks[0][0];
  const c = rate == null ? null : rate / 100 / 12;
  const N = years == null ? null : Math.round(years * 12);

  try {
    if (field === "M") {
      const out = payment(P, c, N);
      return finishLoan({ P, c, N, M: round2(out), solved: { field, label: "Monthly payment", value: round2(out) } });
    }
    if (field === "P") {
      const out = c === 0 ? M * N : (M * (1 - Math.pow(1 + c, -N))) / c;
      return finishLoan({ P: round2(out), c, N, M, solved: { field, label: "Loan amount", value: round2(out) } });
    }
    if (field === "years") {
      if (c <= 0) return { error: "Enter a rate above 0 to solve for the term." };
      if (M <= P * c) return { error: "Monthly payment is too low to ever pay off this loan (it must exceed the first month's interest)." };
      const nOut = -Math.log(1 - (P * c) / M) / Math.log(1 + c);
      return finishLoan({ P, c, N: Math.ceil(nOut), M, solved: { field, label: "Term", value: round2(nOut / 12), unit: "yr" } });
    }
    if (field === "rate") {
      // No closed form — bisection on monthly rate c.
      let lo = 1e-9, hi = 1; // 0%..100%/mo brackets the payment
      const target = M;
      if (M <= P / N) return { error: "Payment is below principal/term — implied rate is ~0% or negative." };
      for (let i = 0; i < 200; i++) {
        const mid = (lo + hi) / 2;
        const pay = payment(P, mid, N);
        if (pay > target) hi = mid; else lo = mid;
      }
      const cOut = (lo + hi) / 2;
      return finishLoan({ P, c: cOut, N, M, solved: { field, label: "Annual rate", value: round2(cOut * 12 * 100), unit: "%" } });
    }
  } catch (e) {
    return { error: "Could not compute — check your inputs." };
  }
  return { error: "Nothing to solve." };
}

function finishLoan({ P, c, N, M, solved }) {
  // Build the amortization schedule + totals.
  const rows = [];
  let balance = P;
  let totalInterest = 0;
  for (let i = 1; i <= N && balance > 0.005 && i <= 1200; i++) {
    const interest = balance * c;
    let principal = M - interest;
    if (principal > balance) principal = balance;
    balance -= principal;
    totalInterest += interest;
    rows.push({ i, payment: round2(principal + interest), principal: round2(principal), interest: round2(interest), balance: round2(Math.max(balance, 0)) });
  }
  return {
    solved,
    summary: {
      monthly: round2(M),
      payments: rows.length,
      totalPaid: round2(rows.reduce((s, r) => s + r.payment, 0)),
      totalInterest: round2(totalInterest),
      loan: round2(P),
    },
    rows,
  };
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

function Field({ label, value, onChange, placeholder, suffix }) {
  return (
    <label className="block">
      <span className="text-xs text-slate-400">{label}</span>
      <div className="mt-1 flex items-center gap-1">
        <input
          type="number"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder || "leave blank to solve"}
          className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 focus:border-sky-500 focus:outline-none"
        />
        {suffix && <span className="text-xs text-slate-500 w-6 shrink-0">{suffix}</span>}
      </div>
    </label>
  );
}

function CompoundTab() {
  const [f, setF] = useState({ P: "10000", rate: "6", n: "12", t: "10", A: "" });
  const [res, setRes] = useState(null);
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));
  const calc = () =>
    setRes(solveCompound({ P: num(f.P), rate: num(f.rate), n: num(f.n), t: num(f.t), A: num(f.A) }));

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">Leave exactly one of Principal / Rate / Years / Future value blank, then Calculate.</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Principal" value={f.P} onChange={set("P")} />
        <Field label="Annual rate" value={f.rate} onChange={set("rate")} suffix="%" />
        <Field label="Compounds / year" value={f.n} onChange={set("n")} placeholder="12" />
        <Field label="Years" value={f.t} onChange={set("t")} suffix="yr" />
        <Field label="Future value" value={f.A} onChange={set("A")} />
      </div>
      <button onClick={calc} className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium">Calculate</button>
      {res?.error && (
        <div className="flex items-start gap-2 text-rose-400 text-sm"><AlertCircle size={14} className="mt-0.5 shrink-0" /><span>{res.error}</span></div>
      )}
      {res?.info && (
        <div className="flex items-start gap-2 bg-sky-900/20 border border-sky-800 rounded-lg p-4 text-sky-200 text-sm"><Info size={14} className="mt-0.5 shrink-0" /><span>{res.info}</span></div>
      )}
      {res && !res.error && !res.info && (
        <div className="bg-slate-800/60 border border-slate-700 rounded-lg p-4">
          <div className="text-xs text-slate-400">{res.label}</div>
          <div className="text-2xl font-semibold text-sky-300">
            {res.unit ? `${res.value}${res.unit === "%" ? "%" : " " + res.unit}` : money(res.value)}
          </div>
          {res.note && <div className="text-xs text-slate-400 mt-1">{res.note}</div>}
        </div>
      )}
    </div>
  );
}

function LoanTab() {
  const [f, setF] = useState({ P: "250000", rate: "6.5", years: "30", M: "" });
  const [res, setRes] = useState(null);
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));
  const calc = () =>
    setRes(solveLoan({ P: num(f.P), rate: num(f.rate), years: num(f.years), M: num(f.M) }));

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">Leave exactly one of Loan amount / Rate / Years / Monthly payment blank, then Calculate.</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Loan amount" value={f.P} onChange={set("P")} />
        <Field label="Annual rate" value={f.rate} onChange={set("rate")} suffix="%" />
        <Field label="Term (years)" value={f.years} onChange={set("years")} suffix="yr" />
        <Field label="Monthly payment" value={f.M} onChange={set("M")} />
      </div>
      <button onClick={calc} className="px-4 py-2 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium">Calculate</button>
      {res?.error && (
        <div className="flex items-start gap-2 text-rose-400 text-sm"><AlertCircle size={14} className="mt-0.5 shrink-0" /><span>{res.error}</span></div>
      )}
      {res && !res.error && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label={res.solved.label} value={res.solved.unit ? `${res.solved.value}${res.solved.unit === "%" ? "%" : " " + res.solved.unit}` : money(res.solved.value)} highlight />
            <Stat label="Monthly payment" value={money(res.summary.monthly)} />
            <Stat label="Total interest" value={money(res.summary.totalInterest)} />
            <Stat label="Total paid" value={money(res.summary.totalPaid)} />
          </div>
          <div className="border border-slate-700 rounded-lg overflow-hidden">
            <div className="px-3 py-2 text-xs text-slate-400 bg-slate-800/60 border-b border-slate-700">
              Amortization schedule ({res.summary.payments} payments)
            </div>
            <div className="max-h-72 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-500 sticky top-0 bg-slate-900">
                  <tr><th className="text-left px-3 py-1">#</th><th className="text-right px-3 py-1">Payment</th><th className="text-right px-3 py-1">Principal</th><th className="text-right px-3 py-1">Interest</th><th className="text-right px-3 py-1">Balance</th></tr>
                </thead>
                <tbody>
                  {res.rows.map((r) => (
                    <tr key={r.i} className="border-t border-slate-800 text-slate-300">
                      <td className="px-3 py-1">{r.i}</td>
                      <td className="text-right px-3 py-1">{money(r.payment)}</td>
                      <td className="text-right px-3 py-1">{money(r.principal)}</td>
                      <td className="text-right px-3 py-1">{money(r.interest)}</td>
                      <td className="text-right px-3 py-1">{money(r.balance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value, highlight }) {
  return (
    <div className={`rounded-lg border p-3 ${highlight ? "border-emerald-700 bg-emerald-900/20" : "border-slate-700 bg-slate-800/60"}`}>
      <div className="text-[10px] text-slate-400">{label}</div>
      <div className={`text-sm font-semibold ${highlight ? "text-emerald-300" : "text-slate-200"}`}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Scientific calculator — tokenizer + shunting-yard evaluator (no eval()).
// ---------------------------------------------------------------------------

const SCI_FUNCS = {
  sin: (x, deg) => Math.sin(deg ? (x * Math.PI) / 180 : x),
  cos: (x, deg) => Math.cos(deg ? (x * Math.PI) / 180 : x),
  tan: (x, deg) => Math.tan(deg ? (x * Math.PI) / 180 : x),
  asin: (x, deg) => (deg ? (Math.asin(x) * 180) / Math.PI : Math.asin(x)),
  acos: (x, deg) => (deg ? (Math.acos(x) * 180) / Math.PI : Math.acos(x)),
  atan: (x, deg) => (deg ? (Math.atan(x) * 180) / Math.PI : Math.atan(x)),
  ln: (x) => Math.log(x),
  log: (x) => Math.log10(x),
  sqrt: (x) => Math.sqrt(x),
  abs: (x) => Math.abs(x),
  exp: (x) => Math.exp(x),
};
const SCI_OPS = {
  "+": { p: 2, f: (a, b) => a + b },
  "-": { p: 2, f: (a, b) => a - b },
  "*": { p: 3, f: (a, b) => a * b },
  "/": { p: 3, f: (a, b) => a / b },
  "^": { p: 4, right: true, f: (a, b) => Math.pow(a, b) },
};
function sciFactorial(n) {
  if (n < 0 || !Number.isInteger(n)) return NaN;
  let r = 1;
  for (let k = 2; k <= n; k++) r *= k;
  return r;
}
function sciTokenize(expr) {
  const s = expr.replace(/×/g, "*").replace(/÷/g, "/").replace(/−/g, "-").replace(/π/g, "PI").replace(/√/g, "sqrt");
  const tokens = [];
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === " ") { i++; continue; }
    if (/[0-9.]/.test(ch)) {
      let n = ""; while (i < s.length && /[0-9.]/.test(s[i])) n += s[i++];
      tokens.push({ t: "num", v: parseFloat(n) }); continue;
    }
    if (/[a-zA-Z]/.test(ch)) {
      let name = ""; while (i < s.length && /[a-zA-Z0-9]/.test(s[i])) name += s[i++];
      if (name === "PI") tokens.push({ t: "num", v: Math.PI });
      else if (name === "e") tokens.push({ t: "num", v: Math.E });
      else if (SCI_FUNCS[name]) tokens.push({ t: "func", v: name });
      else throw new Error("unknown " + name);
      continue;
    }
    if (ch === "!") { tokens.push({ t: "fact" }); i++; continue; }
    if (ch === "(") { tokens.push({ t: "lp" }); i++; continue; }
    if (ch === ")") { tokens.push({ t: "rp" }); i++; continue; }
    if (SCI_OPS[ch]) { tokens.push({ t: "op", v: ch }); i++; continue; }
    throw new Error("bad char " + ch);
  }
  return tokens;
}
function sciToRPN(tokens) {
  const out = [], ops = [];
  let prev = null;
  for (const tk of tokens) {
    if (tk.t === "num") out.push(tk);
    else if (tk.t === "func") ops.push(tk);
    else if (tk.t === "fact") out.push(tk);
    else if (tk.t === "op") {
      const unary = tk.v === "-" && (prev === null || prev.t === "op" || prev.t === "lp" || prev.t === "func");
      if (unary) { ops.push({ t: "uneg" }); }
      else {
        const o1 = SCI_OPS[tk.v];
        while (ops.length) {
          const top = ops[ops.length - 1];
          if (top.t === "func" || top.t === "uneg") { out.push(ops.pop()); continue; }
          if (top.t === "op") {
            const o2 = SCI_OPS[top.v];
            if (o1.right ? o1.p < o2.p : o1.p <= o2.p) { out.push(ops.pop()); continue; }
          }
          break;
        }
        ops.push(tk);
      }
    } else if (tk.t === "lp") ops.push(tk);
    else if (tk.t === "rp") {
      while (ops.length && ops[ops.length - 1].t !== "lp") out.push(ops.pop());
      if (!ops.length) throw new Error("mismatched )");
      ops.pop();
      if (ops.length && ops[ops.length - 1].t === "func") out.push(ops.pop());
    }
    prev = tk;
  }
  while (ops.length) {
    const top = ops.pop();
    if (top.t === "lp") throw new Error("mismatched (");
    out.push(top);
  }
  return out;
}
function sciEval(expr, deg) {
  const st = [];
  for (const tk of sciToRPN(sciTokenize(expr))) {
    if (tk.t === "num") st.push(tk.v);
    else if (tk.t === "uneg") st.push(-st.pop());
    else if (tk.t === "fact") st.push(sciFactorial(st.pop()));
    else if (tk.t === "func") st.push(SCI_FUNCS[tk.v](st.pop(), deg));
    else if (tk.t === "op") { const b = st.pop(), a = st.pop(); st.push(SCI_OPS[tk.v].f(a, b)); }
  }
  if (st.length !== 1) throw new Error("invalid");
  return st[0];
}

function ScientificTab() {
  const [expr, setExpr] = useState("");
  const [deg, setDeg] = useState(true);
  const [err, setErr] = useState(false);
  const push = (s) => { setErr(false); setExpr((e) => e + s); };
  const clear = () => { setExpr(""); setErr(false); };
  const back = () => { setErr(false); setExpr((e) => e.slice(0, -1)); };
  const equals = () => {
    if (!expr.trim()) return;
    try {
      const v = sciEval(expr, deg);
      if (!Number.isFinite(v)) throw new Error("math");
      setExpr(String(Math.round(v * 1e12) / 1e12));
    } catch { setErr(true); }
  };

  // [label, onClick, className]
  const C = "bg-slate-800 hover:bg-slate-700 text-slate-200";
  const Fn = "bg-slate-700/70 hover:bg-slate-600 text-sky-300 text-xs";
  const Op = "bg-slate-700 hover:bg-slate-600 text-amber-300";
  const Eq = "bg-sky-600 hover:bg-sky-500 text-white";
  const keys = [
    [deg ? "DEG" : "RAD", () => setDeg((d) => !d), "bg-slate-700 hover:bg-slate-600 text-emerald-300 text-xs"],
    ["(", () => push("("), Fn], [")", () => push(")"), Fn], ["C", clear, "bg-rose-800/70 hover:bg-rose-700 text-rose-200"], ["⌫", back, C],
    ["sin", () => push("sin("), Fn], ["cos", () => push("cos("), Fn], ["tan", () => push("tan("), Fn], ["^", () => push("^"), Op], ["√", () => push("sqrt("), Fn],
    ["ln", () => push("ln("), Fn], ["log", () => push("log("), Fn], ["7", () => push("7"), C], ["8", () => push("8"), C], ["9", () => push("9"), C],
    ["π", () => push("π"), Fn], ["e", () => push("e"), Fn], ["4", () => push("4"), C], ["5", () => push("5"), C], ["6", () => push("6"), C],
    ["x!", () => push("!"), Fn], ["÷", () => push("÷"), Op], ["1", () => push("1"), C], ["2", () => push("2"), C], ["3", () => push("3"), C],
    ["×", () => push("×"), Op], ["−", () => push("-"), Op], ["0", () => push("0"), C], [".", () => push("."), C], ["+", () => push("+"), Op],
  ];

  return (
    <div className="max-w-xs">
      <div className={`rounded-lg border px-3 py-3 mb-3 text-right font-mono break-all min-h-[3.5rem] ${err ? "border-rose-700 bg-rose-900/20" : "border-slate-700 bg-slate-900"}`}>
        <div className="text-lg text-slate-100">{expr || "0"}</div>
        {err && <div className="text-xs text-rose-400">Error</div>}
      </div>
      <div className="grid grid-cols-5 gap-1.5">
        {keys.map(([label, onClick, cls], idx) => (
          <button key={idx} onClick={onClick} className={`h-10 rounded text-sm font-medium ${cls}`}>{label}</button>
        ))}
        <button onClick={equals} className={`col-span-5 h-10 rounded text-sm font-semibold ${Eq}`}>=</button>
      </div>
      <p className="text-[10px] text-slate-500 mt-2">Trig uses {deg ? "degrees" : "radians"} — tap DEG/RAD to switch. Supports + − × ÷ ^, parentheses, π, e, √, ln, log, factorial (x!).</p>
    </div>
  );
}

export default function CalculatorsApp() {
  const [tab, setTab] = useState("scientific");
  const tabBtn = (id, label, Icon, activeCls) => (
    <button onClick={() => setTab(id)} className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-sm ${tab === id ? activeCls : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}>
      <Icon size={14} /> {label}
    </button>
  );
  return (
    <div className="h-full overflow-y-auto p-4 max-w-2xl">
      <div className="flex items-center gap-2 mb-4">
        <Calculator size={18} className="text-sky-400" />
        <h1 className="text-base font-bold text-slate-200">Calculators</h1>
      </div>
      <div className="flex flex-wrap gap-1 mb-4">
        {tabBtn("scientific", "Scientific", FlaskConical, "bg-slate-600 text-white")}
        {tabBtn("compound", "Compound interest", TrendingUp, "bg-sky-700 text-white")}
        {tabBtn("loan", "Loan / amortization", Landmark, "bg-emerald-700 text-white")}
      </div>
      {tab === "scientific" && <ScientificTab />}
      {tab === "compound" && <CompoundTab />}
      {tab === "loan" && <LoanTab />}
    </div>
  );
}
