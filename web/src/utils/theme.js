// Light/dark theme handling (issue #26).
//
// Dark is the default; light is opt-in via the header toggle and persisted
// per-browser in localStorage. The visual switch is done in index.css by
// re-pointing Tailwind's neutral color variables under html[data-theme="light"]
// (variable inversion) — this module only drives WHICH theme is active and
// keeps it in sync (document attribute, <meta theme-color>, localStorage).
//
// Pure helpers (resolveInitialTheme / nextTheme) are exported for testing.

import { useState, useEffect, useCallback } from "react";

const THEME_KEY = "skipperbot_theme";
const THEME_COLOR = { dark: "#0f172a", light: "#f1f5f9" };

// Clamp any stored/incoming value to the known set. Anything that is not
// exactly "light" (missing, corrupted, legacy) resolves to the dark default,
// so the load path is deterministic and never throws.
export function resolveInitialTheme(stored) {
  return stored === "light" ? "light" : "dark";
}

export function nextTheme(current) {
  return current === "light" ? "dark" : "light";
}

export function getStoredTheme() {
  try {
    return localStorage.getItem(THEME_KEY) || "";
  } catch {
    return "";
  }
}

// Apply a theme to the document: set <html data-theme>, sync the mobile browser
// chrome color, and persist. Returns the clamped theme actually applied.
export function applyTheme(theme) {
  const t = resolveInitialTheme(theme);
  try {
    document.documentElement.setAttribute("data-theme", t);
  } catch { /* ignore */ }
  try {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", THEME_COLOR[t]);
  } catch { /* ignore */ }
  try {
    localStorage.setItem(THEME_KEY, t);
  } catch { /* ignore */ }
  return t;
}

// React hook: current theme + a toggle. The effect re-applies on change so the
// document attribute, meta color, and storage stay in lockstep with state.
export function useTheme() {
  const [theme, setTheme] = useState(() => resolveInitialTheme(getStoredTheme()));
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => nextTheme(t)), []);
  return { theme, toggle, setTheme };
}
