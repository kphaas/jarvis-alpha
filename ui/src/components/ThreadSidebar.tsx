import { useEffect, useState, useCallback } from "react";
import { apiJson } from "../lib/apiFetch";

export interface Thread {
  id: string;
  title: string;
  mode: "realtime" | "overnight";
  model_used: string | null;
  project_id: number | null;
  created_at: string;
  updated_at: string;
}

interface Props {
  activeId: string | null;
  onSelect: (thread: Thread) => void;
  onNew: () => void;
  refreshTick: number;
}

function groupThreads(threads: Thread[]): Record<string, Thread[]> {
  const now = new Date();
  const groups: Record<string, Thread[]> = { Today: [], Yesterday: [], "This week": [], Older: [] };
  for (const t of threads) {
    const d = new Date(t.updated_at);
    const diffDays = Math.floor((now.getTime() - d.getTime()) / 86400000);
    if (diffDays < 1) groups["Today"].push(t);
    else if (diffDays < 2) groups["Yesterday"].push(t);
    else if (diffDays < 7) groups["This week"].push(t);
    else groups["Older"].push(t);
  }
  return groups;
}

const MODEL_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  auto:               { label: "AUTO",       color: "#0C447C", bg: "#E6F1FB" },
  local:              { label: "Local",      color: "#444441", bg: "#F1EFE8" },
  claude:             { label: "Claude",     color: "#3C3489", bg: "#EEEDFE" },
  perplexity:         { label: "Perplexity", color: "#27500A", bg: "#EAF3DE" },
  gemini:             { label: "Gemini",     color: "#633806", bg: "#FAEEDA" },
  "council/synthesis":{ label: "Council",    color: "#3C3489", bg: "#EEEDFE" },
};

function badgeFor(model: string | null) {
  if (!model) return MODEL_BADGE["auto"];
  const key = Object.keys(MODEL_BADGE).find(k => model.toLowerCase().includes(k));
  return key ? MODEL_BADGE[key] : MODEL_BADGE["auto"];
}

export function ThreadSidebar({ activeId, onSelect, onNew, refreshTick }: Props) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiJson<Thread[]>("/v1/threads");
      setThreads(data);
    } catch {}
  }, []);

  useEffect(() => { load(); }, [load, refreshTick]);

  async function handleRename(t: Thread) {
    if (!editTitle.trim() || editTitle === t.title) { setEditingId(null); return; }
    try {
      await apiJson(`/v1/threads/${t.id}`, { method: "PATCH", body: JSON.stringify({ title: editTitle }) });
      setEditingId(null);
      load();
    } catch {}
  }

  const groups = groupThreads(threads);

  return (
    <aside style={{
      width: 220, flexShrink: 0, borderRight: "0.5px solid var(--color-border-tertiary)",
      display: "flex", flexDirection: "column", background: "var(--color-background-secondary)",
      height: "100%", overflow: "hidden",
    }}>
      <div style={{ padding: 12, borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
        <button onClick={onNew} style={{
          width: "100%", padding: "7px 12px", border: "0.5px solid var(--color-border-secondary)",
          borderRadius: "var(--border-radius-md)", background: "var(--color-background-primary)",
          color: "var(--color-text-primary)", fontSize: 13, fontWeight: 500, cursor: "pointer",
          display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--font-sans)",
        }}>
          <span style={{ fontSize: 16, lineHeight: 1, color: "var(--color-text-secondary)" }}>+</span>
          New conversation
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
        {Object.entries(groups).map(([label, items]) => items.length === 0 ? null : (
          <div key={label}>
            <div style={{
              fontSize: 10, fontWeight: 500, color: "var(--color-text-tertiary)",
              padding: "8px 12px 4px", textTransform: "uppercase", letterSpacing: "0.06em",
            }}>{label}</div>
            {items.map(t => {
              const badge = badgeFor(t.model_used);
              const isActive = t.id === activeId;
              return (
                <div key={t.id} onClick={() => onSelect(t)}
                  style={{
                    padding: "7px 12px", cursor: "pointer", borderRadius: 6, margin: "1px 6px",
                    background: isActive ? "var(--color-background-primary)" : "transparent",
                    border: isActive ? "0.5px solid var(--color-border-tertiary)" : "0.5px solid transparent",
                    position: "relative",
                  }}
                  onMouseEnter={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "var(--color-background-primary)"; }}
                  onMouseLeave={e => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                >
                  {editingId === t.id ? (
                    <input
                      autoFocus value={editTitle} onChange={e => setEditTitle(e.target.value)}
                      onBlur={() => handleRename(t)}
                      onKeyDown={e => { if (e.key === "Enter") handleRename(t); if (e.key === "Escape") setEditingId(null); }}
                      onClick={e => e.stopPropagation()}
                      style={{
                        width: "100%", border: "none", background: "transparent", outline: "none",
                        fontSize: 13, color: "var(--color-text-primary)", fontFamily: "var(--font-sans)",
                      }}
                    />
                  ) : (
                    <div onDoubleClick={e => { e.stopPropagation(); setEditingId(t.id); setEditTitle(t.title); }}
                      style={{ fontSize: 13, color: "var(--color-text-primary)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {t.title}
                    </div>
                  )}
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>
                      {new Date(t.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                    <span style={{
                      fontSize: 10, padding: "1px 5px", borderRadius: 3, fontWeight: 500,
                      background: badge.bg, color: badge.color,
                    }}>{badge.label}</span>
                    {t.mode === "overnight" && (
                      <span style={{ fontSize: 10, color: "#BA7517" }}>◑</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
        {threads.length === 0 && (
          <div style={{ padding: "24px 16px", fontSize: 13, color: "var(--color-text-tertiary)", textAlign: "center" }}>
            No conversations yet
          </div>
        )}
      </div>
    </aside>
  );
}
