import { useEffect, useRef } from 'react'
import { getJob } from '@/api/client'
import type { JobStatus } from '@/api/types'

export const FAST_POLL_MS = 2000
export const SLOW_POLL_MS = 5000
export const SLOW_AFTER_MS = 60_000

/** Poll every 2 s, then every 5 s once the job has been running for a minute. */
export function pollDelay(elapsedMs: number): number {
  return elapsedMs < SLOW_AFTER_MS ? FAST_POLL_MS : SLOW_POLL_MS
}

/**
 * Polls GET /jobs/{id} until the job is done or failed, then stops. Stops on unmount or when
 * jobId changes. `onJob` runs for every answer; if it or the request throws 3 times in a row, `onError` runs and polling
 * stops. A 404 (expired job) is not transient, so it fails at once.
 */
export function useJobPolling(
  jobId: string | null,
  onJob: (job: JobStatus) => void | Promise<void>,
  onError: (e: unknown) => void,
) {
  const cb = useRef({ onJob, onError })
  useEffect(() => {
    cb.current = { onJob, onError }
  })
  useEffect(() => {
    if (!jobId) return
    let alive = true
    const start = Date.now()
    let timer: ReturnType<typeof setTimeout>
    let failures = 0
    // shortcut: fixed 3-failure limit with no backoff, revisit if the API gets rate limiting
    const MAX_FAILURES = 3
    const tick = async () => {
      try {
        const job = await getJob(jobId)
        if (!alive) return
        await cb.current.onJob(job)
        failures = 0
        if (!alive || job.status === 'done' || job.status === 'failed') return
      } catch (e) {
        if (!alive) return
        if (++failures >= MAX_FAILURES || (e as { status?: number }).status === 404) {
          cb.current.onError(e)
          return
        }
      }
      timer = setTimeout(tick, pollDelay(Date.now() - start))
    }
    timer = setTimeout(tick, FAST_POLL_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [jobId])
}
