import { useState, useRef, useEffect } from "react";
import { setToken } from "../utils/api";

/**
 * Login screen with two-step authentication.
 *
 * Flow:
 *  Step 1: Enter username → "Continue"
 *  Step 2: User has password → show password field → "Sign In"
 *  On success → onLogin({ name, display_name, role })
 *
 * There is intentionally no self-service "set a password" path: every account is
 * created with a password, so a passwordless account is an admin-recovery case
 * (Settings → Members → reset password), not something any visitor can claim.
 */

const API_BASE = "";  // same origin (Vite proxy in dev)

export default function LoginScreen({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // "name" = step 1 (enter username)
  // "password" = step 2 (enter existing password)
  const [step, setStep] = useState("name");
  const [userInfo, setUserInfo] = useState(null); // { name, display_name }

  const passwordRef = useRef(null);

  // Auto-focus password field when step changes
  useEffect(() => {
    if (step === "password" && passwordRef.current) {
      passwordRef.current.focus();
    }
  }, [step]);

  async function handleCheckUser(e) {
    e.preventDefault();
    setError("");
    const name = username.trim();
    if (!name) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: name }),
      });
      const data = await res.json();

      if (data.error === "no_password") {
        // Accounts are always created with a password (onboarding + admin "Add
        // member" both require one), so there is no self-service claim. A
        // passwordless account is recovered by an admin setting a temporary one.
        setError("This account has no password yet. Ask an admin to set a temporary password for you (Settings → Members → reset password).");
      } else if (data.error === "password_required") {
        setUserInfo({ name: data.name, display_name: data.display_name });
        setStep("password");
      } else if (data.error === "Unknown user.") {
        setError("No account found with that name.");
      } else {
        setError(data.error || "Something went wrong.");
      }
    } catch {
      setError("Cannot reach server.");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    if (!password) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: userInfo.name, password }),
      });
      const data = await res.json();

      if (data.ok) {
        setToken(data.token);
        onLogin(data.user);
      } else {
        setError(data.error || "Login failed.");
      }
    } catch {
      setError("Cannot reach server.");
    } finally {
      setLoading(false);
    }
  }

  function handleBack() {
    setStep("name");
    setPassword("");
    setError("");
    setUserInfo(null);
  }

  const onSubmit = step === "name" ? handleCheckUser : handleLogin;

  const subtitle =
    step === "password"
      ? `Welcome back, ${userInfo?.display_name}!`
      : "Sign in to start chatting";

  const buttonLabel = step === "name" ? "Continue" : "Sign In";

  const buttonDisabled =
    loading ||
    (step === "name" && !username.trim()) ||
    (step === "password" && !password);

  return (
    <div className="flex items-center justify-center h-full bg-slate-950">
      <form
        onSubmit={onSubmit}
        className="flex flex-col items-center gap-5 px-8 py-10 max-w-sm w-full"
      >
        {/* Avatar */}
        <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white text-4xl font-bold shadow-lg shadow-indigo-500/20">
          S
        </div>

        <div className="text-center">
          <h1 className="text-xl font-semibold text-white">SkipperBot</h1>
          <p className="text-sm text-slate-400 mt-1">{subtitle}</p>
        </div>

        {/* Step 1: Username */}
        {step === "name" && (
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            autoFocus
            autoComplete="username"
            className="w-full px-4 py-3 rounded-xl bg-slate-800 text-sm text-white placeholder-slate-500 outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
        )}

        {/* Step 2: Enter existing password */}
        {step === "password" && (
          <input
            ref={passwordRef}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            className="w-full px-4 py-3 rounded-xl bg-slate-800 text-sm text-white placeholder-slate-500 outline-none focus:ring-2 focus:ring-indigo-500/50"
          />
        )}

        {error && (
          <p className="text-sm text-red-400 text-center">{error}</p>
        )}

        <button
          type="submit"
          disabled={buttonDisabled}
          className="w-full py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 text-white font-semibold text-sm transition-colors"
        >
          {loading ? "..." : buttonLabel}
        </button>

        {step !== "name" && (
          <button
            type="button"
            onClick={handleBack}
            className="text-sm text-slate-500 hover:text-slate-300 transition-colors"
          >
            Back
          </button>
        )}

        <a
          href="https://skipperbot.com"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-slate-500 hover:text-indigo-400 transition-colors mt-2"
        >
          What is Skipper? →
        </a>
      </form>
    </div>
  );
}
