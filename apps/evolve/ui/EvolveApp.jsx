import { useState, useEffect, useCallback, useRef } from "react";
import { Workflow, Loader2, CheckCircle2, XCircle, RefreshCw, GitBranch, FlaskConical, Activity, Circle, ChevronDown, ChevronRight, Archive, ArchiveRestore } from "lucide-react";
import { hasAnyRole } from "../../../web/src/utils/roles";

const API = "/api/apps/evolve";
const POLL_MS = 1500;

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let d = "";
    try { d = (await res.json()).detail || ""; } catch {}
    const e = new Error(d || `${res.status} ${res.statusText}`); e.status = res.status; throw e;
  }
  return res.json();
}

const REC_COLOR = {
  approve: "text-emerald-300 bg-emerald-900/30 border-emerald-700/40",
  change: "text-amber-300 bg-amber-900/30 border-amber-700/40",
  reject: "text-red-300 bg-red-900/30 border-red-700/40",
};
const SEV_COLOR = { high: "bg-red-900/50 text-red-300", med: "bg-amber-900/50 text-amber-300",
  medium: "bg-amber-900/50 text-amber-300", low: "bg-slate-700/60 text-slate-300" };
const ATTENTION = new Set(["crit", "lead"]);
// Code Scout "planned change" action badges — rewrite/delete/move read as higher-impact
const ACTION_CLS = {
  add: "bg-emerald-900/50 text-emerald-300", modify: "bg-sky-900/50 text-sky-300",
  rewrite: "bg-amber-900/50 text-amber-300", delete: "bg-red-900/50 text-red-300",
  move: "bg-violet-900/50 text-violet-300",
};

// run status -> chip style + label
const STATUS = {
  running:  { cls: "bg-sky-900/50 text-sky-300", label: "running" },
  building: { cls: "bg-violet-900/50 text-violet-300", label: "building" },
  waiting:  { cls: "bg-amber-900/50 text-amber-300", label: "needs you" },
  merged:   { cls: "bg-emerald-900/50 text-emerald-300", label: "merged" },
  rejected: { cls: "bg-red-900/50 text-red-300", label: "rejected" },
  error:    { cls: "bg-red-900/50 text-red-300", label: "error" },
};
const isActive = (s) => s === "running" || s === "building";
// pretty labels for the per-agent lanes
const AGENT_LABEL = {
  engine: "Engine", lead: "Lead", design: "Design", "spec-author": "Spec-author",
  spec: "Spec-author", "code-scout": "Code scout", scout: "Code scout",
  crit: "Spec-audit", "spec-audit": "Spec-audit", triage: "Triage",
  "vision-fit": "Vision-fit", vision: "Vision-fit", prioritize: "Prioritize", prio: "Prioritize",
  security: "Security", architecture: "Architecture", interop: "Interop", ux: "UX / UI",
  serialize: "Serialize", implement: "Implement", validate: "Validate", merge: "Merge",
  "review-packet": "Review packet", packet: "Review packet",
};
const KIND_CLS = {
  tool: "text-slate-400", emit: "text-indigo-300", agent_start: "text-sky-300",
  agent_end: "text-emerald-300", node: "text-slate-300", info: "text-slate-500",
  error: "text-red-300", text: "text-slate-200",   // the agent's own narration
};

function Field({ k, v }) {
  let body;
  if (typeof v === "string") body = <span className="text-slate-300">{v}</span>;
  else if (Array.isArray(v)) body = (
    <ul className="list-disc ml-4 text-slate-300 space-y-0.5">
      {v.map((x, i) => (
        <li key={i}>
          {typeof x === "string" ? x : (x.detail || x.why || x.text || x.title || JSON.stringify(x))}
          {x && x.severity && <span className={`ml-1 text-[9px] px-1 rounded ${SEV_COLOR[String(x.severity).toLowerCase()] || ""}`}>{x.severity}</span>}
          {x && x.category && <span className="ml-1 text-[10px] text-slate-500">{x.category}</span>}
        </li>
      ))}
    </ul>
  );
  else if (v && typeof v === "object") body = <span className="text-slate-300">{Object.entries(v).map(([kk, vv]) => `${kk}: ${vv}`).join(" · ")}</span>;
  else body = <span className="text-slate-300">{String(v)}</span>;
  return <div className="text-xs"><span className="text-slate-500">{k.replace(/_/g, " ")}: </span>{body}</div>;
}

