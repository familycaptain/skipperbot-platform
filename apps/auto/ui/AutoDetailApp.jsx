import { useState, useEffect, useCallback, useRef } from "react";
import {
  Edit3, Save, Trash2, Plus, X, Wrench, AlertTriangle,
  TrendingUp, Activity, Loader2, RotateCcw, Car, CalendarClock, CheckCircle2, PenLine, User, Droplet, Camera,
} from "lucide-react";

/**
 * Auto Maintenance Detail App — view/edit a single vehicle with tabs.
 *
 * Props: appId, userId, context, onTitle, onOpenApp, refreshKey
 * Context: { autoVehicleId, editing? }
 */

const TABS = [
  { id: "maintenance", label: "Maintenance", icon: CalendarClock },
  { id: "services", label: "Service History", icon: Wrench },
  { id: "issues", label: "Issues", icon: AlertTriangle },
  { id: "condition", label: "Condition", icon: Activity },
  { id: "value", label: "Value", icon: TrendingUp },
];

const SEVERITY_COLORS = {
  critical: "bg-red-600 text-on-accent",
  major: "bg-orange-600 text-on-accent",
  moderate: "bg-yellow-600 text-[#000]",
  minor: "surface-raised text-default",
};

const COND_COLORS = {
  good: "text-emerald-400", fair: "text-yellow-400", worn: "text-orange-400",
  needs_replacement: "text-red-400", weak: "text-orange-400",
  excellent: "text-emerald-400", poor: "text-red-400",
  all_working: "text-emerald-400", issues: "text-red-400",
  all_good: "text-emerald-400", needs_attention: "text-orange-400",
};

