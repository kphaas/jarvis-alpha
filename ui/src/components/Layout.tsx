import { useState, type ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Zap, Home, Newspaper, Network,
  Activity, Bug, Bot, Terminal,
  ShieldAlert, ShieldCheck, DollarSign,
  FileText, Settings, Moon, Sun,
  User, ChevronRight, Lock, Unlock, RefreshCw,
  FolderOpen, Wrench, Fingerprint, Sparkles,
} from 'lucide-react'
import type { Theme } from '../types'
import { useAppStore } from '../store'
import { PinModal } from './PinModal'

const NAV = [
  { group: 'OBSERVE', items: [
    { to: '/',          label: 'Home',         icon: Home          },
    { to: '/briefing',  label: 'Briefing',     icon: Newspaper     },
  ]},
  { group: 'OPERATE', items: [
    { to: '/health',    label: 'Health',       icon: Activity      },
    { to: '/errors',    label: 'Errors & Logs',icon: Bug           },
    { to: '/mesh',      label: 'Mesh',         icon: Network       },
    { to: '/agents',    label: 'Agents',       icon: Bot           },
    { to: '/skills',    label: 'Skills',       icon: Wrench        },
    { to: '/spark',     label: 'Spark',        icon: Sparkles      },
    { to: '/ops',       label: 'Ops',          icon: Terminal      },
  ]},
  { group: 'SECURE', items: [
    { to: '/approvals', label: 'Approvals',    icon: ShieldCheck   },
    { to: '/security',  label: 'Security',     icon: ShieldAlert   },
    { to: '/privacy',   label: 'Privacy',      icon: Fingerprint    },
    { to: '/governance',label: 'Governance',   icon: ShieldAlert   },
  ]},
  { group: 'COST', items: [
    { to: '/cost',      label: 'Cost Center',  icon: DollarSign    },
  ]},
  { group: 'SYSTEM', items: [
    { to: '/documents', label: 'Documents',    icon: FileText      },
    { to: '/settings',  label: 'Settings',     icon: Settings      },
  ]},
]

const SPACE_ITEMS = [
  { to: '/space/familyvault', label: 'Family Vault', icon: FolderOpen },
]

interface Props {
  theme: Theme
  children: ReactNode
  monthSpend?: number
  budget?: number
  onRefresh?: () => void
  loading?: boolean
}

