// Auth-token handling for the SPA.
//
// Tokens are bearer tokens issued by /auth/login etc. (see app_platform/auth.py).
// installAuthFetch() wraps window.fetch so EVERY same-origin API/auth/ws call
// carries `Authorization: Bearer <token>` — without touching the ~60 scattered
// fetch call sites — and turns a 401 (token rejected/expired) into a clean
// logout + reload to the login screen.

const TOKEN_KEY = "skipperbot_token";

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
}

export function setToken(token) {
  try { if (token) localStorage.setItem(TOKEN_KEY, token); } catch { /* ignore */ }
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
}

let _installed = false;

export function installAuthFetch() {
  if (_installed || typeof window === "undefined" || !window.fetch) return;
  _installed = true;
  const orig = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    init = init ? { ...init } : {};
    let url = "";
    try { url = typeof input === "string" ? input : (input && input.url) || ""; } catch { /* */ }
    const sameOrigin = url.startsWith("/") || url.startsWith(window.location.origin);
    const token = getToken();
    if (token && sameOrigin) {
      const headers = new Headers(
        init.headers || (typeof input !== "string" && input && input.headers) || {}
      );
      if (!headers.has("Authorization")) headers.set("Authorization", `Bearer ${token}`);
      init.headers = headers;
    }
    const res = await orig(input, init);
    if (res.status === 401 && token && sameOrigin) {
      // Token rejected/expired — drop the session and bounce to login.
      clearToken();
      try { localStorage.removeItem("skipperbot_user"); } catch { /* */ }
      window.location.reload();
    }
    return res;
  };
}

// Optional JSON convenience (the shim already covers raw fetch). Returns parsed
// JSON or throws with the server's detail/error message.
export async function apiFetch(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
  return data;
}
