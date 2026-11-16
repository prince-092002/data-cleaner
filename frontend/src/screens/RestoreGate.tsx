import { useEffect, useState, type ReactNode } from 'react'
import { getProfile, getResults } from '@/api/client'
import { ExpiredCard } from '@/components/ExpiredCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { isNotFound } from '@/lib/jobErrors'
import { useFocusOnMount } from '@/lib/useFocusOnMount'
import { useAppState } from '@/state/AppState'
import { PAGE_SIZE } from './ResultsScreen'

/**
 * After a reload or a reopened link only the ids are known. This fetches the profile (Profile or
 * Suggested fixes screen) or the results (Results or Downloads) before the screen shows.
 */
export function RestoreGate({ children }: { children: ReactNode }) {
  const { state, dispatch } = useAppState()
  const { step, datasetId, jobId, profile, results } = state
  const kind =
    !datasetId ? null
    : (step === 2 || (step === 1 && !jobId)) && !profile ? 'profile'
    : step >= 4 && !results ? 'results'
    : null
  const [failure, setFailure] = useState<{ kind: string; expired: boolean; message: string } | null>(null)

  useEffect(() => {
    if (!kind || !datasetId) return
    let live = true
    const load =
      kind === 'profile'
        ? getProfile(datasetId).then((p) => dispatch({ type: 'profile_loaded', profile: p }))
        : getResults(datasetId, { limit: PAGE_SIZE }).then((r) => dispatch({ type: 'results_loaded', results: r }))
    load.catch((e) => {
      if (live) {
        setFailure({
          kind,
          expired: isNotFound(e),
          message: e instanceof Error ? e.message : 'Something went wrong.',
        })
      }
    })
    return () => {
      live = false
    }
  }, [kind, datasetId, dispatch])

  if (!kind) return <>{children}</>
  if (failure?.kind === kind) {
    if (failure.expired) return <ExpiredCard />
    return <FailureCard message={failure.message} onAction={() => dispatch({ type: 'reset' })} />
  }
  return (
    <Card>
      <CardContent className="pt-6">
        <p aria-live="polite" className="text-sm text-slate-700">
          Loading your file…
        </p>
      </CardContent>
    </Card>
  )
}

function FailureCard({ message, onAction }: { message: string; onAction: () => void }) {
  const msg = useFocusOnMount<HTMLParagraphElement>()
  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        <p ref={msg} tabIndex={-1} role="alert" className="text-red-700 outline-none">
          {message}
        </p>
        <Button onClick={onAction}>Upload another file</Button>
      </CardContent>
    </Card>
  )
}
