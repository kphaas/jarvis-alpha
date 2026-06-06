import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'

type PinGateProps = {
  children: ReactNode
}

type LoginProfile = {
  id: string
  display_name: string
  role: string
  child_age?: number | null
  max_rating: string
}

function getJwtExpSeconds(token: string): number | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null
    let b64 = parts[1].replace(/-/g, '+').replace(/_/g, '/')
    const pad = (4 - (b64.length % 4)) % 4
    b64 += '='.repeat(pad)
    const payload = JSON.parse(atob(b64)) as { exp?: unknown }
    const exp = payload.exp
    return typeof exp === 'number' ? exp : null
  } catch {
    return null
  }
}

async function refreshHttpOnlySessionCookie(token: string): Promise<void> {
  const base = import.meta.env.VITE_BRAIN_URL as string
  await fetch(`${base}/v1/auth/session-cookie`, {
    method: 'POST',
    credentials: 'include',
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
}

export function PinGate({ children }: PinGateProps) {
  const [authenticated, setAuthenticated] = useState(false)
  const [pin, setPin] = useState('')
  const [profiles, setProfiles] = useState<LoginProfile[]>([])
  const [selectedProfileId, setSelectedProfileId] = useState('ken')
  const [error, setError] = useState<string | null>(null)
  const [profilesLoading, setProfilesLoading] = useState(false)
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const token = localStorage.getItem('alpha_token')
    if (!token) return
    const exp = getJwtExpSeconds(token)
    if (exp !== null && exp > Date.now() / 1000) {
      setAuthenticated(true)
      void refreshHttpOnlySessionCookie(token).catch(() => undefined)
    }
  }, [])

  useEffect(() => {
    if (authenticated) return

    let cancelled = false
    async function loadProfiles() {
      setProfilesLoading(true)
      try {
        const base = import.meta.env.VITE_BRAIN_URL as string
        const res = await fetch(`${base}/v1/auth/login-profiles`)
        if (!res.ok) throw new Error('profile_load_failed')
        const rows = (await res.json()) as LoginProfile[]
        if (!cancelled) {
          setProfiles(rows)
          setSelectedProfileId(rows[0]?.id ?? 'ken')
        }
      } catch {
        if (!cancelled) {
          setProfiles([{ id: 'ken', display_name: 'Ken', role: 'admin', max_rating: 'adult' }])
          setSelectedProfileId('ken')
        }
      } finally {
        if (!cancelled) setProfilesLoading(false)
      }
    }

    void loadProfiles()
    return () => {
      cancelled = true
    }
  }, [authenticated])

  useEffect(() => {
    if (!authenticated && inputRef.current) {
      inputRef.current.focus()
    }
  }, [authenticated])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const base = import.meta.env.VITE_BRAIN_URL as string
      const res = await fetch(`${base}/v1/auth/pin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin, profile_id: selectedProfileId }),
      })
      if (res.status === 200) {
        const data = (await res.json()) as { token: string; expires_at: string }
        localStorage.setItem('alpha_token', data.token)
        setAuthenticated(true)
        setPin('')
      } else if (res.status === 401) {
        setError('Invalid PIN')
      } else {
        setError('Server error — try again')
      }
    } catch {
      setError('Server error — try again')
    } finally {
      setLoading(false)
    }
  }

  if (authenticated) {
    return <>{children}</>
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-gray-900/95">
      <div className="w-full max-w-sm rounded-xl border border-gray-700 bg-gray-800 p-8 shadow-2xl mx-4">
        <h1 className="mb-6 text-center text-2xl font-semibold text-white">
          JARVIS Alpha
        </h1>
        <div className="mb-5 grid grid-cols-2 gap-2" aria-label="Choose profile">
          {profilesLoading && [0, 1, 2, 3].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-lg bg-white/10" />
          ))}
          {!profilesLoading && profiles.map((profile) => {
            const selected = selectedProfileId === profile.id
            return (
              <button
                key={profile.id}
                type="button"
                onClick={() => {
                  setSelectedProfileId(profile.id)
                  setError(null)
                  setPin('')
                  inputRef.current?.focus()
                }}
                className={`min-h-16 rounded-lg border px-3 py-2 text-left transition ${
                  selected
                    ? 'border-blue-400 bg-blue-500/20 text-white'
                    : 'border-gray-700 bg-gray-900/60 text-gray-300 hover:border-gray-500'
                }`}
                aria-pressed={selected}
              >
                <span className="block text-sm font-semibold">{profile.display_name}</span>
                <span className="block text-[10px] uppercase tracking-wide text-gray-400">
                  {profile.role}{profile.child_age ? ` · Age ${profile.child_age}` : ''}
                </span>
              </button>
            )
          })}
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="alpha-pin"
              className="mb-2 block text-sm font-medium text-gray-300"
            >
              Enter PIN
            </label>
            <input
              ref={inputRef}
              id="alpha-pin"
              type="password"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 6))}
              className="w-full rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-center text-lg tracking-widest text-white outline-none ring-offset-2 focus:border-blue-500 focus:ring-2 focus:ring-blue-500"
            />
          </div>
          {error ? (
            <p className="text-center text-sm text-red-400" role="alert">
              {error}
            </p>
          ) : null}
          <button
            type="submit"
            disabled={loading || pin.length === 0}
            className="w-full rounded-lg bg-blue-600 py-2.5 font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? 'Verifying...' : 'Unlock'}
          </button>
        </form>
      </div>
    </div>
  )
}
