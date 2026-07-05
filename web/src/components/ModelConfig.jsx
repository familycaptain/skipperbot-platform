// =============================================================================
// ModelConfig — shared 3-tier model picker (MODEL_FLEXIBILITY #44)
// =============================================================================
// Used by BOTH the first-run onboarding model step and Settings > Models. Renders three
// dropdowns (Smart / Fast / Text-encoding) listing every installed connector's baked models as
// "Provider / model" with (default) markers and an experimental tag for not-live-verified
// connectors, plus a per-tier API-key box shown ONLY when the selected connector requires a key,
// and a per-tier Validate that does a REAL round-trip (POST /api/onboarding/validate-tier).
//
// Props:
//   mode            "onboarding" | "settings"
//   embeddingLocked when true, the embedding dropdown is read-only (locked after first setup)
//   onChange({tiers, allValid})  reports the current selections + whether all required tiers
//                                validated (the parent gates Finish/Save on allValid)
//
// Style: plain Tailwind utilities only (avoid multi-value-var box-shadow / :not() chains that
// trip Lightning CSS in the web build).

import { useEffect, useMemo, useState } from "react";
import { Loader2, ShieldCheck, AlertCircle, Lock } from "lucide-react";

const API = "";

const TIERS = [
  { key: "smart", label: "Smart", kind: "chat", blurb: "Your main reasoning model." },
  { key: "fast", label: "Fast", kind: "chat", blurb: "A cheaper/faster model for light work." },
  { key: "embedding", label: "Text-encoding", kind: "embedding",
    blurb: "Turns text into vectors for search & memory." },
];

const optValue = (r) => `${r.connector}::${r.model}`;
// Tier-aware: a row is a "(default)" for THIS tier iff tierKey ∈ its default_tiers, so the Smart
// dropdown marks the smart default, Fast the FAST default, Text-encoding its embedding default.
const isTierDefault = (r, tierKey) =>
  Array.isArray(r.default_tiers) && r.default_tiers.includes(tierKey);
const optLabel = (r, tierKey) =>
  `${r.provider_display} / ${r.model}` +
  (isTierDefault(r, tierKey) ? " (default)" : "") +
  (r.verified ? "" : " — experimental");

function pickDefault(rows, tierKey) {
  if (!rows || !rows.length) return null;
  // Happy path: prefer a verified connector's tier default, then any tier default, then row 0.
  return (
    rows.find((r) => r.verified && isTierDefault(r, tierKey)) ||
    rows.find((r) => isTierDefault(r, tierKey)) ||
    rows[0]
  );
}

