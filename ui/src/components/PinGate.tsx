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

export function PinGate({ children }: PinGateProps) {
  const [authenticated, setAuthenticated] = useState(false)
  const [pin, setPin] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const token = localStorage.getItem('alpha_token')
    if (!token) return
    const exp = getJwtExpSeconds(token)
    if (exp !== null && exp > Date.now() / 1000) {
      setAuthenticated(true)
    }
  }, [])

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
        body: JSON.stringify({ pin }),
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
