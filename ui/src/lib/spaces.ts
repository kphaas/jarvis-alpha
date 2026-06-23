export interface SpaceDefinition {
  slug: string
  label: string
  summary: string
  status: string
  tabs: string[]
  launchUrl: string
  launchLabel: string
  aliases?: string[]
}

function normalizeBaseUrl(value: string | undefined): string | undefined {
  const trimmed = value?.trim().replace(/\/+$/, '')
  return trimmed || undefined
}

function alphaUrl(path: string): string {
  const baseUrl =
    normalizeBaseUrl(import.meta.env.VITE_ALPHA_UI_URL as string | undefined) ??
    (typeof window === 'undefined' ? '' : window.location.origin)
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return baseUrl ? `${baseUrl}${normalizedPath}` : normalizedPath
}

const FAMILY_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_FAMILY_UI_URL as string | undefined) ??
  'https://jarvis-endpoint.tail40ed36.ts.net:4200'
const FINANCIAL_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_FINANCIAL_UI_URL as string | undefined) ??
  'https://jarvis-sandbox.tail40ed36.ts.net:5443/admin/net-worth'
const MEDICAL_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_MEDICAL_UI_URL as string | undefined) ??
  'https://jarvis-endpoint.tail40ed36.ts.net:4217/lab-ui'
const PRINTY_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_PRINTY_UI_URL as string | undefined) ??
  'http://jarvis-print.tail40ed36.ts.net:5002'
const FORGE_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_FORGE_UI_URL as string | undefined) ??
  'https://jarvis-sandbox.tail40ed36.ts.net:5001'
const SMITHY_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_SMITHY_UI_URL as string | undefined) ??
  'https://jarvis-sandbox.tail40ed36.ts.net:5001/smithy/'

export const SPACES: SpaceDefinition[] = [
  {
    slug: 'family',
    label: 'Family',
    summary: 'Household, school, calendar, and family-safe coordination.',
    status: 'Private vault',
    tabs: ['Family Vault', 'School', 'Calendar', 'Care', 'Approvals'],
    launchUrl: FAMILY_UI_URL,
    launchLabel: 'Family Vault',
    aliases: ['familyvault'],
  },
  {
    slug: 'financial',
    label: 'Financial',
    summary: 'Money, banking posture, broker boundaries, and trade guard evidence.',
    status: 'Guarded',
    tabs: ['Accounts', 'Budget', 'Bills', 'Investments', 'Trade Guard'],
    launchUrl: FINANCIAL_UI_URL,
    launchLabel: 'Financial Dashboard',
  },
  {
    slug: 'medical',
    label: 'Medical',
    summary: 'Health records, appointments, medication context, and PHI-gated recall.',
    status: 'PHI gated',
    tabs: ['Records', 'Appointments', 'Medications', 'Care Team', 'Vault'],
    launchUrl: MEDICAL_UI_URL,
    launchLabel: 'VYVE Lab Workbench',
  },
  {
    slug: 'legal',
    label: 'Legal',
    summary: 'Contracts, notices, case packets, and approval-ready legal workflows.',
    status: 'Review only',
    tabs: ['Documents', 'Deadlines', 'Review Packets', 'Approvals', 'Vault'],
    launchUrl: alphaUrl('/space/legal'),
    launchLabel: 'Legal Space',
  },
  {
    slug: 'home',
    label: 'Home',
    summary: 'Home automation, utilities, devices, maintenance, and household state.',
    status: 'Local control',
    tabs: ['Automation', 'Utilities', 'Devices', 'Maintenance', 'Scenes'],
    launchUrl: alphaUrl('/space/home'),
    launchLabel: 'Home Space',
  },
  {
    slug: 'printer',
    label: 'Printy',
    summary: 'Crucible fabrication, print queue, materials, and printer health.',
    status: 'Fabrication',
    tabs: ['Crucible', 'Print Queue', 'Materials', 'Printer Health', 'Parts'],
    launchUrl: PRINTY_UI_URL,
    launchLabel: 'Printy',
    aliases: ['crucible', 'print-copilot', 'printer'],
  },
  {
    slug: 'forge',
    label: 'Forge',
    summary: 'Code pipeline, CI posture, deploy approvals, and engineering backlog.',
    status: 'Code pipeline',
    tabs: ['Backlog', 'Pull Requests', 'CI', 'Deploys', 'Lessons'],
    launchUrl: FORGE_UI_URL,
    launchLabel: 'Forge Dashboard',
  },
  {
    slug: 'smithy',
    label: 'Smithy',
    summary: 'Ideas, specs, architecture decisions, and build-ready handoffs.',
    status: 'Spec shop',
    tabs: ['Ideas', 'Specs', 'ADRs', 'Roadmap', 'Handoffs'],
    launchUrl: SMITHY_UI_URL,
    launchLabel: 'Smithy',
  },
  {
    slug: 'spark',
    label: 'Spark',
    summary: 'Persona, voice, memory tone, drafting style, and operator preferences.',
    status: 'Persona',
    tabs: ['Voice', 'Style', 'Memory', 'Feedback', 'Drafts'],
    launchUrl: alphaUrl('/spark'),
    launchLabel: 'Spark',
  },
  {
    slug: 'privacy',
    label: 'Privacy',
    summary: 'Privacy scrub, removal packets, approved actions, and evidence tracking.',
    status: 'Approval gated',
    tabs: ['Intake', 'Targets', 'Review Packets', 'Approved Actions', 'Reports'],
    launchUrl: alphaUrl('/privacy'),
    launchLabel: 'Privacy',
  },
]

export function getSpaceRoute(space: SpaceDefinition): string {
  return `/space/${space.slug}`
}

export function getSpaceBySlug(slug: string | undefined): SpaceDefinition | undefined {
  const normalizedSlug = (slug ?? '').toLowerCase()
  return SPACES.find((space) => space.slug === normalizedSlug || space.aliases?.includes(normalizedSlug))
}
