import { useState, useEffect, useCallback, useRef } from "react";
import { Workflow, Loader2, CheckCircle2, XCircle, RefreshCw, GitBranch, FlaskConical, Activity, Circle } from "lucide-react";
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
  spec: "Spec-author", crit: "Spec-audit", "spec-audit": "Spec-audit", triage: "Triage",
  "vision-fit": "Vision-fit", vision: "Vision-fit", prioritize: "Prioritize", prio: "Prioritize",
  security: "Security", architecture: "Architecture", interop: "Interop", ux: "UX / UI",
  serialize: "Serialize", implement: "Implement", validate: "Validate", merge: "Merge",
  "review-packet": "Review packet", packet: "Review packet",
};
const KIND_CLS = {
  tool: "text-slate-400", emit: "text-indigo-300", agent_start: "text-sky-300",
  agent_end: "text-emerald-300", node: "text-slate-300", info: "text-slate-500",
  error: "text-red-300",
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

// one per-agent live log lane
function AgentLog({ name, events, active, done }) {
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "nearest" }); }, [events.length]);
  return (
    <div className={`border rounded-md ${active ? "border-sky-600/60" : "border-slate-800"}`}>
      <div className="flex items-center gap-1.5 px-2.5 py-1 border-b border-slate-800/60">
        {active ? <Circle size={8} className="text-sky-400 fill-sky-400 animate-pulse" />
          : done ? <CheckCircle2 size={11} className="text-emerald-500" />
          : <Circle size={8} className="text-slate-600" />}
        <span className="text-xs font-medium">{AGENT_LABEL[name] || name}</span>
        <span className="text-[10px] text-slate-500 ml-auto">{active ? "active" : done ? "done" : "idle"}</span>
      </div>
      <div className="max-h-40 overflow-y-auto px-2.5 py-1.5 font-mono text-[11px] leading-relaxed bg-black/30">
        {events.map((e) => (
          <div key={e.id} className={`whitespace-pre-wrap break-words ${KIND_CLS[e.kind] || "text-slate-400"}`}>{e.message}</div>
        ))}
        <div ref={endRef} />
      </div>
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
  const lastId = useRef(0);
  const selRef = useRef(null);

  useEffect(() => { onTitle?.("Evolve"); }, [onTitle]);
  useEffect(() => { selRef.current = sel; }, [sel]);

  const loadRuns = useCallback(async () => {
    try {
      const r = await apiFetch(`/runs`);
      const rows = r.runs || [];
      setRuns(rows);
      if (!selRef.current && rows.length) setSel(rows[0].instance_id);
    } catch (e) { setError(String(e.message || e)); }
  }, []);

  // poll the runs list
  useEffect(() => {
    loadRuns();
    const t = setInterval(loadRuns, POLL_MS);
    return () => clearInterval(t);
  }, [loadRuns, refreshKey]);

  // when the selection changes: reset the stream + fetch the gate packet if one exists
  useEffect(() => {
    lastId.current = 0; setEvents([]); setDetail(null);
    if (!sel) return;
    apiFetch(`/gates/${sel}`).then(setDetail).catch((e) => { if (e.status !== 404) setError(String(e.message || e)); });
  }, [sel]);

  // tail the selected run's activity stream
  useEffect(() => {
    if (!sel) return;
    let alive = true;
    const tick = async () => {
      try {
        const r = await apiFetch(`/runs/${sel}/events?since=${lastId.current}`);
        if (!alive) return;
        if (r.run) setRun(r.run);
        if (r.events?.length) {
          lastId.current = r.last;
          setEvents((prev) => [...prev, ...r.events]);
        }
      } catch { /* best-effort */ }
    };
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(t); };
  }, [sel]);

  async function decide(decision) {
    if (!sel) return;
    setBusy(decision); setError("");
    try {
      await apiFetch(`/gates/${sel}/decision`, { method: "POST", body: JSON.stringify({ decision }) });
      setDetail(await apiFetch(`/gates/${sel}`).catch(() => null));
      loadRuns();
    } catch (e) { setError(String(e.message || e)); }
    finally { setBusy(""); }
  }

  const pkt = detail?.packet || {};
  const rec = pkt.recommendation || {};
  const proposal = pkt.proposal || {};
  const agents = pkt.agents || [];
  const atGate = detail?.status === "waiting";
  const needsYou = runs.filter((r) => r.status === "waiting").length;

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
    <div className="flex h-full w-full bg-zinc-950 text-zinc-100">
      {/* LEFT: runs */}
      <div className="w-72 shrink-0 border-r border-slate-800 flex flex-col">
        <div className="flex items-center justify-between px-3 h-10 border-b border-slate-800 shrink-0">
          <span className="text-sm font-medium flex items-center gap-1.5">
            <Workflow size={14} /> Runs
            {needsYou > 0 && <span className="text-[10px] bg-indigo-600 rounded-full px-1.5" title="need your decision">{needsYou}</span>}
          </span>
          <span className="text-[10px] text-slate-600 flex items-center gap-1"><Activity size={11} className="text-sky-500" /> live</span>
        </div>
        <div className="flex-1 overflow-y-auto">
          {runs.length === 0 && (
            <div className="text-slate-600 text-sm text-center mt-8 px-4">No runs yet. Ingested issues and their builds show up here live.</div>
          )}
          {runs.map((g) => {
            const active = g.instance_id === sel;
            const st = STATUS[g.status] || { cls: "bg-slate-700/60 text-slate-300", label: g.status };
            return (
              <button key={g.instance_id} onClick={() => setSel(g.instance_id)}
                className={`w-full text-left px-3 py-2.5 border-b border-slate-800/60 ${active ? "bg-slate-800/70" : "hover:bg-slate-900/60"}`}>
                <div className="flex items-center gap-1.5 mb-0.5">
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
              </button>
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
            </div>
            <h2 className="text-lg font-semibold mb-3">{run?.title || pkt.work_item?.title || sel}</h2>

            {/* GATE REVIEW (only when parked at a human gate) */}
            {atGate && (
              <>
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

                {isParent ? (
                  <div className="flex gap-2 mb-5">
                    <button disabled={!!busy} onClick={() => decide("approve")} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-700 hover:bg-emerald-600 text-sm disabled:opacity-50">
                      {busy === "approve" ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Approve
                    </button>
                    <button disabled={!!busy} onClick={() => decide("change")} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-700 hover:bg-amber-600 text-sm disabled:opacity-50">
                      {busy === "change" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Change
                    </button>
                    <button disabled={!!busy} onClick={() => decide("reject")} className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-red-800 hover:bg-red-700 text-sm disabled:opacity-50">
                      {busy === "reject" ? <Loader2 size={14} className="animate-spin" /> : <XCircle size={14} />} Reject
                    </button>
                  </div>
                ) : <div className="text-xs text-slate-500 mb-5">A parent or admin decides this gate.</div>}

                {pkt.decisions_needed?.length > 0 && (
                  <Section title="Decisions for you">
                    {pkt.decisions_needed.map((d, i) => (
                      <div key={i} className="border border-sky-700/40 bg-sky-900/15 rounded p-2 mb-1.5">
                        <div className="text-slate-200">{d.question}</div>
                        {d.options?.length > 0 && <div className="text-xs text-slate-400 mt-0.5">options: {d.options.join(" · ")}</div>}
                        {d.recommendation && <div className="text-xs text-sky-300 mt-0.5">→ recommends: {d.recommendation}</div>}
                      </div>
                    ))}
                  </Section>
                )}
              </>
            )}

            {/* LIVE ACTIVITY — per-agent scrolling logs */}
            <Section title={`Live activity${run?.current_agent && isActive(run?.status) ? ` · ⚙ ${AGENT_LABEL[run.current_agent] || run.current_agent}` : ""}`}>
              {lanes.length === 0 ? (
                <div className="text-slate-600 text-xs">No activity yet for this run.</div>
              ) : (
                <div className="space-y-1.5">
                  {lanes.map((a) => (
                    <AgentLog key={a} name={a} events={byAgent[a]}
                      active={isActive(run?.status) && run?.current_agent === a} done={doneAgents.has(a)} />
                  ))}
                </div>
              )}
            </Section>

            {/* GATE REVIEW DETAIL (proposal / specs / team / validation / diff) */}
            {atGate && (
              <>
                {pkt.work_item?.body && <Section title="Report"><p className="whitespace-pre-wrap text-slate-300">{pkt.work_item.body}</p></Section>}

                {proposal.spec_id && (
                  <Section title="Proposed spec">
                    <div className="font-mono text-xs text-indigo-300 mb-1">{proposal.spec_id}</div>
                    <div className="mb-2">{proposal.behavior}</div>
                    {proposal.tests?.length > 0 && proposal.tests.map((t, i) => (
                      <div key={i} className="text-xs text-slate-300 flex gap-1.5 mb-1">
                        <FlaskConical size={12} className="mt-0.5 shrink-0 text-slate-500" />
                        <span><span className="font-mono text-slate-400">{t.path || t.type}</span>{t.rubric ? ` — ${t.rubric}` : ""}</span>
                      </div>
                    ))}
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
  );
}