export default function AutoDetailApp({ appId, userId, context = {}, onTitle, onOpenApp, refreshKey }) {
  const [vehicle, setVehicle] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState(!!context.editing);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [activeTab, setActiveTab] = useState("maintenance");

  const [form, setForm] = useState({});

  // Sub-data
  const [services, setServices] = useState([]);
  const [issues, setIssues] = useState([]);
  const [conditions, setConditions] = useState([]);
  const [valuations, setValuations] = useState([]);

  // Add-form states
  const [maintenance, setMaintenance] = useState([]);
  const [showAddService, setShowAddService] = useState(false);
  const [showAddIssue, setShowAddIssue] = useState(false);
  const [showAddCondition, setShowAddCondition] = useState(false);
  const [showAddValuation, setShowAddValuation] = useState(false);
  const [showAddMaint, setShowAddMaint] = useState(false);

  const vehicleId = context.autoVehicleId || null;

  const loadVehicle = useCallback(async (id) => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/apps/auto/${id}`);
      if (res.ok) {
        const data = await res.json();
        setVehicle(data);
        onTitle?.(data.name || "Vehicle");
        setForm(buildForm(data));
      }
    } catch {}
    setLoading(false);
  }, [onTitle]);

  const loadSubData = useCallback(async (id) => {
    if (!id) return;
    const [svcRes, issRes, condRes, valRes, maintRes] = await Promise.all([
      fetch(`/api/apps/auto/${id}/services`),
      fetch(`/api/apps/auto/${id}/issues`),
      fetch(`/api/apps/auto/${id}/conditions`),
      fetch(`/api/apps/auto/${id}/valuations`),
      fetch(`/api/apps/auto/${id}/maintenance`),
    ]);
    if (svcRes.ok) { const d = await svcRes.json(); setServices(d.services || []); }
    if (issRes.ok) { const d = await issRes.json(); setIssues(d.issues || []); }
    if (condRes.ok) { const d = await condRes.json(); setConditions(d.conditions || []); }
    if (valRes.ok) { const d = await valRes.json(); setValuations(d.valuations || []); }
    if (maintRes.ok) { const d = await maintRes.json(); setMaintenance(d.schedules || []); }
  }, []);

  useEffect(() => {
    if (vehicleId) {
      loadVehicle(vehicleId);
      loadSubData(vehicleId);
      setEditing(!!context.editing);
      setDirty(false);
    }
  }, [vehicleId]);

  useEffect(() => {
    if (refreshKey === undefined || refreshKey === 0) return;
    if (vehicleId && !dirty) { loadVehicle(vehicleId); loadSubData(vehicleId); }
  }, [refreshKey]);

  function buildForm(v) {
    return {
      make: v.make || "",
      model: v.model || "",
      trim_level: v.trim_level || "",
      year: v.year ?? "",
      color: v.color || "",
      vin: v.vin || "",
      license_plate: v.license_plate || "",
      odometer: v.odometer ?? "",
      owner: v.owner || "",
      responsible_user: v.responsible_user || "",
      notes: v.notes || "",
    };
  }

  function updateForm(key, value) {
    setForm(prev => ({ ...prev, [key]: value }));
    setDirty(true);
  }

  async function handleSave() {
    if (!vehicleId) return;
    setSaving(true);
    try {
      const body = {
        make: form.make || null,
        model: form.model || null,
        trim_level: form.trim_level || null,
        year: form.year ? parseInt(form.year, 10) || null : null,
        color: form.color || null,
        vin: form.vin || null,
        license_plate: form.license_plate || null,
        odometer: form.odometer ? parseInt(form.odometer, 10) || null : null,
        owner: form.owner || null,
        responsible_user: form.responsible_user || null,
        notes: form.notes || null,
      };
      const res = await fetch(`/api/apps/auto/${vehicleId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const updated = await res.json();
        setVehicle(updated);
        setForm(buildForm(updated));
        onTitle?.(updated.name || "Vehicle");
        setEditing(false);
        setDirty(false);
      }
    } catch {}
    setSaving(false);
  }

  async function handleDelete() {
    if (!vehicleId) return;
    try {
      const res = await fetch(`/api/apps/auto/${vehicleId}`, { method: "DELETE" });
      if (res.ok) onOpenApp?.("auto");
    } catch {}
  }

  function handleCancel() {
    if (vehicle) setForm(buildForm(vehicle));
    setEditing(false);
    setDirty(false);
  }

  if (!vehicleId) {
    return <div className="flex items-center justify-center h-full text-faint text-sm">No vehicle selected.</div>;
  }
  if (loading || !vehicle) {
    return <div className="flex items-center justify-center h-full text-muted"><Loader2 size={18} className="animate-spin mr-2" /> Loading vehicle...</div>;
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 h-10 surface-panel border-b border-subtle shrink-0">
        <h2 className="text-sm font-medium text-default truncate">
          {editing ? "Editing " : ""}{vehicle.year ? `${vehicle.year} ` : ""}{vehicle.name}
        </h2>
        <div className="flex items-center gap-1.5">
          {editing ? (
            <>
              <button onClick={handleCancel} className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)] rounded"><RotateCcw size={12} /> Cancel</button>
              <button onClick={handleSave} disabled={saving} className="flex items-center gap-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded disabled:opacity-50"><Save size={12} /> {saving ? "Saving..." : "Save"}</button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)} className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)] rounded"><Edit3 size={12} /> Edit</button>
              {confirmDelete ? (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-red-400">Delete?</span>
                  <button onClick={handleDelete} className="px-2 py-0.5 text-xs bg-red-600 hover:bg-red-500 text-on-accent rounded">Yes</button>
                  <button onClick={() => setConfirmDelete(false)} className="px-2 py-0.5 text-xs surface-raised hover:bg-[var(--ds-raised)] text-default rounded">No</button>
                </div>
              ) : (
                <button onClick={() => setConfirmDelete(true)} className="flex items-center gap-1 px-2 py-1 text-xs text-muted hover:text-red-400 hover:bg-[var(--ds-raised)] rounded"><Trash2 size={12} /></button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {editing ? (
          <EditForm form={form} updateForm={updateForm} />
        ) : (
          <>
            {/* Vehicle info header */}
            <div className="px-4 py-3 surface-panel border-b border-subtle">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm text-default">
                {vehicle.make && <span>{vehicle.make} {vehicle.model}{vehicle.trim_level ? ` ${vehicle.trim_level}` : ""}</span>}
                {vehicle.color && <span>{vehicle.color}</span>}
                {vehicle.odometer && <span>{vehicle.odometer.toLocaleString()} mi</span>}
                {vehicle.license_plate && <span className="px-1.5 py-0 surface-raised rounded text-xs">{vehicle.license_plate}</span>}
                {vehicle.vin && <span className="text-xs text-faint break-all">VIN: {vehicle.vin}</span>}
                {(vehicle.owner || vehicle.created_by) && (
                  <span className="flex items-center gap-1 text-xs text-muted"><User size={10} /> Owner: {vehicle.owner || vehicle.created_by}</span>
                )}
                {vehicle.responsible_user && (
                  <span className="flex items-center gap-1 text-xs text-amber-400"><User size={10} /> Responsible: {vehicle.responsible_user}</span>
                )}
              </div>
            </div>

            {/* Tabs */}
            <div className="flex items-center gap-1 px-3 py-2 surface-panel border-b border-subtle overflow-x-auto taskbar-scroll">
              {TABS.map(t => {
                const Icon = t.icon;
                const count = t.id === "issues" ? issues.filter(i => i.status !== "fixed").length
                : t.id === "maintenance" ? maintenance.filter(m => m.next_due && new Date(m.next_due) < new Date()).length
                : 0;
                return (
                  <button key={t.id} onClick={() => setActiveTab(t.id)}
                    className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded transition-colors whitespace-nowrap shrink-0 ${
                      activeTab === t.id ? "bg-indigo-600 text-on-accent" : "text-muted hover:text-[var(--ds-text)] hover:bg-[var(--ds-raised)]"
                    }`}>
                    <Icon size={12} /> {t.label}
                    {count > 0 && <span className="ml-0.5 px-1 py-0 bg-red-600/30 text-red-300 rounded text-[10px]">{count}</span>}
                  </button>
                );
              })}
            </div>

            {/* Tab content */}
            <div className="p-4">
              {activeTab === "maintenance" && <MaintenanceTab maintenance={maintenance} vehicleId={vehicleId} vehicle={vehicle} userId={userId} show={showAddMaint} setShow={setShowAddMaint} onRefresh={() => { loadSubData(vehicleId); loadVehicle(vehicleId); }} />}
              {activeTab === "services" && <ServicesTab services={services} vehicleId={vehicleId} userId={userId} show={showAddService} setShow={setShowAddService} onRefresh={() => { loadSubData(vehicleId); loadVehicle(vehicleId); }} />}
              {activeTab === "issues" && <IssuesTab issues={issues} vehicleId={vehicleId} userId={userId} show={showAddIssue} setShow={setShowAddIssue} onRefresh={() => loadSubData(vehicleId)} />}
              {activeTab === "condition" && <ConditionTab conditions={conditions} vehicleId={vehicleId} userId={userId} show={showAddCondition} setShow={setShowAddCondition} onRefresh={() => { loadSubData(vehicleId); loadVehicle(vehicleId); }} />}
              {activeTab === "value" && <ValueTab valuations={valuations} vehicleId={vehicleId} userId={userId} show={showAddValuation} setShow={setShowAddValuation} onRefresh={() => loadSubData(vehicleId)} />}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* ── Edit Form ── */
function EditForm({ form, updateForm }) {
  const [users, setUsers] = useState([]);
  useEffect(() => {
    fetch("/api/users").then(r => r.ok ? r.json() : []).then(d => setUsers(d)).catch(() => {});
  }, []);
  return (
    <div className="p-4 space-y-4 max-w-lg">
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        <div>
          <label className="block text-xs text-muted mb-1">Year</label>
          <input type="number" value={form.year} onChange={e => updateForm("year", e.target.value)}
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Make</label>
          <input value={form.make} onChange={e => updateForm("make", e.target.value)}
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Model</label>
          <input value={form.model} onChange={e => updateForm("model", e.target.value)}
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Trim</label>
          <input value={form.trim_level} onChange={e => updateForm("trim_level", e.target.value)} placeholder="e.g. SV, EX-L"
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Color</label>
          <input value={form.color} onChange={e => updateForm("color", e.target.value)} placeholder="e.g. White"
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted mb-1">Odometer</label>
          <input type="number" value={form.odometer} onChange={e => updateForm("odometer", e.target.value)} placeholder="Miles"
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">License Plate</label>
          <input value={form.license_plate} onChange={e => updateForm("license_plate", e.target.value)}
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
        </div>
      </div>
      <div>
        <label className="block text-xs text-muted mb-1">VIN</label>
        <input value={form.vin} onChange={e => updateForm("vin", e.target.value)}
          className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted mb-1">Owner</label>
          <select value={form.owner} onChange={e => updateForm("owner", e.target.value)}
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500">
            <option value="">(default — creator)</option>
            {users.map(u => <option key={u.name} value={u.name}>{u.display_name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted mb-1">Responsible User</label>
          <select value={form.responsible_user} onChange={e => updateForm("responsible_user", e.target.value)}
            className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500">
            <option value="">(default — creator)</option>
            {users.map(u => <option key={u.name} value={u.name}>{u.display_name}</option>)}
          </select>
        </div>
      </div>
      <div>
        <label className="block text-xs text-muted mb-1">Notes</label>
        <textarea value={form.notes} onChange={e => updateForm("notes", e.target.value)} rows={3}
          className="w-full surface-card text-default text-sm px-3 py-2 rounded border border-subtle outline-none focus:border-indigo-500 resize-none" />
      </div>
    </div>
  );
}

/* ── Services Tab ── */
function ServicesTab({ services, vehicleId, userId, show, setShow, onRefresh }) {
  const [svcForm, setSvcForm] = useState({ service_type: "", date_performed: "", odometer_at_service: "", cost: "", shop_name: "", description: "", notes: "" });
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  function startEdit(svc) {
    setEditId(svc.id);
    setEditForm({
      service_type: svc.service_type || "",
      date_performed: svc.date_performed || "",
      odometer_at_service: svc.odometer_at_service ?? "",
      cost: svc.cost ?? "",
      shop_name: svc.shop_name || "",
      description: svc.description || "",
      notes: svc.notes || "",
    });
  }

  async function handleEditSave() {
    if (!editForm.service_type.trim()) return;
    setSaving(true);
    await fetch(`/api/apps/auto/services/${editId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        service_type: editForm.service_type,
        date_performed: editForm.date_performed || undefined,
        odometer_at_service: editForm.odometer_at_service ? parseInt(editForm.odometer_at_service) : undefined,
        cost: editForm.cost !== "" ? parseFloat(editForm.cost) : undefined,
        shop_name: editForm.shop_name,
        description: editForm.description,
        notes: editForm.notes,
      }),
    });
    setSaving(false);
    setEditId(null);
    onRefresh();
  }

  async function handleAdd(e) {
    e.preventDefault();
    if (!svcForm.service_type.trim()) return;
    try {
      await fetch(`/api/apps/auto/${vehicleId}/services`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vehicle_id: vehicleId,
          service_type: svcForm.service_type,
          date_performed: svcForm.date_performed || undefined,
          odometer_at_service: svcForm.odometer_at_service ? parseInt(svcForm.odometer_at_service) : undefined,
          cost: svcForm.cost ? parseFloat(svcForm.cost) : undefined,
          shop_name: svcForm.shop_name,
          description: svcForm.description,
          notes: svcForm.notes,
          created_by: userId,
        }),
      });
      setSvcForm({ service_type: "", date_performed: "", odometer_at_service: "", cost: "", shop_name: "", description: "", notes: "" });
      setShow(false);
      onRefresh();
    } catch {}
  }

  async function handleDeleteSvc(svcId) {
    await fetch(`/api/apps/auto/services/${svcId}`, { method: "DELETE" });
    onRefresh();
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs text-faint uppercase tracking-wider">Service History ({services.length})</h4>
        <button onClick={() => setShow(!show)} className="flex items-center gap-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded"><Plus size={12} /> Log Service</button>
      </div>
      {show && (
        <form onSubmit={handleAdd} className="surface-card border border-subtle rounded-lg p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input value={svcForm.service_type} onChange={e => setSvcForm(p => ({...p, service_type: e.target.value}))} placeholder="Service type *" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input type="date" value={svcForm.date_performed} onChange={e => setSvcForm(p => ({...p, date_performed: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <input type="number" value={svcForm.odometer_at_service} onChange={e => setSvcForm(p => ({...p, odometer_at_service: e.target.value}))} placeholder="Mileage" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input type="number" step="0.01" value={svcForm.cost} onChange={e => setSvcForm(p => ({...p, cost: e.target.value}))} placeholder="Cost $" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input value={svcForm.shop_name} onChange={e => setSvcForm(p => ({...p, shop_name: e.target.value}))} placeholder="Shop / DIY" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <input value={svcForm.description} onChange={e => setSvcForm(p => ({...p, description: e.target.value}))} placeholder="Description" className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          <div className="flex justify-end gap-1">
            <button type="button" onClick={() => setShow(false)} className="px-2 py-1 text-xs text-muted hover:text-[var(--ds-text)]">Cancel</button>
            <button type="submit" className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded">Save</button>
          </div>
        </form>
      )}
      {services.length === 0 ? (
        <p className="text-sm text-faint italic">No service records yet.</p>
      ) : (
        <div className="space-y-1.5">
          {services.map(s => editId === s.id ? (
            <div key={s.id} className="surface-card border border-indigo-600/50 rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <input value={editForm.service_type} onChange={e => setEditForm(p => ({...p, service_type: e.target.value}))} placeholder="Service type *" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                <input type="date" value={editForm.date_performed} onChange={e => setEditForm(p => ({...p, date_performed: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <input type="number" value={editForm.odometer_at_service} onChange={e => setEditForm(p => ({...p, odometer_at_service: e.target.value}))} placeholder="Mileage" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                <input type="number" step="0.01" value={editForm.cost} onChange={e => setEditForm(p => ({...p, cost: e.target.value}))} placeholder="Cost $" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                <input value={editForm.shop_name} onChange={e => setEditForm(p => ({...p, shop_name: e.target.value}))} placeholder="Shop / DIY" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
              </div>
              <input value={editForm.description} onChange={e => setEditForm(p => ({...p, description: e.target.value}))} placeholder="Description" className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
              <textarea value={editForm.notes} onChange={e => setEditForm(p => ({...p, notes: e.target.value}))} placeholder="Notes" rows={2} className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none resize-none" />
              <div className="flex justify-end gap-1">
                <button type="button" onClick={() => setEditId(null)} className="px-2 py-1 text-xs text-muted">Cancel</button>
                <button onClick={handleEditSave} disabled={saving} className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded disabled:opacity-50">{saving ? "Saving..." : "Save"}</button>
              </div>
            </div>
          ) : (
            <div key={s.id} className="flex items-start justify-between surface-card border border-subtle rounded p-2.5 group">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-faint">{s.date_performed || "?"}</span>
                  <span className="text-sm text-default font-medium">{s.service_type}</span>
                  {s.cost != null && <span className="text-xs text-emerald-400">${s.cost.toFixed(2)}</span>}
                </div>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-0.5 text-[10px] text-faint">
                  {s.odometer_at_service && <span>{s.odometer_at_service.toLocaleString()} mi</span>}
                  {s.shop_name && <span>at {s.shop_name}</span>}
                  {s.description && <span>— {s.description}</span>}
                </div>
              </div>
              <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity">
                <button onClick={() => startEdit(s)} className="text-faint hover:text-indigo-400"><PenLine size={12} /></button>
                <button onClick={() => handleDeleteSvc(s.id)} className="text-faint hover:text-red-400"><X size={12} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Auto Issue Photo Panel ── */
function AutoIssuePhotoPanel({ issueId, userId }) {
  const [images, setImages] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef();

  useEffect(() => {
    fetch(`/api/apps/auto/issues/${issueId}/images`)
      .then(r => r.ok ? r.json() : { images: [] })
      .then(d => { setImages(d.images || []); setLoaded(true); })
      .catch(() => setLoaded(true));
  }, [issueId]);

  async function handleFileChange(e) {
    const file = e.target.files[0];
    if (!file) return;
    setUploading(true);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("entity_type", "auto_issue");
    fd.append("entity_id", issueId);
    fd.append("uploaded_by", userId || "");
    try {
      const res = await fetch("/api/apps/images/upload", { method: "POST", body: fd });
      if (res.ok) { const img = await res.json(); setImages(prev => [...prev, img]); }
    } catch {}
    setUploading(false);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function handleRemove(imgId) {
    await fetch(`/api/apps/auto/issues/${issueId}/images/${imgId}/unlink`, { method: "DELETE" });
    setImages(prev => prev.filter(i => i.id !== imgId));
  }

  function imgSrc(img) {
    return img.storage_path ? "/" + img.storage_path : `/api/apps/images/${img.id}/file`;
  }

  if (!loaded) return <div className="px-2.5 pb-2 text-[10px] text-faint">Loading photos...</div>;

  return (
    <div className="px-2.5 pb-2.5 border-t border-subtle pt-2">
      <div className="flex items-center gap-2 flex-wrap">
        {images.map(img => (
          <div key={img.id} className="relative group/img">
            <img src={imgSrc(img)} alt="" className="w-14 h-14 object-cover rounded border border-subtle cursor-pointer"
              onClick={() => window.open(imgSrc(img), "_blank")} />
            <button onClick={() => handleRemove(img.id)}
              className="absolute -top-1 -right-1 w-4 h-4 bg-red-600 rounded-full flex items-center justify-center opacity-0 group-hover/img:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity">
              <X size={8} className="text-default" />
            </button>
          </div>
        ))}
        <label className={`flex flex-col items-center justify-center w-14 h-14 rounded border-2 border-dashed cursor-pointer transition-colors ${
          uploading ? "border-subtle opacity-50" : "border-subtle hover:border-indigo-500"
        }`}>
          <Camera size={14} className="text-faint" />
          <span className="text-[8px] text-faint mt-0.5">Add</span>
          <input ref={inputRef} type="file" accept="image/*" capture="environment" className="hidden"
            onChange={handleFileChange} disabled={uploading} />
        </label>
      </div>
    </div>
  );
}


/* ── Issues Tab ── */
function IssuesTab({ issues, vehicleId, userId, show, setShow, onRefresh }) {
  const [issForm, setIssForm] = useState({ title: "", severity: "minor", description: "", date_noticed: "" });
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [expandedPhotoId, setExpandedPhotoId] = useState(null);
  const [saving, setSaving] = useState(false);

  function startEdit(issue) {
    setEditId(issue.id);
    setEditForm({
      title: issue.title || "",
      severity: issue.severity || "minor",
      description: issue.description || "",
      notes: issue.notes || "",
      status: issue.status || "open",
    });
  }

  async function handleEditSave() {
    if (!editForm.title.trim()) return;
    setSaving(true);
    await fetch(`/api/apps/auto/issues/${editId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(editForm),
    });
    setSaving(false);
    setEditId(null);
    onRefresh();
  }

  async function handleAdd(e) {
    e.preventDefault();
    if (!issForm.title.trim()) return;
    await fetch(`/api/apps/auto/${vehicleId}/issues`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vehicle_id: vehicleId, ...issForm, created_by: userId }),
    });
    setIssForm({ title: "", severity: "minor", description: "", date_noticed: "" });
    setShow(false);
    onRefresh();
  }

  async function handleResolve(issueId) {
    await fetch(`/api/apps/auto/issues/${issueId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "fixed", date_fixed: new Date().toISOString().split("T")[0] }),
    });
    onRefresh();
  }

  async function handleDeleteIssue(issueId) {
    await fetch(`/api/apps/auto/issues/${issueId}`, { method: "DELETE" });
    onRefresh();
  }

  const open = issues.filter(i => i.status !== "fixed");
  const fixed = issues.filter(i => i.status === "fixed");

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs text-faint uppercase tracking-wider">Issues ({open.length} open)</h4>
        <button onClick={() => setShow(!show)} className="flex items-center gap-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded"><Plus size={12} /> Report Issue</button>
      </div>
      {show && (
        <form onSubmit={handleAdd} className="surface-card border border-subtle rounded-lg p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input value={issForm.title} onChange={e => setIssForm(p => ({...p, title: e.target.value}))} placeholder="Issue title *" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <select value={issForm.severity} onChange={e => setIssForm(p => ({...p, severity: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none">
              <option value="minor">Minor</option>
              <option value="moderate">Moderate</option>
              <option value="major">Major</option>
              <option value="critical">Critical</option>
            </select>
          </div>
          <input value={issForm.description} onChange={e => setIssForm(p => ({...p, description: e.target.value}))} placeholder="Description" className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          <div className="flex justify-end gap-1">
            <button type="button" onClick={() => setShow(false)} className="px-2 py-1 text-xs text-muted">Cancel</button>
            <button type="submit" className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded">Save</button>
          </div>
        </form>
      )}
      {open.length === 0 && fixed.length === 0 ? (
        <p className="text-sm text-faint italic">No issues reported.</p>
      ) : (
        <>
          {open.map(i => editId === i.id ? (
            <div key={i.id} className="surface-card border border-indigo-600/50 rounded-lg p-3 space-y-2">
              <div className="grid grid-cols-2 gap-2">
                <input value={editForm.title} onChange={e => setEditForm(p => ({...p, title: e.target.value}))} placeholder="Issue title *" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                <select value={editForm.severity} onChange={e => setEditForm(p => ({...p, severity: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none">
                  <option value="minor">Minor</option>
                  <option value="moderate">Moderate</option>
                  <option value="major">Major</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <input value={editForm.description} onChange={e => setEditForm(p => ({...p, description: e.target.value}))} placeholder="Description" className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
              <textarea value={editForm.notes} onChange={e => setEditForm(p => ({...p, notes: e.target.value}))} placeholder="Notes" rows={2} className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none resize-none" />
              <div className="flex justify-end gap-1">
                <button type="button" onClick={() => setEditId(null)} className="px-2 py-1 text-xs text-muted">Cancel</button>
                <button onClick={handleEditSave} disabled={saving} className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded disabled:opacity-50">{saving ? "Saving..." : "Save"}</button>
              </div>
            </div>
          ) : (
            <div key={i.id} className="surface-card border border-subtle rounded overflow-hidden group">
              <div className="flex items-start justify-between p-2.5">
                <div>
                  <div className="flex items-center gap-2">
                    <span className={`px-1.5 py-0 rounded text-[10px] font-medium ${SEVERITY_COLORS[i.severity]}`}>{i.severity}</span>
                    <span className="text-sm text-default">{i.title}</span>
                  </div>
                  {i.description && <p className="text-[11px] text-faint mt-0.5">{i.description}</p>}
                  {i.notes && <p className="text-[11px] text-faint mt-0.5 italic">{i.notes}</p>}
                  <span className="text-[10px] text-faint">Noticed: {i.date_noticed || "?"}</span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => setExpandedPhotoId(prev => prev === i.id ? null : i.id)}
                    className={`px-1.5 py-0.5 text-[10px] rounded opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 transition-all ${
                      expandedPhotoId === i.id ? "bg-indigo-600 text-on-accent" : "surface-raised hover:bg-[var(--ds-raised)] text-on-accent"
                    }`}
                    title="Photos"
                  >
                    <Camera size={10} />
                  </button>
                  <button onClick={() => startEdit(i)} className="px-1.5 py-0.5 text-[10px] surface-raised hover:bg-[var(--ds-raised)] text-default rounded opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100"><PenLine size={10} /></button>
                  <button onClick={() => handleResolve(i.id)} className="px-1.5 py-0.5 text-[10px] bg-emerald-700 hover:bg-emerald-600 text-on-accent rounded opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100">Fix</button>
                  <button onClick={() => handleDeleteIssue(i.id)} className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 text-faint hover:text-red-400"><X size={12} /></button>
                </div>
              </div>
              {expandedPhotoId === i.id && (
                <AutoIssuePhotoPanel issueId={i.id} userId={userId} />
              )}
            </div>
          ))}
          {fixed.length > 0 && (
            <details className="mt-2">
              <summary className="text-xs text-faint cursor-pointer hover:text-[var(--ds-muted)]">Fixed ({fixed.length})</summary>
              <div className="space-y-1 mt-1">
                {fixed.map(i => (
                  <div key={i.id} className="surface-card border border-subtle rounded p-2 text-xs text-faint flex justify-between group">
                    <span><span className="line-through">{i.title}</span> — fixed {i.date_fixed || ""}</span>
                    <button onClick={() => handleDeleteIssue(i.id)} className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 text-faint hover:text-red-400"><X size={10} /></button>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </div>
  );
}

/* ── Condition Tab ── */
function ConditionTab({ conditions, vehicleId, userId, show, setShow, onRefresh }) {
  const [condForm, setCondForm] = useState({
    date_recorded: "", mileage_at_report: "", brakes: "good", tires: "good",
    tire_tread_depth: "", oil_life_pct: "", battery: "good",
    exterior: "good", interior: "good", lights_signals: "all_working", fluids: "all_good", notes: "",
  });
  const [editId, setEditId] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);

  function startEdit(c) {
    setEditId(c.id);
    setEditForm({
      date_recorded: c.date_recorded || "",
      mileage_at_report: c.mileage_at_report != null ? String(c.mileage_at_report) : "",
      brakes: c.brakes || "good",
      tires: c.tires || "good",
      tire_tread_depth: c.tire_tread_depth != null ? String(c.tire_tread_depth) : "",
      oil_life_pct: c.oil_life_pct != null ? String(c.oil_life_pct) : "",
      battery: c.battery || "good",
      exterior: c.exterior || "good",
      interior: c.interior || "good",
      lights_signals: c.lights_signals || "all_working",
      fluids: c.fluids || "all_good",
      notes: c.notes || "",
    });
  }

  async function handleEditSave() {
    setSaving(true);
    const payload = {
      date_recorded: editForm.date_recorded || undefined,
      mileage_at_report: editForm.mileage_at_report ? parseInt(editForm.mileage_at_report) : undefined,
      brakes: editForm.brakes,
      tires: editForm.tires,
      tire_tread_depth: editForm.tire_tread_depth ? parseFloat(editForm.tire_tread_depth) : undefined,
      oil_life_pct: editForm.oil_life_pct !== "" ? parseInt(editForm.oil_life_pct) : undefined,
      battery: editForm.battery,
      exterior: editForm.exterior,
      interior: editForm.interior,
      lights_signals: editForm.lights_signals,
      fluids: editForm.fluids,
      notes: editForm.notes,
    };
    await fetch(`/api/apps/auto/conditions/${editId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setSaving(false);
    setEditId(null);
    onRefresh();
  }

  async function handleAdd(e) {
    e.preventDefault();
    await fetch(`/api/apps/auto/${vehicleId}/conditions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...condForm,
        mileage_at_report: condForm.mileage_at_report ? parseInt(condForm.mileage_at_report) : undefined,
        tire_tread_depth: condForm.tire_tread_depth ? parseFloat(condForm.tire_tread_depth) : undefined,
        oil_life_pct: condForm.oil_life_pct !== "" ? parseInt(condForm.oil_life_pct) : undefined,
        created_by: userId,
      }),
    });
    setCondForm({ date_recorded: "", mileage_at_report: "", brakes: "good", tires: "good", tire_tread_depth: "", oil_life_pct: "", battery: "good", exterior: "good", interior: "good", lights_signals: "all_working", fluids: "all_good", notes: "" });
    setShow(false);
    onRefresh();
  }

  async function handleDelete(condId) {
    await fetch(`/api/apps/auto/conditions/${condId}`, { method: "DELETE" });
    onRefresh();
  }

  const condOpts = (vals) => vals.map(v => <option key={v} value={v}>{v.replace(/_/g, " ")}</option>);

  function CondEditForm({ form, setForm, onSave, onCancel, saveLabel, isSaving }) {
    return (
      <div className="surface-card border border-indigo-600/50 rounded-lg p-3 space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <input type="date" value={form.date_recorded} onChange={e => setForm(p => ({...p, date_recorded: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          <input type="number" value={form.mileage_at_report} onChange={e => setForm(p => ({...p, mileage_at_report: e.target.value}))} placeholder="Mileage" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div><label className="text-[10px] text-faint">Brakes</label><select value={form.brakes} onChange={e => setForm(p => ({...p, brakes: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["good","fair","worn","needs_replacement"])}</select></div>
          <div><label className="text-[10px] text-faint">Tires</label><select value={form.tires} onChange={e => setForm(p => ({...p, tires: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["good","fair","worn","needs_replacement"])}</select></div>
          <div><label className="text-[10px] text-faint">Battery</label><select value={form.battery} onChange={e => setForm(p => ({...p, battery: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["good","fair","weak","needs_replacement"])}</select></div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div><label className="text-[10px] text-faint">Exterior</label><select value={form.exterior} onChange={e => setForm(p => ({...p, exterior: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["excellent","good","fair","poor"])}</select></div>
          <div><label className="text-[10px] text-faint">Interior</label><select value={form.interior} onChange={e => setForm(p => ({...p, interior: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["excellent","good","fair","poor"])}</select></div>
          <div><label className="text-[10px] text-faint">Lights</label><select value={form.lights_signals} onChange={e => setForm(p => ({...p, lights_signals: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["all_working","issues"])}</select></div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div><label className="text-[10px] text-faint">Fluids</label><select value={form.fluids} onChange={e => setForm(p => ({...p, fluids: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["all_good","needs_attention"])}</select></div>
          <input type="number" step="0.1" value={form.tire_tread_depth} onChange={e => setForm(p => ({...p, tire_tread_depth: e.target.value}))} placeholder="Tread /32&quot;" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          <input type="number" value={form.oil_life_pct} onChange={e => setForm(p => ({...p, oil_life_pct: e.target.value}))} placeholder="Oil life %" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
        </div>
        <textarea value={form.notes} onChange={e => setForm(p => ({...p, notes: e.target.value}))} placeholder="Notes" rows={2} className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none resize-none" />
        <div className="flex justify-end gap-1">
          <button type="button" onClick={onCancel} className="px-2 py-1 text-xs text-muted">Cancel</button>
          <button onClick={onSave} disabled={isSaving} className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded disabled:opacity-50">{isSaving ? "Saving..." : saveLabel}</button>
        </div>
      </div>
    );
  }

  function CondRow({ c }) {
    if (editId === c.id) {
      return <CondEditForm form={editForm} setForm={setEditForm} onSave={handleEditSave} onCancel={() => setEditId(null)} saveLabel="Save" isSaving={saving} />;
    }
    return (
      <div className="surface-card border border-subtle rounded-lg p-3 group">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs text-faint">{c.date_recorded}{c.mileage_at_report ? ` @ ${c.mileage_at_report.toLocaleString()} mi` : ""}</div>
          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 transition-opacity">
            <button onClick={() => startEdit(c)} className="text-faint hover:text-indigo-400"><PenLine size={12} /></button>
            <button onClick={() => handleDelete(c.id)} className="text-faint hover:text-red-400"><X size={12} /></button>
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
          <span>Brakes: <span className={COND_COLORS[c.brakes]}>{c.brakes}</span></span>
          <span>Tires: <span className={COND_COLORS[c.tires]}>{c.tires}</span></span>
          <span>Battery: <span className={COND_COLORS[c.battery]}>{c.battery}</span></span>
          <span>Exterior: <span className={COND_COLORS[c.exterior]}>{c.exterior}</span></span>
          <span>Interior: <span className={COND_COLORS[c.interior]}>{c.interior}</span></span>
          <span>Lights: <span className={COND_COLORS[c.lights_signals]}>{c.lights_signals.replace(/_/g, " ")}</span></span>
          <span>Fluids: <span className={COND_COLORS[c.fluids]}>{c.fluids.replace(/_/g, " ")}</span></span>
          {c.oil_life_pct != null && <span>Oil: {c.oil_life_pct}%</span>}
          {c.tire_tread_depth != null && <span>Tread: {c.tire_tread_depth}/32"</span>}
        </div>
        {c.notes && <p className="text-[11px] text-faint mt-2">{c.notes}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs text-faint uppercase tracking-wider">Condition Reports ({conditions.length})</h4>
        <button onClick={() => setShow(!show)} className="flex items-center gap-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded"><Plus size={12} /> Log Condition</button>
      </div>
      {show && (
        <form onSubmit={handleAdd} className="surface-card border border-subtle rounded-lg p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input type="date" value={condForm.date_recorded} onChange={e => setCondForm(p => ({...p, date_recorded: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input type="number" value={condForm.mileage_at_report} onChange={e => setCondForm(p => ({...p, mileage_at_report: e.target.value}))} placeholder="Mileage" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <div><label className="text-[10px] text-faint">Brakes</label><select value={condForm.brakes} onChange={e => setCondForm(p => ({...p, brakes: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["good","fair","worn","needs_replacement"])}</select></div>
            <div><label className="text-[10px] text-faint">Tires</label><select value={condForm.tires} onChange={e => setCondForm(p => ({...p, tires: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["good","fair","worn","needs_replacement"])}</select></div>
            <div><label className="text-[10px] text-faint">Battery</label><select value={condForm.battery} onChange={e => setCondForm(p => ({...p, battery: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["good","fair","weak","needs_replacement"])}</select></div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <div><label className="text-[10px] text-faint">Exterior</label><select value={condForm.exterior} onChange={e => setCondForm(p => ({...p, exterior: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["excellent","good","fair","poor"])}</select></div>
            <div><label className="text-[10px] text-faint">Interior</label><select value={condForm.interior} onChange={e => setCondForm(p => ({...p, interior: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["excellent","good","fair","poor"])}</select></div>
            <div><label className="text-[10px] text-faint">Lights</label><select value={condForm.lights_signals} onChange={e => setCondForm(p => ({...p, lights_signals: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["all_working","issues"])}</select></div>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <div><label className="text-[10px] text-faint">Fluids</label><select value={condForm.fluids} onChange={e => setCondForm(p => ({...p, fluids: e.target.value}))} className="w-full surface-card text-default text-xs px-2 py-1 rounded border border-subtle">{condOpts(["all_good","needs_attention"])}</select></div>
            <input type="number" step="0.1" value={condForm.tire_tread_depth} onChange={e => setCondForm(p => ({...p, tire_tread_depth: e.target.value}))} placeholder="Tread /32&quot;" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input type="number" value={condForm.oil_life_pct} onChange={e => setCondForm(p => ({...p, oil_life_pct: e.target.value}))} placeholder="Oil life %" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <textarea value={condForm.notes} onChange={e => setCondForm(p => ({...p, notes: e.target.value}))} placeholder="Notes" rows={2} className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none resize-none" />
          <div className="flex justify-end gap-1">
            <button type="button" onClick={() => setShow(false)} className="px-2 py-1 text-xs text-muted">Cancel</button>
            <button type="submit" className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded">Save</button>
          </div>
        </form>
      )}
      {conditions.length === 0 ? (
        <p className="text-sm text-faint italic">No condition reports yet.</p>
      ) : (
        <div className="space-y-1.5">
          {conditions.map(c => <CondRow key={c.id} c={c} />)}
        </div>
      )}
    </div>
  );
}

/* ── Value Tab ── */
function ValueTab({ valuations, vehicleId, userId, show, setShow, onRefresh }) {
  const [valForm, setValForm] = useState({ private_party_value: "", trade_in_value: "", condition: "good", mileage_at_valuation: "", source: "kbb", date_recorded: "", notes: "" });

  async function handleAdd(e) {
    e.preventDefault();
    if (!valForm.private_party_value || !valForm.trade_in_value) return;
    await fetch(`/api/apps/auto/${vehicleId}/valuations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...valForm,
        private_party_value: parseFloat(valForm.private_party_value),
        trade_in_value: parseFloat(valForm.trade_in_value),
        mileage_at_valuation: valForm.mileage_at_valuation ? parseInt(valForm.mileage_at_valuation) : undefined,
        created_by: userId,
      }),
    });
    setValForm({ private_party_value: "", trade_in_value: "", condition: "good", mileage_at_valuation: "", source: "kbb", date_recorded: "", notes: "" });
    setShow(false);
    onRefresh();
  }

  async function handleDeleteVal(valId) {
    await fetch(`/api/apps/auto/valuations/${valId}`, { method: "DELETE" });
    onRefresh();
  }

  const latest = valuations[0];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="text-xs text-faint uppercase tracking-wider">Valuations ({valuations.length})</h4>
        <button onClick={() => setShow(!show)} className="flex items-center gap-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded"><Plus size={12} /> Log Value</button>
      </div>
      {show && (
        <form onSubmit={handleAdd} className="surface-card border border-subtle rounded-lg p-3 space-y-2">
          <div className="grid grid-cols-2 gap-2">
            <input type="number" step="0.01" value={valForm.private_party_value} onChange={e => setValForm(p => ({...p, private_party_value: e.target.value}))} placeholder="Private party $ *" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input type="number" step="0.01" value={valForm.trade_in_value} onChange={e => setValForm(p => ({...p, trade_in_value: e.target.value}))} placeholder="Trade-in $ *" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <select value={valForm.condition} onChange={e => setValForm(p => ({...p, condition: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle">
              <option value="excellent">Excellent</option>
              <option value="very_good">Very Good</option>
              <option value="good">Good</option>
              <option value="fair">Fair</option>
            </select>
            <select value={valForm.source} onChange={e => setValForm(p => ({...p, source: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle">
              <option value="kbb">KBB</option>
              <option value="edmunds">Edmunds</option>
              <option value="nada">NADA</option>
              <option value="other">Other</option>
            </select>
            <input type="date" value={valForm.date_recorded} onChange={e => setValForm(p => ({...p, date_recorded: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <input type="number" value={valForm.mileage_at_valuation} onChange={e => setValForm(p => ({...p, mileage_at_valuation: e.target.value}))} placeholder="Mileage at valuation" className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          <div className="flex justify-end gap-1">
            <button type="button" onClick={() => setShow(false)} className="px-2 py-1 text-xs text-muted">Cancel</button>
            <button type="submit" className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded">Save</button>
          </div>
        </form>
      )}
      {latest && (
        <div className="surface-card border border-subtle rounded-lg p-3">
          <div className="text-xs text-faint mb-2">Latest — {latest.date_recorded} ({latest.source.toUpperCase()}, {latest.condition.replace(/_/g, " ")})</div>
          <div className="flex items-center gap-6">
            <div>
              <div className="text-[10px] text-faint uppercase">Private Party</div>
              <div className="text-lg font-semibold text-emerald-400">${latest.private_party_value?.toLocaleString(undefined, {minimumFractionDigits: 0})}</div>
            </div>
            <div>
              <div className="text-[10px] text-faint uppercase">Trade-in</div>
              <div className="text-lg font-semibold text-accent">${latest.trade_in_value?.toLocaleString(undefined, {minimumFractionDigits: 0})}</div>
            </div>
          </div>
        </div>
      )}
      {valuations.length > 1 && (
        <div className="space-y-1">
          {valuations.slice(1).map(v => (
            <div key={v.id} className="flex items-center justify-between surface-card border border-subtle rounded p-2 text-xs text-faint group">
              <span>{v.date_recorded} — PP: ${v.private_party_value?.toLocaleString()} | TI: ${v.trade_in_value?.toLocaleString()} ({v.source})</span>
              <button onClick={() => handleDeleteVal(v.id)} className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 text-faint hover:text-red-400"><X size={10} /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}


/* ── Oil Change Tracking Card ── */
const MILEAGE_INTERVALS = [3000, 5000, 7500, 10000];
const COOLDOWN_OPTIONS = [2, 3, 4, 6];

function OilTrackingCard({ vehicleId, vehicle, onRefresh }) {
  const [tracking, setTracking] = useState(null);
  const [loading, setLoading] = useState(true);
  const [mileageInput, setMileageInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [setupForm, setSetupForm] = useState({ date_performed: "", odometer: "", interval: 5000, cooldown: 3 });
  const [settingsForm, setSettingsForm] = useState({ interval: 5000, cooldown: 3 });

  const loadTracking = useCallback(async () => {
    try {
      const res = await fetch(`/api/apps/auto/${vehicleId}/oil-tracking`);
      if (res.ok) {
        const d = await res.json();
        setTracking(d.tracking || null);
        if (d.tracking) {
          setSettingsForm({ interval: d.tracking.mileage_interval, cooldown: d.tracking.cooldown_months });
        }
      }
    } catch {}
    setLoading(false);
  }, [vehicleId]);

  useEffect(() => { loadTracking(); }, [loadTracking]);

  async function handleSetup(e) {
    e.preventDefault();
    if (!setupForm.odometer) return;
    setSubmitting(true);
    await fetch(`/api/apps/auto/${vehicleId}/oil-tracking`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date_performed: setupForm.date_performed || undefined,
        odometer_at_service: parseInt(setupForm.odometer),
        mileage_interval: setupForm.interval,
        cooldown_months: setupForm.cooldown,
      }),
    });
    setSubmitting(false);
    setShowSetup(false);
    loadTracking();
    onRefresh();
  }

  async function handleMileageCheck() {
    if (!mileageInput) return;
    setSubmitting(true);
    await fetch(`/api/apps/auto/${vehicleId}/mileage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ odometer: parseInt(mileageInput) }),
    });
    setMileageInput("");
    setSubmitting(false);
    loadTracking();
    onRefresh();
  }

  async function handleSettingsSave() {
    setSubmitting(true);
    await fetch(`/api/apps/auto/${vehicleId}/oil-tracking`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mileage_interval: settingsForm.interval,
        cooldown_months: settingsForm.cooldown,
      }),
    });
    setSubmitting(false);
    setShowSettings(false);
    loadTracking();
  }

  async function handleDelete() {
    await fetch(`/api/apps/auto/${vehicleId}/oil-tracking`, { method: "DELETE" });
    setTracking(null);
    loadTracking();
  }

  if (loading) return null;

  // No tracking set up
  if (!tracking) {
    return (
      <div className="surface-card border border-subtle rounded-lg p-3 mb-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm text-muted">
            <Droplet size={14} className="text-amber-400" />
            <span>Oil Change Tracking</span>
            <span className="text-xs text-faint">— not set up</span>
          </div>
          <button onClick={() => { setShowSetup(!showSetup); setSetupForm({ date_performed: "", odometer: vehicle?.odometer || "", interval: 5000, cooldown: 3 }); }}
            className="flex items-center gap-1 px-2 py-1 text-xs bg-amber-700 hover:bg-amber-600 text-on-accent rounded">
            <Plus size={12} /> Set Up
          </button>
        </div>
        {showSetup && (
          <form onSubmit={handleSetup} className="mt-3 space-y-2 border-t border-subtle pt-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-faint">Last Oil Change Date</label>
                <input type="date" value={setupForm.date_performed} onChange={e => setSetupForm(p => ({...p, date_performed: e.target.value}))}
                  className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
              </div>
              <div>
                <label className="text-[10px] text-faint">Mileage at Oil Change *</label>
                <input type="number" value={setupForm.odometer} onChange={e => setSetupForm(p => ({...p, odometer: e.target.value}))} placeholder="e.g. 62000"
                  className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" required />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-[10px] text-faint">Interval (miles)</label>
                <select value={setupForm.interval} onChange={e => setSetupForm(p => ({...p, interval: parseInt(e.target.value)}))}
                  className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none">
                  {MILEAGE_INTERVALS.map(m => <option key={m} value={m}>{m.toLocaleString()} mi</option>)}
                </select>
              </div>
              <div>
                <label className="text-[10px] text-faint">Cooldown (months)</label>
                <select value={setupForm.cooldown} onChange={e => setSetupForm(p => ({...p, cooldown: parseInt(e.target.value)}))}
                  className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none">
                  {COOLDOWN_OPTIONS.map(m => <option key={m} value={m}>{m} months</option>)}
                </select>
              </div>
            </div>
            <div className="flex justify-end gap-1">
              <button type="button" onClick={() => setShowSetup(false)} className="px-2 py-1 text-xs text-muted">Cancel</button>
              <button type="submit" disabled={submitting} className="px-3 py-1 text-xs bg-amber-600 hover:bg-amber-500 text-on-accent rounded disabled:opacity-50">
                {submitting ? "Saving..." : "Create Tracking"}
              </button>
            </div>
          </form>
        )}
      </div>
    );
  }

  // Determine status
  const isDue = tracking.is_due;
  const cooldownActive = tracking.cooldown_expires && new Date(tracking.cooldown_expires) > new Date();
  const remaining = tracking.next_due_mileage - (vehicle?.odometer || tracking.last_reported_mileage || tracking.odometer_at_service);
  const statusColor = isDue ? "text-red-400" : cooldownActive ? "text-emerald-400" : "text-amber-400";
  const statusLabel = isDue ? "OVERDUE" : cooldownActive ? "Cooldown" : "Monitoring";
  const statusBg = isDue ? "bg-red-600/20 border-red-600/40" : cooldownActive ? "bg-emerald-600/10 border-emerald-600/30" : "bg-amber-600/10 border-amber-600/30";

  return (
    <div className={`border rounded-lg p-3 mb-4 ${statusBg}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Droplet size={14} className={isDue ? "text-red-400" : "text-amber-400"} />
          <span className="text-sm text-default font-medium">Oil Change Tracking</span>
          <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${isDue ? "bg-red-600/30 text-red-300" : cooldownActive ? "bg-emerald-600/20 text-emerald-300" : "bg-amber-600/20 text-amber-300"}`}>
            {statusLabel}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setShowSettings(!showSettings)}
            className="text-[10px] text-faint hover:text-[var(--ds-text)] px-1.5 py-0.5 rounded hover:bg-[var(--ds-raised)]">Settings</button>
          <button onClick={handleDelete}
            className="text-faint hover:text-red-400"><X size={12} /></button>
        </div>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs mb-2">
        <div>
          <div className="text-[10px] text-faint">Last Changed</div>
          <div className="text-default">{tracking.date_performed || "?"}</div>
          <div className="text-faint">{tracking.odometer_at_service?.toLocaleString()} mi</div>
        </div>
        <div>
          <div className="text-[10px] text-faint">Due At</div>
          <div className={`font-medium ${statusColor}`}>{tracking.next_due_mileage?.toLocaleString()} mi</div>
        </div>
        <div>
          <div className="text-[10px] text-faint">Current</div>
          <div className="text-default">{(vehicle?.odometer || tracking.last_reported_mileage || "—")?.toLocaleString?.()} mi</div>
        </div>
        <div>
          <div className="text-[10px] text-faint">{isDue ? "Overdue By" : "Remaining"}</div>
          <div className={`font-medium ${statusColor}`}>
            {remaining != null && !isNaN(remaining) ? `${Math.abs(remaining).toLocaleString()} mi` : "—"}
          </div>
        </div>
      </div>

      {/* Cooldown info or mileage entry */}
      {cooldownActive ? (
        <div className="text-[11px] text-faint">
          Cooldown until {tracking.cooldown_expires}. No mileage checks needed yet.
        </div>
      ) : (
        <div className="flex items-center gap-2 mt-1">
          <input type="number" value={mileageInput} onChange={e => setMileageInput(e.target.value)}
            placeholder={`Enter current mileage${vehicle?.odometer ? ` (was ${vehicle.odometer.toLocaleString()})` : ""}`}
            className="flex-1 surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none focus:border-amber-500"
            onKeyDown={e => e.key === "Enter" && handleMileageCheck()} />
          <button onClick={handleMileageCheck} disabled={!mileageInput || submitting}
            className="px-3 py-1.5 text-xs bg-amber-600 hover:bg-amber-500 text-on-accent rounded disabled:opacity-50">
            {submitting ? "..." : "Check"}
          </button>
        </div>
      )}

      {tracking.last_mileage_check && (
        <div className="text-[10px] text-faint mt-1">
          Last checked: {tracking.last_mileage_check} @ {tracking.last_reported_mileage?.toLocaleString()} mi
        </div>
      )}

      {/* Settings panel */}
      {showSettings && (
        <div className="mt-3 border-t border-subtle pt-3 space-y-2">
          <div className="text-[10px] text-muted uppercase tracking-wider font-medium">Settings</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="text-[10px] text-faint">Interval</label>
              <select value={settingsForm.interval} onChange={e => setSettingsForm(p => ({...p, interval: parseInt(e.target.value)}))}
                className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none">
                {MILEAGE_INTERVALS.map(m => <option key={m} value={m}>{m.toLocaleString()} mi</option>)}
              </select>
            </div>
            <div>
              <label className="text-[10px] text-faint">Cooldown</label>
              <select value={settingsForm.cooldown} onChange={e => setSettingsForm(p => ({...p, cooldown: parseInt(e.target.value)}))}
                className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none">
                {COOLDOWN_OPTIONS.map(m => <option key={m} value={m}>{m} months</option>)}
              </select>
            </div>
          </div>
          <div className="flex justify-end gap-1">
            <button onClick={() => setShowSettings(false)} className="px-2 py-1 text-xs text-muted">Cancel</button>
            <button onClick={handleSettingsSave} disabled={submitting} className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded disabled:opacity-50">
              {submitting ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}


/* ── Maintenance Tab ── */
const RECURRENCE_PRESETS = [
  { label: "Every 6 months", type: "interval", rule: { days: 180 } },
  { label: "Every 3 months", type: "interval", rule: { days: 90 } },
  { label: "Every year", type: "yearly", rule: { month: 1, day: 1 } },
  { label: "Every 5,000 mi", type: "interval", rule: { days: 180 } },
  { label: "Every 10,000 mi", type: "interval", rule: { days: 365 } },
  { label: "Custom interval", type: "interval", rule: { days: 30 } },
];

function MaintenanceTab({ maintenance, vehicleId, vehicle, userId, show, setShow, onRefresh }) {
  const [mForm, setMForm] = useState({ title: "", preset: 0, custom_days: "180", start_date: "" });
  const [completing, setCompleting] = useState(null); // schedule id being completed
  const [compForm, setCompForm] = useState({ date_performed: "", odometer: "", cost: "", shop_name: "", notes: "" });
  const [confirmDel, setConfirmDel] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ title: "", preset: 0, custom_days: "180", next_due: "" });
  const [editSaving, setEditSaving] = useState(false);

  function matchPreset(m) {
    const rule = m.recurrence_rule || {};
    if (m.recurrence_type === "yearly") return 2;
    if (m.recurrence_type === "interval") {
      if (rule.days === 180) return 0;
      if (rule.days === 90) return 1;
      if (rule.days === 365) return 4;
      return 5; // custom
    }
    return 5;
  }

  function openEdit(m) {
    const pi = matchPreset(m);
    setEditingId(m.id);
    setEditForm({
      title: m.title,
      preset: pi,
      custom_days: String((m.recurrence_rule || {}).days || 180),
      next_due: m.next_due ? m.next_due.slice(0, 10) : "",
    });
    setCompleting(null);
  }

  async function handleEditSave(scheduleId) {
    if (!editForm.title.trim()) return;
    setEditSaving(true);
    const preset = RECURRENCE_PRESETS[editForm.preset];
    const rule = editForm.preset === 5 ? { days: parseInt(editForm.custom_days) || 30 } : preset.rule;
    const body = {
      title: editForm.title.trim(),
      recurrence_type: preset.type,
      recurrence_rule: rule,
    };
    if (editForm.next_due) {
      body.next_due = editForm.next_due;
    }
    await fetch(`/api/apps/schedules/${scheduleId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setEditingId(null);
    setEditSaving(false);
    onRefresh();
  }

  async function handleAdd(e) {
    e.preventDefault();
    if (!mForm.title.trim()) return;
    const preset = RECURRENCE_PRESETS[mForm.preset];
    const rule = mForm.preset === 5 ? { days: parseInt(mForm.custom_days) || 30 } : preset.rule;
    await fetch(`/api/apps/auto/${vehicleId}/maintenance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: mForm.title,
        recurrence_type: preset.type,
        recurrence_rule: rule,
        start_date: mForm.start_date || undefined,
        created_by: userId,
        assigned_to: userId,
      }),
    });
    setMForm({ title: "", preset: 0, custom_days: "180", start_date: "" });
    setShow(false);
    onRefresh();
  }

  async function handleComplete(scheduleId) {
    const body = {
      completed_by: userId,
      date_performed: compForm.date_performed || undefined,
      odometer: compForm.odometer ? parseInt(compForm.odometer) : undefined,
      cost: compForm.cost ? parseFloat(compForm.cost) : undefined,
      shop_name: compForm.shop_name || undefined,
      notes: compForm.notes || undefined,
    };
    await fetch(`/api/apps/auto/${vehicleId}/maintenance/${scheduleId}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setCompleting(null);
    setCompForm({ date_performed: "", odometer: "", cost: "", shop_name: "", notes: "" });
    onRefresh();
  }

  async function handleDelete(scheduleId) {
    await fetch(`/api/apps/auto/maintenance/${scheduleId}`, { method: "DELETE" });
    setConfirmDel(null);
    onRefresh();
  }

  const now = new Date();

  function formatDue(nextDue) {
    if (!nextDue) return { text: "No due date", color: "text-faint" };
    const d = new Date(nextDue);
    const diff = Math.round((d - now) / (1000 * 60 * 60 * 24));
    if (diff < 0) return { text: `${Math.abs(diff)}d overdue`, color: "text-red-400" };
    if (diff === 0) return { text: "Due today", color: "text-amber-400" };
    if (diff <= 7) return { text: `${diff}d`, color: "text-amber-400" };
    if (diff <= 30) return { text: `${diff}d`, color: "text-default" };
    return { text: `${diff}d`, color: "text-faint" };
  }

  return (
    <div className="space-y-3">
      <OilTrackingCard vehicleId={vehicleId} vehicle={vehicle} onRefresh={onRefresh} />

      <div className="flex items-center justify-between">
        <h4 className="text-xs text-faint uppercase tracking-wider">Maintenance Schedules ({maintenance.length})</h4>
        <button onClick={() => setShow(!show)} className="flex items-center gap-1 px-2 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 text-on-accent rounded"><Plus size={12} /> Add Schedule</button>
      </div>

      {show && (
        <form onSubmit={handleAdd} className="surface-card border border-subtle rounded-lg p-3 space-y-2">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            <input value={mForm.title} onChange={e => setMForm(p => ({...p, title: e.target.value}))} placeholder="e.g. Oil Change, Tire Rotation *" className="col-span-2 surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            <input type="date" value={mForm.start_date} onChange={e => setMForm(p => ({...p, start_date: e.target.value}))} title="First due date" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
          </div>
          <div className="flex items-center gap-2">
            <select value={mForm.preset} onChange={e => setMForm(p => ({...p, preset: parseInt(e.target.value)}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none flex-1">
              {RECURRENCE_PRESETS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
            </select>
            {mForm.preset === 5 && (
              <input type="number" value={mForm.custom_days} onChange={e => setMForm(p => ({...p, custom_days: e.target.value}))} placeholder="Days" className="w-20 surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
            )}
          </div>
          <div className="flex justify-end gap-1">
            <button type="button" onClick={() => setShow(false)} className="px-2 py-1 text-xs text-muted">Cancel</button>
            <button type="submit" className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded">Create</button>
          </div>
        </form>
      )}

      {maintenance.length === 0 ? (
        <p className="text-sm text-faint italic">No maintenance schedules yet. Add one to start tracking recurring service.</p>
      ) : (
        <div className="space-y-2">
          {maintenance.map(m => {
            const due = formatDue(m.next_due);
            const isCompleting = completing === m.id;
            const isEditing = editingId === m.id;
            return (
              <div key={m.id} className="surface-card border border-subtle rounded-lg group">
                <div className="flex items-center justify-between p-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <CalendarClock size={14} className="text-orange-400 shrink-0" />
                      <span className="text-sm text-default font-medium">{m.title}</span>
                      <span className={`text-xs font-medium ${due.color}`}>{due.text}</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-0.5 text-[10px] text-faint">
                      <span>{m.recurrence_description}</span>
                      {m.completed_count > 0 && <span>Done {m.completed_count}×</span>}
                      {m.last_completed && <span>Last: {m.last_completed.slice(0, 10)}</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button onClick={() => isEditing ? setEditingId(null) : openEdit(m)}
                      className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${isEditing ? "bg-indigo-700 text-on-accent" : "text-faint hover:text-indigo-400 hover:bg-[var(--ds-raised)] opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100"}`}>
                      <PenLine size={12} /> Edit
                    </button>
                    <button onClick={() => { setCompleting(isCompleting ? null : m.id); setEditingId(null); setCompForm({ date_performed: new Date().toISOString().slice(0, 10), odometer: "", cost: "", shop_name: "", notes: "" }); }}
                      className={`flex items-center gap-1 px-2 py-1 text-xs rounded ${isCompleting ? "surface-raised text-on-accent" : "bg-emerald-700 hover:bg-emerald-600 text-on-accent opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100"}`}>
                      <CheckCircle2 size={12} /> Done
                    </button>
                    {confirmDel === m.id ? (
                      <div className="flex items-center gap-0.5">
                        <button onClick={() => handleDelete(m.id)} className="px-1.5 py-0.5 text-[10px] bg-red-600 hover:bg-red-500 text-on-accent rounded">Yes</button>
                        <button onClick={() => setConfirmDel(null)} className="px-1.5 py-0.5 text-[10px] surface-raised text-default rounded">No</button>
                      </div>
                    ) : (
                      <button onClick={() => setConfirmDel(m.id)} className="opacity-0 group-hover:opacity-100 [@media(hover:none)]:opacity-100 text-faint hover:text-red-400"><X size={12} /></button>
                    )}
                  </div>
                </div>

                {isEditing && (
                  <div className="border-t border-subtle p-3 bg-indigo-900/10 space-y-2">
                    <div className="text-[10px] text-indigo-400 uppercase tracking-wider font-medium">Edit Schedule</div>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      <input value={editForm.title} onChange={e => setEditForm(p => ({...p, title: e.target.value}))} placeholder="Title *" className="col-span-2 surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none focus:border-indigo-500" />
                      <input type="date" value={editForm.next_due} onChange={e => setEditForm(p => ({...p, next_due: e.target.value}))} title="Next due date" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none focus:border-indigo-500" />
                    </div>
                    <div className="flex items-center gap-2">
                      <select value={editForm.preset} onChange={e => setEditForm(p => ({...p, preset: parseInt(e.target.value)}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none focus:border-indigo-500 flex-1">
                        {RECURRENCE_PRESETS.map((p, i) => <option key={i} value={i}>{p.label}</option>)}
                      </select>
                      {editForm.preset === 5 && (
                        <input type="number" value={editForm.custom_days} onChange={e => setEditForm(p => ({...p, custom_days: e.target.value}))} placeholder="Days" className="w-20 surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none focus:border-indigo-500" />
                      )}
                    </div>
                    <div className="flex justify-end gap-1">
                      <button onClick={() => setEditingId(null)} className="px-2 py-1 text-xs text-muted">Cancel</button>
                      <button onClick={() => handleEditSave(m.id)} disabled={editSaving || !editForm.title.trim()} className="px-3 py-1 text-xs bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-on-accent rounded">
                        {editSaving ? "Saving..." : "Save Changes"}
                      </button>
                    </div>
                  </div>
                )}

                {isCompleting && (
                  <div className="border-t border-subtle p-3 bg-emerald-900/10 space-y-2">
                    <div className="text-[10px] text-emerald-400 uppercase tracking-wider font-medium">Log Completion</div>
                    <div className="grid grid-cols-2 gap-2">
                      <input type="date" value={compForm.date_performed} onChange={e => setCompForm(p => ({...p, date_performed: e.target.value}))} className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                      <input type="number" value={compForm.odometer} onChange={e => setCompForm(p => ({...p, odometer: e.target.value}))} placeholder="Mileage" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <input type="number" step="0.01" value={compForm.cost} onChange={e => setCompForm(p => ({...p, cost: e.target.value}))} placeholder="Cost $" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                      <input value={compForm.shop_name} onChange={e => setCompForm(p => ({...p, shop_name: e.target.value}))} placeholder="Shop / DIY" className="surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                    </div>
                    <input value={compForm.notes} onChange={e => setCompForm(p => ({...p, notes: e.target.value}))} placeholder="Notes" className="w-full surface-card text-default text-xs px-2 py-1.5 rounded border border-subtle outline-none" />
                    <div className="flex justify-end gap-1">
                      <button onClick={() => setCompleting(null)} className="px-2 py-1 text-xs text-muted">Cancel</button>
                      <button onClick={() => handleComplete(m.id)} className="px-3 py-1 text-xs bg-emerald-600 hover:bg-emerald-500 text-on-accent rounded">Save & Advance</button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
