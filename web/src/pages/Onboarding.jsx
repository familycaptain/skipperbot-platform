// =============================================================================
// Onboarding wizard
// =============================================================================
// First-run setup, shown when `GET /api/onboarding/status` reports zero
// non-bot users in public.users. Four steps:
//
//   1. Welcome      — what Skipperbot is
//   2. Models       — pick a provider + model per tier (Smart/Fast/Text-encoding) and
//                     validate each with a real round-trip (MODEL_FLEXIBILITY #44)
//   3. Primary user — username + display name + password + timezone
//   4. Done         — auto-login via the returned user
//
// The wizard intentionally lives at "/" (covering the root) until the
// first user exists. Once created, the same root URL flips to the
// LoginScreen.
//
// Styling matches LoginScreen — dark background, centered card.

import { useEffect, useMemo, useRef, useState } from "react";
import { setToken } from "../utils/api";
import ModelConfig from "../components/ModelConfig";
import {
  ArrowRight, ArrowLeft, Check, Loader2, AlertCircle, User as UserIcon,
} from "lucide-react";

const API = "";

function detectTimezone() {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz && typeof tz === "string" ? tz : "Etc/UTC";
  } catch {
    return "Etc/UTC";
  }
}

// A short list of common IANA zones for the dropdown. Users with a
// different zone can keep the browser-detected default (always
// preselected in the input).
const COMMON_TIMEZONES = [
  "Etc/UTC",
  "America/New_York",
  "America/Chicago", // noqa: family-name — generic US-zone dropdown option, not a household locator
  "America/Denver",
  "America/Los_Angeles",
  "America/Anchorage",
  "America/Phoenix",
  "America/Halifax",
  "America/Sao_Paulo",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Madrid",
  "Europe/Stockholm",
  "Europe/Istanbul",
  "Africa/Johannesburg",
  "Asia/Jerusalem",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

function ErrorLine({ children }) {
  if (!children) return null;
  return (
    <div className="mt-4 flex items-start gap-2 text-rose-400 text-sm">
      <AlertCircle size={14} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function StepHeader({ index, total, title, blurb }) {
  return (
    <div className="mb-6 text-center">
      <div className="text-xs uppercase tracking-wider text-faint">
        Step {index} of {total}
      </div>
      <h2 className="mt-1 text-2xl font-medium text-default">{title}</h2>
      {blurb && <p className="mt-2 text-sm text-muted">{blurb}</p>}
    </div>
  );
}

function Welcome({ onNext }) {
  return (
    <>
      <StepHeader
        index={1}
        total={4}
        title="Welcome to Skipperbot"
        blurb="An agentic app platform for your family."
      />
      <ul className="space-y-3 text-sm text-default">
        <li className="flex items-start gap-3">
          <Check size={16} className="mt-0.5 text-emerald-400 shrink-0" />
          <span>Postgres is up, the agent is running, every required app loaded successfully.</span>
        </li>
        <li className="flex items-start gap-3">
          <Check size={16} className="mt-0.5 text-emerald-400 shrink-0" />
          <span>Skipperbot does not phone home — no telemetry, no usage reporting, ever.</span>
        </li>
        <li className="flex items-start gap-3">
          <Check size={16} className="mt-0.5 text-emerald-400 shrink-0" />
          <span>The next three steps pick your AI models, create your admin account, and set a timezone.</span>
        </li>
      </ul>
      <div className="mt-8 flex justify-end">
        <button
          className="inline-flex items-center gap-2 rounded btn-primary px-4 py-2 text-sm font-medium"
          onClick={onNext}
        >
          Get started <ArrowRight size={14} />
        </button>
      </div>
    </>
  );
}


function CreatePrimaryUser({ onCreated, onBack }) {
  const detected = useMemo(detectTimezone, []);
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [tz, setTz] = useState(detected);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Synchronous in-flight guard against rapid double-taps (issue #36).
  const inFlightRef = useRef(false);

  // Surface the browser-detected zone in the dropdown even if it's
  // not in COMMON_TIMEZONES.
  const tzOptions = useMemo(() => {
    const base = [...COMMON_TIMEZONES];
    if (!base.includes(detected)) base.unshift(detected);
    return base;
  }, [detected]);

  const usernameOk = /^[a-z][a-z0-9_]{1,30}$/.test(username);
  const passwordOk = password.length >= 8;

  const submit = async (e) => {
    e?.preventDefault();
    setError("");
    if (!usernameOk) {
      setError("Username must be 2–31 lowercase letters / digits / underscores, starting with a letter.");
      return;
    }
    if (!passwordOk) {
      setError("A password is required and must be at least 8 characters.");
      return;
    }
    // In-flight guard set only after the synchronous validation early-returns,
    // so an invalid tap never locks the form (the finally below always clears it).
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/onboarding/create-user`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          display_name: displayName,
          password,
          timezone: tz,
        }),
      });
      const data = await res.json();
      if (!data.ok) {
        setError(data.error || "Could not create user.");
        return;
      }
      setToken(data.token);
      onCreated(data.user);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
      inFlightRef.current = false;
    }
  };

  // Explicit Enter handler for the text inputs: this multi-input form has no
  // submit control after the button became type="button" (issue #36), so browser
  // implicit submission no longer fires. Skip while IME-composing.
  const onInputKeyDown = (e) => {
    if (e.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter") {
      e.preventDefault();
      submit();
    }
  };

  return (
    <form onSubmit={submit}>
      <StepHeader
        index={3}
        total={4}
        title="Your admin account"
        blurb="The first user is the admin — you can add household members from the chat later."
      />
      <div className="space-y-4">
        <div>
          <label className="text-sm text-default">Username</label>
          <input
            autoFocus
            name="username"
            autoComplete="username"
            className="mt-1 w-full rounded input px-3 py-2 font-mono text-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/\s+/g, ""))}
            onKeyDown={onInputKeyDown}
            placeholder="alice"
            spellCheck={false}
          />
          <p className="mt-1 text-xs text-faint">Lowercase letters / digits / underscores. This is your canonical id.</p>
        </div>
        <div>
          <label className="text-sm text-default">Display name</label>
          <input
            name="display_name"
            autoComplete="name"
            className="mt-1 w-full rounded input px-3 py-2 text-sm"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            onKeyDown={onInputKeyDown}
            placeholder={username ? username.charAt(0).toUpperCase() + username.slice(1) : "Alice"}
          />
          <p className="mt-1 text-xs text-faint">Shown in the UI. Defaults to your username with a capital first letter.</p>
        </div>
        <div>
          <label className="text-sm text-default">Password</label>
          <input
            type="password"
            name="password"
            autoComplete="new-password"
            className="mt-1 w-full rounded input px-3 py-2 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={onInputKeyDown}
            required
            minLength={8}
            placeholder="at least 8 characters"
          />
          <p className="mt-1 text-xs text-faint">Used to sign in to the web UI. Minimum 8 characters — you can change it later from Settings.</p>
        </div>
        <div>
          <label className="text-sm text-default">Timezone</label>
          <select
            className="mt-1 w-full rounded input px-3 py-2 text-sm"
            value={tz}
            onChange={(e) => setTz(e.target.value)}
          >
            {tzOptions.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
          <p className="mt-1 text-xs text-faint">
            Detected from your browser: <code className="font-mono text-muted">{detected}</code>.
          </p>
        </div>
      </div>
      <ErrorLine>{error}</ErrorLine>
      <div className="mt-8 flex items-center justify-between">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded text-sm text-muted hover:text-default"
          onClick={onBack}
        >
          <ArrowLeft size={14} /> Back
        </button>
        {/* Controlled button (type=button + onClick), never a native submit button,
            so a native form submit can never fire a full-page reload under load
            (issue #36). Enter is handled by onInputKeyDown on the text inputs;
            <form onSubmit> kept as a backstop. */}
        <button
          type="button"
          onClick={submit}
          className="inline-flex items-center gap-2 rounded btn-primary px-4 py-2 text-sm font-medium disabled:cursor-not-allowed"
          disabled={saving || !usernameOk || !passwordOk}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <UserIcon size={14} />}
          {saving ? "Creating…" : "Create account"}
        </button>
      </div>
    </form>
  );
}

function Done({ user, onContinue }) {
  return (
    <>
      <StepHeader
        index={4}
        total={4}
        title="You're set up"
        blurb={`Welcome, ${user.display_name}. Skipperbot is ready.`}
      />
      <div className="mt-4 rounded surface-card border border-subtle p-4 text-sm text-default">
        <div className="flex items-center justify-between">
          <span className="text-faint">Username</span>
          <code className="font-mono text-default">{user.name}</code>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <span className="text-faint">Role</span>
          <span className="text-default">{user.role}</span>
        </div>
      </div>
      <div className="mt-8 flex justify-end">
        <button
          className="inline-flex items-center gap-2 rounded btn-primary px-4 py-2 text-sm font-medium"
          onClick={onContinue}
        >
          Open the desktop <ArrowRight size={14} />
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Model selection step (MODEL_FLEXIBILITY #44) — replaces the OpenAI-key-only step.
// ---------------------------------------------------------------------------

function ModelStep({ onNext, onBack }) {
  const [valid, setValid] = useState(false);
  const [tiersState, setTiersState] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const proceed = async () => {
    setError("");
    setSaving(true);
    try {
      const tiers = {};
      for (const k of ["smart", "fast", "embedding"]) {
        const t = tiersState[k] || {};
        tiers[k] = { connector: t.connector, model: t.model, key: t.key || null };
      }
      const res = await fetch(`${API}/api/onboarding/save-models`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tiers }),
      });
      const data = await res.json();
      if (!data.ok) {
        setError(data.error || "Could not save your model selections.");
        return;
      }
      onNext();
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <StepHeader
        index={2}
        total={4}
        title="Choose your models"
        blurb="Pick a provider + model for each tier and validate it. Smart & Fast can be changed later in Settings."
      />
      <div className="mt-4">
        <ModelConfig
          mode="onboarding"
          onChange={({ tiers, allValid }) => { setTiersState(tiers); setValid(allValid); }}
        />
      </div>
      <ErrorLine>{error}</ErrorLine>
      <div className="mt-6 flex items-center justify-between">
        <button
          className="inline-flex items-center gap-2 rounded text-sm text-muted hover:text-default"
          onClick={onBack}
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          className="inline-flex items-center gap-2 rounded btn-primary px-4 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50"
          disabled={!valid || saving}
          onClick={proceed}
        >
          {saving ? "Saving…" : "Next"} <ArrowRight size={14} />
        </button>
      </div>
      {!valid && (
        <p className="mt-2 text-right text-xs text-faint">Validate all three tiers to continue.</p>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Top-level wizard
// ---------------------------------------------------------------------------

export default function Onboarding({ onComplete }) {
  // step: "welcome" | "models" | "user" | "done"
  const [step, setStep] = useState("welcome");
  const [user, setUser] = useState(null);

  return (
    <div className="min-h-screen w-full flex items-center justify-center surface-page p-4">
      <div className="w-full max-w-md rounded-xl border border-subtle surface-card p-8 shadow-2xl">
        <div className="mb-8 flex items-center justify-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-xl bg-[var(--ds-accent)] text-2xl font-bold text-on-accent">
            S
          </div>
          <div className="text-lg font-medium text-default">Skipperbot</div>
        </div>
        {step === "welcome" && <Welcome onNext={() => setStep("models")} />}
        {step === "models" && (
          <ModelStep
            onNext={() => setStep("user")}
            onBack={() => setStep("welcome")}
          />
        )}
        {step === "user" && (
          <CreatePrimaryUser
            onCreated={(u) => { setUser(u); setStep("done"); }}
            onBack={() => setStep("models")}
          />
        )}
        {step === "done" && user && (
          <Done user={user} onContinue={() => onComplete(user)} />
        )}
      </div>
    </div>
  );
}
