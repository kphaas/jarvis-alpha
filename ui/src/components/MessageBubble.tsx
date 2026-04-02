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
  councilStreams?: Record<string, string>;
  streaming?: boolean;
  complexity?: number;
  thread_id?: string;
}

interface Props {
  msg: Message;
  showCouncilPanels?: boolean;
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

export function MessageBubble({ msg, showCouncilPanels, onEscalated }: Props) {
  const [escalating, setEscalating] = useState(false);
  const [escalated, setEscalated] = useState(false);
  const [hovered, setHovered] = useState(false);

  const isUser = msg.role === "user";
  const isCouncil = !!msg.council_detail && Object.keys(msg.council_detail).length > 0;
  const showPanels = !!showCouncilPanels && isCouncil;
  const panelData = msg.council_detail ?? {};
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
            <span style={{ fontSize: "0.75rem", color: "var(--color-text-tertiary)" }}>
              {showPanels ? "Showing Council" : "Hiding Council"}
            </span>
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

        {showPanels && Object.keys(panelData).length > 0 && (
          <div style={{
            marginTop: 8, display: "grid",
            gridTemplateColumns: `repeat(${Object.keys(panelData).length}, 1fr)`, gap: 6,
          }}>
            {Object.entries(panelData).map(([model, text]) => {
              const mc2 = modelColor(model);
              return (
                <div key={model} style={{
                  padding: "7px 9px", borderRadius: "var(--border-radius-md)",
                  background: mc2.bg, border: `0.5px solid ${mc2.color}40`,
                  minHeight: 40,
                }}>
                  <div style={{ fontSize: 9, fontWeight: 500, color: mc2.color, marginBottom: 3, textTransform: "uppercase" }}>
                    {model}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--color-text-primary)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                    {text || <span style={{ opacity: 0.4 }}>waiting…</span>}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
