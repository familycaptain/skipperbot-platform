import { useState, useEffect, useCallback, useRef } from "react";
import {
  Search, Plus, Car, Loader2, AlertTriangle, Wrench, CircleDot,
} from "lucide-react";

/**
 * Auto Maintenance List App — singleton for browsing vehicles.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey, isActive
 */
export default function AutoListApp({ appId, userId, context = {}, onOpenApp, refreshKey, isActive }) {
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  const loadVehicles = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchQuery.trim()) params.set("q", searchQuery.trim());
      const res = await fetch(`/api/apps/auto?${params}`);
      if (res.ok) {
        const data = await res.json();
        setVehicles(data.vehicles || []);
      }
    } catch {}
    setLoading(false);
  }, [searchQuery]);

  useEffect(() => { loadVehicles(); }, [loadVehicles]);

  // Auto-refresh from chat mutations
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    loadVehicles();
  }, [refreshKey]);

  // Reload when tab becomes active
  const wasActive = useRef(isActive);
  useEffect(() => {
    if (isActive && !wasActive.current) loadVehicles();
    wasActive.current = isActive;
  }, [isActive]);

  function openVehicle(v) {
    onOpenApp?.("auto-vehicle", { autoVehicleId: v.id, title: v.name });
  }

  async function handleCreateVehicle() {
    try {
      const res = await fetch("/api/apps/auto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ created_by: userId }),
      });
      if (res.ok) {
        const vehicle = await res.json();
        onOpenApp?.("auto-vehicle", { autoVehicleId: vehicle.id, title: vehicle.name, editing: true });
        loadVehicles();
      }
    } catch {}
  }

  const CONDITION_COLOR = {
    good: "bg-emerald-500", fair: "bg-yellow-500", worn: "bg-orange-500",
    needs_replacement: "bg-red-500", weak: "bg-orange-500",
    excellent: "bg-emerald-500", poor: "bg-red-500",
    all_working: "bg-emerald-500", issues: "bg-red-500",
    all_good: "bg-emerald-500", needs_attention: "bg-orange-500",
  };

  function ConditionDot({ label, value }) {
    return (
      <span title={`${label}: ${value}`} className="flex items-center gap-0.5 text-[10px] text-slate-500">
        <span className={`w-1.5 h-1.5 rounded-full ${CONDITION_COLOR[value] || "bg-slate-600"}`} />
        {label}
      </span>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-2 px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <div className="relative flex-1 min-w-0 max-w-xs">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search vehicles..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-slate-800/60 text-sm text-white pl-7 pr-2 py-1 rounded border border-slate-700 outline-none focus:border-indigo-500"
            />
          </div>
        </div>
        <button
          onClick={handleCreateVehicle}
          className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-white rounded transition-colors shrink-0"
          title="Add Vehicle"
        >
          <Plus size={12} /> <span className="hidden sm:inline">Add Vehicle</span>
        </button>
      </div>

      {/* Vehicle list */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2">
        {loading && vehicles.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-slate-400">
            <Loader2 size={18} className="animate-spin mr-2" /> Loading vehicles...
          </div>
        ) : vehicles.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500 text-sm">
            <Car size={32} className="mb-2 opacity-40" />
            {searchQuery ? "No vehicles match your search." : "No vehicles tracked yet. Click + Add Vehicle to start!"}
          </div>
        ) : (
          vehicles.map((v) => {
            const summary = v._summary || {};
            const cond = summary.latest_condition;
            const issueCount = summary.open_issue_count || 0;
            const nextSvc = summary.next_service;
            return (
              <button
                key={v.id}
                onClick={() => openVehicle(v)}
                className="w-full text-left bg-slate-800/40 hover:bg-slate-800/70 border border-slate-700/50 hover:border-slate-600 rounded-lg p-3 transition-colors group"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium text-white truncate group-hover:text-indigo-300 transition-colors">
                        {[v.year, v.make, v.model, v.trim_level].filter(Boolean).join(" ") || v.name || "Untitled"}
                      </h3>
                      {issueCount > 0 && (
                        <span className="flex items-center gap-0.5 px-1.5 py-0 bg-red-600/20 text-red-400 rounded text-[10px] font-medium shrink-0">
                          <AlertTriangle size={9} /> {issueCount}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-xs text-slate-500">
                      {v.odometer && (
                        <span>{v.odometer.toLocaleString()} mi</span>
                      )}
                      {v.license_plate && (
                        <span className="px-1.5 py-0 bg-slate-700/50 rounded text-[10px]">{v.license_plate}</span>
                      )}
                      {nextSvc && nextSvc.next_due_date && (
                        <span className="flex items-center gap-1">
                          <Wrench size={10} />
                          {nextSvc.service_type} due {nextSvc.next_due_date}
                        </span>
                      )}
                    </div>
                  </div>
                  {/* Condition dots */}
                  {cond && (
                    <div className="flex flex-col gap-0.5 shrink-0 pt-0.5">
                      <ConditionDot label="Brk" value={cond.brakes} />
                      <ConditionDot label="Tire" value={cond.tires} />
                      <ConditionDot label="Bat" value={cond.battery} />
                    </div>
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
