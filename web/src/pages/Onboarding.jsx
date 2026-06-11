// =============================================================================
// Onboarding wizard
// =============================================================================
// First-run setup, shown when `GET /api/onboarding/status` reports zero
// non-bot users in public.users. Four steps:
//
//   1. Welcome      — what Skipperbot is
//   2. OpenAI key   — `POST /api/onboarding/check-openai` calls the
//                     /v1/models endpoint to verify the key in `.env`
//   3. Primary user — username + display name + password + timezone
//   4. Done         — auto-login via the returned user
//
// The wizard intentionally lives at "/" (covering the root) until the
// first user exists. Once created, the same root URL flips to the
// LoginScreen.
//
// Styling matches LoginScreen — dark background, centered card.

import { useEffect, useMemo, useState } from "react";
import { setToken } from "../utils/api";
import {
  ArrowRight, ArrowLeft, Check, Loader2, AlertCircle, KeyRound, User as UserIcon, ShieldCheck,
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
      <div className="text-xs uppercase tracking-wider text-zinc-500">
        Step {index} of {total}
      </div>
      <h2 className="mt-1 text-2xl font-medium text-zinc-100">{title}</h2>
      {blurb && <p className="mt-2 text-sm text-zinc-400">{blurb}</p>}
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
      <ul className="space-y-3 text-sm text-zinc-300">
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
          <span>The next three steps verify your OpenAI key, create your admin account, and pick a timezone.</span>
        </li>
      </ul>
      <div className="mt-8 flex justify-end">
        <button
          className="inline-flex items-center gap-2 rounded bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
          onClick={onNext}
        >
          Get started <ArrowRight size={14} />
        </button>
      </div>
    </>
  );
}

