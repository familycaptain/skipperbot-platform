import { useState, useCallback, useRef, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  Handle,
  Position,
  MarkerType,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import { Plus, LayoutGrid, Trash2 } from "lucide-react";

// ---------------------------------------------------------------------------
// Dagre auto-layout
// ---------------------------------------------------------------------------
const NODE_WIDTH = 180;
const NODE_HEIGHT = 40;

function autoLayout(nodes, edges, direction = "TB") {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 50, ranksep: 60 });

  nodes.forEach((n) => {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  });
  edges.forEach((e) => {
    g.setEdge(e.source, e.target);
  });

  dagre.layout(g);

  return nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      ...n,
      position: { x: pos.x - NODE_WIDTH / 2, y: pos.y - NODE_HEIGHT / 2 },
    };
  });
}

// ---------------------------------------------------------------------------
// Editable Node
// ---------------------------------------------------------------------------
function EditableNode({ id, data }) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(data.label || "");
  const inputRef = useRef(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  function commit() {
    setEditing(false);
    data.onLabelChange?.(id, label);
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") { setLabel(data.label); setEditing(false); }
        }}
        className="bg-slate-700 text-white text-xs px-2 py-1 rounded border border-indigo-500 outline-none w-full text-center"
        style={{ minWidth: 60 }}
      />
    );
  }

  return (
    <div
      onDoubleClick={() => setEditing(true)}
      className="px-3 py-1.5 text-xs text-white cursor-pointer select-none text-center truncate"
      title="Double-click to edit"
      style={{ maxWidth: NODE_WIDTH - 20 }}
    >
      <Handle id="top" type="target" position={Position.Top} className="!w-2 !h-2 !bg-slate-500 !border-slate-400" />
      <Handle id="bottom" type="source" position={Position.Bottom} className="!w-2 !h-2 !bg-slate-500 !border-slate-400" />
      <Handle id="left" type="target" position={Position.Left} className="!w-2 !h-2 !bg-slate-500 !border-slate-400" />
      <Handle id="right" type="source" position={Position.Right} className="!w-2 !h-2 !bg-slate-500 !border-slate-400" />
      {data.label || "Node"}
    </div>
  );
}

const nodeTypes = { editable: EditableNode };

// ---------------------------------------------------------------------------
// Default node style
// ---------------------------------------------------------------------------
const defaultNodeStyle = {
  background: "#1e293b",
  border: "1px solid #475569",
  borderRadius: 6,
  color: "#e2e8f0",
  fontSize: 12,
  padding: 0,
  minWidth: 80,
};

