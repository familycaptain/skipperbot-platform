import { useState, useEffect, useCallback } from "react";
import { Workflow, Loader2, CheckCircle2, XCircle, RefreshCw, GitBranch } from "lucide-react";
import { hasAnyRole } from "../../../web/src/utils/roles";

const API = "/api/apps/evolve";

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" }, ...opts,
  });
  if (!res.ok) {
    let d = "";
    try { d = (await res.json()).detail || ""; } catch {}
    throw new Error(d || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

const REC_COLOR = {
  approve: "text-emerald-300 bg-emerald-900/30 border-emerald-700/40",
  change: "text-amber-300 bg-amber-900/30 border-amber-700/40",
  reject: "text-red-300 bg-red-900/30 border-red-700/40",
};

function Section({ title, children }) {
  if (!children) return null;
  return (
    <div className="mb-4">
      <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{title}</div>
      <div className="text-sm text-slate-200">{children}</div>
    </div>
  );
}

export default function EvolveApp({ userId, userRole, refreshKey, onTitle }) {
  const isParent = hasAnyRole(userRole, ["admin", "parent"]);
  const [gates, setGates] = useState([]);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { onTitle?.("Evolve"); }, [onTitle]);

  const loadGates = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const r = await apiFetch(`/gates?status=`);
      setGates(r.gates || []);
      if (!sel && r.gates?.length) setSel(r.gates[0].instance_id);
    } catch (e) { setError(String(e.message || e)); }
    finally { setLoading(false); }
  }, [sel]);

  useEffect(() => { loadGates(); }, [refreshKey]); // eslint-disable-line

  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    apiFetch(`/gates/${sel}`).then(setDetail).catch((e) => setError(String(e.message || e)));
  }, [sel]);

  async function decide(decision) {
    if (!sel) return;
    setBusy(decision); setError("");
    try {
      await apiFetch(`/gates/${sel}/decision`, {
        method: "POST", body: JSON.stringify({ decision }),
      });
      await loadGates();
      setDetail(await apiFetch(`/gates/${sel}`));
    } catch (e) { setError(String(e.message || e)); }
    finally { setBusy(""); }
  }

  const pkt = detail?.packet || {};
  const rec = pkt.recommendation || {};
  const proposal = pkt.proposal || {};
  const reviews = pkt.reviews || {};
  const waiting = gates.filter((g) => g.status === "waiting").length;

  return (
    <div className="flex h-full w-full bg-zinc-950 text-zinc-100">
      {/* LEFT: queue */}
      <div className="w-72 shrink-0 border-r border-slate-800 flex flex-col">
        <div className="flex items-center justify-between px-3 h-10 border-b border-slate-800 shrink-0">
          <span className="text-sm font-medium flex items-center gap-1.5">
            <Workflow size={14} /> Work queue
            {waiting > 0 && <span className="text-[10px] bg-indigo-600 rounded-full px-1.5">{waiting}</span>}
          </span>
          <button onClick={loadGates} className="text-slate-500 hover:text-white" title="Refresh">
            {loading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={13} />}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {gates.length === 0 && !loading && (
            <div className="text-slate-600 text-sm text-center mt-8 px-4">
              No gates yet. Evolve pushes work here when it needs your decision.
            </div>
          )}
          {gates.map((g) => {
            const active = g.instance_id === sel;
            return (
              <button key={g.instance_id} onClick={() => setSel(g.instance_id)}
                className={`w-full text-left px-3 py-2.5 border-b border-slate-800/60 ${
                  active ? "bg-slate-800/70" : "hover:bg-slate-900/60"}`}>
                <div className="flex items-center gap-1.5 mb-0.5">
                  <span className={`text-[10px] px-1.5 rounded ${g.gate === "gate2"
                    ? "bg-violet-900/50 text-violet-300" : "bg-sky-900/50 text-sky-300"}`}>
                    {g.gate === "gate2" ? "GATE 2" : "GATE 1"}
                  </span>
                  {g.status === "decided"
                    ? <span className="text-[10px] text-slate-500">{g.decision}d</span>
                    : <span className="text-[10px] text-amber-400">waiting</span>}
                </div>
                <div className="text-sm leading-snug line-clamp-2">{g.title || g.instance_id}</div>
                {g.rec_action && (
                  <div className="text-[11px] text-slate-500 mt-0.5">→ recommend: {g.rec_action}</div>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* RIGHT: packet */}
      <div className="flex-1 min-w-0 overflow-y-auto p-4">
        {error && <div className="text-red-300 bg-red-900/20 p-2 rounded mb-3 text-sm">{error}</div>}
        {!detail && <div className="text-slate-600 mt-10 text-center">Select a gate to review.</div>}
        {detail && (
          <div className="max-w-3xl">
            <div className="flex items-center gap-2 mb-1 text-xs text-slate-500">
              <span>{detail.gate === "gate2" ? "Gate 2 · approve result" : "Gate 1 · approve intent"}</span>
              <span>·</span><span className="font-mono">{detail.instance_id}</span>
            </div>
            <h2 className="text-lg font-semibold mb-3">{pkt.work_item?.title || detail.title}</h2>

            {/* Recommendation — always leads */}
            <div className={`border rounded-lg p-3 mb-4 ${REC_COLOR[rec.action] || "bg-slate-800/40 border-slate-700"}`}>
              <div className="text-[11px] uppercase tracking-wide opacity-70">Recommendation</div>
              <div className="font-semibold capitalize">{rec.action || "review"}</div>
              <div className="text-sm opacity-90 mt-0.5">{rec.why || rec.rationale}</div>
            </div>

            {/* Decision buttons */}
            {detail.status === "waiting" ? (
              isParent ? (
                <div className="flex gap-2 mb-5">
                  <button disabled={!!busy} onClick={() => decide("approve")}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-700 hover:bg-emerald-600 text-sm disabled:opacity-50">
                    {busy === "approve" ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />} Approve
                  </button>
                  <button disabled={!!busy} onClick={() => decide("change")}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-700 hover:bg-amber-600 text-sm disabled:opacity-50">
                    {busy === "change" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Change
                  </button>
                  <button disabled={!!busy} onClick={() => decide("reject")}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-red-800 hover:bg-red-700 text-sm disabled:opacity-50">
                    {busy === "reject" ? <Loader2 size={14} className="animate-spin" /> : <XCircle size={14} />} Reject
                  </button>
                </div>
              ) : <div className="text-xs text-slate-500 mb-5">A parent or admin decides this gate.</div>
            ) : (
              <div className="text-sm text-emerald-300 mb-5">
                Decided: <b>{detail.decision}</b> by {detail.decided_by}
              </div>
            )}

            {pkt.work_item?.body && <Section title="Report"><p className="whitespace-pre-wrap text-slate-300">{pkt.work_item.body}</p></Section>}

            {proposal.spec_id && (
              <Section title="Proposed spec">
                <div className="font-mono text-xs text-indigo-300 mb-1">{proposal.spec_id}</div>
                <div className="mb-1">{proposal.behavior}</div>
                {proposal.implements?.length > 0 && (
                  <ul className="text-xs text-slate-400 list-disc ml-5">
                    {proposal.implements.map((x, i) => <li key={i} className="font-mono">{x}</li>)}
                  </ul>
                )}
              </Section>
            )}

            {Object.keys(reviews).some((k) => reviews[k]) && (
              <Section title="Reviews">
                <div className="space-y-1">
                  {Object.entries(reviews).filter(([, v]) => v).map(([k, v]) => (
                    <div key={k} className="text-xs flex gap-2">
                      <span className="w-24 text-slate-500">{k}</span>
                      <span className={v.approve === false || v.sound === false ? "text-amber-400" : "text-emerald-400"}>
                        {v.approve === false ? "concerns" : v.sound === false ? "audit findings" : "ok"}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            {pkt.validation && (
              <Section title="Validation (box 2)">
                <span className={pkt.validation.passed ? "text-emerald-400" : "text-red-400"}>
                  {pkt.validation.passed ? "bound tests passed" : "FAILED"}
                </span>
              </Section>
            )}

            {pkt.diff && (
              <Section title="Diff">
                <pre className="text-[11px] bg-black/40 rounded p-2 overflow-x-auto max-h-96 text-slate-300">{pkt.diff}</pre>
              </Section>
            )}

            {pkt.feature?.branch && (
              <div className="text-xs text-slate-500 flex items-center gap-1.5 mt-2">
                <GitBranch size={12} /> {pkt.feature.branch}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
