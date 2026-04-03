import { useEffect, useRef, useState, useCallback } from "react";
import { apiJson } from "../lib/apiFetch";
import { apiFetchStream } from "../lib/apiFetchStream";
import { MessageBubble, type Message } from "./MessageBubble";
import { NeuralPulse } from "./NeuralPulse";
import { pillSendColor } from "./ModelSelector";

interface Props {
  threadId: string | null;
  selectedModels: string[];
  showCouncil: boolean;
  onThreadCreated: (id: string) => void;
  onEscalated: () => void;
}

export function ChatWindow({ threadId, selectedModels, showCouncil, onThreadCreated, onEscalated }: Props) {
  const [messages, setMessages]   = useState<Message[]>([]);
  const [input, setInput]         = useState("");
  const [streaming, setStreaming] = useState(false);
  const [waiting, setWaiting]     = useState(false);
  const bottomRef      = useRef<HTMLDivElement>(null);
  const scrollRef      = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const activeThread              = useRef<string | null>(threadId);
  const sendingRef = useRef(false);
  const lastSendTime = useRef(0);
  const [isSending, setIsSending] = useState(false);

  useEffect(() => { activeThread.current = threadId; }, [threadId]);

  useEffect(() => {
    if (!threadId) { setMessages([]); return; }
    if (streaming || sendingRef.current) return;
    apiJson<Message[]>(`/v1/threads/${threadId}/messages`)
      .then(msgs => setMessages(msgs))
      .catch(() => {});
  }, [threadId]);

  useEffect(() => {
    if (isAtBottom) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isAtBottom]);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
      setIsAtBottom(gap < 60);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, []);

  const send = useCallback(async () => {
    if ((window as any).__jarvisSending) return;
    (window as any).__jarvisSending = true;

    const text = input.trim();
    const now = Date.now();
    if (!text || streaming || isSending || sendingRef.current || (now - lastSendTime.current < 500)) {
      (window as any).__jarvisSending = false;
      return;
    }
    lastSendTime.current = now;
    setIsSending(true);
    (document.activeElement as HTMLElement)?.blur();
    sendingRef.current = true;
    setInput("");
    setStreaming(true);
    setWaiting(true);

    if (selectedModels.length >= 2) {
      setIsAtBottom(false);
    }

    setMessages(prev => [...prev, { role: "user", content: text }]);

    const isCouncil = selectedModels.length >= 2;
    const model     = selectedModels.length === 0 ? "auto"
                    : selectedModels.length === 1 ? selectedModels[0]
                    : "council";

    setMessages(prev => [...prev, {
      role: "assistant", content: "", streaming: true,
      model_used: model, thread_id: activeThread.current ?? undefined,
      councilStreams: undefined,
    }]);

    let accumulated = "";
    const councilAccum: Record<string, string> = {};

    await apiFetchStream(
      "/v1/chat/completions",
      {
        messages: [{ role: "user", content: text }],
        model,
        council_models: isCouncil ? selectedModels : [],
        thread_id: activeThread.current,
        stream: true,
        show_council: true,
      },
      (chunk) => {
        setWaiting(false);

        if (chunk.thread_id && !activeThread.current) {
          activeThread.current = chunk.thread_id;
          onThreadCreated(chunk.thread_id);
        }

        if (chunk.council_model) {
          councilAccum[chunk.council_model] = (councilAccum[chunk.council_model] ?? "") + (chunk.delta ?? "");
          if (chunk.thread_id) {
            setMessages(prev => {
              const next = [...prev];
              const idx  = next.findLastIndex(m => m.role === "assistant" && m.streaming);
              if (idx >= 0) next[idx] = { ...next[idx], thread_id: chunk.thread_id };
              return next;
            });
          }
        } else {
          accumulated += chunk.delta;
          setMessages(prev => {
            const next = [...prev];
            const idx  = next.findLastIndex(m => m.role === "assistant" && m.streaming);
            if (idx >= 0) next[idx] = {
              ...next[idx],
              content: accumulated,
              thread_id: chunk.thread_id,
            };
            return next;
          });
        }
      },
      (tid, finalModel, councilDetail) => {
        (window as any).__jarvisSending = false;
        const resolved = tid || activeThread.current;
        if (resolved && !activeThread.current) {
          activeThread.current = resolved;
          onThreadCreated(resolved);
        }
        const resolvedCouncilDetail =
          councilDetail && Object.keys(councilDetail).length > 0
            ? councilDetail
            : Object.keys(councilAccum).length > 0
              ? { ...councilAccum }
              : null;
        setMessages(prev => {
          const next = [...prev];
          const idx  = next.findLastIndex(m => m.role === "assistant" && m.streaming);
          if (idx >= 0) next[idx] = {
            ...next[idx],
            streaming: false,
            model_used: finalModel,
            council_detail: resolvedCouncilDetail,
            councilStreams: undefined,
            thread_id: resolved ?? undefined,
            complexity: text.split(" ").length > 30 ? 4 : 2,
          };
          return next;
        });
        setStreaming(false);
        setWaiting(false);
        sendingRef.current = false;
        setIsSending(false);
      },
      (err) => {
        (window as any).__jarvisSending = false;
        setMessages(prev => {
          const next = [...prev];
          const idx  = next.findLastIndex(m => m.role === "assistant" && m.streaming);
          if (idx >= 0) next[idx] = { ...next[idx], streaming: false, content: `Error: ${err}` };
          return next;
        });
        setStreaming(false);
        setWaiting(false);
        sendingRef.current = false;
        setIsSending(false);
      }
    );
  }, [input, streaming, selectedModels, showCouncil, onThreadCreated]);

  const sendColor = pillSendColor(selectedModels);

  const _fadeStyle = `@keyframes msgFadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }`;

  const statusLine = selectedModels.length === 0
    ? "Tier: auto · JARVIS decides · keyword-routed"
    : selectedModels.length === 1
    ? `Tier: manual · ${selectedModels[0]} · enter to send`
    : `Council: ${selectedModels.join(" + ")} · synthesis after · enter to send`;

  return (
    <div style={{
      flex: 1, display: "flex", flexDirection: "column",
      minWidth: 0, height: "100%", overflow: "hidden",
      position: "relative", zIndex: 0,
    }}>
      <style>{_fadeStyle}</style>
      <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "24px 0", position: "relative", zIndex: 0 }}>
        <div style={{ maxWidth: 720, margin: "0 auto", padding: "0 24px" }}>
        {messages.length === 0 && (
          <div style={{
            height: "100%", display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 10,
            color: "var(--color-text-tertiary)",
          }}>
            <svg width="36" height="36" viewBox="0 0 40 40" fill="none">
              <ellipse cx="20" cy="16" rx="10" ry="10" stroke="currentColor" strokeWidth="1.5"/>
              <ellipse cx="20" cy="18" rx="5" ry="5" stroke="currentColor" strokeWidth="1"/>
              <line x1="20" y1="26" x2="20" y2="34" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
            <span style={{ fontSize: 12 }}>Ask JARVIS anything</span>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} showCouncilPanels={showCouncil} onEscalated={onEscalated} />
        ))}
        {(streaming || waiting) && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0 4px 36px" }}>
            <NeuralPulse active={streaming || waiting} />
            <span style={{ fontSize: 10, color: "var(--color-text-tertiary)", fontWeight: 500 }}>
              JARVIS is thinking…
            </span>
          </div>
        )}
        </div><div ref={bottomRef} />
      </div>

      {!isAtBottom && (
        <div
          onClick={() => {
            bottomRef.current?.scrollIntoView({ behavior: "smooth" });
            setIsAtBottom(true);
          }}
          style={{
            position: "absolute",
            bottom: 80,
            right: 24,
            width: 36,
            height: 36,
            borderRadius: "50%",
            background: "var(--color-bg-primary, #fff)",
            border: "1px solid var(--color-border-secondary, #ddd)",
            boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            zIndex: 10,
            transition: "opacity 0.2s ease",
          }}
          title="Scroll to bottom"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M4 9l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
      )}

      <div style={{
        borderTop: "0.5px solid var(--color-border-tertiary)",
        padding: "10px 14px", background: "var(--color-background-primary)", flexShrink: 0,
      }}>
        <div style={{ display: "flex", gap: 7, alignItems: "flex-end" }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.stopPropagation(); send(); } }}
            placeholder="Ask JARVIS anything…"
            rows={1}
            style={{
              flex: 1, border: "0.5px solid var(--color-border-secondary)",
              borderRadius: "var(--border-radius-md)", padding: "8px 11px",
              fontSize: 12, color: "var(--color-text-primary)",
              background: "var(--color-background-primary)",
              resize: "none", fontFamily: "var(--font-sans)", lineHeight: 1.5,
              minHeight: 36, maxHeight: 110, outline: "none",
            }}
          />
          <button
            onClick={send}
            disabled={streaming || waiting || !input.trim()}
            style={{
              width: 32, height: 32, borderRadius: 8, border: "none",
              background: streaming || waiting || !input.trim() ? "var(--color-border-tertiary)" : sendColor,
              cursor: streaming || waiting || !input.trim() ? "default" : "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0, transition: "background 0.2s",
            }}
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="white">
              <path d="M2 8L14 2L8 14L7 9L2 8Z"/>
            </svg>
          </button>
        </div>
        <div style={{ marginTop: 5, fontSize: 9, color: "var(--color-text-tertiary)", letterSpacing: "0.02em" }}>
          {statusLine}
        </div>
      </div>
    </div>
  );
}
