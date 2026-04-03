import { useState, useCallback } from "react";
import { ThreadSidebar, type Thread } from "../components/ThreadSidebar";
import { ChatWindow } from "../components/ChatWindow";
import { ModelSelector } from "../components/ModelSelector";
import { apiJson } from "../lib/apiFetch";

export default function Ask() {
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activeTitle, setActiveTitle]       = useState("New conversation");
  const [editingTitle, setEditingTitle]     = useState(false);
  const [titleInput, setTitleInput]         = useState("");
  const [sidebarTick, setSidebarTick]       = useState(0);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [showCouncil, setShowCouncil]       = useState(false);

  const isCouncil = selectedModels.length >= 2;

  function refreshSidebar() { setSidebarTick(t => t + 1); }

  const handleSelectThread = useCallback((t: Thread) => {
    setActiveThreadId(t.id);
    setActiveTitle(t.title);
  }, []);

  const handleNewThread = useCallback(() => {
    setActiveThreadId(null);
    setActiveTitle("New conversation");
  }, []);

  const handleThreadCreated = useCallback((id: string) => {
    setActiveThreadId(id);
    refreshSidebar();
    setTimeout(refreshSidebar, 2000);
  }, []);

  async function handleTitleSave() {
    if (!activeThreadId || !titleInput.trim()) { setEditingTitle(false); return; }
    try {
      await apiJson(`/v1/threads/${activeThreadId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: titleInput.trim() }),
      });
      setActiveTitle(titleInput.trim());
      refreshSidebar();
    } catch {}
    setEditingTitle(false);
  }

  return (
    <div style={{ display: "flex", height: "100%", overflow: "hidden" }}>
      <ThreadSidebar
        activeId={activeThreadId}
        onSelect={handleSelectThread}
        onNew={handleNewThread}
        refreshTick={sidebarTick}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, overflow: "visible" }}>
        <div style={{
          padding: "9px 14px",
          borderBottom: "0.5px solid var(--color-border-tertiary)",
          display: "flex", alignItems: "center", gap: 8,
          background: "var(--color-background-primary)",
          flexShrink: 0, overflow: "visible",
          position: "relative", zIndex: 10,
        }}>
          {editingTitle ? (
            <input
              autoFocus value={titleInput}
              onChange={e => setTitleInput(e.target.value)}
              onBlur={handleTitleSave}
              onKeyDown={e => { if (e.key === "Enter") handleTitleSave(); if (e.key === "Escape") setEditingTitle(false); }}
              style={{
                flex: 1, fontSize: 13, fontWeight: 500,
                border: "none", borderBottom: "1px solid var(--color-border-secondary)",
                background: "transparent", outline: "none",
                fontFamily: "var(--font-sans)", color: "var(--color-text-primary)",
              }}
            />
          ) : (
            <span
              style={{ flex: 1, fontSize: 13, fontWeight: 500, color: "var(--color-text-primary)", cursor: "text" }}
              onDoubleClick={() => { setTitleInput(activeTitle); setEditingTitle(true); }}
            >
              {activeTitle}
            </span>
          )}
          <svg
            width="12" height="12" viewBox="0 0 16 16" fill="none"
            stroke="var(--color-text-tertiary)" strokeWidth="1.5"
            style={{ cursor: "pointer", opacity: 0.4, flexShrink: 0 }}
            onClick={() => { setTitleInput(activeTitle); setEditingTitle(true); }}
          >
            <path d="M11 2L14 5L5 14H2V11L11 2Z"/>
          </svg>

          <button
            onClick={() => isCouncil && setShowCouncil(s => !s)}
            style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "4px 9px", borderRadius: 20, fontSize: 11, fontWeight: 500,
              fontFamily: "var(--font-sans)", cursor: isCouncil ? "pointer" : "default",
              border: `0.5px solid ${isCouncil ? "rgba(83,74,183,0.3)" : "var(--color-border-tertiary)"}`,
              background: isCouncil && showCouncil ? "rgba(83,74,183,0.12)" : "transparent",
              color: isCouncil ? (showCouncil ? "#3C3489" : "var(--color-text-secondary)") : "var(--color-text-tertiary)",
              transition: "all 0.2s",
            }}
          >
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
              <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1"/>
              <circle cx="6" cy="6" r="2" fill="currentColor"/>
            </svg>
            {isCouncil ? (showCouncil ? "Hide Council" : `··· Council (${selectedModels.length})`) : "Council"}
          </button>

          <ModelSelector selected={selectedModels} onChange={setSelectedModels} />
        </div>

        <ChatWindow
          threadId={activeThreadId}
          selectedModels={selectedModels}
          showCouncil={showCouncil}
          onThreadCreated={handleThreadCreated}
          onEscalated={refreshSidebar}
        />
      </div>
    </div>
  );
}
