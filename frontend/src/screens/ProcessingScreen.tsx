import { useState } from 'react'
import { getResults } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { useAppState } from '@/state/AppState'
import { PAGE_SIZE } from './ResultsScreen'
import { ExpiredCard } from '@/components/ExpiredCard'
import { friendlyJobError, isNotFound } from '@/lib/jobErrors'
import { FocusedAlert } from '@/components/FocusedAlert'
import { useJobPolling } from '@/lib/useJobPolling'

export function ProcessingScreen() {
  const { state, dispatch } = useAppState()
  const { jobId, datasetId } = state
  const [pct, setPct] = useState(0)
  const [step, setStep] = useState('Starting')
  const [queued, setQueued] = useState(true)
  const [failure, setFailure] = useState<{ code: string; message: string } | null>(null)

  useJobPolling(
    datasetId ? jobId : null,
    async (job) => {
      setQueued(job.status === 'queued')
      setPct(job.progress_pct)
      setStep(job.current_step)
      if (job.status === 'failed') {
        dispatch({ type: 'job_finished' })
        setFailure({
          code: job.error?.code ?? 'internal_error',
          message: friendlyJobError(job.error?.code, job.error?.message, 'Cleaning failed.'),
        })
      } else if (job.status === 'done') {
        dispatch({ type: 'job_finished' })
        const results = await getResults(datasetId!, { limit: PAGE_SIZE })
        dispatch({ type: 'results_loaded', results })
        dispatch({ type: 'goto', step: 4 })
      }
    },
    (e) => {
      dispatch({ type: 'job_finished' })
      setFailure({
        code: isNotFound(e) ? 'expired' : 'client_error',
        message: e instanceof Error ? e.message : 'Something went wrong.',
      })
    },
  )

  if (!jobId || !datasetId) {
    return (
      <Card>
        <CardContent className="space-y-4 pt-6">
          <p>There is no cleaning job to show yet. Choose your fixes first.</p>
          <Button onClick={() => dispatch({ type: 'goto', step: 2 })}>Back to suggested fixes</Button>
        </CardContent>
      </Card>
    )
  }

  if (failure?.code === 'expired') return <ExpiredCard />

  if (failure) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2 className="text-xl font-semibold">Cleaning did not finish</h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <FocusedAlert className="text-red-700">{failure.message}</FocusedAlert>
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => dispatch({ type: 'goto', step: 2 })}>Back to suggested fixes</Button>
            <Button variant="outline" onClick={() => dispatch({ type: 'reset' })}>
              Try another file
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 className="text-xl font-semibold">Cleaning your file</h2>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Progress value={pct} aria-label="Cleaning progress" />
        <p aria-live="polite" className="text-sm text-slate-700">
          {queued ? 'Waiting to start. Your file is in line.' : `${step} (${Math.round(pct)}%)`}
        </p>
        <p className="text-sm text-slate-600">
          Your file is cleaned on the server. The original upload is never modified.
        </p>
      </CardContent>
    </Card>
  )
}
