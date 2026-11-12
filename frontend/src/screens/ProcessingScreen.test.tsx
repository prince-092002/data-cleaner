import { act, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getJob, getResults } from '@/api/client'
import type { JobStatus, ResultsResponse, UploadResponse } from '@/api/types'
import { AppStateProvider, useAppState } from '@/state/AppState'
import { ProcessingScreen } from './ProcessingScreen'

vi.mock('@/api/client', () => ({ getJob: vi.fn(), getResults: vi.fn() }))

const job = (over: Partial<JobStatus>): JobStatus =>
  ({ job_id: 'j1', status: 'running', progress_pct: 20, current_step: 'Reading', error: null, ...over }) as JobStatus

function Probe() {
  const { state } = useAppState()
  return <p data-testid="probe">{`${state.step}|${state.results ? 'results' : 'none'}`}</p>
}

function Seed({ withJob = true }: { withJob?: boolean }) {
  const { dispatch } = useAppState()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    dispatch({ type: 'uploaded', upload: { dataset_id: 'd1' } as UploadResponse })
    if (withJob) dispatch({ type: 'job_started', jobId: 'j1' })
    dispatch({ type: 'goto', step: 3 })
    setReady(true)
  }, [dispatch, withJob])
  return ready ? (
    <>
      <ProcessingScreen />
      <Probe />
    </>
  ) : null
}

function setup(withJob = true) {
  return render(
    <AppStateProvider>
      <Seed withJob={withJob} />
    </AppStateProvider>,
  )
}

const tick = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(2000)
  })

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(getJob).mockReset()
  vi.mocked(getResults).mockReset()
})
afterEach(() => vi.useRealTimers())

describe('ProcessingScreen', () => {
  it('updates progress across polls', async () => {
    vi.mocked(getJob)
      .mockResolvedValueOnce(job({ progress_pct: 20, current_step: 'Reading' }))
      .mockResolvedValueOnce(job({ progress_pct: 60, current_step: 'Working' }))
    setup()
    await tick()
    expect(screen.getByText('Reading (20%)')).toBeTruthy()
    await tick()
    expect(screen.getByText('Working (60%)')).toBeTruthy()
    expect(getJob).toHaveBeenCalledTimes(2)
    expect(screen.queryAllByRole('listitem')).toHaveLength(0)
  })

  it('loads results and goes to step 4 when done', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getResults).mockResolvedValue({ run_id: 'j1' } as unknown as ResultsResponse)
    setup()
    await tick()
    expect(getResults).toHaveBeenCalledWith('d1', { limit: 50 })
    expect(screen.getByTestId('probe').textContent).toBe('4|results')
  })

  it('shows the failure message and buttons', async () => {
    vi.mocked(getJob).mockResolvedValue(
      job({ status: 'failed', error: { code: 'internal_error', message: 'Boom happened' } }),
    )
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('Boom happened')
    act(() => screen.getByRole('button', { name: 'Back to suggested fixes' }).click())
    expect(screen.getByTestId('probe').textContent).toBe('2|none')
  })

  it('shows a friendlier line for interrupted jobs and can start over', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'failed', error: { code: 'interrupted', message: 'raw' } }))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toMatch(/server restarted/)
    act(() => screen.getByRole('button', { name: 'Start over' }).click())
    expect(screen.getByTestId('probe').textContent).toBe('0|none')
  })

  it('shows an error with buttons when loading results fails after done', async () => {
    vi.mocked(getJob).mockResolvedValue(job({ status: 'done', progress_pct: 100 }))
    vi.mocked(getResults).mockImplementation(() => Promise.reject(new Error('Results unavailable')))
    setup()
    await tick()
    expect(screen.getByRole('alert').textContent).toBe('Results unavailable')
    expect(screen.getByRole('button', { name: 'Start over' })).toBeTruthy()
  })

  it('clears the interval on unmount', async () => {
    vi.mocked(getJob).mockResolvedValue(job({}))
    const { unmount } = setup()
    await tick()
    unmount()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000)
    })
    expect(getJob).toHaveBeenCalledTimes(1)
  })

  it('offers a way back when there is no job', () => {
    setup(false)
    expect(screen.getByRole('button', { name: 'Back to suggested fixes' })).toBeTruthy()
    expect(getJob).not.toHaveBeenCalled()
  })
})