export default function ModelConfig({ mode = "onboarding", embeddingLocked = false, onChange }) {
  const [available, setAvailable] = useState({ chat: [], embedding: [] });
  const [loadErr, setLoadErr] = useState("");
  // per-tier: { connector, model, key, status: idle|validating|ok|error, error }
  const [tiers, setTiers] = useState({});

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const res = await fetch(`${API}/api/onboarding/models`);
        const data = await res.json();
        if (!alive) return;
        setAvailable({ chat: data.chat || [], embedding: data.embedding || [] });
        // seed selections from current (settings) or the happy-path defaults (onboarding)
        const seed = {};
        for (const t of TIERS) {
          const rows = (t.kind === "chat" ? data.chat : data.embedding) || [];
          const cur = (data.current || {})[t.key] || {};
          const chosen =
            (cur.connector && cur.model
              ? rows.find((r) => r.connector === cur.connector && r.model === cur.model)
              : null) || pickDefault(rows, t.key);
          seed[t.key] = {
            connector: chosen ? chosen.connector : "",
            model: chosen ? chosen.model : "",
            key: "",
            status: "idle",
            error: "",
          };
        }
        setTiers(seed);
      } catch (e) {
        if (alive) setLoadErr(String(e.message || e));
      }
    })();
    return () => { alive = false; };
  }, []);

  const rowFor = (tier) => {
    const sel = tiers[tier.key];
    if (!sel) return null;
    const rows = tier.kind === "chat" ? available.chat : available.embedding;
    return rows.find((r) => r.connector === sel.connector && r.model === sel.model) || null;
  };

  const requiresKey = (tier) => {
    const r = rowFor(tier);
    return r ? !!r.requires_key : false;
  };

  // allValid: every tier validated OK.
  const allValid = useMemo(
    () => TIERS.every((t) => tiers[t.key] && tiers[t.key].status === "ok"),
    [tiers]
  );

  useEffect(() => {
    if (onChange) onChange({ tiers, allValid });
  }, [tiers, allValid]); // eslint-disable-line

  const update = (tierKey, patch) =>
    setTiers((prev) => ({ ...prev, [tierKey]: { ...prev[tierKey], ...patch } }));

  const onSelect = (tier, value) => {
    const [connector, model] = value.split("::");
    // changing the selection invalidates a prior validation
    update(tier.key, { connector, model, status: "idle", error: "" });
  };

  const validate = async (tier) => {
    const sel = tiers[tier.key];
    update(tier.key, { status: "validating", error: "" });
    try {
      const res = await fetch(`${API}/api/onboarding/validate-tier`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tier: tier.key,
          connector: sel.connector,
          model: sel.model,
          key: sel.key || null,
        }),
      });
      const data = await res.json();
      if (data.ok) update(tier.key, { status: "ok", error: "" });
      else update(tier.key, { status: "error", error: friendlyError(data.error) });
    } catch (e) {
      update(tier.key, { status: "error", error: String(e.message || e) });
    }
  };

  if (loadErr) {
    return (
      <div className="flex items-center gap-2 text-sm text-rose-400">
        <AlertCircle size={14} /> Could not load model list: {loadErr}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {TIERS.map((tier) => {
        const sel = tiers[tier.key] || {};
        const rows = tier.kind === "chat" ? available.chat : available.embedding;
        const needsKey = requiresKey(tier);
        const locked = tier.key === "embedding" && embeddingLocked;
        return (
          <div key={tier.key} className="rounded border border-subtle surface-card p-3">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-default">{tier.label}</label>
              <TierStatus status={sel.status} />
            </div>
            <p className="mt-0.5 text-xs text-faint">{tier.blurb}</p>

            <select
              className="mt-2 w-full rounded input px-3 py-2 text-sm disabled:opacity-60"
              value={sel.connector ? optValue(sel) : ""}
              disabled={locked}
              onChange={(e) => onSelect(tier, e.target.value)}
            >
              {rows.map((r) => (
                <option key={optValue(r)} value={optValue(r)}>{optLabel(r, tier.key)}</option>
              ))}
            </select>

            {locked && (
              <p className="mt-1 flex items-center gap-1 text-xs text-faint">
                <Lock size={12} /> Locked — changing the text-encoding model would require
                re-encoding everything (a separate future feature).
              </p>
            )}
            {tier.key === "embedding" && mode === "onboarding" && (
              <p className="mt-1 flex items-center gap-1 text-xs text-amber-300">
                <AlertCircle size={12} /> This choice is permanent — it can’t be changed later
                without re-encoding all your data.
              </p>
            )}

            {needsKey ? (
              <div className="mt-2">
                <input
                  type="password"
                  className="w-full rounded input px-3 py-2 font-mono text-sm"
                  placeholder={
                    mode === "settings" ? "•••• (leave blank to keep current key)" : "Paste API key"
                  }
                  value={sel.key || ""}
                  onChange={(e) => update(tier.key, { key: e.target.value, status: "idle" })}
                />
                <p className="mt-1 text-xs text-faint">
                  {sel.connector ? `${providerName(rowFor(tier))} needs an API key.` : ""}
                </p>
              </div>
            ) : (
              <p className="mt-2 text-xs text-faint">
                {sel.connector ? `${providerName(rowFor(tier))} runs locally — no key needed.` : ""}
              </p>
            )}

            <div className="mt-2 flex items-center gap-3">
              <button
                type="button"
                className="rounded btn-secondary px-3 py-1.5 text-xs disabled:opacity-50"
                disabled={!sel.connector || sel.status === "validating"}
                onClick={() => validate(tier)}
              >
                {sel.status === "validating" ? "Validating…" : "Validate"}
              </button>
              {sel.status === "error" && (
                <span className="text-xs text-rose-400">{sel.error}</span>
              )}
              {sel.status !== "ok" && sel.status !== "error" && (
                <span className="text-xs text-faint">Validate this tier to continue.</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function providerName(row) {
  return row ? row.provider_display : "This provider";
}

function TierStatus({ status }) {
  if (status === "ok")
    return <span className="flex items-center gap-1 text-xs text-emerald-400"><ShieldCheck size={13} /> Validated</span>;
  if (status === "validating")
    return <span className="flex items-center gap-1 text-xs text-muted"><Loader2 size={13} className="animate-spin" /> Validating</span>;
  if (status === "error")
    return <span className="flex items-center gap-1 text-xs text-rose-400"><AlertCircle size={13} /> Failed</span>;
  return <span className="text-xs text-faint">Not validated</span>;
}

function friendlyError(code) {
  switch (code) {
    case "missing_key": return "An API key is required for this provider.";
    case "auth": return "The provider rejected the key. Check it and try again.";
    case "quota": return "The provider reports no quota/credit on this account.";
    case "model_not_found": return "That model isn’t available on this account.";
    case "network":
      return "Couldn’t reach the provider (network, or a local server that isn’t running).";
    default: return "Validation failed. Check the selection and key.";
  }
}
