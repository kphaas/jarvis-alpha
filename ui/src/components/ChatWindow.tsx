import { useEffect, useRef, useState, useCallback } from "react";
import { apiJson } from "../lib/apiFetch";
import { apiFetchStream } from "../lib/apiFetchStream";
import { ModelSelector } from "./ModelSelector";
import { MessageBubble, type Message } from "./MessageBubble";

interface Props {
  threadId: string | null;
  onThreadCreated: (id: string) => void;
  onEscalated: () => void;
}

export function ChatWindow({ threadId, onThreadCreated, onEscalated }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const activeThread = useRef<string | null>(threadId);

  useEffect(() => { activeThread.current = threadId; }, [threadId]);

  useEffect(() => {
    if (!threadId) { setMessages([]); return; }
    apiJson<Message[]>(`/v1/threads/${threadId}/messages`)
      .then(msgs => setMessages(msgs))
      .catch(() => {});
  }, [threadId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    setStreaming(true);

    const userMsg: Message = { role: "user", content: text };
    setMessages(prev => [...prev, userMsg]);

    const isCouncil = selectedModels.length >= 2;
    const model = selectedModels.length === 1 ? selectedModels[0] : selectedModels.length === 0 ? "auto" : "council";

    const streamingMsg: Message = {
      role: "assistant", content: "", streaming: true,
      model_used: model, thread_id: activeThread.current ?? undefined,
    };
    setMessages(prev => [...prev, streamingMsg]);

    let accumulated = "";
    let finalThreadId = activeThread.current ?? null;

    await apiFetchStream(
      "/v1/chat/completions",
      {
        messages: [{ role: "user", content: text }],
        model,
        council_models: isCouncil ? selectedModels : [],
        thread_id: activeThread.current,
        stream: true,
        show_council: false,
      },
      (chunk) => {
        accumulated += chunk.delta;
        if (chunk.thread_id && !activeThread.current) {
          finalThreadId = chunk.thread_id;
          activeThread.current = chunk.thread_id;
          onThreadCreated(chunk.thread_id);
        }
        setMessages(prev => {
          const next = [...prev];
          const idx = next.findLastIndex(m => m.role === "assistant" && m.streaming);
          if (idx >= 0) next[idx] = { ...next[idx], content: accumulated, thread_id: chunk.thread_id };
          return next;
        });
      },
      (tid, finalModel, councilDetail) => {
        const resolvedThread = tid || finalThreadId;
        if (resolvedThread && !activeThread.current) {
          activeThread.current = resolvedThread;
          onThreadCreated(resolvedThread);
        }
        setMessages(prev => {
          const next = [...prev];
          const idx = next.findLastIndex(m => m.role === "assistant" && m.streaming);
          if (idx >= 0) next[idx] = {
            ...next[idx],
            streaming: false,
            model_used: finalModel,
            council_detail: councilDetail ?? null,
            thread_id: resolvedThread ?? undefined,
            complexity: text.split(" ").length > 30 ? 4 : 2,
          };
          return next;
        });
        setStreaming(false);
      },
      (err) => {
        setMessages(prev => {
          const next = [...prev];
          const idx = next.findLastIndex(m => m.role === "assistant" && m.streaming);
          if (idx >= 0) next[idx] = { ...next[idx], streaming: false, content: `Error: ${err}` };
          return next;
        });
        setStreaming(false);
      }
    );
  }, [input, streaming, selectedModels, onThreadCreated]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, height: "100%" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
        {messages.length === 0 && (
          <div style={{
            height: "100%", display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center", gap: 12,
            color: "var(--color-text-tertiary)",
          }}>
            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
              <ellipse cx="20" cy="16" rx="10" ry="10" stroke="currentColor" strokeWidth="1.5"/>
              <ellipse cx="20" cy="18" rx="5" ry="5" stroke="currentColor" strokeWidth="1"/>
              <line x1="20" y1="26" x2="20" y2="34" stroke="currentColor" strokeWidth="1.5"/>
            </svg>
            <span style={{ fontSize: 13 }}>Ask JARVIS anything</span>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} onEscalated={onEscalated} />
        ))}
        <div ref={bottomRef} />
      </div>

      <div style={{ borderTop: "0.5px solid var(--color-border-tertiary)", padding: "10px 16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
          <ModelSelector selected={selectedModels} onChange={setSelectedModels} />
          {selectedModels.length >= 2 && (
            <span style={{ fontSize: 11, color: "#534AB7", fontWeight: 500 }}>Council mode active</span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea
            value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Ask JARVIS anything…"
            rows={1}
            style={{
              flex: 1, border: "0.5px solid var(--color-border-secondary)",
              borderRadius: "var(--border-radius-md)", padding: "8px 12px",
              fontSize: 13, color: "var(--color-text-primary)", background: "var(--color-background-primary)",
              resize: "none", fontFamily: "var(--font-sans)", lineHeight: 1.5,
              minHeight: 38, maxHeight: 120, outline: "none",
            }}
          />
          <button onClick={send} disabled={streaming || !input.trim()} style={{
            width: 34, height: 34, borderRadius: 8, border: "none",
            background: streaming || !input.trim() ? "var(--color-border-tertiary)" : "#378ADD",
            cursor: streaming || !input.trim() ? "default" : "pointer",
            display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
          }}>
            <svg width="14" height="14" viewBox="0 0 16 16" fill="white">
              <path d="M2 8L14 2L8 14L7 9L2 8Z"/>
            </svg>
          </button>
        </div>
        <div style={{ marginTop: 6, fontSize: 10, color: "var(--color-text-tertiary)" }}>
          {selectedModels.length === 0 && "TIER: AUTO · JARVIS DECIDES · KEYWORD-ROUTED"}
          {selectedModels.length === 1 && `TIER: MANUAL · ${selectedModels[0].toUpperCase()} · ENTER TO SEND`}
          {selectedModels.length >= 2 && `COUNCIL: ${selectedModels.join(" + ").toUpperCase()} · ENTER TO SEND`}
        </div>
      </div>
    </div>
  );
}
