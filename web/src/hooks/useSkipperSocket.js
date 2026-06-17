import { useRef, useState, useCallback, useEffect } from "react";
import { getToken, forceLogout } from "../utils/api";

/**
 * WebSocket hook for SkipperBot chat.
 *
 * Manages connection lifecycle, auto-reconnect, and message dispatch.
 * Protocol matches agent.py WebSocket endpoint:
 *   Send:    { message: "..." }
 *   Receive: { type: "typing"|"progress"|"chat_response"|"notification"|"message_from_user", ... }
 */

const RECONNECT_DELAY = 3000;
const PING_INTERVAL = 30000;
// Server closes with this code when the token is missing/rejected (agent.py).
const WS_AUTH_FAILED = 4401;

// Carry the bearer token in the Sec-WebSocket-Protocol header instead of the URL
// querystring, so it never lands in the access log (issue #7). The raw token isn't
// a legal subprotocol value (it contains ':'), so base64url-encode it; the server
// decodes 'bearer.<b64url>'. Read per-connect so a refreshed token is used on reconnect.
function bearerSubprotocol() {
  const token = getToken();
  if (!token) return null;
  const b64 = btoa(token).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `bearer.${b64}`;
}

// The user's IANA timezone — sent to /api/chat/history so the server buckets dates
// (and Today/Yesterday) in the SAME zone the client uses for live grouping (issue #8).
function browserTz() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { return ""; }
}

// Local calendar day-key 'YYYY-MM-DD' for an ISO timestamp (en-CA renders ISO order).
// Must match the server's local-Y-M-D day-key so live and reloaded separators line up.
function localDayKey(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleDateString("en-CA");
}

// Append a live message: stamp ts (server ts or local receive time), and insert a
// date_separator before it when its local day differs from the last real message's
// (so a session crossing midnight stays grouped without a reload).
function appendLive(prev, msg, makeId) {
  const ts = msg.ts || new Date().toISOString();
  const out = prev.slice();
  let lastKey = null;
  for (let i = out.length - 1; i >= 0; i--) {
    if (out[i].role !== "date_separator" && out[i].ts) { lastKey = localDayKey(out[i].ts); break; }
  }
  const key = localDayKey(ts);
  if (key && key !== lastKey) out.push({ id: makeId(), role: "date_separator", date: key });
  out.push({ ...msg, ts });
  return out;
}

