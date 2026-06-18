import { useEffect, useState } from 'react'
import { CheckCircle, Loader2, MapPin, Save, XCircle } from 'lucide-react'
import { apiJson } from '../../lib/apiFetch'
import { useAppStore } from '../../store'

interface HomeLocation {
  label: string
  postal_code?: string | null
  city?: string | null
  region?: string | null
  country: string
  latitude: number
  longitude: number
  updated_at?: string | null
  updated_by_profile_id?: string | null
  data_classification: 'personal_information'
}

interface WebAgentSettings {
  home_location: HomeLocation | null
  storage_classification: 'alpha_db_personal_settings'
}

interface FormState {
  label: string
  postal_code: string
  city: string
  region: string
  country: string
  latitude: string
  longitude: string
}

const EMPTY_FORM: FormState = {
  label: 'Home',
  postal_code: '',
  city: '',
  region: '',
  country: 'US',
  latitude: '',
  longitude: '',
}

function toForm(location: HomeLocation | null): FormState {
  if (!location) return EMPTY_FORM
  return {
    label: location.label,
    postal_code: location.postal_code ?? '',
    city: location.city ?? '',
    region: location.region ?? '',
    country: location.country,
    latitude: String(location.latitude),
    longitude: String(location.longitude),
  }
}

export function WebAgentLocationForm() {
  const { theme } = useAppStore()
  const isDark = theme === 'dark'
  const border = isDark ? 'border-white/10' : 'border-[#141414]/10'
  const subtle = isDark ? 'bg-white/5' : 'bg-[#141414]/5'
  const inputBg = isDark ? 'bg-white/5' : 'bg-[#141414]/5'

  const [form, setForm] = useState<FormState>(EMPTY_FORM)
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
      setForm(toForm(settings.home_location))
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to load Web Agent settings'
      setResult('error')
      setMessage(msg)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadSettings()
  }, [])

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
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
      setForm(toForm(settings.home_location))
      setResult('success')
      setMessage('Home location saved')
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save home location'
      setResult('error')
      setMessage(msg)
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
        )}

        {result !== 'idle' && (
          <div className={`flex items-center gap-2 text-xs ${result === 'success' ? 'text-emerald-400' : 'text-rose-400'}`}>
            {result === 'success' ? <CheckCircle size={12} /> : <XCircle size={12} />}
            {message}
          </div>
        )}

        <button
          onClick={saveLocation}
          disabled={loading || saving}
          className="min-h-11 w-full inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-sm font-mono hover:bg-emerald-500/30 disabled:opacity-40 transition-colors"
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? 'Saving...' : 'Save Location'}
        </button>
      </div>
    </section>
  )
}
