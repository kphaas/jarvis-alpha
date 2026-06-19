import { CheckCircle, XCircle } from 'lucide-react'

export type SaveState = 'idle' | 'saving' | 'success' | 'error'

export function SettingsStatusLine({ state, message }: { state: SaveState; message: string }) {
  if (state === 'idle' || state === 'saving') return null
  return (
    <div className={`flex items-center gap-2 text-xs ${state === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
      {state === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
      {message}
    </div>
  )
}