// ---------------------------------------------------------------------------
// FlowchartEditor
// ---------------------------------------------------------------------------
export default function FlowchartEditor({ meta, onMetaChange, readOnly = false }) {
  const initialNodes = (meta?.nodes || []).map((n) => ({
    id: n.id,
    type: "editable",
    position: n.position || { x: 0, y: 0 },
    data: { label: n.label || "Node", onLabelChange: handleLabelChange },
    style: { ...defaultNodeStyle, ...(n.style || {}) },
  }));

  const initialEdges = (meta?.edges || []).map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label || "",
    type: "smoothstep",
    animated: false,
    style: { stroke: "#64748b" },
    labelStyle: { fill: "#94a3b8", fontSize: 10 },
    markerEnd: { type: MarkerType.ArrowClosed, color: "#64748b" },
  }));

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);
  const nodeCounterRef = useRef(
    Math.max(0, ...initialNodes.map((n) => {
      const m = n.id.match(/^node-(\d+)$/);
      return m ? parseInt(m[1], 10) : 0;
    })) + 1
  );

  // Sync meta changes back to parent
  const saveTimeoutRef = useRef(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;

  const debouncedSave = useCallback(() => {
    clearTimeout(saveTimeoutRef.current);
    saveTimeoutRef.current = setTimeout(() => {
      const saveMeta = {
        nodes: nodesRef.current.map((n) => ({
          id: n.id,
          label: n.data?.label || "",
          position: n.position,
          style: n.style !== defaultNodeStyle ? n.style : undefined,
        })),
        edges: edgesRef.current.map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label || "",
        })),
      };
      onMetaChange?.(saveMeta);
    }, 500);
  }, [onMetaChange]);

  // Trigger save on any change
  useEffect(() => { debouncedSave(); }, [nodes, edges, debouncedSave]);

  function handleLabelChange(nodeId, newLabel) {
    setNodes((nds) =>
      nds.map((n) =>
        n.id === nodeId
          ? { ...n, data: { ...n.data, label: newLabel, onLabelChange: handleLabelChange } }
          : n
      )
    );
  }

  const onConnect = useCallback(
    (params) => {
      const edgeId = `edge-${params.source}-${params.target}`;
      setEdges((eds) =>
        addEdge(
          {
            ...params,
            id: edgeId,
            type: "smoothstep",
            style: { stroke: "#64748b" },
            labelStyle: { fill: "#94a3b8", fontSize: 10 },
            markerEnd: { type: MarkerType.ArrowClosed, color: "#64748b" },
          },
          eds
        )
      );
    },
    [setEdges]
  );

  function handleAddNode() {
    const id = `node-${nodeCounterRef.current++}`;
    const newNode = {
      id,
      type: "editable",
      position: { x: 100 + Math.random() * 200, y: 100 + Math.random() * 200 },
      data: { label: "New Node", onLabelChange: handleLabelChange },
      style: { ...defaultNodeStyle },
    };
    setNodes((nds) => [...nds, newNode]);
  }

  function handleAutoLayout() {
    const laid = autoLayout(nodes, edges);
    setNodes(
      laid.map((n) => ({
        ...n,
        data: { ...n.data, onLabelChange: handleLabelChange },
      }))
    );
  }

  function handleDeleteSelected() {
    setNodes((nds) => nds.filter((n) => !n.selected));
    setEdges((eds) => {
      const removedNodeIds = new Set(nodes.filter((n) => n.selected).map((n) => n.id));
      return eds.filter(
        (e) => !e.selected && !removedNodeIds.has(e.source) && !removedNodeIds.has(e.target)
      );
    });
  }

  // Handle edge double-click for label editing
  function handleEdgeDoubleClick(_, edge) {
    if (readOnly) return;
    const newLabel = prompt("Edge label:", edge.label || "");
    if (newLabel === null) return;
    setEdges((eds) =>
      eds.map((e) => (e.id === edge.id ? { ...e, label: newLabel } : e))
    );
  }

  return (
    <div className="w-full h-full" style={{ minHeight: 400 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={readOnly ? undefined : onNodesChange}
        onEdgesChange={readOnly ? undefined : onEdgesChange}
        onConnect={readOnly ? undefined : onConnect}
        onEdgeDoubleClick={handleEdgeDoubleClick}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode={readOnly ? null : "Delete"}
        multiSelectionKeyCode="Shift"
        proOptions={{ hideAttribution: true }}
        style={{ background: "#0f172a" }}
      >
        <Background color="#1e293b" gap={20} size={1} />
        <Controls
          showInteractive={false}
          style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: 6 }}
        />
        <MiniMap
          style={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 6 }}
          nodeColor="#334155"
          maskColor="rgba(0,0,0,0.3)"
        />
        {!readOnly && (
          <Panel position="top-right" className="flex items-center gap-1">
            <button
              onClick={handleAddNode}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
              title="Add node"
            >
              <Plus size={12} /> Node
            </button>
            <button
              onClick={handleAutoLayout}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 hover:text-white transition-colors"
              title="Auto-layout"
            >
              <LayoutGrid size={12} /> Layout
            </button>
            <button
              onClick={handleDeleteSelected}
              className="flex items-center gap-1 px-2 py-1 rounded text-xs bg-slate-800 border border-slate-700 text-slate-300 hover:bg-red-900/60 hover:text-red-300 transition-colors"
              title="Delete selected"
            >
              <Trash2 size={12} />
            </button>
          </Panel>
        )}
      </ReactFlow>
    </div>
  );
}
