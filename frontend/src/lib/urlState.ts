export const SLUGS = ['upload', 'profile', 'fixes', 'processing', 'results', 'downloads'] as const

export interface UrlState {
  step: number
  datasetId: string | null
  jobId: string | null
}

const ID = /^[A-Za-z0-9-]{1,64}$/

/** `?d=<dataset>&j=<job>&s=<screen>`; empty on the Upload screen so a fresh visit stays clean. */
export function buildSearch({ step, datasetId, jobId }: UrlState): string {
  if (!datasetId || step <= 0) return ''
  const p = new URLSearchParams({ d: datasetId })
  if (jobId) p.set('j', jobId)
  p.set('s', SLUGS[step] ?? SLUGS[1])
  return `?${p}`
}

/** Returns null unless the query holds a usable dataset id and a screen after Upload. */
export function parseUrl(search: string): UrlState | null {
  const p = new URLSearchParams(search)
  const d = p.get('d')
  if (!d || !ID.test(d)) return null
  const slug = p.get('s')
  const step = slug === null ? 1 : SLUGS.indexOf(slug as (typeof SLUGS)[number])
  if (step < 1) return null
  const j = p.get('j')
  return { datasetId: d, jobId: j && ID.test(j) ? j : null, step }
}
