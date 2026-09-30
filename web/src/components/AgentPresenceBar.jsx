import { useEffect, useState } from "react";
import { WifiOff } from "lucide-react";

/**
 * Who is in this chat (the shared thread): Skipper plus every registered agent participant
 * (app_platform.agents). Online participants are highlighted; offline ones (e.g. the Professor
 * when its loop isn't running) stay listed but greyed out with an offline icon. Polls /api/agents.
 */
const POLL_MS = 30000;

function ago(ts) {
  if (!ts) return "";
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000);
  if (isNaN(s)) return "";
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export default function AgentPresenceBar({ connected }) {
  const [agents, setAgents] = useState([]);

  useEffect(() => {
    let live = true;
    const load = () =>
      fetch("/api/agents")
        .then((r) => (r.ok ? r.json() : { agents: [] }))
        .then((d) => { if (live) setAgents(d.agents || []); })
        .catch(() => {});
    load();
    const t = setInterval(load, POLL_MS);
    return () => { live = false; clearInterval(t); };
  }, []);

  // One chip per participant. `online`: true / false / null (the agent reports no status).
  function Chip({ label, online, title }) {
    const off = online === false;
    return (
      <span
        className={`pill ${online ? "pill-success" : "pill-neutral"} shrink-0 inline-flex items-center gap-1 ${off ? "opacity-50" : ""}`}
        title={title}
      >
        {off && <WifiOff size={11} aria-hidden="true" />}
        {label}
        {off && <span className="sr-only"> (offline)</span>}
      </span>
    );
  }

  return (
    <div
      // h-9 matches the app panel's taskbar (AppPanel) — the two bars sit side by side.
      className="shrink-0 flex items-center h-9 gap-2 px-4 border-b border-subtle surface-panel text-xs overflow-x-auto overflow-y-hidden"
      aria-label="Who's in this chat"
    >
      <span className="text-faint shrink-0">In chat:</span>
      <Chip label="Skipper" online={connected}
            title={connected ? "Skipper is connected" : "Skipper is offline — reconnecting…"} />
      {agents.map((a) => {
        const online = a.status ? a.status.online : null;
        const title = [
          online === false ? "Offline" : online ? "Online" : "",
          a.description,
          a.status?.detail,
          a.status?.last_seen && `last seen ${ago(a.status.last_seen)}`,
        ].filter(Boolean).join(" · ");
        return <Chip key={a.name} label={`${a.icon ? a.icon + " " : ""}${a.display_name}`}
                     online={online} title={title} />;
      })}
    </div>
  );
}
