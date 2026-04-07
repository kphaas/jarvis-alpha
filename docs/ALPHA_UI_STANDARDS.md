# JARVIS Alpha — UI Standards & Component Map

**April 2026 · github.com/kphaas/jarvis-alpha · main**
**Purpose:** Define UI architecture, design system, component patterns, and conventions for the jarvis-alpha React frontend.

---

## 1. Stack

| Layer | Choice | Version |
|---|---|---|
| Framework | React | 19.2.4 |
| Build tool | Vite | latest |
| Language | TypeScript (strict) | — |
| Styling | Tailwind CSS utility classes | — |
| Data fetching | TanStack React Query | 5.96.1 |
| Routing | React Router DOM | 7.13.2 |
| Icons | Lucide React | 1.7.0 |
| Charts | Recharts | 3.8.1 |
| Animation | Framer Motion | 12.38.0 |
| State (global) | Zustand | 5.0.12 |

---

## 2. Directory Layout
ui/src/
├── App.tsx                  # Router + providers, slim
├── main.jsx                 # Entry point
├── lib/
│   ├── apiFetch.ts          # apiJson() + apiFetch() — all HTTP through here
│   └── time.ts              # Date/time formatting helpers
├── hooks/
│   ├── index.ts             # Barrel export — MANDATORY
│   ├── useTheme.ts
│   ├── useCosts.ts
│   ├── useLogs.ts
│   ├── useBriefings.ts
│   └── useWatchdog.ts
├── components/
│   ├── Layout.tsx           # Shell — sidebar + main content
│   ├── ChatWindow.tsx       # Reusable chat surface
│   ├── home/                # Subdirs for page-specific components
│   │   ├── BriefingCard.tsx
│   │   ├── HealthCard.tsx
│   │   └── OvernightCard.tsx
│   ├── cost/
│   ├── errors/
│   └── settings/
├── pages/
│   ├── Home.tsx             # Compose components, no inline JSX cards
│   ├── Health.tsx
│   ├── Mesh.tsx
│   ├── CostCenter.tsx
│   ├── Errors.tsx
│   ├── Security.tsx
│   ├── Approvals.tsx
│   └── Ask.tsx
└── types/
├── costs.ts
├── errors.ts
└── briefings.ts

**Rule:** Pages compose, components render. If a page has more than 2 inline `{section}` blocks longer than 30 lines each, extract them to `components/<page>/`.

---

## 3. Design System

### 3.1 Colors — Tailwind utility classes only

NEVER hardcode hex colors. Always use Tailwind tokens.

| Concern | Tailwind class |
|---|---|
| Page background (dark) | `bg-black` or `bg-zinc-950` |
| Card background | `bg-white/5` (subtle elevation) |
| Card border | `border-white/10` |
| Primary text | `text-white` |
| Secondary text | `text-white/70` |
| Tertiary / muted | `text-white/40` |
| Disabled / opacity | `opacity-40` |
| Success | `text-emerald-500` |
| Failure | `text-rose-500` |
| Warning / pending | `text-amber-500` |
| Info / accent | `text-blue-500` |

Theme is controlled via `data-theme` attribute on root and the `useTheme()` hook returns the current theme. Pages destructure `border`, `subtle`, `muted` from theme — see existing pattern in `Home.tsx`.

### 3.2 Typography

| Element | Class pattern |
|---|---|
| Section labels | `text-[10px] font-mono uppercase opacity-40 tracking-widest` |
| Card titles | `text-sm font-semibold` |
| Body text | `text-sm` |
| Subtext / meta | `text-xs opacity-70` |
| Numbers / data | `text-xl font-bold` for headlines, `text-sm font-mono` for values |
| Status badges | `text-xs font-mono font-bold uppercase px-2 py-1 rounded-md border` |

Font stack is system default — no external fonts.

### 3.3 Spacing & Layout

| Element | Class pattern |
|---|---|
| Card padding | `p-4` standard, `p-6` for hero |
| Card radius | `rounded-2xl` |
| Section vertical gap | `space-y-3` inside cards, `space-y-6` between sections |
| Grid gap | `gap-3` for tight, `gap-6` for breathing room |

### 3.4 Lucide Icons

ALL icons from `lucide-react`. Standard sizing:

| Use | Class |
|---|---|
| Inline section icon | `w-3.5 h-3.5 opacity-40` |
| Button icon | `w-4 h-4` |
| Hero icon | `w-6 h-6` |
| Sidebar nav | `w-5 h-5` |

---

## 4. Data Fetching — React Query

ALL data fetching goes through React Query hooks. No raw `useEffect` + `fetch` patterns in pages or components.

### 4.1 Hook File Pattern
```typescript
// hooks/useBriefings.ts
import { useQuery } from '@tanstack/react-query'
import { apiJson } from '../lib/apiFetch'

export interface BriefingFull { /* ... */ }

export function useLatestBriefing() {
  return useQuery<BriefingFull | null>({
    queryKey: ['briefings', 'latest'],
    queryFn: async () => {
      try {
        return await apiJson<BriefingFull>('/v1/briefings/latest')
      } catch (err: unknown) {
        if (err instanceof Error && err.message === 'HTTP 404') return null
        throw err
      }
    },
    staleTime: 60 * 1000,
  })
}
```

### 4.2 Cache Key Convention

