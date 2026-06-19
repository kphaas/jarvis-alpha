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
  alphaUrl('/space/family')
const FORGE_UI_URL =
  normalizeBaseUrl(import.meta.env.VITE_FORGE_UI_URL as string | undefined) ??
  alphaUrl('/space/forge')

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
    launchUrl: alphaUrl('/space/financial'),
    launchLabel: 'Financial Space',
  },
  {
    slug: 'medical',
    label: 'Medical',
    summary: 'Health records, appointments, medication context, and PHI-gated recall.',
    status: 'PHI gated',
    tabs: ['Records', 'Appointments', 'Medications', 'Care Team', 'Vault'],
    launchUrl: alphaUrl('/space/medical'),
    launchLabel: 'Medical Space',
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
    label: 'Printer',
    summary: 'Crucible fabrication, print queue, materials, and printer health.',
    status: 'Fabrication',
    tabs: ['Crucible', 'Print Queue', 'Materials', 'Printer Health', 'Parts'],
    launchUrl: alphaUrl('/space/printer'),
    launchLabel: 'Printer Space',
    aliases: ['crucible', 'print-copilot'],
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
    launchUrl: alphaUrl('/space/smithy'),
    launchLabel: 'Smithy Space',
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
