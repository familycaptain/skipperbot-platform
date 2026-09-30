import { useEffect, useState } from "react";

// Registered agent participants in the shared chat thread (GET /api/agents), fetched once
// per page load and shared by every caller. Keyed by agent name → {display_name, icon, …}.
let _cache = null;
let _pending = null;

function load() {
  if (_cache) return Promise.resolve(_cache);
  if (!_pending) {
    _pending = fetch("/api/agents")
      .then((r) => (r.ok ? r.json() : { agents: [] }))
      .then((d) => {
        _cache = Object.fromEntries((d.agents || []).map((a) => [a.name, a]));
        return _cache;
      })
      .catch(() => ({}))
      .finally(() => { _pending = null; });
  }
  return _pending;
}

export function agentLabel(agents, name) {
  const a = agents?.[name];
  if (!a) return name ? name.charAt(0).toUpperCase() + name.slice(1) : "";
  return `${a.icon ? a.icon + " " : ""}${a.display_name}`;
}

export default function useAgents() {
  const [agents, setAgents] = useState(_cache || {});
  useEffect(() => {
    let live = true;
    load().then((a) => { if (live && a) setAgents(a); });
    return () => { live = false; };
  }, []);
  return agents;
}