Shared cache keys, namespaced by domain:
['costs', 'summary']
['costs', 'power']
['briefings', 'latest']
['briefings', 'list', { source, dateFrom, dateTo }]
['briefings', 'detail', batchRunId]
['logs', 'query', filters]

Multiple components reading the same data hit the same cache entry. Never page-scope cache keys.

### 4.3 Stale Time Defaults

| Data type | Stale time |
|---|---|
| Slow-changing (cost summary, briefings) | 60 seconds |
| Medium (mesh status) | 30 seconds |
| Fast (logs, live metrics) | 10 seconds |
| Static (config) | 5 minutes |

### 4.4 Barrel Export — MANDATORY

Every new hook MUST be added to `hooks/index.ts`:
```typescript
// hooks/index.ts
export { useTheme } from './useTheme'
export * from './useCosts'
export * from './useLogs'
export * from './useBriefings'
export * from './useWatchdog'
```

Imports use the barrel: `import { useLatestBriefing } from '../hooks'`

### 4.5 404 Handling

Endpoints that return 404 for "no data yet" should return `null` from the hook, not throw. UI then shows an empty state instead of an error state.

---

## 5. Component Patterns

### 5.1 Loading / Error / Empty / Populated

Every data-driven card MUST have all four states:
```tsx
{isLoading && <p className="text-sm opacity-40">Loading...</p>}
{!isLoading && error && <p className="text-xs text-rose-500">Failed to load</p>}
{!isLoading && !error && data === null && <p className="text-sm opacity-40">No data yet</p>}
{!isLoading && !error && data && (
  <div className="space-y-3">{/* render data */}</div>
)}
```

### 5.2 Section Card Template
```tsx
<section>
  <p className="text-[10px] font-mono uppercase opacity-40 tracking-widest mb-3">
    Section Title
  </p>
  <div className={`p-4 rounded-2xl border ${border} ${subtle}`}>
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-3.5 h-3.5 opacity-40" />
      <p className="text-[10px] font-mono uppercase opacity-40">Subtitle</p>
    </div>
    {/* states */}
  </div>
</section>
```

### 5.3 Status Badges
```tsx
<span className="text-xs font-mono font-bold px-2 py-1 rounded-md border border-emerald-500/30 text-emerald-500">
  pass {count}
</span>
```

### 5.4 Component Decomposition Rule

If a section in a page is more than 30 lines of JSX, extract it to `components/<page>/<Section>Card.tsx`. Pages should be < 200 lines total.

---

## 6. TypeScript Conventions

| Concern | Convention |
|---|---|
| Interfaces vs types | `interface` for object shapes, `type` for unions/aliases |
| Naming | `PascalCase` for types/interfaces, `camelCase` for variables |
| Optional fields | `?:` not `\| undefined` |
| Error narrowing | `err instanceof Error` before accessing `.message` |
| API response shapes | Live in `types/<domain>.ts`, exported from there |

---

## 7. Imports

| Source | Pattern |
|---|---|
| External | `import { useQuery } from '@tanstack/react-query'` |
| Hooks | `import { useLatestBriefing } from '../hooks'` (barrel) |
| Components | `import { BriefingCard } from '../components/home/BriefingCard'` |
| Lib | `import { apiJson } from '../lib/apiFetch'` |
| Types | `import type { BriefingFull } from '../types/briefings'` |
| Icons | `import { FileText, Brain } from 'lucide-react'` |

No path aliases. Relative paths only.

---

## 8. Naming Conventions

| Concern | Convention |
|---|---|
| Files (components) | `PascalCase.tsx`: `BriefingCard.tsx` |
| Files (hooks) | `camelCase.ts` with `use` prefix: `useBriefings.ts` |
| Files (lib) | `camelCase.ts`: `apiFetch.ts`, `time.ts` |
| Files (types) | `camelCase.ts`: `briefings.ts` |
| Hook function names | `use<Domain><Action>`: `useLatestBriefing`, `useCostsSummary` |
| Component names | Match filename: `BriefingCard` in `BriefingCard.tsx` |
| Exports | Named exports for components and hooks. Default exports only for top-level page components. |
| Props | Typed via `interface` block, destructured in function signature |

---

## 9. Anti-Patterns — DO NOT

- ❌ Raw `useEffect + fetch` for data — use React Query
- ❌ Inline 60+ line cards in pages — extract to components
- ❌ Hex colors inline — use Tailwind tokens
- ❌ Hardcoded hostnames or URLs — use env vars / VITE_ vars
- ❌ Forgetting to add new hooks to `hooks/index.ts` barrel
- ❌ `any` type without explicit comment justifying it
- ❌ Mixing `.jsx` and `.tsx` for new files — `.tsx` only
- ❌ Direct Postgres queries from frontend — always through Brain API

---

## 10. Migration Notes (Tech Debt)

| Item | Status |
|---|---|
| `main.jsx` → `main.tsx` | Pending — cosmetic |
| `LogsPage.jsx` → `LogsPage.tsx` | Pending — F-item |
| All pages using barrel hook imports | Partial — some still use direct paths |
| All cards extracted to components | Partial — Home, Errors, CostCenter done; others pending |

---

*ALPHA_UI_STANDARDS.md · April 2026 · github.com/kphaas/jarvis-alpha*
