import { create } from 'zustand'
import type { Theme } from './types'

interface AppState {
  theme: Theme
  userId: string
  sessionId: string
  mode: string
  workspaceId: string | null
  persistent: boolean
  vaultUnlocked: boolean
  setTheme: (t: Theme) => void
  setMode: (m: string) => void
  setPersistent: (v: boolean) => void
  setWorkspaceId: (id: string | null) => void
  setVaultUnlocked: (v: boolean) => void
}

export const useAppStore = create<AppState>((set) => ({
  theme: (localStorage.getItem('jarvis-theme') as Theme) ?? 'light',
  userId: 'ken',
  sessionId: crypto.randomUUID(),
  mode: 'auto',
  workspaceId: null,
  persistent: false,
  vaultUnlocked: false,
  setTheme: (theme) => { localStorage.setItem('jarvis-theme', theme); set({ theme }) },
  setMode: (mode) => set({ mode }),
  setPersistent: (persistent) => set({ persistent }),
  setWorkspaceId: (workspaceId) => set({ workspaceId }),
  setVaultUnlocked: (vaultUnlocked) => set({ vaultUnlocked }),
}))