export function Layout({ theme, children, monthSpend = 0, budget = 500, onRefresh, loading }: Props) {
  const { vaultUnlocked, setVaultUnlocked, setTheme } = useAppStore()
  const [showPin, setShowPin] = useState(false)
  const [pendingSpaceTo, setPendingSpaceTo] = useState<string | null>(null)
  const isDark = theme === 'dark'
  const location = useLocation()

  const border = isDark ? 'border-white/10' : 'border-[#141414]'
  const sidebarBg = isDark ? 'bg-[#0F0F0F]' : 'bg-[#E4E3E0]'
  const subtle = isDark ? 'hover:bg-white/5' : 'hover:bg-[#141414]/5'

  const activeTab = location.pathname === '/' ? 'Home'
    : NAV.flatMap(g => g.items).find(i => location.pathname.startsWith(i.to) && i.to !== '/')?.label
    ?? SPACE_ITEMS.find(i => location.pathname.startsWith(i.to))?.label
    ?? ''

  const handleSpaceClick = (to: string) => {
    if (vaultUnlocked) return
    setPendingSpaceTo(to)
    setShowPin(true)
  }

  return (
    <div className={`flex h-screen overflow-hidden font-sans transition-colors duration-300 ${isDark ? 'bg-[#0A0A0A] text-[#E4E3E0]' : 'bg-[#E4E3E0] text-[#141414]'}`}>

      {/* Sidebar */}
      <aside className={`hidden w-64 flex-shrink-0 border-r flex-col h-screen sticky top-0 lg:flex ${border} ${sidebarBg}`}>

        {/* Logo + user */}
        <div className={`p-6 border-b flex-shrink-0 ${border}`}>
          <div className="flex items-center justify-between mb-4">
            <h1 className="text-2xl font-bold tracking-tighter flex items-center gap-2">
              <Zap className={`w-6 h-6 fill-current ${isDark ? 'text-emerald-500' : 'text-[#141414]'}`} />
              JARVIS
            </h1>
            <button
              onClick={() => setTheme(isDark ? 'light' : 'dark')}
              className={`p-2 rounded-lg border transition-all ${border} ${subtle}`}
            >
              {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>
          </div>
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-full flex items-center justify-center ${isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'}`}>
              <User className="w-4 h-4" />
            </div>
            <div>
              <p className="text-[10px] font-mono font-bold uppercase leading-none">Kenneth Haas</p>
              <p className="text-[10px] font-mono opacity-50 uppercase mt-1">Haas · Private AI</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-4 py-4 space-y-0.5">
          {NAV.map(group => (
            <div key={group.group}>
              <p className="text-[8px] font-mono uppercase font-bold opacity-30 tracking-widest px-2 pt-4 pb-1">
                {group.group}
              </p>
              {group.items.map(item => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-sm font-medium ${
                      isActive
                        ? isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'
                        : subtle
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <item.icon className="w-4 h-4 flex-shrink-0" />
                      <span className="truncate">{item.label}</span>
                      {isActive && (
                        <motion.div layoutId="active-nav" className="ml-auto">
                          <ChevronRight className="w-3 h-3" />
                        </motion.div>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}

          {/* Spaces group */}
          <div>
            <div className="flex items-center gap-1.5 px-2 pt-4 pb-1">
              {vaultUnlocked
                ? <Unlock className="w-2.5 h-2.5 text-emerald-500" />
                : <Lock className="w-2.5 h-2.5 opacity-40" />}
              <p className="text-[8px] font-mono uppercase font-bold opacity-30 tracking-widest flex-1">Spaces</p>
              {vaultUnlocked && <span className="text-[7px] font-mono text-emerald-500 uppercase">Unlocked</span>}
            </div>
            {SPACE_ITEMS.map(item => (
              vaultUnlocked ? (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-sm font-medium ${
                      isActive
                        ? isDark ? 'bg-emerald-500 text-[#0A0A0A]' : 'bg-[#141414] text-[#E4E3E0]'
                        : subtle
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      <item.icon className="w-4 h-4 flex-shrink-0" />
                      <span className="truncate">{item.label}</span>
                      {isActive && (
                        <motion.div layoutId="active-nav-space">
                          <ChevronRight className="w-3 h-3 ml-auto" />
                        </motion.div>
                      )}
                    </>
                  )}
                </NavLink>
              ) : (
                <button
                  key={item.to}
                  onClick={() => handleSpaceClick(item.to)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-200 text-sm font-medium ${subtle} opacity-60`}
                >
                  <item.icon className="w-4 h-4 flex-shrink-0" />
                  <span className="truncate">{item.label}</span>
                  <Lock className="ml-auto w-3 h-3 opacity-25" />
                </button>
              )
            ))}
          </div>
        </nav>

        {/* System status */}
        <div className={`p-4 border-t flex-shrink-0 ${border}`}>
          <div className="flex items-center justify-between text-[8px] font-mono uppercase opacity-30">
            <span>System Status</span>
            <span className="text-emerald-500">Connected</span>
          </div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">

        {/* TopBar */}
        <header className={`min-h-16 border-b flex flex-wrap items-center justify-between gap-3 px-4 py-3 backdrop-blur-sm sticky top-0 z-10 sm:px-6 lg:px-8 ${border} ${isDark ? 'bg-[#0A0A0A]/80' : 'bg-[#E4E3E0]/80'}`}>
          <div className="flex min-w-0 items-center gap-3 sm:gap-4">
            <div className="flex shrink-0 items-center gap-2 lg:hidden">
              <Zap className={`h-4 w-4 fill-current ${isDark ? 'text-emerald-400' : 'text-[#141414]'}`} />
              <span className="text-sm font-bold tracking-tight">AT-0 Alpha</span>
            </div>
            <h2 className="truncate text-lg font-semibold tracking-tight capitalize">{activeTab || 'Dashboard'}</h2>
            <div className={`h-4 w-px ${isDark ? 'bg-white/20' : 'bg-[#141414]/20'}`} />
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-[10px] font-mono uppercase tracking-widest opacity-50">System Nominal</span>
            </div>
          </div>
          <div className="flex items-center gap-3 sm:gap-6">
            {onRefresh && (
              <button onClick={onRefresh} disabled={loading} className={`p-1.5 rounded-lg ${subtle} disabled:opacity-30`}>
                <RefreshCw className={`w-3.5 h-3.5 opacity-40 ${loading ? 'animate-spin' : ''}`} />
              </button>
            )}
            <div className="text-right">
              <p className="text-[10px] font-mono opacity-50 uppercase">Cloud Spend (MTD)</p>
              <p className="text-sm font-bold">${monthSpend.toFixed(2)} <span className="opacity-40">/ ${budget}</span></p>
            </div>
            <div className={`w-10 h-10 border flex items-center justify-center rounded transition-colors cursor-pointer ${border} ${subtle}`}>
              <Lock className="w-4 h-4" />
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <div className="p-4 sm:p-6 lg:p-8"><AnimatePresence mode="wait">{children}</AnimatePresence></div>
        </main>
      </div>

      {/* PIN Modal */}
      <AnimatePresence>
        {showPin && (
          <PinModal
            theme={theme}
            title="Spaces"
            subtitle="Enter PIN to unlock all spaces"
            onUnlock={() => {
              setVaultUnlocked(true)
              setShowPin(false)
              if (pendingSpaceTo) {
                window.location.href = pendingSpaceTo
                setPendingSpaceTo(null)
              }
            }}
            onCancel={() => { setShowPin(false); setPendingSpaceTo(null) }}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
