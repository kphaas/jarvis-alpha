export interface SpaceDefinition {
  slug: string
  label: string
  summary: string
  status: string
  tabs: string[]
  aliases?: string[]
}

export const SPACES: SpaceDefinition[] = [
  {
    slug: 'family',
    label: 'Family',
    summary: 'Household, school, calendar, and family-safe coordination.',
    status: 'Private vault',
    tabs: ['Family Vault', 'School', 'Calendar', 'Care', 'Approvals'],
    aliases: ['familyvault'],
  },
  {
    slug: 'financial',
    label: 'Financial',
    summary: 'Money, banking posture, broker boundaries, and trade guard evidence.',
    status: 'Guarded',
    tabs: ['Accounts', 'Budget', 'Bills', 'Investments', 'Trade Guard'],
  },
  {
    slug: 'medical',
    label: 'Medical',
    summary: 'Health records, appointments, medication context, and PHI-gated recall.',
    status: 'PHI gated',
    tabs: ['Records', 'Appointments', 'Medications', 'Care Team', 'Vault'],
  },
  {
    slug: 'legal',
    label: 'Legal',
    summary: 'Contracts, notices, case packets, and approval-ready legal workflows.',
    status: 'Review only',
    tabs: ['Documents', 'Deadlines', 'Review Packets', 'Approvals', 'Vault'],
  },
  {
    slug: 'home',
    label: 'Home',
    summary: 'Home automation, utilities, devices, maintenance, and household state.',
    status: 'Local control',
    tabs: ['Automation', 'Utilities', 'Devices', 'Maintenance', 'Scenes'],
  },
  {
    slug: 'printer',
    label: 'Printer',
    summary: 'Crucible fabrication, print queue, materials, and printer health.',
    status: 'Fabrication',
    tabs: ['Crucible', 'Print Queue', 'Materials', 'Printer Health', 'Parts'],
    aliases: ['crucible', 'print-copilot'],
  },
  {
    slug: 'forge',
    label: 'Forge',
    summary: 'Code pipeline, CI posture, deploy approvals, and engineering backlog.',
    status: 'Code pipeline',
    tabs: ['Backlog', 'Pull Requests', 'CI', 'Deploys', 'Lessons'],
  },
  {
    slug: 'smithy',
    label: 'Smithy',
    summary: 'Ideas, specs, architecture decisions, and build-ready handoffs.',
    status: 'Spec shop',
    tabs: ['Ideas', 'Specs', 'ADRs', 'Roadmap', 'Handoffs'],
  },
  {
    slug: 'spark',
    label: 'Spark',
    summary: 'Persona, voice, memory tone, drafting style, and operator preferences.',
    status: 'Persona',
    tabs: ['Voice', 'Style', 'Memory', 'Feedback', 'Drafts'],
  },
  {
    slug: 'privacy',
    label: 'Privacy',
    summary: 'Privacy scrub, removal packets, approved actions, and evidence tracking.',
    status: 'Approval gated',
    tabs: ['Intake', 'Targets', 'Review Packets', 'Approved Actions', 'Reports'],
  },
]

export function getSpaceRoute(space: SpaceDefinition): string {
  return `/space/${space.slug}`
}

export function getSpaceBySlug(slug: string | undefined): SpaceDefinition | undefined {
  const normalizedSlug = (slug ?? '').toLowerCase()
  return SPACES.find((space) => space.slug === normalizedSlug || space.aliases?.includes(normalizedSlug))
}