function AgentPanel({ agent }) {
  const o = agent.output || {};
  const detailKeys = Object.keys(o).filter((k) => k !== "summary" && o[k] != null
    && (Array.isArray(o[k]) ? o[k].length : o[k] !== ""));
  const [open, setOpen] = useState(ATTENTION.has(agent.key));
  return (
    <div className="border border-slate-800 rounded-md">
      <button onClick={() => detailKeys.length && setOpen((x) => !x)} className="w-full text-left px-2.5 py-1.5">
        <div className="flex items-center justify-between">
          <span className="text-sm font-medium">{agent.label}</span>
          {detailKeys.length > 0 && <span className="text-[11px] text-slate-500">{open ? "− less" : "+ details"}</span>}
        </div>
        {o.summary && <div className="text-xs text-slate-300 mt-0.5 leading-snug">{o.summary}</div>}
      </button>
      {open && (
        <div className="px-2.5 pb-2 border-t border-slate-800/60 pt-2 space-y-1.5">
          {detailKeys.map((k) => <Field key={k} k={k} v={o[k]} />)}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }) {
  if (!children) return null;
  return (
    <div className="mb-4">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{title}</div>
      <div className="text-sm text-slate-200">{children}</div>
    </div>
  );
}

// one per-agent live log lane — collapsible, scrollable, sticks to the bottom only when
// you're already there (so you can scroll up through history without it yanking you down).
function AgentLog({ name, events, active, done, expandAll }) {
  const [open, setOpen] = useState(false);
  const [tall, setTall] = useState(false);
  const boxRef = useRef(null);
  const stick = useRef(true);
  const isOpen = open || expandAll || active;          // active agent + "expand all" auto-open
  useEffect(() => {
    const el = boxRef.current;
    if (isOpen && el && stick.current) el.scrollTop = el.scrollHeight;
  }, [events.length, isOpen, tall]);
  const onScroll = (e) => {
    const el = e.currentTarget;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
  };
  const last = events.length ? events[events.length - 1].message : "";
  return (
    <div className={`border rounded-md ${active ? "border-sky-600/60" : "border-slate-800"}`}>
      <div className="flex items-center gap-1.5 px-2.5 py-1 border-b border-slate-800/60">
        {active ? <Circle size={8} className="text-sky-400 fill-sky-400 animate-pulse shrink-0" />
          : done ? <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
          : <Circle size={8} className="text-slate-600 shrink-0" />}
        <span className="text-xs font-medium">{AGENT_LABEL[name] || name}</span>
        <span className="text-[10px] text-slate-500 ml-auto shrink-0">{events.length} · {active ? "active" : done ? "done" : "idle"}</span>
        {isOpen && (
          <button onClick={() => setTall((t) => !t)} className="text-[10px] text-slate-500 hover:text-slate-200 shrink-0" title="taller / shorter">
            {tall ? "▣" : "⤢"}
          </button>
        )}
        <button onClick={() => setOpen((o) => !o)} className="text-slate-500 hover:text-white shrink-0">
          {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>
      </div>
      {isOpen ? (
        <div ref={boxRef} onScroll={onScroll}
             className={`${tall ? "max-h-[32rem]" : "max-h-72"} overflow-y-auto px-2.5 py-1.5 font-mono text-[11px] leading-relaxed bg-black/30`}>
          {events.length === 0 && <div className="text-slate-600">waiting…</div>}
          {events.map((e) => (
            <div key={e.id} className={`whitespace-pre-wrap break-words ${KIND_CLS[e.kind] || "text-slate-400"}`}>{e.message}</div>
          ))}
        </div>
      ) : (
        last && <button onClick={() => setOpen(true)} className="block w-full text-left px-2.5 py-1 font-mono text-[11px] text-slate-500 truncate hover:text-slate-300">{last}</button>
      )}
    </div>
  );
}

export default function EvolveApp({ userId, userRole, refreshKey, onTitle }) {
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);
  const [runs, setRuns] = useState([]);
  const [sel, setSel] = useState(null);
  const [run, setRun] = useState(null);        // selected run's live meta
  const [events, setEvents] = useState([]);    // selected run's activity stream
  const [detail, setDetail] = useState(null);  // gate packet (only when parked at a gate)
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [expandAll, setExpandAll] = useState(false);
  const [answers, setAnswers] = useState({});   // operator's answer per decisions_needed question
  const [guidance, setGuidance] = useState(""); // free-text guidance to the spec team
  const [showArchived, setShowArchived] = useState(false);  // list view: active vs archived
  const [totalCost, setTotalCost] = useState(0);            // cumulative Evolve spend (all runs)
  const [weekCost, setWeekCost] = useState(0);              // spend this week (since Monday)
  const [decided, setDecided] = useState({});              // instance_id -> decided gate (approved/changed but engine hasn't acted yet)
  const [bump, setBump] = useState(0);                      // manual/visibility refresh trigger (also re-pulls the detail)
  const lastId = useRef(0);
  const selRef = useRef(null);

  useEffect(() => { onTitle?.("Evolve"); }, [onTitle]);
  useEffect(() => { selRef.current = sel; }, [sel]);

  const loadRuns = useCallback(async () => {
    try {
      const r = await apiFetch(`/runs?archived=${showArchived}`);
      const rows = r.runs || [];
      setRuns(rows);
      if (typeof r.total_cost === "number") setTotalCost(r.total_cost);
      if (typeof r.week_cost === "number") setWeekCost(r.week_cost);
      if (!selRef.current && rows.length) setSel(rows[0].instance_id);
      // gates you've already decided but the engine hasn't acted on yet → "approved, building soon"
      apiFetch(`/gates?status=decided`).then((g) => {
        const m = {}; (g.gates || []).forEach((x) => { m[x.instance_id] = x; });
        setDecided(m);
      }).catch(() => {});
    } catch (e) { setError(String(e.message || e)); }
  }, [showArchived]);

  // manual + auto refresh: reload the list AND re-pull the selected detail/gate (bump drives the tail)
  const refresh = useCallback(() => { loadRuns(); setBump((b) => b + 1); }, [loadRuns]);

  // browsers throttle/pause our 1.5s poll while the tab is backgrounded — so refresh the instant
  // the operator returns to the tab/window (this is what made gates look stale until reopening).
  useEffect(() => {
    const onVisible = () => { if (document.visibilityState === "visible") refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [refresh]);

  async function archiveRun(id, archived) {
    try {
      await apiFetch(`/runs/${id}/archive`, { method: "POST", body: JSON.stringify({ archived }) });
      if (sel === id) setSel(null);
      loadRuns();
    } catch (e) { setError(String(e.message || e)); }
  }

  // poll the runs list
  useEffect(() => {
    loadRuns();
    const t = setInterval(loadRuns, POLL_MS);
    return () => clearInterval(t);
  }, [loadRuns, refreshKey]);

  // when the selection changes: reset the stream (the tail below fetches the gate packet)
  useEffect(() => {
    lastId.current = 0; setEvents([]); setDetail(null); setAnswers({}); setGuidance("");
  }, [sel]);

  // tail the selected run's activity stream, and keep the gate packet in sync with status:
  // load it whenever the run is waiting on a human, drop it when the run goes back to work.
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    let gateLoadedFor = null;     // which status we currently hold a packet for
    const tick = async () => {
      try {
        const r = await apiFetch(`/runs/${sel}/events?since=${lastId.current}`);
        if (!alive) return;
        if (r.run) setRun(r.run);
        if (r.events?.length) {
          lastId.current = r.last;
          setEvents((prev) => [...prev, ...r.events]);
        }
        const st = r.run?.status;
        if (st === "waiting" && gateLoadedFor !== "waiting") {
          gateLoadedFor = "waiting";   // it parked at a gate — pull the review packet + actions
          apiFetch(`/gates/${sel}`).then((d) => alive && setDetail(d)).catch(() => {});
        } else if (st && st !== "waiting" && gateLoadedFor !== st) {
          gateLoadedFor = st;          // back to working — clear the stale gate review
          setDetail(null);
        }
      } catch { /* best-effort */ }
    };
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [sel, bump]);

  // assemble the operator's written response (answers to each "decision for you" + guidance)
  // into one note the spec team reads as human_note on a 'change'.
  function buildNote(pkt) {
    const parts = [];
    (pkt?.decisions_needed || []).forEach((d, i) => {
      const a = (answers[i] || "").trim();
      if (a) parts.push(`Q: ${d.question}\nA: ${a}`);
    });
    const g = guidance.trim();
    if (g) parts.push(g);
    return parts.join("\n\n");
  }

  async function decide(decision) {
    if (!sel) return;
    const note = buildNote(detail?.packet || {});
    setBusy(decision); setError("");
    try {
      await apiFetch(`/gates/${sel}/decision`, { method: "POST", body: JSON.stringify({ decision, note }) });
      // optimistically flip the list chip to "<decision> · …soon" instantly (don't wait for the poll)
      setDecided((m) => ({ ...m, [sel]: { instance_id: sel, decision, gate: detail?.gate } }));
      setDetail(await apiFetch(`/gates/${sel}`).catch(() => null));
      loadRuns();
    } catch (e) { setError(String(e.message || e)); }
    finally { setBusy(""); }
  }

  // re-open a merged/done item at the verify gate ("it shipped but doesn't work")
  async function reverify() {
    if (!sel) return;
    setBusy("reverify"); setError("");
    try {
      await apiFetch(`/runs/${sel}/reverify`, { method: "POST", body: "{}" });
      loadRuns();   // status -> waiting; the tail then loads the Gate-3 packet
    } catch (e) { setError(String(e.message || e)); }
    finally { setBusy(""); }
  }

  const pkt = detail?.packet || {};
  const rec = pkt.recommendation || {};
  const proposal = pkt.proposal || {};
  const codePlan = pkt.code_plan || null;   // Code Scout's read-only "what would change" sketch (Gate 1)
  const agents = pkt.agents || [];
  const atGate = detail?.status === "waiting";
  const gate2 = (detail?.gate || pkt.gate) === "gate2";   // Gate 2 = approve the RESULT → merge to release
  const gate3 = (detail?.gate || pkt.gate) === "gate3";   // Gate 3 = VERIFY — you tested it on your Pi; works or still broken?
  // "needs you" = waiting AND you haven't already decided it (a decided gate is the engine's to act on)
  const needsYou = runs.filter((r) => r.status === "waiting" && !decided[r.instance_id]).length;
  // chip for a gate you've decided but the engine hasn't picked up yet — GATE-AWARE
  // (approve means build@gate1, merge@gate2, but VERIFIED/done@gate3 — not "building")
  const decidedChip = (dec) => {
    const g = dec.gate, d = dec.decision;
    if (d === "approve") {
      if (g === "gate3") return { cls: "bg-emerald-900/50 text-emerald-300", label: "verified · finishing soon" };
      if (g === "gate2") return { cls: "bg-violet-900/50 text-violet-300", label: "approved · merging soon" };
      return { cls: "bg-violet-900/50 text-violet-300", label: "approved · building soon" };
    }
    if (d === "change")
      return { cls: "bg-amber-900/50 text-amber-300", label: g === "gate3" ? "reported · re-fixing soon" : "changes · revising soon" };
    return { cls: "bg-red-900/50 text-red-300", label: "rejected · closing soon" };
  };

  // group the activity stream into per-agent lanes, in first-seen order
  const lanes = [];
  const byAgent = {};
  for (const e of events) {
    const a = e.agent || "engine";
    if (!byAgent[a]) { byAgent[a] = []; lanes.push(a); }
    byAgent[a].push(e);
  }
  const doneAgents = new Set(lanes.filter((a) => byAgent[a].some((e) => e.kind === "agent_end")));

  return (
    <div className="flex flex-col h-full w-full bg-zinc-950 text-zinc-100">
      {/* TOP BAR: live cumulative Evolve spend */}
      <div className="flex items-center justify-between px-3 h-8 border-b border-slate-800 shrink-0">
        <span className="text-[11px] uppercase tracking-wide text-slate-500 flex items-center gap-1.5"><Workflow size={12} /> Evolve</span>
        <span className="text-[11px] flex items-center gap-2">
          <span className="flex items-center gap-1" title="Evolve spend this week (since Monday)">
            <span className="text-slate-600 uppercase tracking-wide">this week</span>
            <span className="font-mono text-emerald-300">${weekCost.toFixed(2)}</span>
          </span>
          <span className="text-slate-700">·</span>
          <span className="flex items-center gap-1" title="cumulative Evolve spend across all items">
            <span className="text-slate-600 uppercase tracking-wide">all items</span>
            <span className="font-mono text-emerald-400/80">${totalCost.toFixed(2)}</span>
          </span>
        </span>
      </div>
      <div className="flex flex-1 min-h-0">
      {/* LEFT: runs */}
      <div className="w-72 shrink-0 border-r border-slate-800 flex flex-col">
        <div className="flex items-center justify-between px-3 h-10 border-b border-slate-800 shrink-0">
          <span className="text-sm font-medium flex items-center gap-1.5">
            <Workflow size={14} /> {showArchived ? "Archived" : "Runs"}
            {!showArchived && needsYou > 0 && <span className="text-[10px] bg-indigo-600 rounded-full px-1.5" title="need your decision">{needsYou}</span>}
          </span>
          <div className="flex items-center gap-2">
            <button onClick={refresh} title="refresh now"
              className="text-slate-500 hover:text-slate-200 flex items-center">
              <RefreshCw size={12} />
            </button>
            <button onClick={() => { setShowArchived((v) => !v); setSel(null); }}
              className="text-[10px] text-slate-500 hover:text-slate-200 flex items-center gap-1"
              title={showArchived ? "show active runs" : "show archived runs"}>
              {showArchived ? (<><Activity size={11} className="text-sky-500" /> active</>)
                            : (<><Archive size={11} /> archived</>)}
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto">
          {runs.length === 0 && (
            <div className="text-slate-600 text-sm text-center mt-8 px-4">{showArchived ? "No archived runs." : "No runs yet. Ingested issues and their builds show up here live."}</div>
          )}
          {runs.map((g) => {
            const active = g.instance_id === sel;
            const st = (g.status === "waiting" && decided[g.instance_id])
              ? decidedChip(decided[g.instance_id])
              : (STATUS[g.status] || { cls: "bg-slate-700/60 text-slate-300", label: g.status });
            return (
              <div key={g.instance_id} role="button" onClick={() => setSel(g.instance_id)}
                className={`relative group w-full text-left px-3 py-2.5 border-b border-slate-800/60 cursor-pointer ${active ? "bg-slate-800/70" : "hover:bg-slate-900/60"}`}>
                <button onClick={(e) => { e.stopPropagation(); archiveRun(g.instance_id, !showArchived); }}
                  className="absolute top-1.5 right-1.5 p-1 rounded text-slate-600 hover:text-slate-200 hover:bg-slate-700/60 opacity-0 group-hover:opacity-100"
                  title={showArchived ? "unarchive" : "archive (hide from list)"}>
                  {showArchived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                </button>
                <div className="flex items-center gap-1.5 mb-0.5 pr-6">
                  <span className={`text-[10px] px-1.5 rounded inline-flex items-center gap-1 ${st.cls}`}>
                    {isActive(g.status) && <Loader2 size={9} className="animate-spin" />}{st.label}
                  </span>
                  {g.phase && <span className="text-[10px] text-slate-500">{g.phase}</span>}
                </div>
                <div className="text-sm leading-snug line-clamp-2">{g.title || g.instance_id}</div>
                <div className="text-[11px] text-slate-500 mt-0.5">
                  {isActive(g.status) && g.current_agent ? `⚙ ${AGENT_LABEL[g.current_agent] || g.current_agent}`
                    : g.source || g.instance_id}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* RIGHT: drill-down — live activity + (if parked) gate review */}
      <div className="flex-1 min-w-0 overflow-y-auto p-4">
        {error && <div className="text-red-300 bg-red-900/20 p-2 rounded mb-3 text-sm">{error}</div>}
        {!sel && <div className="text-slate-600 mt-10 text-center">Select a run to watch it work.</div>}
        {sel && (
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 mb-1 text-xs text-slate-500">
              <span>{run?.status ? (STATUS[run.status]?.label || run.status) : "run"}</span>
              <span>·</span><span className="font-mono">{sel}</span>
              {(run?.source || pkt.work_item?.source) && <><span>·</span><span>{run?.source || pkt.work_item?.source}</span></>}
              {pkt.baseline?.sha && <><span>·</span><span className="font-mono" title="code/specs the agents were grounded on">⎇ {pkt.baseline.branch}@{pkt.baseline.sha}</span></>}
              {run?.cost_usd > 0 && <><span>·</span><span className="font-mono text-emerald-300" title="this item's spend so far (all its agents, every phase)">${run.cost_usd.toFixed(2)}</span></>}
            </div>
            <h2 className="text-lg font-semibold mb-3">{run?.title || pkt.work_item?.title || sel}</h2>

            {/* DIDN'T WORK — re-open a merged/done item at the verify gate */}
            {!atGate && run?.status === "merged" && isParent && (
              <div className="mb-4">
                <button disabled={!!busy} onClick={reverify}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-amber-700/60 text-amber-300 hover:bg-amber-900/30 text-sm disabled:opacity-50">
                  {busy === "reverify" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Didn't work — re-verify
                </button>
                <div className="text-[11px] text-slate-500 mt-1">Re-opens this at the verify gate so you can report what's broken; it resumes the same conversation to fix it.</div>
              </div>
            )}

            {/* DECIDED but the engine hasn't picked it up yet — explain the limbo (gate-aware) */}
            {!atGate && detail?.status === "decided" && (() => {
              const g = detail.gate, d = detail.decision;
              const verified = g === "gate3" && d === "approve";
              const did = verified ? "verified this works"
                : d === "approve" ? "approved this" : `chose "${d}"`;
              const next = d === "approve"
                  ? (g === "gate3" ? "closes the GitHub issue and finishes it"
                     : g === "gate2" ? "merges it to release, then asks you to verify"
                     : "builds it")
                : d === "change"
                  ? (g === "gate3" ? "resumes the same conversation to fix what you reported"
                     : "re-works it")
                : "tears it down";
              return (
                <div className={`mb-4 border rounded-lg p-3 text-sm ${verified ? "bg-emerald-900/20 border-emerald-700/40 text-emerald-200" : "bg-violet-900/20 border-violet-700/40 text-violet-200"}`}>
                  <div className="font-medium mb-0.5">
                    ✓ You {did}{detail.decided_by ? ` (${detail.decided_by})` : ""} — nothing more needed from you.
                  </div>
                  <div className={`text-xs ${verified ? "text-emerald-300/80" : "text-violet-300/80"}`}>
                    The engine {next} on the next loop pass (make sure the box-1 /loop is running).
                  </div>
                </div>
              );
            })()}

            {/* GATE REVIEW (only when parked at a human gate) */}
            {atGate && (
              <>
                <div className={`mb-2 inline-flex items-center gap-1.5 text-[11px] font-medium px-2 py-1 rounded ${gate3 ? "bg-amber-900/40 text-amber-300 border border-amber-700/50" : gate2 ? "bg-emerald-900/40 text-emerald-300 border border-emerald-700/50" : "bg-sky-900/30 text-sky-300 border border-sky-700/40"}`}>
                  {gate3 ? <><FlaskConical size={12} /> Gate 3 · Verify — it's merged to release. Deploy to your Pi, test it, then confirm.</>
                         : gate2 ? <><GitBranch size={12} /> Gate 2 · approving here MERGES to release (ships it)</>
                         : <>Gate 1 · approve the intent (no code ships yet)</>}
                </div>
                <div className={`border rounded-lg p-3 mb-4 ${REC_COLOR[rec.action] || "bg-slate-800/40 border-slate-700"}`}>
                  <div className="text-[11px] uppercase tracking-wide opacity-70">Lead's recommendation</div>
                  <div className="font-semibold capitalize">{rec.action || "review"}</div>
                  <div className="text-sm opacity-90 mt-0.5">{rec.why || rec.rationale}</div>
                  {(rec.current || rec.after) && (
                    <div className="mt-2 space-y-1 text-xs border-t border-white/10 pt-2">
                      {rec.current && <div><span className="font-semibold opacity-60">Today: </span><span className="opacity-90">{rec.current}</span></div>}
                      {rec.after && <div><span className="font-semibold opacity-60">After this change: </span><span className="opacity-90">{rec.after}</span></div>}
                    </div>
                  )}
                </div>

                {pkt.conflict_alerts?.length > 0 && (
                  <div className="border border-red-700/50 bg-red-900/25 rounded-lg p-2.5 mb-4 text-xs">
                    <div className="text-red-300 font-medium mb-1">
                      ⚠ A related item MERGED after this was planned — re-review (send back with “Change” to have the Lead re-evaluate)
                    </div>
                    {pkt.conflict_alerts.map((c, i) => (
                      <div key={i} className="text-slate-300 mb-1">
                        • <span className="font-mono">{c.from}</span> {c.from_title ? `“${c.from_title}” ` : ""}
                        changed <span className="text-slate-400">{(c.shared || []).join(", ")}</span>
                        {c.conflicts?.length > 0
                          ? <div className="text-red-300 ml-2 mt-0.5">conflict: {c.conflicts.map((x) => x.detail || x).join("; ")}</div>
                          : <span className="text-slate-500"> — overlap; plan may be stale</span>}
                      </div>
                    ))}
                  </div>
                )}

                {pkt.related?.length > 0 && (
                  <div className="border border-amber-700/40 bg-amber-900/20 rounded-lg p-2.5 mb-4 text-xs">
                    <div className="text-amber-300 font-medium mb-1">
                      ⚠ Overlaps {pkt.related.length} other in-flight item{pkt.related.length > 1 ? "s" : ""} — may collide at merge
                    </div>
                    {pkt.related.map((r, i) => (
                      <div key={i} className="text-slate-300">
                        • {r.title || r.instance}{" "}
                        <span className="text-slate-500">({r.source || r.gate || r.status}; shares {(r.overlap || []).join(", ")})</span>
                      </div>
                    ))}
                  </div>
                )}

                {pkt.decisions_needed?.length > 0 && (
                  <Section title="Decisions for you">
                    {pkt.decisions_needed.map((d, i) => (
                      <div key={i} className="border border-sky-700/40 bg-sky-900/15 rounded p-2 mb-2">
                        <div className="text-slate-200"><span className="opacity-50 mr-1">{i + 1}.</span>{d.question}</div>
                        {d.recommendation && <div className="text-xs text-sky-300 mt-0.5">→ recommends: {d.recommendation}</div>}
                        {d.options?.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-1.5">
                            {d.options.map((opt, j) => (
                              <button key={j} disabled={!isParent}
                                onClick={() => setAnswers((a) => ({ ...a, [i]: opt }))}
                                className={`text-[11px] px-2 py-0.5 rounded border disabled:opacity-50 ${answers[i] === opt ? "bg-sky-700 border-sky-500 text-white" : "border-slate-600 text-slate-300 hover:border-slate-400"}`}>
                                {opt}
                              </button>
                            ))}
                          </div>
                        )}
                        <input type="text" disabled={!isParent} value={answers[i] || ""}
                          onChange={(e) => setAnswers((a) => ({ ...a, [i]: e.target.value }))}
                          placeholder="your answer…"
                          className="mt-1.5 w-full bg-slate-900/70 border border-slate-700 rounded px-2 py-1 text-sm text-slate-100 placeholder-slate-600 focus:border-sky-600 focus:outline-none disabled:opacity-50" />
                      </div>
                    ))}
                  </Section>
                )}

                {atGate && isParent && (
                  <div className="mb-3">
                    <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
                      {gate3 ? "What went wrong? (required if it's still broken)" : "Guidance to the team (optional)"}
                    </div>
                    <textarea value={guidance} onChange={(e) => setGuidance(e.target.value)} rows={2}
                      placeholder={gate3 ? "Describe what didn't work — it goes back to the same conversation to fix…" : "Anything else the agents should change or keep in mind…"}
                      className="w-full bg-slate-900/70 border border-slate-700 rounded px-2 py-1.5 text-sm text-slate-100 placeholder-slate-600 focus:border-sky-600 focus:outline-none" />
                  </div>
                )}

                {isParent ? (
                  <>
                    <div className="flex gap-2">
                      <button disabled={!!busy} onClick={() => decide("approve")} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-700 hover:bg-emerald-600 text-sm disabled:opacity-50">
                        {busy === "approve" ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} {gate3 ? "✓ Works — close it out" : gate2 ? "Approve & merge → release" : "Approve"}
                      </button>
                      <button disabled={!!busy} onClick={() => decide("change")} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-700 hover:bg-amber-600 text-sm disabled:opacity-50">
                        {busy === "change" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} {gate3 ? "Still broken — send back" : "Change & send answers"}
                      </button>
                      <button disabled={!!busy} onClick={() => decide("reject")} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-red-800 hover:bg-red-700 text-sm disabled:opacity-50">
                        {busy === "reject" ? <Loader2 size={14} className="animate-spin" /> : <XCircle size={14} />} {gate3 ? "Abandon" : "Reject"}
                      </button>
                    </div>
                    <div className="text-[11px] text-slate-500 mt-1.5 mb-5">
                      {gate3
                        ? <><span className="text-emerald-300">Works</span> closes the GitHub issue (the loop is done); <span className="text-amber-300">Still broken</span> reopens the SAME conversation with your note to fix → re-validate → re-merge; <span className="text-red-300">Abandon</span> gives up on it.</>
                        : gate2
                        ? <><span className="text-emerald-300">Approve</span> merges this branch into <span className="text-slate-300">release</span> and publishes it; <span className="text-amber-300">Change</span> sends it back to rebuild; <span className="text-red-300">Reject</span> discards it.</>
                        : <>Your answers above are sent to the agents with <span className="text-amber-300">Change</span> (they revise the spec) or attached as a build note with <span className="text-emerald-300">Approve</span>.</>}
                    </div>
                  </>
                ) : <div className="text-xs text-slate-500 mb-5">A parent or admin decides this gate.</div>}
              </>
            )}

            {/* LIVE ACTIVITY — per-agent scrolling logs */}
            <div className="mb-4">
              <div className="flex items-center justify-between mb-1">
                <div className="text-[11px] uppercase tracking-wide text-slate-500">
                  Live activity{run?.current_agent && isActive(run?.status) ? ` · ⚙ ${AGENT_LABEL[run.current_agent] || run.current_agent}` : ""}
                </div>
                {lanes.length > 0 && (
                  <button onClick={() => setExpandAll((x) => !x)} className="text-[10px] text-slate-500 hover:text-slate-200">
                    {expandAll ? "collapse all" : "expand all"}
                  </button>
                )}
              </div>
              {lanes.length === 0 ? (
                <div className="text-slate-600 text-xs">No activity yet for this run.</div>
              ) : (
                <div className="space-y-1.5">
                  {lanes.map((a) => (
                    <AgentLog key={a} name={a} events={byAgent[a]} expandAll={expandAll}
                      active={isActive(run?.status) && run?.current_agent === a} done={doneAgents.has(a)} />
                  ))}
                </div>
              )}
            </div>

            {/* GATE REVIEW DETAIL (proposal / specs / team / validation / diff) */}
            {atGate && (
              <>
                {pkt.work_item?.body && <Section title="Report"><p className="whitespace-pre-wrap text-slate-300">{pkt.work_item.body}</p></Section>}

                {proposal.spec_id && (
                  <Section title="Proposed spec">
                    <div className="font-mono text-xs text-indigo-300 mb-1">{proposal.spec_id}</div>
                    {proposal.title && <div className="font-medium mb-1">{proposal.title}</div>}
                    <div className="mb-2 whitespace-pre-wrap">{proposal.behavior}</div>
                    {proposal.implements?.length > 0 && (
                      <div className="text-xs text-slate-400 mb-2">implements: {proposal.implements.join(", ")}</div>
                    )}
                    {proposal.tests?.length > 0 && proposal.tests.map((t, i) => (
                      <div key={i} className="text-xs text-slate-300 flex gap-1.5 mb-1">
                        <FlaskConical size={12} className="mt-0.5 shrink-0 text-slate-500" />
                        <span><span className="font-mono text-slate-400">{t.path || t.type}</span>{t.rubric ? <span className="whitespace-pre-wrap"> — {t.rubric}</span> : null}</span>
                      </div>
                    ))}
                    {proposal.notes && <div className="text-xs text-slate-500 mt-2 whitespace-pre-wrap">{proposal.notes}</div>}
                  </Section>
                )}

                {codePlan && !gate2 && !gate3 && (
                  <Section title="Planned code changes (read-only sketch — no code written yet)">
                    {codePlan.summary && <div className="text-sm text-slate-200 mb-1">{codePlan.summary}</div>}
                    {codePlan.approach && <div className="text-xs text-slate-400 mb-2 whitespace-pre-wrap">{codePlan.approach}</div>}
                    {codePlan.changes?.length > 0 && (
                      <div className="space-y-1 mb-2">
                        {codePlan.changes.map((c, i) => (
                          <div key={i} className="text-xs flex gap-1.5 items-baseline">
                            <span className={`text-[9px] uppercase px-1 rounded shrink-0 ${ACTION_CLS[c.action] || "bg-slate-700/60 text-slate-300"}`}>{c.action}</span>
                            <span className="font-mono text-indigo-300 shrink-0">{c.path}</span>
                            {c.what && <span className="text-slate-400">— {c.what}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                    {codePlan.new_modules?.length > 0 && (
                      <div className="text-xs text-slate-400 mb-1.5">
                        <span className="text-slate-500">new modules: </span>
                        {codePlan.new_modules.map((m, i) => <span key={i} className="font-mono text-emerald-300 mr-2">{m}</span>)}
                      </div>
                    )}
                    {codePlan.placement_notes?.length > 0 && (
                      <div className="border border-amber-700/40 bg-amber-900/15 rounded p-2 mb-1.5">
                        <div className="text-[11px] text-amber-300 font-medium mb-0.5">Placement / dependency-rule notes</div>
                        <ul className="list-disc ml-4 text-xs text-slate-300 space-y-0.5">
                          {codePlan.placement_notes.map((n, i) => <li key={i}>{n}</li>)}
                        </ul>
                      </div>
                    )}
                    {codePlan.risks?.length > 0 && (
                      <div className="text-xs mb-1"><span className="text-slate-500">risks: </span>
                        <ul className="list-disc ml-4 text-slate-300 space-y-0.5">{codePlan.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                      </div>
                    )}
                    {codePlan.open_questions?.length > 0 && (
                      <div className="text-xs"><span className="text-slate-500">open questions: </span>
                        <ul className="list-disc ml-4 text-slate-400 space-y-0.5">{codePlan.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
                      </div>
                    )}
                  </Section>
                )}

                {pkt.spec_tree?.length > 1 && (
                  <Section title={`Spec tree (${pkt.spec_tree.length} specs)`}>
                    {pkt.spec_tree.map((s, i) => (
                      <div key={i} className="text-xs mb-1.5">
                        <span className="font-mono text-indigo-300">{s.spec_id}</span>
                        <span className="text-slate-400"> — {s.title}</span>
                        {s.summary && <div className="text-slate-500 ml-2 mt-0.5">{s.summary}</div>}
                      </div>
                    ))}
                  </Section>
                )}

                {agents.length > 0 && (
                  <Section title={`The team (${agents.length} agents)`}>
                    <div className="space-y-1.5">
                      {agents.map((a) => <AgentPanel key={a.key} agent={a} />)}
                    </div>
                  </Section>
                )}

                {pkt.validation && (
                  <Section title="Validation (box 2)">
                    <span className={pkt.validation.passed ? "text-emerald-400" : "text-red-400"}>
                      {pkt.validation.passed ? "bound tests passed" : `FAILED${pkt.validation.reason ? " — " + pkt.validation.reason : ""}`}
                    </span>
                  </Section>
                )}

                {pkt.diff && (
                  <Section title="Diff">
                    <pre className="text-[11px] bg-black/40 rounded p-2 overflow-x-auto max-h-96 text-slate-300">{pkt.diff}</pre>
                  </Section>
                )}

                {pkt.feature?.branch && (
                  <div className="text-xs text-slate-500 flex items-center gap-1.5 mt-2"><GitBranch size={12} /> {pkt.feature.branch}</div>
                )}
              </>
            )}
          </div>
        )}
      </div>
      </div>
    </div>
  );
}
