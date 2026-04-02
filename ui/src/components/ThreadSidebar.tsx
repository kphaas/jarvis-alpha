import { useEffect, useState, useCallback, useRef } from "react";
import type { MouseEvent } from "react";
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
  auto:                { label: "AUTO",       color: "#0C447C", bg: "#E6F1FB" },
  local:               { label: "Local",      color: "#444441", bg: "#F1EFE8" },
  claude:              { label: "Claude",     color: "#3C3489", bg: "#EEEDFE" },
  perplexity:          { label: "Perplexity", color: "#27500A", bg: "#EAF3DE" },
  gemini:              { label: "Gemini",     color: "#633806", bg: "#FAEEDA" },
  "council/synthesis": { label: "Council",    color: "#3C3489", bg: "#EEEDFE" },
};

function badgeFor(model: string | null) {
  if (!model) return MODEL_BADGE["auto"];
  const key = Object.keys(MODEL_BADGE).find(k => model.toLowerCase().includes(k));
  return key ? MODEL_BADGE[key] : MODEL_BADGE["auto"];
}

interface Toast {
  id: string;
  title: string;
  timer: ReturnType<typeof setTimeout>;
}

export function ThreadSidebar({ activeId, onSelect, onNew, refreshTick }: Props) {
  const [threads, setThreads]     = useState<Thread[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [toast, setToast]         = useState<Toast | null>(null);
  const undoRef                   = useRef<{ id: string } | null>(null);

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

  async function handleDelete(t: Thread, e: MouseEvent) {
    e.stopPropagation();
    undoRef.current = { id: t.id };

    if (toast) {
      clearTimeout(toast.timer);
      await apiJson(`/v1/threads/${toast.id}`, { method: "DELETE" }).catch(() => {});
    }

    setThreads(prev => prev.filter(th => th.id !== t.id));

    const timer = setTimeout(async () => {
      if (undoRef.current?.id === t.id) {
        await apiJson(`/v1/threads/${t.id}`, { method: "DELETE" }).catch(() => {});
        undoRef.current = null;
      }
      setToast(null);
    }, 4000);

    setToast({ id: t.id, title: t.title, timer });
  }

  async function handleUndo() {
    if (!toast) return;
    clearTimeout(toast.timer);
    undoRef.current = null;
    setToast(null);
    load();
  }

  const groups = groupThreads(threads);

  return (
    <aside style={{
      width: 220, flexShrink: 0,
      borderRight: "0.5px solid var(--color-border-tertiary)",
      display: "flex", flexDirection: "column",
      background: "#F7F6F2", height: "100%", overflow: "hidden",
      position: "relative",
    }}>
      <div style={{ padding: 11, borderBottom: "0.5px solid var(--color-border-tertiary)" }}>
        <button onClick={onNew} style={{
          width: "100%", padding: "7px 11px",
          border: "0.5px solid var(--color-border-secondary)",
          borderRadius: "var(--border-radius-md)",
          background: "var(--color-background-primary)",
          color: "var(--color-text-primary)", fontSize: 12, fontWeight: 500,
          cursor: "pointer", display: "flex", alignItems: "center", gap: 6,
          fontFamily: "var(--font-sans)",
        }}>
          <span style={{ fontSize: 14, color: "var(--color-text-secondary)" }}>+</span>
          New conversation
        </button>
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "6px 0" }}>
        {Object.entries(groups).map(([label, items]) => items.length === 0 ? null : (
          <div key={label}>
            <div style={{
              fontSize: 10, fontWeight: 500, color: "var(--color-text-tertiary)",
              padding: "8px 11px 3px", textTransform: "uppercase", letterSpacing: "0.06em",
            }}>{label}</div>
            {items.map(t => {
              const badge   = badgeFor(t.model_used);
              const isActive = t.id === activeId;
              const isHover  = hoveredId === t.id;
              return (
                <div
                  key={t.id}
                  onClick={() => onSelect(t)}
                  onMouseEnter={() => setHoveredId(t.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  style={{
                    padding: "7px 11px", cursor: "pointer", borderRadius: 6,
                    margin: "1px 5px", position: "relative",
                    background: isActive ? "var(--color-background-primary)" : isHover ? "var(--color-background-primary)" : "transparent",
                    border: isActive ? "0.5px solid var(--color-border-tertiary)" : "0.5px solid transparent",
                  }}
                >
                  {editingId === t.id ? (
                    <input
                      autoFocus value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      onBlur={() => handleRename(t)}
                      onKeyDown={e => { if (e.key === "Enter") handleRename(t); if (e.key === "Escape") setEditingId(null); }}
                      onClick={e => e.stopPropagation()}
                      style={{
                        width: "100%", border: "none", background: "transparent",
                        outline: "none", fontSize: 12, color: "var(--color-text-primary)",
                        fontFamily: "var(--font-sans)",
                      }}
                    />
                  ) : (
                    <div
                      onDoubleClick={e => { e.stopPropagation(); setEditingId(t.id); setEditTitle(t.title); }}
                      style={{
                        fontSize: 12, color: "var(--color-text-primary)",
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                        paddingRight: isHover ? 18 : 0,
                      }}
                    >
                      {t.title}
                    </div>
                  )}
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
                    <span style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>
                      {new Date(t.updated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                    <span style={{
                      fontSize: 9, padding: "1px 5px", borderRadius: 3, fontWeight: 500,
                      background: badge.bg, color: badge.color,
                    }}>{badge.label}</span>
                    {t.mode === "overnight" && (
                      <span style={{ fontSize: 10, color: "#BA7517" }}>◑</span>
                    )}
                  </div>
                  {isHover && editingId !== t.id && (
                    <button
                      onClick={e => handleDelete(t, e)}
                      style={{
                        position: "absolute", right: 8, top: "50%",
                        transform: "translateY(-50%)",
                        background: "transparent", border: "none", cursor: "pointer",
                        padding: 3, borderRadius: 4, display: "flex", alignItems: "center",
                        color: "var(--color-text-tertiary)",
                      }}
                      onMouseEnter={e => (e.currentTarget.style.color = "#E24B4A")}
                      onMouseLeave={e => (e.currentTarget.style.color = "var(--color-text-tertiary)")}
                    >
                      <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <path d="M3 4h10M6 4V2h4v2M5 4l1 9h4l1-9"/>
                      </svg>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ))}
        {threads.length === 0 && (
          <div style={{ padding: "24px 16px", fontSize: 12, color: "var(--color-text-tertiary)", textAlign: "center" }}>
            No conversations yet
          </div>
        )}
      </div>

      {toast && (
        <div style={{
          position: "absolute", bottom: 12, left: "50%", transform: "translateX(-50%)",
          background: "var(--color-background-primary)",
          border: "0.5px solid var(--color-border-secondary)",
          borderRadius: "var(--border-radius-md)",
          padding: "7px 12px", display: "flex", alignItems: "center", gap: 10,
          fontSize: 11, color: "var(--color-text-primary)", whiteSpace: "nowrap",
          zIndex: 50,
        }}>
          <span style={{ maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", color: "var(--color-text-secondary)" }}>
            Deleted
          </span>
          <button
            onClick={handleUndo}
            style={{
              background: "transparent", border: "none", cursor: "pointer",
              fontSize: 11, fontWeight: 500, color: "#378ADD",
              fontFamily: "var(--font-sans)", padding: 0,
            }}
          >
            Undo
          </button>
        </div>
      )}
    </aside>
  );
}
