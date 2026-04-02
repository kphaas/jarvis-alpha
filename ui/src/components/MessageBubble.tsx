import { useState } from "react";
import { apiJson } from "../lib/apiFetch";

export interface Message {
  id?: string;
  role: "user" | "assistant";
  content: string;
  model_used?: string | null;
  memory_injected?: boolean;
  latency_ms?: number | null;
  council_detail?: Record<string, string> | null;
  streaming?: boolean;
  complexity?: number;
  thread_id?: string;
}

interface Props {
  msg: Message;
  onEscalated?: () => void;
}

const MODEL_COLOR: Record<string, { color: string; bg: string }> = {
  local:               { color: "#444441", bg: "#F1EFE8" },
  claude:              { color: "#3C3489", bg: "#EEEDFE" },
  perplexity:          { color: "#27500A", bg: "#EAF3DE" },
  gemini:              { color: "#633806", bg: "#FAEEDA" },
  "council/synthesis": { color: "#3C3489", bg: "#EEEDFE" },
};

function modelColor(model: string | null | undefined) {
  if (!model) return MODEL_COLOR["local"];
  const key = Object.keys(MODEL_COLOR).find(k => model.toLowerCase().includes(k));
  return key ? MODEL_COLOR[key] : MODEL_COLOR["local"];
}

function modelLabel(model: string | null | undefined): string {
  if (!model) return "auto";
  if (model.includes("council")) return "Council";
  if (model.includes("claude")) return "Claude";
  if (model.includes("perplexity") || model === "local" && false) return "Perplexity";
  if (model.includes("gemini")) return "Gemini";
  return "Local";
}

export function MessageBubble({ msg, onEscalated }: Props) {
  const [showCouncil, setShowCouncil] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [escalated, setEscalated] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isUser = msg.role === "user";
  const isCouncil = !!msg.council_detail && Object.keys(msg.council_detail).length > 0;
  const isHighComplexity = (msg.complexity ?? 0) >= 4;
  const mc = modelColor(msg.model_used);

  async function handleEscalate() {
    if (!msg.thread_id || escalated) return;
    setEscalating(true);
    try {
      await apiJson(`/v1/threads/${msg.thread_id}/escalate`, {
        method: "POST",
        body: JSON.stringify({ reason: "Manual escalation from chat" }),
      });
      setEscalated(true);
      onEscalated?.();
    } catch {}
    setEscalating(false);
  }

  if (isUser) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
        <div style={{
          maxWidth: "72%", padding: "9px 13px", borderRadius: "12px 2px 12px 12px",
          background: "#E6F1FB", color: "#0C447C", fontSize: 13, lineHeight: 1.6,
        }}>
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "flex-start" }}
      onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
      <div style={{
        width: 28, height: 28, borderRadius: "50%", flexShrink: 0, background: "#E6F1FB",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 11, fontWeight: 500, color: "#0C447C",
      }}>J</div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          background: "var(--color-background-secondary)", border: "0.5px solid var(--color-border-tertiary)",
          borderRadius: "2px 12px 12px 12px", padding: "10px 13px",
          fontSize: 13, lineHeight: 1.6, color: "var(--color-text-primary)",
          whiteSpace: "pre-wrap", wordBreak: "break-word",
        }}>
          {msg.content}
          {msg.streaming && (
            <span style={{
              display: "inline-block", width: 2, height: 13, background: "var(--color-text-primary)",
              marginLeft: 2, verticalAlign: "text-bottom",
              animation: "blink 1s step-end infinite",
            }} />
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 5, flexWrap: "wrap" }}>
          {msg.memory_injected && (
            <span style={{
              fontSize: 10, padding: "1px 6px", borderRadius: 3,
              background: "#E1F5EE", color: "#085041", fontWeight: 500,
            }}>drawing from memory</span>
          )}
          {msg.model_used && (
            <span style={{
              fontSize: 10, padding: "1px 6px", borderRadius: 3,
              background: mc.bg, color: mc.color, fontWeight: 500,
            }}>{modelLabel(msg.model_used)}</span>
          )}
          {msg.latency_ms && (
            <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{msg.latency_ms}ms</span>
          )}
          {isCouncil && (
            <button onClick={() => setShowCouncil(s => !s)} style={{
              fontSize: 10, padding: "1px 6px", borderRadius: 3, cursor: "pointer",
              background: "transparent", border: "0.5px solid var(--color-border-secondary)",
              color: "var(--color-text-secondary)", fontFamily: "var(--font-sans)",
            }}>
              {showCouncil ? "Hide thinking" : "Show thinking"}
            </button>
          )}
          {hovered && !escalated && msg.thread_id && (
            <button onClick={handleEscalate} disabled={escalating} style={{
              fontSize: 10, padding: "1px 6px", borderRadius: 3, cursor: "pointer",
              background: "transparent", border: "0.5px solid #BA7517",
              color: "#BA7517", fontFamily: "var(--font-sans)",
              opacity: escalating ? 0.5 : 1,
            }}>
              {escalating ? "Queuing…" : "Send to overnight"}
            </button>
          )}
          {escalated && (
            <span style={{ fontSize: 10, color: "#BA7517" }}>◑ Queued for tonight</span>
          )}
        </div>

        {isHighComplexity && !escalated && msg.thread_id && (
          <div style={{
            marginTop: 6, padding: "6px 10px", borderRadius: "var(--border-radius-md)",
            background: "#FAEEDA", border: "0.5px solid #EF9F27",
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ fontSize: 11, color: "#633806" }}>This looks complex — run overnight for deeper results?</span>
            <button onClick={handleEscalate} style={{
              fontSize: 11, padding: "2px 8px", borderRadius: 4, cursor: "pointer",
              background: "#BA7517", border: "none", color: "#fff", fontFamily: "var(--font-sans)",
            }}>Queue</button>
          </div>
        )}

        {showCouncil && isCouncil && msg.council_detail && (
          <div style={{
            marginTop: 8, display: "grid",
            gridTemplateColumns: `repeat(${Object.keys(msg.council_detail).length}, 1fr)`, gap: 8,
          }}>
            {Object.entries(msg.council_detail).map(([model, text]) => {
              const mc2 = modelColor(model);
              return (
                <div key={model} style={{
                  padding: "8px 10px", borderRadius: "var(--border-radius-md)",
                  background: mc2.bg, border: `0.5px solid ${mc2.color}40`,
                }}>
                  <div style={{ fontSize: 10, fontWeight: 500, color: mc2.color, marginBottom: 4, textTransform: "uppercase" }}>{model}</div>
                  <div style={{ fontSize: 12, color: "var(--color-text-primary)", lineHeight: 1.5 }}>{text}</div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
