import type { BeaconFocusMode, BeaconMode } from '../../types/beacon'

export const BEACON_MODES: BeaconMode[] = [
  { key: 'all', label: 'All', description: 'Balanced web evidence' },
  { key: 'official', label: 'Official', description: 'Official and primary hosts' },
  { key: 'news_current', label: 'News/current', description: 'Freshness required' },
  { key: 'shopping', label: 'Shopping', description: 'Pricing and source checks' },
  { key: 'academic', label: 'Academic', description: 'Primary-source emphasis' },
  { key: 'local_weather', label: 'Local/weather', description: 'Free route first' },
  { key: 'deep_research', label: 'Deep research', description: 'Fanout and coverage' },
]

export const BEACON_PLACEHOLDERS: Record<BeaconFocusMode, string> = {
  all: 'What changed in the latest OpenAI API docs?',
  official: 'OpenAI Responses API official docs',
  news_current: 'latest GitHub Actions runner image changes',
  shopping: 'current Mac mini pricing from official sources',
  academic: 'single kidney pediatric sports guidance',
  local_weather: 'weather right now at home',
  deep_research: 'compare Brave Search API and Perplexity Search API',
}

export function maxPagesForMode(mode: BeaconFocusMode): number {
  if (mode === 'deep_research') return 4
  if (mode === 'official' || mode === 'academic') return 2
  return 1
}
