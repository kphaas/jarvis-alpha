import { useAppStore } from '../../store'
import type { WebAgentLocationFormState } from './webAgentLocationTypes'

export function WebAgentLocationFields({
  form,
  update,
}: {
  form: WebAgentLocationFormState
  update: <K extends keyof WebAgentLocationFormState>(key: K, value: WebAgentLocationFormState[K]) => void
}) {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <label className="space-y-1 sm:col-span-2">
        <span className="text-[10px] font-mono uppercase opacity-40">Label</span>
        <input value={form.label} onChange={e => update('label', e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </label>
      <label className="space-y-1">
        <span className="text-[10px] font-mono uppercase opacity-40">ZIP</span>
        <input value={form.postal_code} onChange={e => update('postal_code', e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </label>
      <label className="space-y-1">
        <span className="text-[10px] font-mono uppercase opacity-40">Country</span>
        <input value={form.country} onChange={e => update('country', e.target.value.toUpperCase())} maxLength={2} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
      </label>
      <label className="space-y-1">
        <span className="text-[10px] font-mono uppercase opacity-40">City</span>
        <input value={form.city} onChange={e => update('city', e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </label>
      <label className="space-y-1">
        <span className="text-[10px] font-mono uppercase opacity-40">State</span>
        <input value={form.region} onChange={e => update('region', e.target.value)} className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm focus:outline-none`} />
      </label>
      <label className="space-y-1">
        <span className="text-[10px] font-mono uppercase opacity-40">Latitude</span>
        <input value={form.latitude} onChange={e => update('latitude', e.target.value)} inputMode="decimal" className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
      </label>
      <label className="space-y-1">
        <span className="text-[10px] font-mono uppercase opacity-40">Longitude</span>
        <input value={form.longitude} onChange={e => update('longitude', e.target.value)} inputMode="decimal" className={`w-full px-3 py-2 rounded-lg border ${border} ${inputBg} text-sm font-mono focus:outline-none`} />
      </label>
    </div>
  )
}
