import { useState, useEffect, useCallback, useRef } from "react";
import {
  Plus, Loader2, X, Check, ChevronUp, ChevronDown, Pencil,
  Settings, RefreshCw, ListTodo, CalendarDays, Bell, BellOff,
  ChevronsUp, ChevronsDown, GripVertical, Printer, Trash2,
  ArrowRight, ArrowLeft, Archive,
} from "lucide-react";

const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
const DAY_LABELS = { sunday: "Sun", monday: "Mon", tuesday: "Tue", wednesday: "Wed", thursday: "Thu", friday: "Fri", saturday: "Sat" };

function isToday(isoStr) {
  if (!isoStr) return false;
  const d = new Date(isoStr);
  const now = new Date();
  return d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
}

function isRecent(isoStr, days = 7) {
  if (!isoStr) return false;
  const d = new Date(isoStr);
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  return d >= cutoff && !isToday(isoStr);
}

export default function TodoApp({ appId, userId, context = {}, onTitle, refreshKey, isActive }) {
  const [config, setConfig] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [todoData, setTodoData] = useState({ items: [], list_id: "", list_name: "", count: 0 });
  const [backlogData, setBacklogData] = useState({ items: [], list_id: "", list_name: "", count: 0 });
  const [loading, setLoading] = useState(true);

  const loadConfig = useCallback(async () => {
    try {
      const res = await fetch(`/api/apps/todo/config?user_id=${userId}`);
      if (res.ok) setConfig(await res.json());
    } catch {}
  }, [userId]);

  const loadTodo = useCallback(async () => {
    try {
      const res = await fetch(`/api/apps/todo/items?user_id=${userId}&include_archived=true`);
      if (res.ok) setTodoData(await res.json());
    } catch {}
  }, [userId]);

  const loadBacklog = useCallback(async () => {
    try {
      const res = await fetch(`/api/apps/todo/backlog?user_id=${userId}&include_archived=true`);
      if (res.ok) setBacklogData(await res.json());
    } catch {}
  }, [userId]);

  const loadAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadConfig(), loadTodo(), loadBacklog()]);
    setLoading(false);
  }, [loadConfig, loadTodo, loadBacklog]);

  useEffect(() => { loadAll(); }, [loadAll, refreshKey]);
  useEffect(() => { onTitle?.("To-Do"); }, [onTitle]);

  async function handleMoveItem(itemId, direction) {
    try {
      await fetch("/api/apps/todo/move-item", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, item_id: itemId, direction }),
      });
      await Promise.all([loadTodo(), loadBacklog()]);
    } catch {}
  }

  const hasBacklog = !!(config?.backlog_list_id);

  if (showSettings) {
    return (
      <SettingsPanel
        userId={userId}
        config={config}
        onClose={() => { setShowSettings(false); loadAll(); }}
      />
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* ── Toolbar ── */}
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <ListTodo size={16} className="text-amber-400" />
          <span className="font-medium">To-Do</span>
        </div>
        <div className="flex items-center gap-1.5">
          {config && (
            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] bg-slate-800 text-slate-400" title={`Nudge day: ${config.nudge_day}`}>
              <CalendarDays size={10} />
              {DAY_LABELS[config.nudge_day] || config.nudge_day}
            </span>
          )}
          {config && (
            <span className="p-1 text-slate-500" title={config.nudge_enabled ? "Nudges on" : "Nudges off"}>
              {config.nudge_enabled ? <Bell size={12} /> : <BellOff size={12} />}
            </span>
          )}
          <button
            onClick={() => setShowSettings(true)}
            className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors"
            title="Settings"
          >
            <Settings size={14} />
          </button>
          <button
            onClick={loadAll}
            disabled={loading}
            className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ── Two-column layout ── */}
      <div className={`flex-1 min-h-0 flex ${hasBacklog ? "" : "flex-col"}`}>
        {/* To-Do column */}
        <div className={`flex flex-col ${hasBacklog ? "w-1/2 border-r border-slate-800/50" : "flex-1"}`}>
          <TodoColumn
            title="To-Do"
            titleIcon={<ListTodo size={13} className="text-amber-400" />}
            accentColor="amber"
            listType="todo"
            data={todoData}
            userId={userId}
            loading={loading}
            onReload={loadTodo}
            onReloadAll={() => Promise.all([loadTodo(), loadBacklog()])}
            moveLabel={hasBacklog ? "Backlog" : null}
            moveDirection="to_backlog"
            onMoveItem={handleMoveItem}
            MoveIcon={ArrowRight}
          />
        </div>

        {/* Backlog column */}
        {hasBacklog && (
          <div className="flex flex-col w-1/2">
            <TodoColumn
              title="Backlog"
              titleIcon={<Archive size={13} className="text-violet-400" />}
              accentColor="violet"
              listType="backlog"
              data={backlogData}
              userId={userId}
              loading={loading}
              onReload={loadBacklog}
              onReloadAll={() => Promise.all([loadTodo(), loadBacklog()])}
              moveLabel="To-Do"
              moveDirection="to_todo"
              onMoveItem={handleMoveItem}
              MoveIcon={ArrowLeft}
            />
          </div>
        )}
      </div>

      {!hasBacklog && (
        <div className="px-3 py-2 border-t border-slate-800/50 text-center">
          <button
            onClick={() => setShowSettings(true)}
            className="text-[11px] text-slate-500 hover:text-violet-400 transition-colors"
          >
            + Add a Backlog list in Settings
          </button>
        </div>
      )}
    </div>
  );
}