export default function useSkipperSocket(userId, onOpenApp, onGoalsUpdated, onDocsUpdated, onRemindersUpdated, onRecipesUpdated, onBrainstormUpdated, onEditProposal, onTodoUpdated) {
  const [connected, setConnected] = useState(false);
  // Coarse connection state for the chat surface: 'connecting' | 'connected' | 'auth_failed'.
  const [connectionState, setConnectionState] = useState("connecting");
  // Starts empty; the history effect below populates prior turns then a greeting.
  const [messages, setMessages] = useState([]);
  const [isTyping, setIsTyping] = useState(false);
  const [progress, setProgress] = useState(null);
  const [sending, setSending] = useState(false);
  const [updateAvailable, setUpdateAvailable] = useState(false);

  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);
  const pingTimer = useRef(null);
  const msgIdRef = useRef(0);
  const buildIdRef = useRef(null);

  // Keep stable refs to event callbacks so ws.onmessage always calls the latest
  const onOpenAppRef = useRef(onOpenApp);
  const onGoalsUpdatedRef = useRef(onGoalsUpdated);
  const onDocsUpdatedRef = useRef(onDocsUpdated);
  const onRemindersUpdatedRef = useRef(onRemindersUpdated);
  const onRecipesUpdatedRef = useRef(onRecipesUpdated);
  const onBrainstormUpdatedRef = useRef(onBrainstormUpdated);
  const onEditProposalRef = useRef(onEditProposal);
  const onTodoUpdatedRef = useRef(onTodoUpdated);
  useEffect(() => { onOpenAppRef.current = onOpenApp; }, [onOpenApp]);
  useEffect(() => { onGoalsUpdatedRef.current = onGoalsUpdated; }, [onGoalsUpdated]);
  useEffect(() => { onDocsUpdatedRef.current = onDocsUpdated; }, [onDocsUpdated]);
  useEffect(() => { onRemindersUpdatedRef.current = onRemindersUpdated; }, [onRemindersUpdated]);
  useEffect(() => { onRecipesUpdatedRef.current = onRecipesUpdated; }, [onRecipesUpdated]);
  useEffect(() => { onBrainstormUpdatedRef.current = onBrainstormUpdated; }, [onBrainstormUpdated]);
  useEffect(() => { onEditProposalRef.current = onEditProposal; }, [onEditProposal]);
  useEffect(() => { onTodoUpdatedRef.current = onTodoUpdated; }, [onTodoUpdated]);

  const nextId = () => `msg-${++msgIdRef.current}-${Date.now()}`;

  // Resume the session on load: pull recent turns (incl. tool calls) from the
  // server, then post a fresh greeting at the end. A brand-new user with no
  // history just gets the greeting. Runs once per userId.
  const historyLoadedRef = useRef(false);
  useEffect(() => {
    if (!userId || historyLoadedRef.current) return;
    historyLoadedRef.current = true;
    let cancelled = false;
    (async () => {
      let hist = [];
      try {
        const res = await fetch(`/api/chat/history?limit=20&tz=${encodeURIComponent(browserTz())}`);
        if (res.ok) {
          const data = await res.json();
          // Server returns ts on each message + date_separator rows (issue #8).
          hist = (data.messages || []).map((m) => ({ ...m, id: nextId() }));
        }
      } catch {
        // Offline or fresh session — fall through to a plain greeting.
      }
      if (cancelled) return;
      const greeting = {
        id: nextId(),
        role: "bot",
        ts: new Date().toISOString(),
        content: hist.length
          ? "Welcome back! Here's where we left off — what can I help you with?"
          : "Hello! I'm Skipper, your AI assistant. How can I help you today?",
      };
      // Prepend history ahead of anything that arrived while loading (e.g. a
      // proactive notification), then the greeting closes out the resume.
      setMessages((prev) => [...hist, greeting, ...prev]);
    })();
    return () => { cancelled = true; };
  }, [userId]);

  // Build WebSocket URL — use Vite proxy in dev, direct in prod
  const getWsUrl = useCallback(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    // No token in the URL — it rides the Sec-WebSocket-Protocol header (issue #7).
    return `${proto}//${host}/ws/${encodeURIComponent(userId)}`;
  }, [userId]);

  const connect = useCallback(() => {
    if (!userId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setConnectionState("connecting");
    const subprotocol = bearerSubprotocol();
    const ws = subprotocol
      ? new WebSocket(getWsUrl(), [subprotocol])
      : new WebSocket(getWsUrl());

    ws.onopen = () => {
      setConnected(true);
      setConnectionState("connected");
      clearInterval(pingTimer.current);
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case "typing":
          setIsTyping(data.status);
          break;

        case "progress":
          setProgress(data.message);
          break;

        case "chat_response":
          setIsTyping(false);
          setProgress(null);
          setSending(false);
          setMessages((prev) => appendLive(prev,
            { id: nextId(), role: "bot", content: data.response, ts: data.ts }, nextId));
          break;

        case "notification":
          setMessages((prev) => appendLive(prev, {
            id: nextId(),
            role: "notification",
            content: data.message,
            source: data.source,
            ts: data.ts,
          }, nextId));
          break;

        case "message_from_user":
          setMessages((prev) => appendLive(prev, {
            id: nextId(),
            role: "bot",
            content: `[Message from ${data.from_user}]: ${data.message}`,
            ts: data.ts,
          }, nextId));
          break;

        case "open_app":
          if (onOpenAppRef.current && data.app_type) {
            onOpenAppRef.current(data.app_type, data.context || {});
          }
          break;

        case "goals_updated":
          if (onGoalsUpdatedRef.current) onGoalsUpdatedRef.current();
          break;

        case "doc_updated":
          if (onDocsUpdatedRef.current) onDocsUpdatedRef.current();
          break;

        case "reminders_updated":
          if (onRemindersUpdatedRef.current) onRemindersUpdatedRef.current();
          break;

        case "recipes_updated":
          if (onRecipesUpdatedRef.current) onRecipesUpdatedRef.current();
          break;

        case "brainstorm_updated":
          if (onBrainstormUpdatedRef.current) onBrainstormUpdatedRef.current();
          break;

        case "todo_updated":
          if (onTodoUpdatedRef.current) onTodoUpdatedRef.current();
          break;

        case "tool_call":
          setMessages((prev) => appendLive(prev, {
            id: nextId(),
            role: "tool_call",
            toolName: data.tool_name,
            toolArgs: data.tool_args || {},
            toolCallId: data.tool_call_id,
            ts: data.ts,
          }, nextId));
          break;

        case "idea_edit_proposal":
          if (onEditProposalRef.current) onEditProposalRef.current(data);
          break;

        case "server_restarting":
          setMessages((prev) => appendLive(prev,
            { id: nextId(), role: "notification", content: "Agent is restarting — draining in-flight work...", source: "system" }, nextId));
          break;

        case "build_id":
          if (buildIdRef.current && buildIdRef.current !== data.build_id) {
            setUpdateAvailable(true);
          }
          buildIdRef.current = data.build_id;
          break;

        default:
          break;
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      wsRef.current = null;
      clearInterval(pingTimer.current);
      if (event && event.code === WS_AUTH_FAILED) {
        // Token missing/rejected — don't retry forever into a silently dead chat.
        // Surface it and bounce to login, mirroring the HTTP 401 path.
        setConnectionState("auth_failed");
        forceLogout();
        return;
      }
      setConnectionState("connecting");
      reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY);
    };

    ws.onerror = () => {
      // onclose will fire after this, triggering reconnect
    };

    wsRef.current = ws;
  }, [userId, getWsUrl]);

  // Connect when userId is set
  useEffect(() => {
    if (userId) connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      clearInterval(pingTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null; // prevent reconnect on unmount
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [userId, connect]);

  const sendMessage = useCallback(
    (text) => {
      if (!text.trim() || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      setSending(true);
      // No server echo for the user turn — stamp it client-side (issue #8).
      setMessages((prev) => appendLive(prev,
        { id: nextId(), role: "user", content: text }, nextId));
      wsRef.current.send(JSON.stringify({ message: text }));
    },
    []
  );

  const sendContext = useCallback(
    (context) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
      wsRef.current.send(JSON.stringify({ type: "app_context", context }));
    },
    []
  );

  return { connected, connectionState, messages, isTyping, progress, sending, updateAvailable, sendMessage, sendContext };
}
