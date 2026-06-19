import { useEffect, useState } from 'react'
import { CheckCircle, Loader2, MapPin, Save, XCircle } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'
import { WebAgentLocationFields } from './WebAgentLocationFields'
import {
  EMPTY_WEB_AGENT_LOCATION_FORM,
  toWebAgentLocationForm,
  type WebAgentLocationFormState,
  type WebAgentSettings,
} from './webAgentLocationTypes'

export function WebAgentLocationForm() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const [form, setForm] = useState<WebAgentLocationFormState>(EMPTY_WEB_AGENT_LOCATION_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<'idle' | 'success' | 'error'>('idle')
  const [message, setMessage] = useState('')

  async function loadSettings() {
    setLoading(true)
    setResult('idle')
    setMessage('')
    try {
      const settings = await apiJson<WebAgentSettings>('/v1/settings/web-agent')
      setForm(toWebAgentLocationForm(settings.home_location))
    } catch (e: unknown) {
      setResult('error')
      setMessage(e instanceof Error ? e.message : 'Failed to load Web Agent settings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSettings()
  }, [])

  function update<K extends keyof WebAgentLocationFormState>(key: K, value: WebAgentLocationFormState[K]) {
    setForm(current => ({ ...current, [key]: value }))
  }

  async function saveLocation() {
    const latitude = Number(form.latitude)
    const longitude = Number(form.longitude)
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      setResult('error')
      setMessage('Latitude and longitude are required')
      return
    }

    setSaving(true)
    setResult('idle')
    setMessage('')
    try {
      const settings = await apiJson<WebAgentSettings>('/v1/settings/web-agent/home-location', {
        method: 'PUT',
        body: JSON.stringify({
          label: form.label || 'Home',
          postal_code: form.postal_code || null,
          city: form.city || null,
          region: form.region || null,
          country: form.country || 'US',
          latitude,
          longitude,
        }),
      })
      setForm(toWebAgentLocationForm(settings.home_location))
      setResult('success')
      setMessage('Home location saved')
    } catch (e: unknown) {
      setResult('error')
      setMessage(e instanceof Error ? e.message : 'Failed to save home location')
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-xs font-mono uppercase opacity-40 tracking-widest">Web Agent</h2>
        <span className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-[10px] font-mono uppercase ${isDark ? 'border-sky-400/30 bg-sky-500/10 text-sky-200' : 'border-sky-600/20 bg-sky-50 text-sky-700'}`}>
          <MapPin size={12} />
          Personal data
        </span>
      </div>

      <div className={`p-5 rounded-2xl border ${border} ${subtle} space-y-4`}>
        <div className="flex items-center gap-2">
          <MapPin size={14} className="opacity-60" />
          <span className="text-sm font-medium">Home Location</span>
          {loading && <Loader2 size={14} className="animate-spin opacity-50" />}
        </div>

        {loading ? (
          <div className="space-y-3">
            <div className={`h-10 rounded-lg ${inputBg} animate-pulse`} />
            <div className={`h-10 rounded-lg ${inputBg} animate-pulse`} />
            <div className={`h-10 rounded-lg ${inputBg} animate-pulse`} />
          </div>
        ) : (
          <WebAgentLocationFields form={form} update={update} />
        )}

        {result !== 'idle' && (
          <div className={`flex items-center gap-2 text-xs ${result === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
            {result === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {message}
          </div>
        )}

        <button onClick={saveLocation} disabled={loading || saving} className="min-h-11 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Saving...' : 'Save Location'}
        </button>
      </div>
    </section>
  )
}