// ── Reusable column for either To-Do or Backlog ──

function TodoColumn({
  title, titleIcon, accentColor, listType, data, userId, loading,
  onReload, onReloadAll, moveLabel, moveDirection, onMoveItem, MoveIcon,
}) {
  const items = data.items || [];
  const listId = data.list_id || "";
  const listName = data.list_name || "";

  const [addText, setAddText] = useState("");
  const [adding, setAdding] = useState(false);
  const [checkingOff, setCheckingOff] = useState(new Set());
  const [dragId, setDragId] = useState(null);
  const [dragOverIdx, setDragOverIdx] = useState(null);
  const [showRecentCompleted, setShowRecentCompleted] = useState(false);
  const [ctxMenu, setCtxMenu] = useState(null);
  const addRef = useRef(null);

  const activeItems = items.filter((i) => !i.archived);
  const completedToday = items.filter((i) => i.archived && isToday(i.archived_at));
  const recentCompleted = items.filter((i) => i.archived && isRecent(i.archived_at));
  const olderCompleted = items.filter((i) => i.archived && !isToday(i.archived_at) && !isRecent(i.archived_at));

  useEffect(() => {
    if (!ctxMenu) return;
    const handler = () => setCtxMenu(null);
    window.addEventListener("click", handler);
    return () => window.removeEventListener("click", handler);
  }, [ctxMenu]);

  async function handleAdd(e) {
    e.preventDefault();
    if (!addText.trim() || adding) return;
    setAdding(true);
    try {
      const res = await fetch("/api/apps/todo/items", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, text: addText.trim(), list_type: listType }),
      });
      if (res.ok) { setAddText(""); await onReload(); addRef.current?.focus(); }
    } catch {}
    setAdding(false);
  }

  async function handleCheckOff(itemId) {
    setCheckingOff((prev) => new Set([...prev, itemId]));
    setTimeout(async () => {
      setCheckingOff((prev) => { const s = new Set(prev); s.delete(itemId); return s; });
      try { await fetch(`/api/apps/lists/${listId}/items/${itemId}`, { method: "DELETE" }); } catch {}
      await onReload();
    }, 400);
  }

  async function handleRemove(itemId) {
    try { await fetch(`/api/apps/lists/${listId}/items/${itemId}`, { method: "DELETE" }); } catch {}
    await onReload();
  }

  async function handleEdit(itemId, newText) {
    try {
      await fetch(`/api/apps/lists/${listId}/items/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: newText }),
      });
      await onReload();
    } catch {}
  }

  async function handleMove(itemId, newPosition) {
    if (newPosition < 0 || newPosition >= activeItems.length) return;
    try {
      await fetch(`/api/apps/lists/${listId}/items/${itemId}/position`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_position: newPosition }),
      });
      await onReload();
    } catch {}
  }

  function handleDragStart(e, itemId) {
    setDragId(itemId);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", itemId);
  }
  function handleDragOver(e, idx) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDragOverIdx(idx); }
  function handleDragLeave() { setDragOverIdx(null); }
  function handleDragEnd() { setDragId(null); setDragOverIdx(null); }

  async function handleDrop(e, dropIdx) {
    e.preventDefault();
    setDragOverIdx(null);
    if (dragId == null) return;
    const fromIdx = activeItems.findIndex((i) => i.id === dragId);
    if (fromIdx === -1 || fromIdx === dropIdx) { setDragId(null); return; }
    const reordered = [...activeItems];
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(dropIdx, 0, moved);
    setDragId(null);
    try {
      await fetch("/api/apps/todo/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, item_ids: reordered.map((i) => i.id), list_type: listType }),
      });
      await onReload();
    } catch { await onReload(); }
  }

  function handlePrint() {
    const printContent = [
      `<html><head><title>${listName || title}</title>`,
      `<style>body{font-family:system-ui,sans-serif;padding:40px;max-width:600px;margin:0 auto}`,
      `h1{font-size:22px;margin-bottom:4px}h2{font-size:14px;color:#888;margin-bottom:20px}`,
      `.item{padding:6px 0;border-bottom:1px solid #eee;font-size:14px;display:flex;gap:8px}`,
      `.num{color:#999;min-width:24px;text-align:right}.done{color:#999;text-decoration:line-through}`,
      `.section{margin-top:20px;font-size:12px;color:#888;text-transform:uppercase;letter-spacing:1px;padding-bottom:4px;border-bottom:2px solid #ddd}`,
      `@media print{body{padding:20px}}</style></head><body>`,
      `<h1>${listName || title}</h1>`,
      `<h2>${activeItems.length} item${activeItems.length !== 1 ? "s" : ""} &middot; ${new Date().toLocaleDateString()}</h2>`,
    ];
    activeItems.forEach((item, idx) => {
      printContent.push(`<div class="item"><span class="num">${idx + 1}.</span><span>&#9744; ${item.text}</span></div>`);
    });
    if (completedToday.length > 0) {
      printContent.push(`<div class="section">Completed Today</div>`);
      completedToday.forEach((item) => {
        printContent.push(`<div class="item"><span class="done">&#9745; ${item.text}</span></div>`);
      });
    }
    printContent.push(`</body></html>`);
    const win = window.open("", "_blank");
    win.document.write(printContent.join(""));
    win.document.close();
    win.print();
  }

  function handleContextMenu(e, itemId) { e.preventDefault(); setCtxMenu({ itemId, x: e.clientX, y: e.clientY }); }

  async function handleClearCompleted(itemIds) {
    for (const id of itemIds) {
      try { await fetch(`/api/apps/lists/${listId}/items/${id}`, { method: "DELETE" }); } catch {}
    }
    await onReload();
  }

  const accentBtn = accentColor === "violet"
    ? "bg-violet-600 hover:bg-violet-500"
    : "bg-amber-600 hover:bg-amber-500";

  return (
    <>
      {/* Column header */}
      <div className="flex items-center justify-between px-2 h-8 bg-slate-900/30 border-b border-slate-800/50 shrink-0">
        <div className="flex items-center gap-1.5 text-xs text-slate-300">
          {titleIcon}
          <span className="font-medium">{title}</span>
          <span className="text-[10px] text-slate-500">{activeItems.length}</span>
        </div>
        <button onClick={handlePrint} className="p-0.5 rounded text-slate-600 hover:text-white hover:bg-slate-700 transition-colors" title="Print">
          <Printer size={12} />
        </button>
      </div>

      {/* Add item */}
      <form onSubmit={handleAdd} className="flex items-center gap-1.5 px-2 py-1.5 bg-slate-900/20 border-b border-slate-800/30">
        <Plus size={12} className="text-slate-500 shrink-0" />
        <input
          ref={addRef}
          type="text"
          value={addText}
          onChange={(e) => setAddText(e.target.value)}
          placeholder={`Add to ${title.toLowerCase()}...`}
          className="flex-1 bg-transparent text-xs text-slate-200 placeholder:text-slate-600 outline-none"
        />
        {addText.trim() && (
          <button type="submit" disabled={adding} className={`px-2 py-0.5 text-[10px] ${accentBtn} disabled:opacity-40 text-white rounded transition-colors`}>
            {adding ? <Loader2 size={10} className="animate-spin" /> : "Add"}
          </button>
        )}
      </form>

      {/* Items */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading && items.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-slate-500">
            <Loader2 size={16} className="animate-spin" />
          </div>
        ) : activeItems.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-24 text-slate-500 text-xs">
            <ListTodo size={20} className="mb-1.5 text-slate-600" />
            <p>{title} is empty</p>
          </div>
        ) : (
          <div className="py-0.5">
            {activeItems.map((item, idx) => (
              <TodoItemRow
                key={item.id}
                item={item}
                idx={idx}
                total={activeItems.length}
                onCheck={handleCheckOff}
                onEdit={handleEdit}
                onMove={handleMove}
                onMoveToTop={(id) => handleMove(id, 0)}
                onMoveToBottom={(id) => handleMove(id, activeItems.length - 1)}
                onRemove={handleRemove}
                isCheckingOff={checkingOff.has(item.id)}
                isDragging={dragId === item.id}
                isDragOver={dragOverIdx === idx}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onDragEnd={handleDragEnd}
                onContextMenu={handleContextMenu}
                moveLabel={moveLabel}
                moveDirection={moveDirection}
                onMoveItem={onMoveItem}
                MoveIcon={MoveIcon}
              />
            ))}
          </div>
        )}

        {/* Completed Today */}
        {completedToday.length > 0 && (
          <div className="border-t border-slate-800/50 mt-0.5">
            <div className="flex items-center justify-between px-2 py-1.5">
              <span className="text-[10px] text-slate-500">Completed Today ({completedToday.length})</span>
              <button onClick={() => handleClearCompleted(completedToday.map((i) => i.id))} className="text-[9px] text-slate-600 hover:text-red-400 transition-colors">clear</button>
            </div>
            <div className="pb-1">
              {completedToday.map((item) => (
                <div key={item.id} className="flex items-center gap-1.5 px-2 py-0.5 text-[10px] text-slate-500">
                  <Check size={10} className="text-green-500 shrink-0" />
                  <span className="line-through flex-1 truncate">{item.text}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recently Completed */}
        {recentCompleted.length > 0 && (
          <div className="border-t border-slate-800/50">
            <button
              onClick={() => setShowRecentCompleted(!showRecentCompleted)}
              className="flex items-center justify-between w-full px-2 py-1.5 text-[10px] text-slate-600 hover:text-slate-400 transition-colors"
            >
              <span className="flex items-center gap-1">
                {showRecentCompleted ? <ChevronDown size={9} /> : <ChevronUp size={9} />}
                Recently ({recentCompleted.length})
              </span>
              {showRecentCompleted && (
                <span onClick={(e) => { e.stopPropagation(); handleClearCompleted(recentCompleted.map((i) => i.id)); }} className="text-[9px] text-slate-600 hover:text-red-400">clear</span>
              )}
            </button>
            {showRecentCompleted && (
              <div className="pb-1">
                {recentCompleted.map((item) => (
                  <div key={item.id} className="flex items-center gap-1.5 px-2 py-0.5 text-[10px] text-slate-600">
                    <Check size={10} className="text-green-600/50 shrink-0" />
                    <span className="line-through flex-1 truncate">{item.text}</span>
                    {item.archived_at && (
                      <span className="text-[9px] text-slate-700 shrink-0">{new Date(item.archived_at).toLocaleDateString(undefined, { weekday: "short" })}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {olderCompleted.length > 0 && (
          <div className="px-2 py-1 text-[9px] text-slate-700 border-t border-slate-800/30">
            {olderCompleted.length} older completed
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-2 py-1 border-t border-slate-800/50 flex items-center justify-between text-[9px] text-slate-600">
        <span className="font-mono">{listId}</span>
        <span className="truncate ml-1">{listName}</span>
      </div>

      {/* Context menu */}
      {ctxMenu && (
        <ContextMenu
          x={ctxMenu.x} y={ctxMenu.y} itemId={ctxMenu.itemId}
          idx={activeItems.findIndex((i) => i.id === ctxMenu.itemId)}
          total={activeItems.length}
          onClose={() => setCtxMenu(null)}
          onMoveToTop={() => { handleMove(ctxMenu.itemId, 0); setCtxMenu(null); }}
          onMoveToBottom={() => { handleMove(ctxMenu.itemId, activeItems.length - 1); setCtxMenu(null); }}
          onRemove={() => { handleRemove(ctxMenu.itemId); setCtxMenu(null); }}
          onCheck={() => { handleCheckOff(ctxMenu.itemId); setCtxMenu(null); }}
          moveLabel={moveLabel}
          onMoveToOther={moveLabel ? () => { onMoveItem(ctxMenu.itemId, moveDirection); setCtxMenu(null); } : null}
          MoveIcon={MoveIcon}
        />
      )}
    </>
  );
}


// ── Context Menu ──

function ContextMenu({ x, y, itemId, idx, total, onClose, onMoveToTop, onMoveToBottom, onRemove, onCheck, moveLabel, onMoveToOther, MoveIcon }) {
  const menuRef = useRef(null);

  useEffect(() => {
    if (menuRef.current) {
      const rect = menuRef.current.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      if (rect.right > vw) menuRef.current.style.left = `${x - rect.width}px`;
      if (rect.bottom > vh) menuRef.current.style.top = `${y - rect.height}px`;
    }
  }, [x, y]);

  const items = [
    { label: "Mark done", icon: Check, action: onCheck },
    { label: "Move to top", icon: ChevronsUp, action: onMoveToTop, disabled: idx === 0 },
    { label: "Move to bottom", icon: ChevronsDown, action: onMoveToBottom, disabled: idx === total - 1 },
  ];
  if (onMoveToOther && MoveIcon) {
    items.push({ divider: true });
    items.push({ label: `Move to ${moveLabel}`, icon: MoveIcon, action: onMoveToOther });
  }
  items.push({ divider: true });
  items.push({ label: "Remove", icon: Trash2, action: onRemove, danger: true });

  return (
    <div
      ref={menuRef}
      className="fixed z-50 bg-slate-800 border border-slate-700 rounded-lg shadow-xl py-1 min-w-[160px]"
      style={{ left: x, top: y }}
      onClick={(e) => e.stopPropagation()}
    >
      {items.map((item, i) =>
        item.divider ? (
          <div key={i} className="border-t border-slate-700 my-1" />
        ) : (
          <button
            key={i}
            onClick={item.action}
            disabled={item.disabled}
            className={`flex items-center gap-2 w-full px-3 py-1.5 text-xs transition-colors disabled:opacity-30 ${
              item.danger
                ? "text-red-400 hover:bg-red-900/30"
                : "text-slate-300 hover:bg-slate-700"
            }`}
          >
            <item.icon size={12} />
            {item.label}
          </button>
        )
      )}
    </div>
  );
}


// ── To-Do Item Row ──

function TodoItemRow({
  item, idx, total, onCheck, onEdit, onMove, onMoveToTop, onMoveToBottom, onRemove,
  isCheckingOff, isDragging, isDragOver,
  onDragStart, onDragOver, onDragLeave, onDrop, onDragEnd, onContextMenu,
  moveLabel, moveDirection, onMoveItem, MoveIcon,
}) {
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(item.text);
  const editRef = useRef(null);

  useEffect(() => {
    if (editing && editRef.current) {
      editRef.current.focus();
      editRef.current.select();
    }
  }, [editing]);

  function startEdit() {
    setEditText(item.text);
    setEditing(true);
  }

  function commitEdit() {
    const trimmed = editText.trim();
    if (trimmed && trimmed !== item.text) {
      onEdit(item.id, trimmed);
    }
    setEditing(false);
  }

  function handleKeyDown(e) {
    if (e.key === "Enter") { e.preventDefault(); commitEdit(); }
    if (e.key === "Escape") { setEditing(false); setEditText(item.text); }
  }

  return (
    <div
      className={`flex items-center gap-1.5 px-2 py-1 group/item transition-all duration-300 ${
        isCheckingOff
          ? "opacity-0 translate-x-4 scale-95 bg-green-900/20"
          : isDragging
          ? "opacity-40"
          : isDragOver
          ? "border-t-2 border-amber-400"
          : "hover:bg-slate-800/30 border-t-2 border-transparent"
      }`}
      draggable={!editing}
      onDragStart={(e) => onDragStart(e, item.id)}
      onDragOver={(e) => onDragOver(e, idx)}
      onDragLeave={onDragLeave}
      onDrop={(e) => onDrop(e, idx)}
      onDragEnd={onDragEnd}
      onContextMenu={(e) => onContextMenu(e, item.id)}
    >
      {/* Drag handle */}
      <span className="cursor-grab active:cursor-grabbing text-slate-700 group-hover/item:text-slate-500 transition-colors shrink-0">
        <GripVertical size={11} />
      </span>

      {/* Check circle */}
      <button
        onClick={() => onCheck(item.id)}
        className={`w-4 h-4 rounded-full border-2 flex items-center justify-center shrink-0 transition-all duration-300 ${
          isCheckingOff
            ? "border-green-400 bg-green-400 scale-110"
            : "border-slate-600 hover:border-amber-400 hover:bg-amber-400/10 group/check"
        }`}
        title="Mark done"
      >
        <Check size={8} className={`transition-all duration-300 ${
          isCheckingOff ? "text-white" : "text-transparent group-hover/check:text-amber-400"
        }`} />
      </button>

      {/* Rank number */}
      <span className="text-[9px] text-slate-600 w-3 text-right shrink-0">{idx + 1}.</span>

      {/* Text */}
      {editing ? (
        <input
          ref={editRef}
          type="text"
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onBlur={commitEdit}
          onKeyDown={handleKeyDown}
          className="flex-1 bg-slate-800 text-white text-xs px-1.5 py-0.5 rounded border border-amber-500/50 outline-none min-w-0"
        />
      ) : (
        <span
          className={`flex-1 text-xs min-w-0 cursor-pointer truncate transition-all duration-300 ${
            isCheckingOff ? "line-through text-green-400" : "text-slate-200 hover:text-white"
          }`}
          onDoubleClick={startEdit}
          title={item.text}
        >
          {item.text}
        </span>
      )}

      {/* Actions */}
      {!editing && !isCheckingOff && (
        <div className="flex items-center gap-0 opacity-0 group-hover/item:opacity-100 transition-all shrink-0">
          <button onClick={startEdit} className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-white transition-colors" title="Edit">
            <Pencil size={10} />
          </button>
          {moveLabel && MoveIcon && (
            <button
              onClick={() => onMoveItem(item.id, moveDirection)}
              className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-violet-400 transition-colors"
              title={`Move to ${moveLabel}`}
            >
              <MoveIcon size={10} />
            </button>
          )}
          <button
            onClick={() => onMoveToTop(item.id)}
            disabled={idx === 0}
            className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-white disabled:opacity-20 transition-colors"
            title="Move to top"
          >
            <ChevronsUp size={10} />
          </button>
          <button
            onClick={() => onMove(item.id, idx - 1)}
            disabled={idx === 0}
            className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-white disabled:opacity-20 transition-colors"
            title="Move up"
          >
            <ChevronUp size={10} />
          </button>
          <button
            onClick={() => onMove(item.id, idx + 1)}
            disabled={idx === total - 1}
            className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-white disabled:opacity-20 transition-colors"
            title="Move down"
          >
            <ChevronDown size={10} />
          </button>
          <button
            onClick={() => onMoveToBottom(item.id)}
            disabled={idx === total - 1}
            className="p-0.5 rounded hover:bg-slate-700 text-slate-500 hover:text-white disabled:opacity-20 transition-colors"
            title="Move to bottom"
          >
            <ChevronsDown size={10} />
          </button>
          <button
            onClick={() => onRemove(item.id)}
            className="p-0.5 rounded hover:bg-red-900/30 text-slate-500 hover:text-red-400 transition-colors"
            title="Remove"
          >
            <X size={10} />
          </button>
        </div>
      )}
    </div>
  );
}


// ── Settings Panel ──

function SettingsPanel({ userId, config, onClose }) {
  const [lists, setLists] = useState([]);
  const [selectedList, setSelectedList] = useState(config?.default_list_id || "");
  const [selectedBacklog, setSelectedBacklog] = useState(config?.backlog_list_id || "");
  const [nudgeEnabled, setNudgeEnabled] = useState(config?.nudge_enabled ?? true);
  const [nudgeDay, setNudgeDay] = useState(config?.nudge_day || "saturday");
  const [nudgeTime, setNudgeTime] = useState(config?.nudge_time || "07:00");
  const [showOnCalendar, setShowOnCalendar] = useState(config?.show_on_calendar ?? true);
  const [saving, setSaving] = useState(false);
  const [loadingLists, setLoadingLists] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`/api/apps/todo/lists?user_id=${userId}`);
        if (res.ok) {
          const data = await res.json();
          setLists(data.lists || []);
        }
      } catch {}
      setLoadingLists(false);
    })();
  }, [userId]);

  async function handleSave() {
    setSaving(true);
    try {
      await fetch("/api/apps/todo/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: userId,
          default_list_id: selectedList || null,
          backlog_list_id: selectedBacklog || null,
          nudge_enabled: nudgeEnabled,
          nudge_day: nudgeDay,
          nudge_time: nudgeTime,
          show_on_calendar: showOnCalendar,
        }),
      });
    } catch {}
    setSaving(false);
    onClose();
  }

  function renderListSelect(value, onChange, label, hint) {
    return (
      <div>
        <label className="block text-xs text-slate-400 font-medium mb-1.5">{label}</label>
        {loadingLists ? (
          <div className="text-xs text-slate-500"><Loader2 size={12} className="animate-spin inline mr-1" /> Loading lists...</div>
        ) : (
          <select
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="w-full bg-slate-800 text-sm text-slate-200 px-3 py-2 rounded border border-slate-700 outline-none focus:border-amber-500/50"
          >
            <option value="">— Select a list —</option>
            {lists.map((l) => (
              <option key={l.id} value={l.id}>{l.trello_board ? `${l.trello_board} / ${l.name}` : l.name} ({l.item_count} items)</option>
            ))}
          </select>
        )}
        <p className="text-[11px] text-slate-600 mt-1">{hint}</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full w-full">
      <div className="flex items-center justify-between px-3 h-10 bg-slate-900/40 border-b border-slate-800 shrink-0">
        <div className="flex items-center gap-2 text-sm text-slate-300">
          <Settings size={14} className="text-slate-500" />
          <span className="font-medium">To-Do Settings</span>
        </div>
        <button onClick={onClose} className="p-1 rounded text-slate-500 hover:text-white hover:bg-slate-700 transition-colors">
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {renderListSelect(selectedList, setSelectedList, "To-Do List", "Your active to-do list. Items you hope to tackle soon.")}
        {renderListSelect(selectedBacklog, setSelectedBacklog, "Backlog List", "Items that will take longer. Move items between lists as priorities shift.")}

        {/* Weekly nudge */}
        <div>
          <label className="block text-xs text-slate-400 font-medium mb-1.5">Weekly Nudge</label>
          <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer mb-3">
            <input
              type="checkbox"
              checked={nudgeEnabled}
              onChange={(e) => setNudgeEnabled(e.target.checked)}
              className="rounded border-slate-600 bg-slate-800 text-amber-500 focus:ring-amber-500/30"
            />
            Send me a weekly to-do summary
          </label>

          <div className="flex items-center gap-3">
            <div>
              <label className="block text-[11px] text-slate-500 mb-1">Day</label>
              <select
                value={nudgeDay}
                onChange={(e) => setNudgeDay(e.target.value)}
                disabled={!nudgeEnabled}
                className="bg-slate-800 text-sm text-slate-200 px-2.5 py-1.5 rounded border border-slate-700 outline-none focus:border-amber-500/50 disabled:opacity-40"
              >
                {DAYS.map((d) => (
                  <option key={d} value={d}>{d.charAt(0).toUpperCase() + d.slice(1)}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-[11px] text-slate-500 mb-1">Time</label>
              <input
                type="time"
                value={nudgeTime}
                onChange={(e) => setNudgeTime(e.target.value)}
                disabled={!nudgeEnabled}
                className="bg-slate-800 text-sm text-slate-200 px-2.5 py-1.5 rounded border border-slate-700 outline-none focus:border-amber-500/50 disabled:opacity-40"
              />
            </div>
          </div>
        </div>

        {/* Calendar */}
        <div>
          <label className="block text-xs text-slate-400 font-medium mb-1.5">Calendar</label>
          <label className="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
            <input
              type="checkbox"
              checked={showOnCalendar}
              onChange={(e) => setShowOnCalendar(e.target.checked)}
              className="rounded border-slate-600 bg-slate-800 text-amber-500 focus:ring-amber-500/30"
            />
            Show to-do block on my nudge day
          </label>
        </div>
      </div>

      {/* Save bar */}
      <div className="px-4 py-3 border-t border-slate-800 flex items-center justify-end gap-2">
        <button
          onClick={onClose}
          className="px-3 py-1.5 text-xs text-slate-400 hover:text-white rounded hover:bg-slate-700 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-1.5 text-xs bg-amber-600 hover:bg-amber-500 disabled:opacity-40 text-white rounded transition-colors"
        >
          {saving ? <Loader2 size={12} className="animate-spin" /> : "Save"}
        </button>
      </div>
    </div>
  );
}