function CheckOpenAI({ onNext, onBack }) {
  const [state, setState] = useState("idle"); // idle | checking | ok | error
  const [error, setError] = useState("");

  const check = async () => {
    setState("checking");
    setError("");
    try {
      const res = await fetch(`${API}/api/onboarding/check-openai`, { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        setState("ok");
      } else {
        setState("error");
        setError(data.error || "OpenAI check failed.");
      }
    } catch (e) {
      setState("error");
      setError(String(e.message || e));
    }
  };

  useEffect(() => { check(); }, []);  // eslint-disable-line

  return (
    <>
      <StepHeader
        index={2}
        total={4}
        title="OpenAI key"
        blurb="We're testing the key you set in .env against api.openai.com/v1/models."
      />
      <div className="mx-auto mt-2 inline-flex items-center gap-3 rounded bg-zinc-900 px-4 py-3 text-sm text-zinc-300 border border-zinc-800">
        <KeyRound size={16} className="text-zinc-500" />
        <code className="font-mono text-zinc-400">OPENAI_API_KEY</code>
      </div>
      <div className="mt-6 min-h-[3rem]">
        {state === "checking" && (
          <div className="flex items-center gap-2 text-zinc-400 text-sm">
            <Loader2 size={14} className="animate-spin" /> Calling OpenAI…
          </div>
        )}
        {state === "ok" && (
          <div className="flex items-center gap-2 text-emerald-400 text-sm">
            <ShieldCheck size={14} /> Key works.
          </div>
        )}
        <ErrorLine>{error}</ErrorLine>
        {state === "error" && (
          <div className="mt-5 rounded border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-zinc-300">
            <div className="mb-3 font-medium text-amber-200">How to fix</div>
            <ol className="list-decimal space-y-3 pl-5">
              <li>
                Get a working key at{" "}
                <a
                  href="https://platform.openai.com/api-keys"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-violet-400 hover:text-violet-300 underline"
                >
                  platform.openai.com/api-keys
                </a>
                . The account needs a payment method on file.
              </li>
              <li>
                Open <code className="font-mono text-zinc-200">.env</code> in
                the platform repo and replace the{" "}
                <code className="font-mono text-zinc-200">OPENAI_API_KEY=</code>{" "}
                line.
              </li>
              <li>
                Restart the agent so it picks up the new key, then come back
                here and click <span className="text-zinc-200">Retry</span>:
                <div className="mt-2 space-y-1.5 font-mono text-xs">
                  <div className="rounded bg-zinc-950 px-2 py-1.5 text-zinc-300">
                    <span className="text-zinc-500"># Docker path</span>
                    <br />
                    docker compose restart agent
                  </div>
                  <div className="rounded bg-zinc-950 px-2 py-1.5 text-zinc-300">
                    <span className="text-zinc-500"># Native path</span>
                    <br />
                    {"# Ctrl-C the running agent, then re-run ./start_agent.sh"}
                  </div>
                </div>
              </li>
            </ol>
          </div>
        )}
      </div>
      <div className="mt-8 flex items-center justify-between">
        <button
          className="inline-flex items-center gap-2 rounded text-sm text-zinc-400 hover:text-zinc-200"
          onClick={onBack}
        >
          <ArrowLeft size={14} /> Back
        </button>
        <div className="flex items-center gap-2">
          {state === "error" && (
            <button
              type="button"
              className="text-xs text-zinc-400 hover:text-zinc-200"
              onClick={check}
            >
              Retry
            </button>
          )}
          <button
            className="inline-flex items-center gap-2 rounded bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:bg-zinc-700 disabled:cursor-not-allowed"
            disabled={state !== "ok"}
            onClick={onNext}
          >
            Next <ArrowRight size={14} />
          </button>
        </div>
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
          <label className="text-sm text-zinc-300">Username</label>
          <input
            autoFocus
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 placeholder-zinc-500 font-mono text-sm"
            value={username}
            onChange={(e) => setUsername(e.target.value.toLowerCase().replace(/\s+/g, ""))}
            placeholder="alice"
            spellCheck={false}
          />
          <p className="mt-1 text-xs text-zinc-500">Lowercase letters / digits / underscores. This is your canonical id.</p>
        </div>
        <div>
          <label className="text-sm text-zinc-300">Display name</label>
          <input
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 placeholder-zinc-500 text-sm"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={username ? username.charAt(0).toUpperCase() + username.slice(1) : "Alice"}
          />
          <p className="mt-1 text-xs text-zinc-500">Shown in the UI. Defaults to your username with a capital first letter.</p>
        </div>
        <div>
          <label className="text-sm text-zinc-300">Password</label>
          <input
            type="password"
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            placeholder="at least 8 characters"
          />
          <p className="mt-1 text-xs text-zinc-500">Used to sign in to the web UI. Minimum 8 characters — you can change it later from Settings.</p>
        </div>
        <div>
          <label className="text-sm text-zinc-300">Timezone</label>
          <select
            className="mt-1 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 text-sm"
            value={tz}
            onChange={(e) => setTz(e.target.value)}
          >
            {tzOptions.map((z) => <option key={z} value={z}>{z}</option>)}
          </select>
          <p className="mt-1 text-xs text-zinc-500">
            Detected from your browser: <code className="font-mono text-zinc-400">{detected}</code>.
          </p>
        </div>
      </div>
      <ErrorLine>{error}</ErrorLine>
      <div className="mt-8 flex items-center justify-between">
        <button
          type="button"
          className="inline-flex items-center gap-2 rounded text-sm text-zinc-400 hover:text-zinc-200"
          onClick={onBack}
        >
          <ArrowLeft size={14} /> Back
        </button>
        <button
          type="submit"
          className="inline-flex items-center gap-2 rounded bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:bg-zinc-700 disabled:cursor-not-allowed"
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
      <div className="mt-4 rounded bg-zinc-900 border border-zinc-800 p-4 text-sm text-zinc-300">
        <div className="flex items-center justify-between">
          <span className="text-zinc-500">Username</span>
          <code className="font-mono text-zinc-200">{user.name}</code>
        </div>
        <div className="mt-2 flex items-center justify-between">
          <span className="text-zinc-500">Role</span>
          <span className="text-zinc-200">{user.role}</span>
        </div>
      </div>
      <div className="mt-8 flex justify-end">
        <button
          className="inline-flex items-center gap-2 rounded bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
          onClick={onContinue}
        >
          Open the desktop <ArrowRight size={14} />
        </button>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Top-level wizard
// ---------------------------------------------------------------------------

export default function Onboarding({ onComplete }) {
  // step: "welcome" | "openai" | "user" | "done"
  const [step, setStep] = useState("welcome");
  const [user, setUser] = useState(null);

  return (
    <div className="min-h-screen w-full flex items-center justify-center bg-zinc-950 p-4">
      <div className="w-full max-w-md rounded-xl border border-zinc-800 bg-zinc-900/40 p-8 shadow-2xl">
        <div className="mb-8 flex items-center justify-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-xl bg-violet-600 text-2xl font-bold text-white">
            S
          </div>
          <div className="text-lg font-medium text-zinc-200">Skipperbot</div>
        </div>
        {step === "welcome" && <Welcome onNext={() => setStep("openai")} />}
        {step === "openai" && (
          <CheckOpenAI
            onNext={() => setStep("user")}
            onBack={() => setStep("welcome")}
          />
        )}
        {step === "user" && (
          <CreatePrimaryUser
            onCreated={(u) => { setUser(u); setStep("done"); }}
            onBack={() => setStep("openai")}
          />
        )}
        {step === "done" && user && (
          <Done user={user} onContinue={() => onComplete(user)} />
        )}
      </div>
    </div>
  );
}
