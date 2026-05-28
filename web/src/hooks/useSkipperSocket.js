import { useRef, useState, useCallback, useEffect } from "react";

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

export default function useSkipperSocket(userId, onOpenApp, onGoalsUpdated, onDocsUpdated, onRemindersUpdated, onRecipesUpdated, onBrainstormUpdated, onEditProposal, onTodoUpdated) {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState([
    { id: "welcome", role: "bot", content: "Hello! I'm Skipper, your AI assistant. How can I help you today?" },
  ]);
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

  // Build WebSocket URL — use Vite proxy in dev, direct in prod
  const getWsUrl = useCallback(() => {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    return `${proto}//${host}/ws/${encodeURIComponent(userId)}`;
  }, [userId]);

  const connect = useCallback(() => {
    if (!userId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(getWsUrl());

    ws.onopen = () => {
      setConnected(true);
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
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: "bot", content: data.response },
          ]);
          break;

        case "notification":
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "notification",
              content: data.message,
              source: data.source,
            },
          ]);
          break;

        case "message_from_user":
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "bot",
              content: `[Message from ${data.from_user}]: ${data.message}`,
            },
          ]);
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
          setMessages((prev) => [
            ...prev,
            {
              id: nextId(),
              role: "tool_call",
              toolName: data.tool_name,
              toolArgs: data.tool_args || {},
              toolCallId: data.tool_call_id,
            },
          ]);
          break;

        case "idea_edit_proposal":
          if (onEditProposalRef.current) onEditProposalRef.current(data);
          break;

        case "server_restarting":
          setMessages((prev) => [
            ...prev,
            { id: nextId(), role: "notification", content: "Agent is restarting — draining in-flight work...", source: "system" },
          ]);
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

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      clearInterval(pingTimer.current);
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
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "user", content: text },
      ]);
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

  return { connected, messages, isTyping, progress, sending, updateAvailable, sendMessage, sendContext };
}
